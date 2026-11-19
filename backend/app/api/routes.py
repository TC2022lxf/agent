"""HTTP API (docs/07). Utterances only enqueue and return 202; the worker runs the Run."""

from __future__ import annotations

import io
import json
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from fastapi import Depends, File, Header, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from PIL import Image
from pydantic import BaseModel, Field

from app.agents.skills import parse_skill
from app.api.declare import ApiError, DeclaredRouter, current_user
from app.api.timeline import build_timeline
from app.api.views import (
    canvas_view,
    constraint_view,
    feedback_view,
    product_view,
    run_view,
    task_view,
    version_view,
)
from app.constraints import platform_constraints
from app.container import Container
from app.domain import slots as slot_registry
from app.domain.canvas_templates import list_templates
from app.evaluators.base import EvalSubject
from app.infrastructure.gateway_logging import current_planner_profile
from app.runtime.compaction import summarize
from app.services import canvas_edits, canvas_templates
from app.services.collab import TERMINAL_RUN
from app.services.credits import InsufficientCredits
from app.services.profiles import (
    FOLLOWUPS_ENABLED,
    FOLLOWUPS_MODEL,
    MAX_TOOL_CALLS,
    SUMMARY_FRACTION,
    SUMMARY_KEEP,
    ProfileDisabled,
    profile_view,
)
from app.services.skill_edits import StaleRevision
from app.services.uow import UnitOfWork
from app.services.uploads import (
    UploadRejected,
    guess_mime,
    is_image,
    read_upload,
    safe_name,
)

api = DeclaredRouter()


def _c(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


def _uow(request: Request) -> UnitOfWork:
    return _c(request).uow_factory()


# ---- schemas ---------------------------------------------------------------
class NormRectIn(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class ImportListing(BaseModel):
    title: str | None = None
    bullets: list[str] | None = None
    description: str | None = None
    main_image_upload_id: str | None = None


class CreateTask(BaseModel):
    goal: str = ""
    agent_id: str
    kind: str | None = None  # needed only when agent_id has no fixed task kind (general)
    profile: str | None = None  # image task: "main_image" turns on main-image rules
    upload_id: str | None = None  # image task: first image
    import_listing: ImportListing | None = None
    product_id: str | None = None  # work on a product: its facts are given to the Agent
    import_product: bool = False  # pdp: import the product's saved listing as first versions


class ListingIn(BaseModel):
    title: str | None = None
    bullets: list[str] | None = None
    description: str | None = None
    search_terms: str | None = None


class CreateProduct(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    brand: str = ""
    marketplace: str = ""
    mode: str = Field(default="generate", pattern="^(generate|optimize)$")
    attributes: dict[str, str] = Field(default_factory=dict)
    listing: ListingIn | None = None
    main_image_upload_id: str | None = None
    gallery_upload_ids: list[str] = Field(default_factory=list)


class Utterance(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    agent_id: str | None = None  # which entry the user is using; defaults to the task's agent
    target_slot: str | None = None
    target_version_id: str | None = None
    target_region: NormRectIn | None = None
    client_hint: str | None = Field(default=None, pattern="^(constraint|preference)$")
    reasoning: bool = False
    skill_id: str | None = None  # `/skill-name`: narrows this Run to that Skill
    attachment_ids: list[str] = Field(default_factory=list)  # composer `+` uploads
    # The `ask_question` this sentence answers. Not a tool_result: a Run is not resumed, it is
    # a new Run — but it must know which question it is replying to, or the answer arrives
    # with no question attached (decisions/0043).
    answers_request_id: str | None = None


class SignalIn(BaseModel):
    signal: str = Field(pattern="^(accept|reject)$")


class PrefBody(BaseModel):
    body_md: str


# ---- meta ------------------------------------------------------------------
@api.route("GET", "/agents", rate="read", auth=False)
def list_agents(request: Request) -> list[dict[str, Any]]:
    reg = _c(request).registry
    return [
        {
            "key": a.key, "title": a.title, "description": a.description,
            "tool_names": list(a.tool_names), "skill_ids": list(a.skill_ids),
            "artifact_kinds": list(a.artifact_kinds), "workbench": a.workbench,
            "task_kind": a.task_kind,
        }
        for a in reg.agents()
    ]


@api.route("GET", "/agents/{agent_id}/skills", rate="read", auth=False)
def agent_skills(agent_id: str, request: Request) -> list[dict[str, str]]:
    reg = _c(request).registry
    if not reg.has_agent(agent_id):
        raise ApiError(404, "NOT_FOUND", agent_id)
    ids = set(reg.agent(agent_id).skill_ids)
    return [{"id": s.id, "description": s.description, "hash": s.content_hash,
             "audience": s.audience}
            for s in reg.skills_for(agent_id) if s.id in ids]


@api.route("GET", "/slots", rate="read", auth=False)
def list_slots() -> list[dict[str, Any]]:
    return [
        {"key": s.key, "value_type": s.value_type, "artifact_kind": s.artifact_kind,
         "max_items": s.max_items, "description": s.description}
        for s in slot_registry.all_slots()
    ]


# ---- uploads & blobs -------------------------------------------------------
def _store_image(request: Request, data: bytes) -> str:
    """Re-encode to PNG: drops metadata and any payload hidden in the original file."""
    if len(data) > 10 * 1024 * 1024:
        raise ApiError(413, "TOO_LARGE", "max 10 MB")
    try:
        img = Image.open(io.BytesIO(data))
        if img.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError(img.format)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="PNG")
    except Exception as e:
        raise ApiError(400, "BAD_IMAGE", "unsupported or corrupt image") from e
    from uuid import uuid4

    key = f"uploads/{uuid4().hex}.png"
    _c(request).store.put(key, buf.getvalue())
    return key


@api.route("POST", "/uploads", rate="upload", status_code=201)
async def upload(
    request: Request, file: UploadFile = File(...), user: str = Depends(current_user)
) -> dict[str, str]:
    del user
    return {"upload_id": _store_image(request, await file.read())}


@api.route("GET", "/blobs/{key:path}", rate="read", auth=False)
def blob(key: str, request: Request) -> Response:
    # Keys are random 128-bit ids; <img> tags cannot send auth headers. Tracked in STATUS.
    store = _c(request).store
    if not store.exists(key):
        raise ApiError(404, "NOT_FOUND", key)
    return Response(store.get(key), media_type=guess_mime(key))


@api.route("POST", "/files", rate="upload", status_code=201)
async def upload_file(
    request: Request, file: UploadFile = File(...), user: str = Depends(current_user)
) -> dict[str, Any]:
    """Composer `+`: any file. Images keep the re-encode path; text is decoded as context.

    Does not create a Version. The returned key goes on the utterance as an attachment.
    """
    del user
    data = await file.read()
    try:
        name = safe_name(file.filename or "upload")
    except UploadRejected as e:
        raise ApiError(400, e.code, e.message) from e
    if is_image(name):
        key = _store_image(request, data)
        return {
            "upload_id": key, "name": name, "mime": "image/png",
            "size": len(data), "readable": False, "kind": "image",
        }
    try:
        uploaded = read_upload(name, data)
    except UploadRejected as e:
        raise ApiError(400, e.code, e.message) from e
    _c(request).store.put(uploaded.key, data)
    return {**uploaded.to_json(), "kind": "file"}


# ---- products --------------------------------------------------------------
def _image_size(c: Container, key: str) -> tuple[int, int]:
    w, h = Image.open(io.BytesIO(c.store.get(key))).size
    return w, h


def _import_product(c: Container, uow: UnitOfWork, task: Any, product: Any) -> None:
    """Saved listing -> first Versions (origin=imported), bound into ONE first PDP Version."""
    lst, assets = product.listing or {}, product.assets or {}
    bound: dict[str, str] = {}

    def put(slot: str, content: dict[str, Any]) -> None:
        bound[slot] = uow.collab.import_slot(task, slot, content, bind=False).id

    for slot in ("title", "description", "search_terms"):
        if lst.get(slot):
            put(slot, {"text": lst[slot]})
    if lst.get("bullets"):
        put("bullets", {"items": list(lst["bullets"])})
    if assets.get("main") and c.store.exists(assets["main"]):
        w, h = _image_size(c, assets["main"])
        put("main_image", {"object_key": assets["main"], "width": w, "height": h})
    if assets.get("gallery"):
        put("secondary_image", {"object_keys": list(assets["gallery"])})
    if bound:
        uow.collab.bind_many_to_pdp(
            task.id, bound, None, "user", "imported",
            create=slot_registry.is_multi_artifact(task.kind),
        )

@api.route("GET", "/products", rate="read")
def list_products(request: Request, user: str = Depends(current_user)) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [product_view(p) for p in uow.products.list_for(user)]


@api.route("POST", "/products", rate="write", status_code=201)
def create_product(
    body: CreateProduct, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    c = _c(request)
    keys = [k for k in [body.main_image_upload_id, *body.gallery_upload_ids] if k]
    if any(not c.store.exists(k) for k in keys):
        raise ApiError(400, "BAD_UPLOAD", "unknown upload_id")
    listing = body.listing.model_dump(exclude_none=True) if body.listing else {}
    with c.uow_factory() as uow:
        p = uow.products.create(
            user, name=body.name, brand=body.brand, marketplace=body.marketplace,
            mode=body.mode, facts={"attributes": body.attributes}, listing=listing,
            assets={"main": body.main_image_upload_id, "gallery": body.gallery_upload_ids},
        )
        uow.commit()
        return product_view(p)


@api.route("POST", "/products/samples", rate="write")
def load_samples(request: Request, user: str = Depends(current_user)) -> list[dict[str, Any]]:
    """Load the saved real listings from fixtures/ for this user. Idempotent."""
    c = _c(request)
    with c.uow_factory() as uow:
        out = [product_view(p) for p in uow.products.seed_samples(user, c.store)]
        uow.commit()
        return out


@api.route("GET", "/products/{product_id}", rate="read")
def get_product(
    product_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        p = uow.products.get(product_id, user)
        tasks = [task_view(uow, t) for t in uow.products.tasks_of(p.id)]
        return {**product_view(p), "tasks": tasks}


# ---- registry (read-only, admin pages) ----------------------------------------
@api.route("GET", "/tools", rate="read", auth=False)
def list_tools(request: Request) -> list[dict[str, Any]]:
    reg = _c(request).registry
    return [_tool_view(reg, t) for t in reg.tools()]


@api.route("GET", "/tools/{name}", rate="read", auth=False)
def get_tool(name: str, request: Request) -> dict[str, Any]:
    reg = _c(request).registry
    try:
        t = reg.tool(name)
    except KeyError as e:
        raise ApiError(404, "NOT_FOUND", name) from e
    return {
        **_tool_view(reg, t),
        "input_schema": t.input_schema(),
        "output_schema": t.output_schema(),
    }


def _tool_view(reg: Any, t: Any) -> dict[str, Any]:
    m = t.meta
    return {
        "name": m.name, "version": m.version, "description": m.description,
        "side_effect": m.side_effect, "cost_credits": m.cost_credits,
        "timeout_s": m.timeout_s, "idempotent": m.idempotent,
        "agents": [a.key for a in reg.agents() if m.name in a.tool_names],
    }


class ToolInvoke(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)


@api.route("POST", "/tools/{name}/invoke", rate="write")
def invoke_tool(
    name: str, body: ToolInvoke, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    """Run one registered tool. Does not start an Agent Run or write a Version."""
    c = _c(request)
    try:
        tool = c.registry.tool(name)
    except KeyError as e:
        raise ApiError(404, "NOT_FOUND", name) from e
    owners = [a for a in c.registry.agents() if name in a.tool_names]
    if not owners:
        raise ApiError(404, "NOT_FOUND", name)
    run_id = f"console_{uuid4().hex[:12]}"
    with c.uow_factory() as uow:
        uow.credits.ensure_user(user, c.settings.initial_credits)
        # Freeze the tool's declared cost first, then settle: same hold/settle shape as a Run,
        # so a console trial cannot spend more than it declared.
        try:
            uow.credits.hold(user, run_id, max(tool.meta.cost_credits, 0))
        except InsufficientCredits as e:
            raise ApiError(402, "INSUFFICIENT_CREDITS", "积分不足，请先充值") from e
        uow.commit()
    result = c.executor.tools.call(
        agent_key=owners[0].key,
        tool_name=name,
        raw_input=body.input,
        run_id=run_id,
        trace_id=run_id,
        user_id=user,
        tool_call_id=uuid4().hex[:12],
        budget_left=max(tool.meta.cost_credits, 1),
    )
    with c.uow_factory() as uow:
        uow.credits.settle(user, run_id, max(tool.meta.cost_credits, 0), result.cost)
        uow.console.save_tool_call(result.record)
        uow.commit()
    return {
        "status": result.record["status"],
        "output": result.record["output"],
        "error": result.record["error"],
        "cost": result.cost,
        "duration_ms": result.record["duration_ms"],
    }


class AgentConfigIn(BaseModel):
    model: str
    system_prompt: str


@api.route("GET", "/admin/config", rate="read", auth="admin")
def admin_config(
    request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    """Agent model, prompt, and model profiles. The loop reads these on the next Run."""
    c = _c(request)
    s = c.settings
    with c.uow_factory() as uow:
        agents = [
            uow.console.agent_config(a.key, a.title, list(a.tool_names), list(a.skill_ids))
            for a in c.registry.agents()
        ]
        profiles = [profile_view(p) for p in uow.profiles.list()]
        image_profile = uow.console.get("image.profile", "")
        runtime = {
            "summary_fraction": uow.profiles.summary_fraction(),
            "summary_keep": uow.profiles.summary_keep(),
            "max_tool_calls": uow.profiles.max_tool_calls(),
            "followups_enabled": uow.profiles.followups_enabled(),
            "followups_model": uow.profiles.followups_model(),
        }
    return {
        "env": [
            {"key": "GATEWAY", "value": s.gateway, "editable": False},
            {"key": "PLANNER_MODEL", "value": s.planner_model or "(控制台默认)", "editable": False},
            {"key": "IMAGE_MODEL", "value": s.image_model or "(控制台默认)", "editable": False},
            {
                "key": "DATABASE",
                "value": "mysql" if s.database_url.startswith("mysql") else "sqlite",
                "editable": False,
            },
            {
                "key": "OPENAI_API_KEY",
                "value": "已设置" if s.openai_api_key else "未设置",
                "editable": False,
            },
            {"key": "INITIAL_CREDITS", "value": str(s.initial_credits), "editable": False},
        ],
        "agents": agents,
        "profiles": profiles,
        "image_profile": image_profile,
        "runtime": runtime,
        "note": (
            "系统提示词里的 {{agent}}、{{tools}}、{{skills}} 在运行时替换。"
            "主模型存的是模型档案 key。停用的档案不能再被选为绑定。"
        ),
    }


@api.route("PUT", "/admin/config/{agent_key}", rate="write", auth="admin", audit=True)
def save_admin_config(
    agent_key: str, body: AgentConfigIn, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    c = _c(request)
    if not c.registry.has_agent(agent_key):
        raise ApiError(404, "NOT_FOUND", agent_key)
    spec = c.registry.agent(agent_key)
    model = body.model.strip() or "fake"
    with c.uow_factory() as uow:
        row = uow.profiles.get(model)
        if row is not None and (not row.enabled or row.kind != "planner"):
            raise ApiError(400, "PROFILE_UNAVAILABLE", f"{model} cannot be bound")
        uow.console.save_agent(agent_key, model, body.system_prompt)
        uow.commit()
        return uow.console.agent_config(
            spec.key, spec.title, list(spec.tool_names), list(spec.skill_ids)
        )


class ProfileIn(BaseModel):
    upstream_model: str | None = None
    kind: str | None = None
    context_window_tokens: int | None = None
    reasoning: dict[str, Any] | None = None
    when_thinking_enabled: dict[str, Any] | None = None
    when_thinking_disabled: dict[str, Any] | None = None
    capabilities: list[str] | None = None
    price: dict[str, Any] | None = None
    param_schema: dict[str, Any] | None = None
    enabled: bool | None = None


class ImageProfileIn(BaseModel):
    key: str


class RuntimeIn(BaseModel):
    summary_fraction: float | None = None
    summary_keep: int | None = None
    max_tool_calls: int | None = None
    followups_enabled: bool | None = None
    followups_model: str | None = None


@api.route("GET", "/admin/model-profiles", rate="read", auth="admin")
def list_model_profiles(
    request: Request, user: str = Depends(current_user),
) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [profile_view(p) for p in uow.profiles.list()]


@api.route("PUT", "/admin/model-profiles/{key}", rate="write", auth="admin", audit=True)
def save_model_profile(
    key: str, body: ProfileIn, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        row = uow.profiles.save(key, body.model_dump(exclude_none=True))
        uow.commit()
        return profile_view(row)


@api.route("PUT", "/admin/image-profile", rate="write", auth="admin", audit=True)
def save_image_profile(
    body: ImageProfileIn, request: Request, user: str = Depends(current_user)
) -> dict[str, str]:
    with _uow(request) as uow:
        try:
            uow.profiles.bind_image(body.key)
        except ProfileDisabled as exc:
            raise ApiError(400, "PROFILE_UNAVAILABLE", str(exc)) from exc
        uow.commit()
        return {"image_profile": body.key}


@api.route("PUT", "/admin/runtime", rate="write", auth="admin", audit=True)
def save_runtime(
    body: RuntimeIn, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        if body.summary_fraction is not None:
            uow.console.put(SUMMARY_FRACTION, str(body.summary_fraction))
        if body.summary_keep is not None:
            uow.console.put(SUMMARY_KEEP, str(body.summary_keep))
        if body.max_tool_calls is not None:
            uow.console.put(MAX_TOOL_CALLS, str(body.max_tool_calls))
        if body.followups_enabled is not None:
            uow.console.put(FOLLOWUPS_ENABLED, "1" if body.followups_enabled else "0")
        if body.followups_model is not None:
            uow.console.put(FOLLOWUPS_MODEL, body.followups_model)
        uow.commit()
        return {
            "summary_fraction": uow.profiles.summary_fraction(),
            "summary_keep": uow.profiles.summary_keep(),
            "max_tool_calls": uow.profiles.max_tool_calls(),
            "followups_enabled": uow.profiles.followups_enabled(),
            "followups_model": uow.profiles.followups_model(),
        }


@api.route("GET", "/admin/logs", rate="read", auth="admin")
def admin_logs(request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        return uow.console.logs()


@api.route("GET", "/skills", rate="read", auth=False)
def list_skills(request: Request) -> list[dict[str, Any]]:
    reg = _c(request).registry
    return [_skill_view(reg, s, body=False) for s in reg.skills()]


@api.route("GET", "/skills/{skill_id}", rate="read", auth=False)
def get_skill(skill_id: str, request: Request) -> dict[str, Any]:
    reg = _c(request).registry
    if not reg.has_skill(skill_id):
        raise ApiError(404, "NOT_FOUND", skill_id)
    return _skill_view(reg, reg.skill(skill_id), body=True)


class SkillBody(BaseModel):
    body: str = Field(min_length=1, max_length=200_000)
    base_revision: int = 0  # the revision the editor opened; stale numbers are rejected


@api.route("PUT", "/skills/{skill_id}", rate="write")
def put_skill(
    skill_id: str, body: SkillBody, request: Request, user: str = Depends(current_user),
) -> dict[str, Any]:
    c = _c(request)
    reg = c.registry
    if not reg.has_skill(skill_id):
        raise ApiError(404, "NOT_FOUND", skill_id)
    parsed = parse_skill(skill_id, body.body)
    if not parsed.description.strip():
        raise ApiError(400, "BAD_SKILL", "front matter 需要 description")
    with c.uow_factory() as uow:
        try:
            row = uow.skill_edits.save(
                skill_id, body.body, base_revision=body.base_revision, edited_by=user,
                description=parsed.description, audience=parsed.audience,
            )
        except StaleRevision as exc:
            raise ApiError(
                409, "STALE_SKILL",
                f"这个 Skill 已被改过（当前修订 {exc.current}），重新加载后再保存",
            ) from exc
        uow.commit()
    skill = reg.load_skill_text(skill_id, row.body, revision=row.revision, source=row.source)
    return _skill_view(reg, skill, body=True)


@api.route("GET", "/skills/{skill_id}/revisions", rate="read")
def skill_revisions(skill_id: str, request: Request) -> list[dict[str, Any]]:
    c = _c(request)
    if not c.registry.has_skill(skill_id):
        raise ApiError(404, "NOT_FOUND", skill_id)
    with c.uow_factory() as uow:
        return [
            {"revision": r.revision, "edited_by": r.edited_by, "source": r.source,
             "created_at": r.created_at.isoformat(), "hash": r.content_hash or ""}
            for r in uow.skill_edits.history(skill_id)
        ]


@api.route("POST", "/skills/{skill_id}/reset", rate="write")
def reset_skill(
    skill_id: str, request: Request, user: str = Depends(current_user),
) -> dict[str, Any]:
    """Restore the shipped file text as a new revision; history is kept."""
    c = _c(request)
    reg = c.registry
    if not reg.has_skill(skill_id):
        raise ApiError(404, "NOT_FOUND", skill_id)
    shipped = reg.shipped_text(skill_id)
    if not shipped:
        raise ApiError(400, "NO_BASELINE", "这个 Skill 没有仓库正文")
    parsed = parse_skill(skill_id, shipped)
    with c.uow_factory() as uow:
        row = uow.skill_edits.save(
            skill_id, shipped, base_revision=(uow.skill_edits.latest(skill_id) or _ZERO).revision,
            edited_by=user, description=parsed.description, audience=parsed.audience,
            source="restored",
        )
        uow.commit()
    skill = reg.load_skill_text(skill_id, row.body, revision=row.revision, source="restored")
    return _skill_view(reg, skill, body=True)


class _Zero:
    revision = 0


_ZERO = _Zero()


def _skill_view(reg: Any, s: Any, *, body: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": s.id, "description": s.description, "hash": s.content_hash,
        "audience": s.audience, "revision": s.revision, "source": s.source,
        "agents": [a.key for a in reg.agents() if s.id in a.skill_ids],
        "tools": [t.meta.name for t in reg.tools() if t.meta.name in s.body],
    }
    if body:
        out["body"] = s.body
    return out


@api.route("GET", "/constraints/platform", rate="read", auth=False)
def platform_rules() -> dict[str, Any]:
    return platform_constraints()


# ---- tasks -----------------------------------------------------------------
@api.route("POST", "/tasks", rate="write", status_code=201)
def create_task(
    body: CreateTask, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    c = _c(request)
    if not c.registry.has_agent(body.agent_id):
        raise ApiError(404, "NOT_FOUND", f"agent {body.agent_id}")
    spec = c.registry.agent(body.agent_id)
    kind = spec.task_kind or body.kind
    if kind not in slot_registry.task_kinds():
        raise ApiError(
            400, "BAD_KIND", "kind is required and must be pdp, image, file, general, or canvas",
        )
    if kind == "image" and body.upload_id and not c.store.exists(body.upload_id):
        raise ApiError(400, "BAD_UPLOAD", "unknown upload_id")
    meta: dict[str, Any] = {"profile": body.profile} if body.profile else {}
    with c.uow_factory() as uow:
        product = uow.products.get(body.product_id, user) if body.product_id else None
        goal = body.goal
        if product is not None:
            goal = goal or f"{product.name} · " + (
                "导入优化" if product.mode == "optimize" else "做一个 PDP"
            )
            main = (product.assets or {}).get("main")
            meta["product"] = {
                "id": product.id, "name": product.name, "brand": product.brand,
                # The first draft must show THIS product: the saved picture is the reference.
                **({"reference_key": main} if isinstance(main, str) and main else {}),
            }
            meta["facts"] = (product.facts or {}).get("attributes", {})
            if kind == "image" and not body.upload_id and main:
                body.upload_id = main
        task = uow.collab.create_task(user, kind, body.agent_id, goal, meta)
        task.product_id = product.id if product is not None else None
        if product is not None and body.import_product and kind != "image":
            # `general` owns no fixed slots, so the import has to create them on first write.
            _import_product(c, uow, task, product)
            task.status = "awaiting_user"
        if kind == "image" and body.upload_id:
            png = c.store.get(body.upload_id)
            w, h = Image.open(io.BytesIO(png)).size
            uow.collab.import_slot(
                task, "image", {"object_key": body.upload_id, "width": w, "height": h}
            )
            task.status = "awaiting_user"
        if kind == "pdp" and body.import_listing:
            il = body.import_listing
            if il.title is not None:
                uow.collab.import_slot(task, "title", {"text": il.title})
            if il.bullets is not None:
                uow.collab.import_slot(task, "bullets", {"items": il.bullets})
            if il.description is not None:
                uow.collab.import_slot(task, "description", {"text": il.description})
            if il.main_image_upload_id and c.store.exists(il.main_image_upload_id):
                png = c.store.get(il.main_image_upload_id)
                w, h = Image.open(io.BytesIO(png)).size
                uow.collab.import_slot(
                    task, "main_image",
                    {"object_key": il.main_image_upload_id, "width": w, "height": h},
                )
            task.status = "awaiting_user"
        _evaluate_baseline(c, uow, task)
        uow.commit()
        return task_view(uow, task)


def _can_handle(spec: Any, kind: str) -> bool:
    """Which entries may run on this Task. A general Task needs both file and image output."""
    if kind == "general":
        return {"file", "image"} <= set(spec.artifact_kinds)
    need = {"image": "image", "file": "file", "canvas": "canvas"}.get(kind, "pdp")
    return need in spec.artifact_kinds


def _evaluate_baseline(c: Container, uow: UnitOfWork, task: Any) -> None:
    """Imported content stays current whatever the rules say; the results are recorded so the
    UI can show which problems were there from the start (baseline) and which got fixed."""
    if slot_registry.is_multi_artifact(task.kind) or task.kind == "file":
        # These kinds own no fixed slots: read what was actually created on import.
        slots = [a.slot for a in uow.collab.artifacts(task.id) if a.slot]
    else:
        slots = list(slot_registry.slots_for_task_kind(task.kind))
    for slot in slots:
        v = uow.collab.current_version(task.id, slot)
        if v is None or v.origin != "imported":
            continue
        subject = EvalSubject(slot, v.content, task.meta, [], c.store)
        for ev in c.evaluators.all():
            if ev.applies_to(subject):
                r = ev.evaluate(subject)
                uow.collab.add_evaluation(v.id, ev.id, r.passed, ev.can_reject, r.details)


@api.route("GET", "/tasks", rate="read")
def list_tasks(request: Request, user: str = Depends(current_user)) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [task_view(uow, t) for t in uow.collab.list_tasks(user)]


@api.route("GET", "/tasks/{task_id}/timeline", rate="read")
def task_timeline(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return build_timeline(uow, uow.collab.get_task(task_id, user))


@api.route("GET", "/tasks/{task_id}", rate="read")
def get_task(task_id: str, request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        return task_view(uow, uow.collab.get_task(task_id, user))


@api.route("POST", "/tasks/{task_id}/utterances", rate="run", status_code=202)
def post_utterance(
    task_id: str,
    body: Utterance,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: str = Depends(current_user),
) -> dict[str, Any]:
    if not idempotency_key:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
    c = _c(request)
    with c.uow_factory() as uow:
        task = uow.collab.get_task(task_id, user)
        if task.status in {"accepted", "abandoned"}:
            raise ApiError(409, "TASK_TERMINAL", "task is finished")
        agent_key = body.agent_id or task.agent_key
        if not c.registry.has_agent(agent_key):
            raise ApiError(404, "NOT_FOUND", f"agent {agent_key}")
        spec = c.registry.agent(agent_key)
        if not _can_handle(spec, task.kind):
            raise ApiError(400, "AGENT_CANNOT_HANDLE", f"{agent_key} cannot work on {task.kind}")
        if body.skill_id:
            if body.skill_id not in spec.skill_ids:
                raise ApiError(400, "SKILL_NOT_FOR_AGENT", f"{agent_key} 不能用 {body.skill_id}")
        for key in body.attachment_ids:
            if not c.store.exists(key):
                raise ApiError(400, "BAD_ATTACHMENT", f"unknown attachment {key}")
        if body.target_slot and not slot_registry.allows_slot(task.kind, body.target_slot):
            raise ApiError(400, "BAD_SLOT", body.target_slot)
        uow.credits.ensure_user(user, c.settings.initial_credits)
        payload = body.model_dump(exclude={"agent_id"})
        held = uow.billing.budget_for(task.kind)
        run, created = uow.collab.create_run(
            task=task, trigger="utterance", payload=payload,
            idempotency_key=idempotency_key, held=held,
            agent_key=agent_key,
        )
        if created:
            # Freeze BEFORE returning 202. A user with no balance must not start a Run whose
            # vendor cost lands before the first settlement (decisions/0004).
            try:
                uow.credits.hold(user, run.id, run.held)
            except InsufficientCredits as e:
                raise ApiError(
                    402, "INSUFFICIENT_CREDITS",
                    f"积分不足：这次需要冻结 {e.needed}，可用 {e.available}。充值后再试。",
                ) from e
        uow.commit()
        return run_view(run)


@api.route("POST", "/tasks/{task_id}/compact", rate="write")
def compact_task(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    """Manual summary. Does not start a Run and does not write a Version."""
    c = _c(request)
    with c.uow_factory() as uow:
        task = uow.collab.get_task(task_id, user)
        if uow.collab.has_active_run(task.id):
            raise ApiError(409, "RUN_ACTIVE", "wait until the current run finishes")
        keep = uow.profiles.summary_keep()
        planner = uow.profiles.planner_for_agent(task.agent_key)
        before = {
            slot: _current_id(uow, task.id, slot)
            for slot in _compact_slots(task.kind)
        }
        token = current_planner_profile.set(planner.key)
        try:
            saved = summarize(
                uow, c.gateway, task,
                keep=keep, trigger="manual", profile_key=planner.key,
            )
        finally:
            current_planner_profile.reset(token)
        if saved is None:
            return {"status": "skipped", "reason": "history_too_short"}
        uow.commit()
        after = {
            slot: _current_id(uow, task.id, slot)
            for slot in _compact_slots(task.kind)
        }
        return {
            "status": "ok", "summary_id": saved.summary_id, "trigger": "manual",
            "turns": saved.turns, "covered_run_id": saved.covered_run_id,
            "versions_unchanged": before == after,
        }


def _compact_slots(kind: str) -> list[str]:
    """The slots a Task kind owns. A multi-artifact Task has no fixed list: it is named so the
    summary check stays honest instead of silently comparing nothing."""
    if slot_registry.is_multi_artifact(kind) or kind == "file":
        return []
    return list(slot_registry.slots_for_task_kind(kind))


def _current_id(uow: UnitOfWork, task_id: str, slot: str) -> str | None:
    v = uow.collab.current_version(task_id, slot)
    return v.id if v is not None else None


@api.route("POST", "/tasks/{task_id}/accept", rate="write")
def accept(task_id: str, request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        t = uow.collab.accept_task(task_id, user)
        uow.commit()
        return task_view(uow, t)


@api.route("POST", "/tasks/{task_id}/abandon", rate="write")
def abandon(task_id: str, request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        t = uow.collab.abandon_task(task_id, user)
        uow.commit()
        return task_view(uow, t)


# ---- runs ------------------------------------------------------------------
@api.route("GET", "/runs/{run_id}", rate="read")
def get_run(run_id: str, request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        return run_view(uow.collab.get_run(run_id, user))


@api.route("GET", "/runs/{run_id}/events", rate="read")
def run_events(
    run_id: str,
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    user: str = Depends(current_user),
) -> StreamingResponse:
    c = _c(request)
    with c.uow_factory() as uow:
        uow.collab.get_run(run_id, user)
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    def gen() -> Iterator[str]:
        nonlocal after
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            with c.uow_factory() as uow:
                events = uow.collab.events_after(run_id, after)
                status = uow.collab.get_run(run_id).status
            for e in events:
                after = e.id
                yield f"id: {e.id}\nevent: {e.type}\ndata: {json.dumps(e.data)}\n\n"
            if status in TERMINAL_RUN and not events:
                return
            time.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream")


@api.route("POST", "/runs/{run_id}/cancel", rate="write")
def cancel_run(run_id: str, request: Request, user: str = Depends(current_user)) -> dict[str, Any]:
    with _uow(request) as uow:
        before = uow.collab.get_run(run_id, user).status
        run = uow.collab.cancel_run(run_id, user)
        if before == "queued":  # never started: give the frozen credits back now
            uow.credits.refund(user, run.id, run.held)
            uow.collab.get_task(run.task_id).status = "awaiting_user"
        uow.commit()
        return run_view(run)


# ---- versions, artifacts ---------------------------------------------------
@api.route("GET", "/tasks/{task_id}/artifacts", rate="read")
def artifacts(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        uow.collab.get_task(task_id, user)
        return [
            {
                "artifact_id": a.id, "kind": a.kind, "slot": a.slot,
                "current_version_id": a.current_version_id,
                "versions": [version_view(uow, v, a.slot) for v in uow.collab.versions_of(a.id)],
            }
            for a in uow.collab.artifacts(task_id)
        ]


@api.route("GET", "/versions/{version_id}", rate="read")
def get_version(
    version_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        v = uow.collab.get_version(version_id)
        uow.collab.get_task(v.task_id, user)
        return version_view(uow, v)


@api.route("POST", "/versions/{version_id}/make-current", rate="write")
def make_current(
    version_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        v = uow.collab.make_current(version_id, user)
        uow.commit()
        return version_view(uow, v)


class CanvasOps(BaseModel):
    """A user's gesture batch. Fractions inside a screen, world px between screens."""

    ops: list[dict[str, Any]] = Field(default_factory=list)


@api.route("GET", "/canvas-templates", rate="read")
def canvas_template_list(
    request: Request, user: str = Depends(current_user),
) -> list[dict[str, str]]:
    """Starter boards. Opening one creates a task; this list does not."""
    del request, user
    return list_templates()


@api.route("POST", "/canvas-templates/{template_id}", rate="write", status_code=201)
def open_canvas_template(
    template_id: str, request: Request, user: str = Depends(current_user),
) -> dict[str, Any]:
    """A new canvas task whose board already holds the template's finished pictures."""
    c = _c(request)
    with c.uow_factory() as uow:
        try:
            task = canvas_templates.instantiate(uow, c.store, user, template_id)
        except canvas_templates.UnknownTemplate:
            raise ApiError(404, "NOT_FOUND", f"unknown canvas template {template_id}") from None
        uow.commit()
        return task_view(uow, task)


@api.route("GET", "/tasks/{task_id}/canvas", rate="read")
def get_canvas(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    """Screens, their modules and each picture's Version. No Version yet: empty, no placeholder."""
    with _uow(request) as uow:
        task = uow.collab.get_task(task_id, user)
        if "canvas" not in _c(request).registry.agent(task.agent_key).artifact_kinds:
            raise ApiError(404, "CANVAS_NOT_OPEN", "this task cannot hold a canvas")
        return canvas_view(uow, task)


@api.route("POST", "/versions/{version_id}/canvas-patches", rate="write")
def canvas_patches(
    version_id: str, body: CanvasOps, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    """A drag, resize, text edit or delete becomes ONE new canvas Version, by the user.

    No Run, no credits: the gesture is already the answer. Still a Version, because a layout
    that only exists in the browser is not a result (AGENTS.md).
    """
    with _uow(request) as uow:
        base = uow.collab.get_version(version_id)
        task = uow.collab.get_task(base.task_id, user)
        if task.status in {"accepted", "abandoned"}:
            raise ApiError(409, "TASK_TERMINAL", "task is finished")
        try:
            v = canvas_edits.apply_canvas_ops(
                uow, task=task, base_version_id=base.id, ops=body.ops, created_by="user",
            )
        except canvas_edits.CanvasEditError as e:
            raise ApiError(409 if e.code == "STALE_CANVAS" else 400, e.code, e.message) from e
        uow.commit()
        return version_view(uow, v)


@api.route("POST", "/versions/{version_id}/signal", rate="write")
def signal(
    version_id: str, body: SignalIn, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        v = uow.collab.set_signal(version_id, user, body.signal)
        uow.commit()
        return version_view(uow, v)


# ---- feedback & constraints ------------------------------------------------
@api.route("GET", "/tasks/{task_id}/feedback", rate="read")
def feedback(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        uow.collab.get_task(task_id, user)
        return [feedback_view(f) for f in uow.collab.feedback_list(task_id)]


@api.route("POST", "/tasks/{task_id}/feedback/{fb_id}/dismiss", rate="write")
def dismiss(
    task_id: str, fb_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, str]:
    with _uow(request) as uow:
        uow.collab.get_task(task_id, user)
        uow.collab.dismiss_feedback(task_id, fb_id)
        uow.commit()
    return {"status": "dismissed"}


@api.route("GET", "/tasks/{task_id}/constraints", rate="read")
def constraints(
    task_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        uow.collab.get_task(task_id, user)
        cs = uow.collab.constraints(task_id)
        return {k: [constraint_view(c) for c in v] for k, v in cs.items()}


@api.route("POST", "/constraints/{constraint_id}/confirm", rate="write")
def confirm_constraint(
    constraint_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        c = uow.collab.confirm_constraint(constraint_id, user)
        uow.commit()
        return constraint_view(c)


@api.route("POST", "/constraints/{constraint_id}/revoke", rate="write")
def revoke_constraint(
    constraint_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        c = uow.collab.revoke_constraint(constraint_id, user)
        uow.commit()
        return constraint_view(c)


# ---- preferences -------------------------------------------------------------
@api.route("GET", "/agents/{agent_id}/preferences", rate="read")
def get_prefs(
    agent_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        body, rev = uow.prefs.current(user, agent_id)
        return {"body_md": body, "revision": rev}


@api.route("PUT", "/agents/{agent_id}/preferences", rate="write")
def put_prefs(
    agent_id: str, body: PrefBody, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        rev = uow.prefs.save(user, agent_id, body.body_md)
        uow.commit()
        return {"body_md": body.body_md, "revision": rev}


@api.route("GET", "/agents/{agent_id}/preferences/proposals", rate="read")
def list_proposals(
    agent_id: str, request: Request, user: str = Depends(current_user)
) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [{"id": p.id, "text": p.text} for p in uow.prefs.proposals(user, agent_id)]


@api.route("POST", "/agents/{agent_id}/preferences/proposals/{proposal_id}/accept", rate="write")
def accept_proposal(
    agent_id: str, proposal_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, Any]:
    with _uow(request) as uow:
        rev = uow.prefs.accept(user, proposal_id)
        uow.commit()
        return {"revision": rev}


@api.route("POST", "/agents/{agent_id}/preferences/proposals/{proposal_id}/reject", rate="write")
def reject_proposal(
    agent_id: str, proposal_id: str, request: Request, user: str = Depends(current_user)
) -> dict[str, str]:
    with _uow(request) as uow:
        uow.prefs.reject(user, proposal_id)
        uow.commit()
    return {"status": "rejected"}
