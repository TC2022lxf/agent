"""Production Agent loop. LangChain and LangGraph are imported only in this file.

`create_agent` runs the tool cycle. The wrapper around each tool validates, commits a
Version, and is idempotent on `(run_id, tool_call_id)`. The checkpointer's thread id
is the run id. Settlement stays in RunExecutor.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphBubbleUp
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from app.agents.prompts import PLAN_CONTRACT
from app.agents.registry import Registry
from app.domain import canvas as canvas_domain
from app.domain import slots as slot_registry
from app.evaluators.base import EvaluatorRegistry
from app.ports import ModelGatewayPort, ObjectStorePort
from app.runtime.commit import commit_output
from app.runtime.guards import ScopeViolation, WriteScopeGuard
from app.runtime.loop import Item, TaskView, stage_of
from app.runtime.tool_runner import ToolRunner
from app.services.collab import NotFound
from app.services.console import PROMPT_KEY, default_prompt_for, render_prompt
from app.services.profiles import thinking_params
from app.services.uow import UowFactory
from app.tools.ask_tools import AskQuestionInput
from app.tools.assist_tools import (
    GenerateImageVariantsInput,
    RequestUploadInput,
    WriteTodosInput,
)
from app.tools.canvas_tools import ComposeCanvasInput, GenerateVariantsInput, ReadCanvasInput
from app.tools.constraint_tools import RecordConstraintInput
from app.tools.version_tools import (
    FixImageInput,
    InspectImageInput,
    ListVersionsInput,
    RestoreVersionInput,
)
from app.tools.edit_listing import EditListingInput
from app.tools.file_tools import ReadFileInput, WriteFileInput
from app.tools.image_tools import EditImageInput, GenerateImageInput
from app.tools.web_tools import WebFetchInput, WebSearchInput


class WorkerStopped(GraphBubbleUp):
    """Raised after a committed tool call so the worker can resume this same run."""


class RunFailed(GraphBubbleUp):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class ListingContextError(ValueError):
    """The planner supplied a listing base that cannot be used for this Task slot."""


@dataclass
class StopAfter:
    """Test hook: raise WorkerStopped after this many new commits. `seen` survives a requeue."""

    commits: int
    seen: int = 0


stop_after: ContextVar[StopAfter | None] = ContextVar("stop_after", default=None)
# The dev database is one SQLite connection. Tool nodes may run in parallel threads.
_TOOL_LOCK = threading.Lock()


@dataclass
class LoopContext:
    run_id: str
    task_id: str
    user_id: str
    agent_key: str
    trace_id: str
    kind: str
    task_meta: dict[str, Any]
    rules: list[dict[str, Any]]
    held: int
    spent: int
    preferences_md: str
    reasoning: bool
    resume: bool
    prior_texts: list[str] = field(default_factory=list)
    skill_id: str | None = None  # `/skill`: this Run is narrowed to one Skill
    attachments: list[dict[str, Any]] = field(default_factory=list)
    target_slot: str | None = None  # the Feedback's write boundary (docs/architecture/data-and-contracts.md, 04)
    target_region: dict[str, float] | None = None  # UI circle; copied into edit_product_image
    # The Version the user pointed at in the UI. It is the picture being edited, so the model
    # must SEE it, not only the current one (docs/architecture/agent-runtime.md).
    target_version_id: str = ""
    # The `ask_question` this sentence answers, when it answers one. The loop needs it to
    # treat the sentence as the missing fact of work already open instead of a fresh brief
    # (a reply "一个电动剃须刀" once became a from-scratch generate call, docs/architecture/system.md).
    replying_to: str = ""
    client_hint: str = ""  # `constraint` / `preference` from the composer chip


@dataclass
class LoopOutcome:
    version_ids: list[str]
    declined: str
    cost: int
    summary_id: str | None = None
    answer: str = ""  # planner `content` when the turn ends with no further tool
    answer_options: list[str] = field(default_factory=list)  # rejection follow-ups only
    human_input_requests: list[dict[str, Any]] = field(default_factory=list)
    # Constraints and preference proposals the model recorded through `record_constraint`.
    # They are already persisted by the time the loop returns; the executor only needs to know
    # one happened, so the Feedback is not marked declined for a turn that did what was asked.
    recorded_constraints: int = 0


@dataclass
class _Session:
    ctx: LoopContext
    uow_factory: UowFactory
    tools: ToolRunner
    evaluators: EvaluatorRegistry
    store: ObjectStorePort
    on_path: Any
    image_caps: set[str]
    max_calls: int
    goal: str = ""
    facts: dict[str, Any] = field(default_factory=dict)
    item: Item | None = None
    on_progress: Any = None  # (stage, detail) -> None; a `step` event for the waiting user
    on_human_input: Any = None  # payload -> None; `human_input_request` run event (ask_question)
    on_delta: Any = None  # (partial text) -> None; `answer_delta` while the reply streams
    on_tool_start: Any = None  # payload -> None; `tool_started` before a Tool runs
    on_todos: Any = None  # items -> None; `todos` run event (the visible plan)
    vision: bool = False  # the bound planner profile declares it can look at pictures
    version_ids: list[str] = field(default_factory=list)
    human_input_requests: list[dict[str, Any]] = field(default_factory=list)
    declined: str = ""
    cost: int = 0
    new_calls: int = 0
    summary_id: str | None = None
    fail: str = ""
    answer: str = ""
    answer_options: list[str] = field(default_factory=list)
    awaiting_user: bool = False
    recorded_constraints: int = 0
    # Evaluator-optimizer: a rejected Version goes back to the model with its numbers, so it
    # can repair in the SAME turn. Bounded, because each retry is another paid image.
    repairs: int = 0
    max_repairs: int = 1
    # The rejected Version the model was given a chance to repair. If the turn ends without a
    # current Version, Runtime still has to say why — a model that answers "完成" after a
    # rejection must not leave the user with a silent no-op.
    awaiting_repair: str = ""
    # Set when Runtime itself has already written the turn's message (a rejected Version says
    # why it was rejected). A model's "完成" must not overwrite a sentence with more detail.
    _runtime_spoke: bool = False
    _partial: str = ""
    _raw: str = ""

    def note_delta(self, piece: str) -> None:
        """Progressive text of the reply currently being written.

        The planner answers in one JSON object, so what arrives is a fragment of JSON, not
        prose. Fragments are accumulated (an escape or a key can be split across two of them)
        and the `content` string inside the accumulated text is what the user can be shown.
        A reply that turns out to be a tool call still streamed its `content` line, which is
        exactly the "why I am waiting" sentence.
        """
        self._raw += piece
        self._partial = _partial_content(self._raw)
        if self._partial and self.on_delta is not None and not self.awaiting_user:
            self.on_delta(self._partial)

    def reset_partial(self) -> None:
        self._partial = ""
        self._raw = ""

    def images_for_planner(self, limit: int = 3) -> list[bytes]:
        """The pictures the model needs to look at, not guess about.

        Without this the planner answered "I cannot read the colour from the current version"
        about a picture it had generated one turn earlier: the payload carried an object key,
        which is a file name to the model, not a picture (docs/architecture/agent-runtime.md).

        The BASE version is included when this turn edits one. "这一版和上一版比一下" and
        "keep what you just did, change only the background" both need the picture being
        edited, and sending only the current one made the model compare a picture with a
        description of itself.
        """
        if not self.vision:
            return []
        wanted: list[str] = []
        if self.ctx.target_version_id:
            wanted.append(self.ctx.target_version_id)
        with self.uow_factory() as uow:
            slots: list[str] = []
            for art in uow.collab.artifacts(self.ctx.task_id):
                if art.kind == "image" and art.slot and art.slot not in slots:
                    slots.append(art.slot)
            for slot in slots[:limit]:
                current = uow.collab.current_version(self.ctx.task_id, slot)
                if current is not None and current.id not in wanted:
                    wanted.append(current.id)
            out: list[bytes] = []
            for vid in wanted[:limit]:
                try:
                    version = uow.collab.get_version(vid)
                except NotFound:
                    continue
                key = (version.content or {}).get("object_key")
                if not isinstance(key, str) or not self.store.exists(key):
                    continue
                out.append(_shrink(self.store.get(key)))
            return out

    def note_review(self, data: dict[str, Any]) -> None:
        """The words that follow a completed Tool call.

        This is the part of the turn the user actually reads: the Tool produced a Version, and
        the model explains what it produced. It used to be dropped (`note_plan` was skipped
        whenever the payload was a review), so a successful turn had an artifact and no
        sentence — and a chat that only renders `answer` events looked stuck on "思考中".

        Two cases stay silent, because in both the turn already has the words it needs:
        `ask_question` (the question card is the message, and a "完成" after it is noise) and
        a rejected Version (`_note_rejection` wrote the reason, which a vendor's "完成" would
        overwrite).
        """
        declined = str(data.get("declined") or "")
        if declined:
            self.declined = declined
        said = str(data.get("content") or "").strip()
        # After `ask_question` the turn's message is the question card plus whatever the model
        # said before calling it. The review that follows only says "完成", which is not an
        # answer to a question the user has not given yet, so it must not replace those words.
        if self.awaiting_user:
            return
        if said and not self._runtime_spoke:
            self.answer = said
        if data.get("path_note"):
            self.on_path(str(data["path_note"]))

    def note_plan(self, data: dict[str, Any]) -> None:
        note = str(data.get("path_note") or "")
        if note:
            self.on_path(note)
        declined = str(data.get("declined") or "")
        if declined:
            self.declined = declined
        # A turn with no tool call still has words for the user. Dropping them made the run
        # look "succeeded" while the screen stayed empty (the model asking for a product).
        said = str(data.get("content") or "").strip()
        if said and not self.awaiting_user:
            self.answer = said

    def finish_planning(self) -> None:
        """After the last plan: never leave a promise with no action behind it.

        The real planner once answered "将调整为纯白背景、商品居中" on an image Task without
        calling any Tool. The Run said succeeded, the picture never changed, and the user had
        no way to tell that nothing happened. A promise of a change must come with a Version,
        or say plainly that it did not happen.
        """
        if self.awaiting_repair:
            # The model was told the rules that failed and chose not to repair. Runtime says
            # so, with the numbers, instead of letting "完成" describe a picture that never
            # became current.
            self._note_rejection(self.awaiting_repair)
            self.declined = "这一版被规则拒绝"
            return
        if self.version_ids or self.declined:
            return
        if not _promises_a_change(self.answer):
            return
        self.declined = self.answer
        # The words were a promise, not a question: buttons would now be answers to a
        # sentence the user is being told did not happen.
        self.answer_options = []
        self.answer = f"{self.answer}\n\n（这一轮没有产生新版本：改图需要一个具体的工具调用。）"

    def phase(self, stage: str, detail: str = "") -> None:
        """One progress line for the waiting user. Cheap: a single appended event row.

        Stages are deliberately few and coarse (`think`, `running`) so the UI can say "思考中"
        and "正在生成图片" without inventing a progress percentage it cannot know.

        This does NOT touch `run.path`: the path is the recorded route a Run took, asserted by
        tests and read as history. Progress is a stream, not a route.
        """
        self.on_progress(stage, detail)

    def remember_summary(self, text: str) -> None:
        """Retained for callers that already hold a summary body; compaction uses
        `runtime/compaction.py` instead, which also records how far the summary reaches."""
        tokens = max(1, len(text) // 4)
        with self.uow_factory() as uow:
            row = uow.collab.add_summary(
                self.ctx.task_id, self.ctx.run_id, text, tokens, "auto",
            )
            run = uow.collab.get_run(self.ctx.run_id)
            refs = dict(run.context_refs or {})
            refs["summary_id"] = row.id
            run.context_refs = refs
            uow.commit()
            self.summary_id = row.id

    def handle(self, name: str, args: dict[str, Any]) -> str:
        with _TOOL_LOCK:
            return self._handle(name, args)

    def _handle(self, name: str, args: dict[str, Any]) -> str:
        args = _plain(args)
        if name == "edit_listing":
            try:
                args = self._fill_listing_context(args)
            except ListingContextError as exc:
                message = str(exc)
                slot = _slot_of(name, args)
                tool_call_id = f"{self.ctx.run_id}:{name}:{_call_identity(name, args, slot)}"
                self._record_error(name, tool_call_id, args, message)
                self.declined = message
                return message
        if self.awaiting_user:
            return "已向用户提问，本轮不要再调用其他工具。"
        if name == "ask_question":
            return self._ask_user(args)
        if name == "record_constraint":
            return self._record_constraint(args)
        if name == "write_todos":
            return self._write_todos(args)
        if name == "request_upload":
            return self._request_upload(args)
        slot = _slot_of(name, args)
        tool_call_id = f"{self.ctx.run_id}:{name}:{_call_identity(name, args, slot)}"
        with self.uow_factory() as uow:
            existing = uow.collab.tool_call(self.ctx.run_id, tool_call_id)
        if existing is not None:
            output = existing.output or {}
            vid = output.get("version_id")
            if isinstance(vid, str):
                self._add_version(vid)
            if existing.status != "ok":
                self.declined = existing.error or "tool failed"
                return existing.error or "tool failed"
            if isinstance(vid, str):
                return json.dumps({"cached": True, "version_id": vid, "status": existing.status})
            # A read tool (search, fetch, read_file) has no version. Replay its body.
            return json.dumps(
                {"status": "ok", "cached": True, "content": output.get("content")},
                ensure_ascii=False,
            )

        if name == "edit_product_image" and "image.edit" not in self.image_caps:
            message = "image profile does not declare image.edit"
            self._record_error(name, tool_call_id, args, message)
            self.declined = message
            return message
        if self.new_calls >= self.max_calls:
            raise RunFailed("run_budget_exceeded")

        meta = self.tools.registry.tool(name).meta
        tool_cost = meta.cost_credits
        available = self.ctx.held - self.ctx.spent - self.cost
        if tool_cost > available:
            # docs/architecture/data-and-contracts.md: reaching the frozen budget stops the Run. It fails instead of quietly
            # declining, so the user sees "预算用完" rather than a tool that did nothing.
            self._record_error(
                name, tool_call_id, args,
                f"运行预算已用完（冻结 {self.ctx.held} 积分，已用 {self.ctx.spent + self.cost}）",
            )
            raise RunFailed("run_budget_exceeded")

        # Search and fetch have no slot and write nothing, so the write boundary does not
        # apply. A turn bound to one slot may still look something up.
        outside = "" if (not meta.writes_version and not slot) else self._outside_scope(slot, name)
        if outside:
            # Refuse BEFORE paying the vendor. The real planner once wrote a first main image
            # to `slot: "image"` on a pdp Task: the picture was drawn, charged, and landed on
            # an Artifact no preview shows. The write boundary has to cost nothing to cross.
            self._record_error(name, tool_call_id, args, outside)
            self.declined = outside
            return outside

        self.on_path(f"tool:{name}")
        if name == "edit_product_image":
            args = self._fill_image_base(args)
            args = self._fill_image_region(args)
        if name == "compose_canvas":
            args = self._fill_canvas_pointers(args)
        if name == "generate_variants":
            args = self._fill_variant_base(args)
        self.phase("running", f"{name}:{slot}")
        # Announce BEFORE the call. The `tool_calls` row is written only after the Tool
        # returns, so a 180s image had no presence on screen until it was already over —
        # the user saw "正在生成图片" and then nothing changed for three minutes. The id is
        # deterministic, so the card that starts here is the same card the timeline later
        # fills in with a result (a card is upserted by `tool_call_id`, never appended twice).
        self._announce_tool(tool_call_id, name, slot, tool_cost, args)
        res = self.tools.call(
            agent_key=self.ctx.agent_key,
            tool_name=name,
            raw_input=args,
            run_id=self.ctx.run_id,
            trace_id=self.ctx.trace_id,
            user_id=self.ctx.user_id,
            tool_call_id=tool_call_id,
            budget_left=self.ctx.held - self.ctx.spent - self.cost,
            preferences_md=self.ctx.preferences_md,
            extras=self._extras(name, slot),
        )
        if res.error is not None or res.output is None:
            message = res.error.message if res.error else "tool failed"
            self._persist(res.record)
            self.declined = message
            return message
        if not meta.writes_version:
            dumped = res.output.model_dump()
            res.record["output"] = dumped
            self._persist(res.record)
            self.cost += res.cost
            self.new_calls += 1
            # A read tool's whole output is its result. Returning only `content` used to be
            # enough when every read tool was web_search/web_fetch/read_file; `list_versions`
            # and `inspect_image` answer in `versions` and `metrics`, so the model would have
            # received an empty object and concluded there was nothing to see.
            return json.dumps(
                {"status": "ok", "result": dumped}, ensure_ascii=False,
            )
        try:
            region = args.get("region") if isinstance(args.get("region"), dict) else None
            WriteScopeGuard.check(res.output, {slot}, region)
        except ScopeViolation as exc:
            res.record["status"] = "error"
            res.record["error"] = str(exc)
            res.record["cost"] = 0
            self._persist(res.record)
            self.declined = str(exc)
            return str(exc)
        return self._commit_tail(args, res, slot)

    def _outside_scope(self, slot: str, name: str) -> str:
        """Why this call may not run at all, or "" when it may.

        Two separate things are checked. The Task kind decides which slots may exist. The
        Feedback's `target_slot` decides which of those this turn may touch: "the main image"
        must not also write the title. Both used to be enforced only *after* the Tool ran,
        which meant a wrong guess still cost a vendor call.
        """
        if not slot_registry.may_write(self.ctx.kind, slot):
            return f"{slot}: this task cannot hold that slot"
        if self.ctx.target_slot and slot != self.ctx.target_slot:
            # A canvas turn is bound to `canvas`, but placing a picture on that canvas needs
            # `canvas_image_N`. Treat the canvas and its own picture slots as one boundary:
            # a bound canvas turn may write its modules, but nothing else (docs/architecture/data-and-contracts.md).
            same_canvas = (
                self.ctx.target_slot == slot_registry.CANVAS_SLOT
                and slot_registry.canvas_module_index(slot) is not None
            )
            if not same_canvas:
                return f"{slot}: this turn is bound to {self.ctx.target_slot}"
        return ""

    def _extras(self, name: str, slot: str) -> dict[str, Any]:
        if name in ("read_canvas", "generate_variants"):
            return {"canvas": self._canvas_payload()}
        if name in ("list_versions", "restore_version", "inspect_image", "fix_image"):
            return self._version_extras()
        if name == "image_variants":
            return self._variant_extras(slot)
        if name == "generate_product_image":
            # A first draft for a product-bound Task must keep the product's real look, so the
            # saved picture is passed as the reference instead of letting the model invent one.
            product = self.ctx.task_meta.get("product")
            key = product.get("reference_key") if isinstance(product, dict) else None
            return {"product_image_key": key} if isinstance(key, str) else {}
        if name != "read_file":
            return {}
        with self.uow_factory() as uow:
            try:
                current = uow.collab.current_version(self.ctx.task_id, slot)
            except NotFound:
                return {"text": None}
        text = current.content.get("text") if current is not None else None
        return {"text": text if isinstance(text, str) else None}

    def _version_extras(self) -> dict[str, Any]:
        """The version history of this Task, for the tools that read or restore one.

        A Tool never touches the database (`tools/base.py`), so the history is gathered here
        and handed in. Each row carries a one-line summary of what the version IS, because
        "v3" alone does not tell a model whether that is the white background one.
        """
        rows: list[dict[str, Any]] = []
        contents: dict[str, dict[str, Any]] = {}
        keys: dict[str, str] = {}
        current_id = ""
        with self.uow_factory() as uow:
            for art in uow.collab.artifacts(self.ctx.task_id):
                slot = art.slot or ""
                if not slot:
                    continue
                current = uow.collab.current_version(self.ctx.task_id, slot)
                if current is not None and current.id == (art.current_version_id or ""):
                    current_id = current.id
                for v in reversed(uow.collab.versions_of(art.id)):
                    content = dict(v.content or {})
                    contents[v.id] = content
                    if isinstance(content.get("object_key"), str):
                        keys[v.id] = content["object_key"]
                    rows.append({
                        "version_id": v.id,
                        "seq": v.seq,
                        "status": v.status,
                        "origin": v.origin,
                        "created_by": v.created_by,
                        "is_current": v.id == art.current_version_id,
                        "slot": slot,
                        "summary": _version_summary(slot, content, v.seq),
                    })
        rows.sort(key=lambda r: (r["slot"], -int(r["seq"])))
        return {
            "versions": rows,
            "contents": contents,
            "object_keys": keys,
            "current_version_id": current_id,
        }

    def _variant_extras(self, slot: str) -> dict[str, Any]:
        """What `image_variants` needs: the base picture and the slot's own shape."""
        extras: dict[str, Any] = {}
        with self.uow_factory() as uow:
            try:
                current = uow.collab.current_version(self.ctx.task_id, slot)
            except NotFound:
                current = None
        if current is not None:
            key = (current.content or {}).get("object_key")
            if isinstance(key, str) and self.store.exists(key):
                extras["reference_png"] = self.store.get(key)
        extras["aspect_ratio"] = slot_registry.aspect_ratio_for(slot)
        return extras

    def _canvas_payload(self) -> dict[str, Any] | None:
        """What `read_canvas` shows the planner: the board plus each picture's version."""
        with self.uow_factory() as uow:
            art = None
            try:
                art = uow.collab.canvas_artifact(self.ctx.task_id)
            except NotFound:
                return None
            current = uow.collab.canvas_version(self.ctx.task_id)
            if current is None:
                return None
            body = canvas_domain.upgrade(current.content)
            screens = []
            for s in body.get("screens", []):
                modules = []
                for m in s.get("modules", []):
                    item = dict(m)
                    if m.get("kind") == "image":
                        item["version_id"] = (current.manifest or {}).get(m["id"])
                    modules.append(item)
                screens.append({
                    **{k: v for k, v in s.items() if k != "modules"}, "modules": modules,
                })
            return {
                "version_id": current.id,
                "seq": current.seq,
                "theme": body.get("theme"),
                "screens": screens,
                "edges": body.get("edges") or [],
                "bounds": canvas_domain.board_bounds(body),
                "artifact_id": art.id,
            }

    def _file_parent(self, slot: str) -> str | None:
        """The current version of whatever this slot holds, file or image."""
        with self.uow_factory() as uow:
            try:
                current = uow.collab.current_version(self.ctx.task_id, slot)
            except NotFound:
                return None
        return current.id if current is not None else None

    def _fill_canvas_pointers(self, args: dict[str, Any]) -> dict[str, Any]:
        """Image modules point at a version. The planner may name only the slot, so fill in the
        slot's current version when the module has no pointer yet (docs/architecture/data-and-contracts.md, 0029)."""
        content = args.get("content")
        if not isinstance(content, dict):
            return args
        pointers = dict(args.get("pointers") or {})
        raw_modules: list[Any] = []
        if isinstance(content.get("screens"), list):
            for s in content["screens"]:
                if isinstance(s, dict) and isinstance(s.get("modules"), list):
                    raw_modules.extend(s["modules"])
        elif isinstance(content.get("modules"), list):
            raw_modules = list(content["modules"])
        with self.uow_factory() as uow:
            for m in raw_modules:
                if not isinstance(m, dict) or m.get("kind") != "image":
                    continue
                mid, slot = m.get("id"), m.get("slot")
                if not isinstance(mid, str) or not isinstance(slot, str):
                    continue
                if pointers.get(mid):
                    continue
                try:
                    current = uow.collab.current_version(self.ctx.task_id, slot)
                except NotFound:
                    continue
                if current is not None:
                    pointers[mid] = current.id
        if pointers:
            args = {**args, "pointers": pointers}
        return args

    def _fill_variant_base(self, args: dict[str, Any]) -> dict[str, Any]:
        """Variants branch from the current board; the planner need not repeat its id."""
        if args.get("base_version_id"):
            return args
        with self.uow_factory() as uow:
            current = uow.collab.canvas_version(self.ctx.task_id)
        if current is None:
            return args
        return {**args, "base_version_id": current.id}

    def _fill_image_base(self, args: dict[str, Any]) -> dict[str, Any]:
        """`edit_product_image` needs a base. The planner may know only the slot, so fill
        `base_version_id` and `base_object_key` from the current version.

        An empty string counts as missing: the schema defaults both to "" so the model is not
        forced to invent an object key, and `setdefault` alone treated that "" as supplied.
        """
        if args.get("base_object_key") and args.get("base_version_id"):
            return args
        slot = str(args.get("slot") or "")
        with self.uow_factory() as uow:
            try:
                current = uow.collab.current_version(self.ctx.task_id, slot)
            except NotFound:
                return args
        if current is None:
            return args
        filled = dict(args)
        if not filled.get("base_version_id"):
            filled["base_version_id"] = current.id
        if not filled.get("base_object_key"):
            filled["base_object_key"] = current.content.get("object_key")
        return filled

    def _listing_base(self, base_id: str, slot: str) -> tuple[str, dict[str, Any]]:
        """Validate an explicit base before reading its content or paying the model.

        Version ids are user/planner supplied and must stay inside the current Task's write
        boundary. A missing, foreign-task, or wrong-slot id cannot be silently ignored: the
        call would otherwise proceed without a base and potentially commit a broken chain.
        """
        try:
            with self.uow_factory() as uow:
                version = uow.collab.get_version(base_id)
                artifact = uow.collab.slot_artifact(self.ctx.task_id, slot)
                if version.task_id != self.ctx.task_id or version.artifact_id != artifact.id:
                    raise ListingContextError(
                        "base_version_id must belong to the current task and slot"
                    )
                return version.id, dict(version.content or {})
        except NotFound as exc:
            raise ListingContextError(
                "base_version_id must belong to the current task and slot"
            ) from exc

    def _fill_listing_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """Restore the Task context the planner often omits from `edit_listing` calls.

        The planner already receives the goal and product facts in its view. A real model,
        however, can call the tool with only `{"slot": "title"}`. Passing that through made the
        listing model write from an empty brief, and the empty reply was committed as a Version.
        Fill missing context here, before the tool-call identity is computed or the vendor is paid.
        """
        filled = dict(args)
        if not str(filled.get("goal") or "").strip():
            filled["goal"] = self.goal
        facts = filled.get("facts")
        if not isinstance(facts, dict) or not facts:
            filled["facts"] = dict(self.facts)

        slot = str(filled.get("slot") or "")
        base_id = str(filled.get("base_version_id") or "")
        base = filled.get("base")

        # A UI-selected base takes precedence over the current Version. Otherwise an edit of
        # the current text should inherit both its id and content without asking the planner
        # to repeat potentially large JSON.
        provided_base = self._listing_base(base_id, slot) if base_id else None
        candidate_id = ""
        candidate_content: dict[str, Any] | None = None
        if self.item is not None and self.item.slot == slot and self.item.base_override:
            candidate_id = self.item.base_override.version_id
            candidate_content = dict(self.item.base_override.content)
        elif provided_base is not None:
            candidate_id, candidate_content = provided_base
        else:
            try:
                with self.uow_factory() as uow:
                    current = uow.collab.current_version(self.ctx.task_id, slot)
                if current is not None:
                    candidate_id = current.id
                    candidate_content = dict(current.content or {})
            except NotFound:
                pass

        if not filled.get("base_version_id") and candidate_id:
            filled["base_version_id"] = candidate_id
        if not isinstance(base, dict) and candidate_content is not None:
            filled["base"] = candidate_content
        if (
            not str(filled.get("instruction") or "").strip()
            and candidate_content is not None
            and self.item is not None
        ):
            filled["instruction"] = self.item.text
        return filled

    def _fill_image_region(self, args: dict[str, Any]) -> dict[str, Any]:
        """The UI circle is the write boundary; the planner must not drop it."""
        if isinstance(args.get("region"), dict) and args["region"].get("w"):
            return args
        reg = self.ctx.target_region
        if not isinstance(reg, dict):
            return args
        try:
            x, y, w, h = float(reg["x"]), float(reg["y"]), float(reg["w"]), float(reg["h"])
        except (KeyError, TypeError, ValueError):
            return args
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            return args
        return {**args, "region": {"x": x, "y": y, "w": w, "h": h}}

    def _record_human_input(self, tool_call_id: str, question: str, options: list[str]) -> None:
        """ask_question is an interaction event, not assistant prose (docs/architecture/agent-runtime.md)."""
        payload = _human_input_payload(tool_call_id, question, options)
        if any(r.get("request_id") == tool_call_id for r in self.human_input_requests):
            self.awaiting_user = True
            return
        self.human_input_requests.append(payload)
        self.awaiting_user = True
        if self.on_human_input is not None:
            self.on_human_input(payload)

    def _ask_user(self, args: dict[str, Any]) -> str:
        """Record a structured question; UI listens for `human_input_request`."""
        tool_call_id = f"{self.ctx.run_id}:ask_question:{_call_identity('ask_question', args, '')}"
        with self.uow_factory() as uow:
            existing = uow.collab.tool_call(self.ctx.run_id, tool_call_id)
        if existing is not None:
            output = existing.output or {}
            q = str(output.get("question") or "")
            opts = _clean_options(output.get("options"))
            if q:
                self._record_human_input(tool_call_id, q, opts)
            return json.dumps({"status": "awaiting_user", "cached": True}, ensure_ascii=False)

        self.on_path("tool:ask_question")
        self.phase("running", "ask_question")
        res = self.tools.call(
            agent_key=self.ctx.agent_key,
            tool_name="ask_question",
            raw_input=args,
            run_id=self.ctx.run_id,
            trace_id=self.ctx.trace_id,
            user_id=self.ctx.user_id,
            tool_call_id=tool_call_id,
            budget_left=self.ctx.held - self.ctx.spent - self.cost,
            preferences_md=self.ctx.preferences_md,
        )
        if res.error is not None or res.output is None:
            message = res.error.message if res.error else "ask_question failed"
            self._persist(res.record)
            self.declined = message
            return message
        dumped = res.output.model_dump()
        res.record["output"] = dumped
        self._persist(res.record)
        self._record_human_input(
            tool_call_id,
            dumped["question"],
            _clean_options(dumped.get("options")),
        )
        return json.dumps({"status": "awaiting_user"}, ensure_ascii=False)

    def _record_constraint(self, args: dict[str, Any]) -> str:
        """Persist a standing rule or a preference proposal. Confirmation is the user's.

        The model decides what a rule is; the database only ever holds a draft. That is the
        whole safety property: an unconfirmed rule must never change what a later Version is
        allowed to be, so the only thing this writes is a `pending` Constraint (or a
        preference proposal) plus the event the UI renders.
        """
        from app.tools.constraint_tools import RecordConstraintInput

        i = RecordConstraintInput.model_validate(args)
        tool_call_id = f"{self.ctx.run_id}:record_constraint:{_call_identity('record_constraint', args, '')}"
        with self.uow_factory() as uow:
            existing = uow.collab.tool_call(self.ctx.run_id, tool_call_id)
            if existing is not None:
                self.recorded_constraints += 1
                return json.dumps(
                    {"status": "ok", "cached": True, "scope": i.scope}, ensure_ascii=False,
                )
        self.on_path("tool:record_constraint")
        self.phase("running", "record_constraint")
        res = self.tools.call(
            agent_key=self.ctx.agent_key,
            tool_name="record_constraint",
            raw_input=args,
            run_id=self.ctx.run_id,
            trace_id=self.ctx.trace_id,
            user_id=self.ctx.user_id,
            tool_call_id=tool_call_id,
            budget_left=self.ctx.held - self.ctx.spent - self.cost,
            preferences_md=self.ctx.preferences_md,
        )
        if res.error is not None or res.output is None:
            message = res.error.message if res.error else "record_constraint failed"
            self._persist(res.record)
            return message
        dumped = res.output.model_dump()
        res.record["output"] = dumped
        self._persist(res.record)
        with self.uow_factory() as uow:
            fb_id = self._feedback_id()
            if i.scope == "user":
                p = uow.prefs.propose(self.ctx.user_id, self.ctx.agent_key, i.text)
                uow.collab.add_event(
                    self.ctx.run_id, "preference_proposed", {"proposal_id": p.id},
                )
            else:
                c = uow.collab.add_constraint_draft(
                    self.ctx.task_id, fb_id, i.text, dict(i.rule or {}),
                )
                uow.collab.add_event(
                    self.ctx.run_id, "constraint_pending", {"constraint_id": c.id},
                )
            # The row starts as `parameter_patch` because the sentence is one request; once a
            # rule is recorded this turn IS a rule turn, and the timeline reads this field to
            # show the constraint card (with its confirm button) instead of a patch row.
            if fb_id:
                fb = uow.collab.get_feedback(fb_id)
                fb.interpretation = "new_constraint"
                fb.extra = {**(fb.extra or {}), "rule": dict(i.rule or {})}
            uow.commit()
        self.recorded_constraints += 1
        return json.dumps(
            {
                "status": "recorded",
                "scope": i.scope,
                "note": (
                    "已记录为偏好提议，用户接受后才写入偏好。"
                    if i.scope == "user"
                    else "已记录为待确认规则，用户确认后才生效。现在照常完成这一轮的请求。"
                ),
            },
            ensure_ascii=False,
        )

    def _feedback_id(self) -> str | None:
        """The Feedback this Run's sentence became. A constraint draft hangs off it so
        confirming the rule closes the right turn."""
        with self.uow_factory() as uow:
            for fb in uow.collab.feedback_for_run(self.ctx.run_id):
                return fb.id
        return None

    def _write_todos(self, args: dict[str, Any]) -> str:
        """The visible plan. Replaces the previous list; nothing but an event is written.

        This is for the user, not for the model: a five-screen canvas showed one `step` line
        at a time and no indication of what was still coming.
        """
        from app.tools.assist_tools import WriteTodosInput

        i = WriteTodosInput.model_validate(args)
        items = [it.model_dump() for it in i.items]
        if self.on_todos is not None:
            self.on_todos(items)
        return json.dumps(
            {
                "status": "ok",
                "done": sum(1 for it in items if it["status"] == "done"),
                "total": len(items),
            },
            ensure_ascii=False,
        )

    def _request_upload(self, args: dict[str, Any]) -> str:
        """Ask for a picture. Same interaction surface as `ask_question`, different payload.

        A free-text `ask_question` ("请上传一张照片") gives the user a text box and no way to
        attach anything; the composer already uploads, so the tool only has to say what it
        wants and stop the turn.
        """
        from app.tools.assist_tools import RequestUploadInput

        i = RequestUploadInput.model_validate(args)
        tool_call_id = (
            f"{self.ctx.run_id}:request_upload:{_call_identity('request_upload', args, '')}"
        )
        payload = _human_input_payload(tool_call_id, i.what, [])
        payload["input_mode"] = "upload"
        payload["source"] = "request_upload"
        if i.for_slot:
            payload["for_slot"] = i.for_slot
        if any(r.get("request_id") == tool_call_id for r in self.human_input_requests):
            self.awaiting_user = True
            return json.dumps({"status": "awaiting_user"}, ensure_ascii=False)
        self.human_input_requests.append(payload)
        self.awaiting_user = True
        if self.on_human_input is not None:
            self.on_human_input(payload)
        self._persist({
            "run_id": self.ctx.run_id,
            "tool_call_id": tool_call_id,
            "agent_key": self.ctx.agent_key,
            "tool_name": "request_upload",
            "tool_version": "1",
            "status": "ok",
            "input": args,
            "output": i.model_dump(),
            "error": None,
            "duration_ms": 0,
            "cost": 0,
        })
        return json.dumps({"status": "awaiting_user"}, ensure_ascii=False)

    def _commit_tail(self, args: dict[str, Any], res: Any, slot: str) -> str:
        base = args.get("base_version_id")
        if not base and "path" in args:
            # Only `write_file` implies "continue from the current text". An image generation
            # with no base is a fresh draft, and must not claim the rejected one as parent.
            base = self._file_parent(slot)
        variants = getattr(res.output, "variants", None)
        if isinstance(variants, list) and variants:
            return self._commit_variants(res, slot, str(base) if base else None)
        vid = commit_output(
            self.uow_factory, self.evaluators, self.store,
            run_id=self.ctx.run_id, task_id=self.ctx.task_id, kind=self.ctx.kind,
            task_meta=self.ctx.task_meta, rules=self.ctx.rules, slot=slot, output=res.output,
            base_version_id=str(base) if base else None,
        )
        dumped = res.output.model_dump()
        dumped["version_id"] = vid
        # `fix_image`/`restore_version` return the picture or text their Version needs. Handing
        # that back to the model is what lets it check the result of its own repair instead of
        # assuming the write worked.
        if slot_registry.is_image_slot(slot):
            dumped["object_key"] = str(getattr(res.output, "object_key", "") or "")
        res.record["output"] = dumped
        self._persist(res.record)
        self._add_version(vid)
        if slot_registry.canvas_module_index(slot) is not None:
            self._place_picture_on_canvas(slot, vid)
        self.cost += res.cost
        self.new_calls += 1
        hook = stop_after.get()
        if hook is not None:
            hook.seen += 1
            if hook.seen >= hook.commits:
                raise WorkerStopped()
        # The evaluator-optimizer edge: a rejected Version goes back to the model WITH its
        # numbers so it can repair in this same turn, instead of being told "ok" and saying
        # "完成" about a picture that never became current.
        rejected = self._after_commit(vid, slot)
        if rejected is not None:
            return json.dumps(
                {"version_id": vid, "status": "rejected", **rejected},
                ensure_ascii=False,
            )
        return json.dumps({"version_id": vid, "status": "ok"})

    def _commit_variants(self, res: Any, slot: str, base: str | None) -> str:
        """Commit each alternative as its own Version; the first one becomes current.

        Alternatives are sibling versions of one slot, not one long history: each keeps
        `variant_of` so the UI can group them and a later `restore_version` can still pick
        one. They are committed in one transaction so a partially drawn set never appears.
        """
        made: list[dict[str, Any]] = []
        first = ""
        total_cost = res.cost
        with self.uow_factory() as uow:
            for index, variant in enumerate(res.output.variants, start=1):
                vid = commit_output(
                    self.uow_factory, self.evaluators, self.store,
                    run_id=self.ctx.run_id, task_id=self.ctx.task_id, kind=self.ctx.kind,
                    task_meta=self.ctx.task_meta, rules=self.ctx.rules, slot=slot,
                    output=variant, base_version_id=base,
                )
                made.append({"version_id": vid, "prompt": variant.prompt})
                first = first or vid
                self._add_version(vid)
            uow.collab.add_event(
                self.ctx.run_id, "variants_created",
                {"slot": slot, "count": len(made), "versions": made},
            )
            uow.commit()
        dumped = res.output.model_dump()
        dumped["version_id"] = first
        dumped["variants"] = made
        res.record["output"] = dumped
        self._persist(res.record)
        self.cost += total_cost
        self.new_calls += 1
        return json.dumps(
            {"status": "ok", "version_ids": [m["version_id"] for m in made], "count": len(made)},
            ensure_ascii=False,
        )

    def _place_picture_on_canvas(self, slot: str, version_id: str) -> None:
        """A picture drawn for a canvas module becomes current on the board, in the same turn.

        `generate_product_image` writes an image slot; the board only shows it once its
        manifest points there. Doing that here means the placeholder a user is looking at is
        replaced by the picture without a second turn (docs/architecture/data-and-contracts.md).
        """
        with self.uow_factory() as uow:
            current = uow.collab.canvas_version(self.ctx.task_id)
            if current is None:
                return
            # Copy first: `upgrade` may hand back the stored dict, and the previous Version
            # must keep the board it was saved with.
            body = copy.deepcopy(canvas_domain.upgrade(current.content))
            target = next(
                (m for s in body.get("screens", []) for m in s.get("modules", [])
                 if m.get("kind") == "image" and m.get("slot") == slot),
                None,
            )
            if target is None:
                return
            picture = uow.collab.get_version(version_id)
            params = picture.params or {}

            def _content(vid: str) -> dict[str, Any] | None:
                row = uow.collab.get_version(vid)
                return row.content if row is not None else None

            ref = canvas_domain.reference_of(
                body,
                current.manifest or {},
                _content,
                reference_object_key=params.get("reference_object_key"),
                base_version_id=params.get("base_version_id"),
                self_id=target["id"],
            )
            if ref:
                target["ref"] = ref
            uow.collab.commit_canvas_version(
                task_id=self.ctx.task_id,
                content=body,
                base_version_id=current.id,
                created_by="agent",
                run_id=self.ctx.run_id,
                pointers={target["id"]: version_id},
            )
            uow.commit()

    def _after_commit(self, vid: str, slot: str) -> dict[str, Any] | None:
        """The rejected-Version payload, or None when the Version became current.

        This is the evaluator-optimizer edge. Before it, a rejected Version produced a
        sentence for the *user* and a `{"status": "ok"}` for the model, which then said
        "完成" about a picture that never became current. The rules are numeric, so the
        numbers are exactly what the model needs to repair in the same turn.

        Two hard limits keep it from becoming a re-roll loop:

        1. `repairs` counts rejections in this Run; past `max_repairs` the model is told
           `retries_left: 0` and Runtime speaks instead (`_note_rejection`).
        2. A retry is never suggested when the remaining budget cannot cover another draw.
           A failed retry costs the same as the first attempt, and a Run that overspends its
           hold is a worse outcome than a picture the user has to ask for again.
        """
        rejected = self._reject_payload(vid, slot)
        if rejected is None:
            # This Version became current, so any earlier rejection is settled.
            self.awaiting_repair = ""
            return None
        self.repairs += 1
        repairable = rejected["can_self_repair"] and self._can_retry(slot)
        rejected["retries_left"] = (
            max(0, self.max_repairs - self.repairs) if repairable else 0
        )
        if rejected["retries_left"] > 0:
            # Still its own turn: the model may call fix_image or draw again.
            self.awaiting_repair = vid
            self.phase("running", f"repair:{slot}")
        else:
            # Out of chances (or nothing left to pay with): the user hears the reason now.
            self._note_rejection(vid)
            self.declined = "这一版被规则拒绝"
            self.awaiting_repair = ""
        return rejected

    def _reject_payload(self, vid: str, slot: str) -> dict[str, Any] | None:
        """The rule result when `vid` was rejected, else None."""
        with self.uow_factory() as uow:
            version = uow.collab.get_version(vid)
            if version.status != "rejected":
                return None
            problems = [
                p
                for e in uow.collab.evaluations(vid)
                if not e.passed
                for p in (e.details or {}).get("problems", [])
            ]
        return {
            "version_id": vid,
            "slot": slot,
            "problems": problems,
            "can_self_repair": _repairable(problems),
        }

    def _rejection_payload(self, vid: str) -> dict[str, Any]:
        payload = self._reject_payload(vid, "")
        return payload or {}

    def _can_retry(self, slot: str) -> bool:
        """Whether drawing again is affordable and plausible.

        A resolution failure (`long side N < 1000`) is not repairable by re-prompting the same
        model, and a retry that cannot be paid for must not be attempted at all.
        """
        if not slot_registry.is_image_slot(slot):
            return False
        meta = self.tools.registry.tool("edit_product_image").meta
        cost = min(meta.cost_credits, self.tools.registry.tool("generate_product_image").meta.cost_credits)
        left = self.ctx.held - self.ctx.spent - self.cost
        return cost <= left and self.new_calls < self.max_calls

    def _note_rejection(self, vid: str) -> None:
        """A rejected Version produced cost and no current version: say why, in the chat.

        Without this the run "succeeded" and the screen showed nothing, which reads as a
        broken agent rather than "the picture did not meet the main-image rules".
        """
        with self.uow_factory() as uow:
            version = uow.collab.get_version(vid)
            if version.status != "rejected":
                return
            problems = [
                p
                for e in uow.collab.evaluations(vid)
                if not e.passed
                for p in (e.details or {}).get("problems", [])
            ]
            slot = uow.collab.artifact(version.artifact_id).slot or ""
        detail = "；".join(problems) or "未通过规则检查"        # Speak, but do not mark the Feedback declined: a Version was produced and paid for.
        # Runtime asks instead of the model: deterministic, no extra model cost, and the
        # options come from the failed checks rather than from the model's imagination.
        options = _next_steps(slot, problems)
        asked = f"这一版被规则拒绝：{detail}。当前版本没有改变。"
        if options:
            asked += "\n" + "\n".join(f"· {o}" for o in options) + "\n你希望哪一种？"
        self.answer = asked
        # Runtime said it: the model's generic "完成" must not replace the actual reason.
        self._runtime_spoke = True

    def _add_version(self, vid: str) -> None:
        if vid not in self.version_ids:
            self.version_ids.append(vid)

    def _announce_tool(
        self, tool_call_id: str, name: str, slot: str, cost: int, args: dict[str, Any],
    ) -> None:
        """Show the call before it runs, so a long Tool has a card while it works.

        `tool_started` is the only event that exists while a Tool is in flight: the durable
        `tool_calls` row is written when it returns (and is what the timeline reads). Both are
        keyed by `tool_call_id`, so the UI upserts one card instead of drawing two.

        The arguments are trimmed: a prompt can be a paragraph, and this event is a status
        line, not a copy of the request. What the user needs while waiting is which Tool and
        which slot — the full input is still in the record that arrives afterwards.
        """
        brief = {
            k: (v if not isinstance(v, str) or len(v) <= 80 else v[:80] + "…")
            for k, v in args.items()
            if k in {"slot", "path", "query", "url", "prompt", "instruction", "operation"}
        }
        self.on_tool_start({
            "tool_call_id": tool_call_id,
            "tool": name,
            "slot": slot or None,
            "cost": cost,
            "args": brief,
        })

    def _record_error(
        self, name: str, tool_call_id: str, args: dict[str, Any], message: str,
    ) -> None:
        self.on_path(f"tool:{name}")
        self._persist({
            "run_id": self.ctx.run_id,
            "tool_call_id": tool_call_id,
            "agent_key": self.ctx.agent_key,
            "tool_name": name,
            "tool_version": "1",
            "status": "error",
            "input": args,
            "output": {},
            "error": message,
            "duration_ms": 0,
            "cost": 0,
        })

    def _persist(self, record: dict[str, Any]) -> None:
        with self.uow_factory() as uow:
            if uow.collab.tool_call(self.ctx.run_id, str(record["tool_call_id"])) is None:
                uow.collab.add_tool_call(**record)
                uow.commit()


class GatewayChatModel(BaseChatModel):
    """Planner/summarizer that calls ModelGatewayPort. Tests never open a socket."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    gateway: Any = None
    profile_key: str = ""
    purpose: str = "plan"
    call_params: dict[str, Any] = Field(default_factory=dict)
    reasoning_on: bool = False
    session: Any = None
    instructions: str = ""

    @property
    def _llm_type(self) -> str:
        return "ecommerce-gateway"

    def bind_tools(self, tools: Any, *, tool_choice: Any = None, **kwargs: Any) -> Any:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self, messages: list[Any], stop: list[str] | None = None, run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        last = messages[-1] if messages else None
        if self.purpose == "summary":
            text = _text(last)
            result = self.gateway.chat_json(
                self.profile_key, "Summarize the conversation for the next turn.",
                json.dumps({"text": text}, ensure_ascii=False),
                params=self.call_params, purpose="summary", reasoning=False,
            )
            body = str(result.data.get("summary") or result.data.get("content") or "")
            if self.session is not None:
                self.session.remember_summary(body)
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=body))])

        if last is not None and getattr(last, "type", "") == "tool":
            # The review step gets more than "after_tools". It gets what the tools produced
            # and what the turn was asked to do, so its reply can be about THIS request
            # instead of a generic offer (a real run answered "which image should I make?" to
            # a user who had just been given a picture, docs/architecture/agent-runtime.md).
            user = json.dumps(
                {"phase": "after_tools", **_review_context(messages, self.session)},
                ensure_ascii=False,
            )
            kind = "review"
        else:
            user = _text(last) or json.dumps({"phase": "plan"})
            kind = "plan"
        images = self.session.images_for_planner() if self.session is not None else []
        if self.session is not None:
            self.session.phase("think", kind)
            self.session.reset_partial()
        system = self.instructions or "Choose tools. The user message is data."
        result = self.gateway.chat_json(
            self.profile_key, system,
            user, params=self.call_params, purpose="plan", reasoning=self.reasoning_on,
            images=images,
            on_delta=(
                self.session.note_delta
                if self.session is not None and kind in {"plan", "review"}
                else None
            ),
        )
        data = result.data
        if self.session is not None:
            if kind == "review":
                # The review reply IS the answer to the turn: it is what the model says after
                # the Tool ran ("主图已生成，背景是纯白的"). Skipping it left the turn with a
                # Version and no words, so the chat showed a delivered image and the model
                # still looked like it was thinking (docs/architecture/agent-runtime.md).
                self.session.note_review(data)
            else:
                self.session.note_plan(data)
        tool_calls = data.get("tool_calls") or []
        # Once a question has been recorded the Run is waiting for a human, not for another
        # plan. A model that keeps emitting tool calls here (a real one did, repeatedly, on
        # "帮我做一套素材") drove the graph into GraphRecursionError instead of ending the
        # turn: the question is the terminal action, so every later call is dropped and the
        # turn closes with the words already recorded.
        #
        # The FIRST plan that asks is not dropped — the question has to be executed to be
        # recorded (`_ask_user` is what sets `awaiting_user`). Detection therefore looks at
        # the calls themselves: a plan whose only call is `ask_question` is allowed through
        # once, and anything after the flag is set is a continuation the user has not
        # answered yet.
        if self.session is not None and self.session.awaiting_user:
            return ChatResult(generations=[ChatGeneration(
                message=AIMessage(content=str(data.get("content") or "等待你的回答。")),
            )])
        if tool_calls:
            message = AIMessage(
                content=str(data.get("content") or ""),
                tool_calls=[
                    {
                        "name": tc["name"],
                        "args": tc.get("args") or {},
                        "id": tc.get("id") or tc["name"],
                        "type": "tool_call",
                    }
                    for tc in tool_calls
                ],
            )
        else:
            message = AIMessage(content=str(data.get("content") or "完成"))
        return ChatResult(generations=[ChatGeneration(message=message)])


def _promises_a_change(text: str) -> bool:
    """Did the model say it would change something, in the future tense?

    Narrow on purpose: it must be a future-tense commitment ("将…", "会…", "正在…"). Plain
    descriptions of the current state, questions and explanations are not promises.
    """
    s = text.strip()
    if not s:
        return False
    if any(w in s for w in ("？", "?")):
        return False
    return any(w in s for w in ("将", "会调整", "会生成", "正在生成", "正在调整", "马上"))


def _repairable(problems: list[str]) -> bool:
    """Whether another draw could plausibly pass.

    A resolution failure is a property of the model's output size, not of the prompt, so
    re-drawing it returns the same failure — those problems are excluded. Whiteness and
    occupancy are prompt-and-composition issues: "make the background pure white, fill more
    of the frame" demonstrably changes them.
    """
    fixable = ("border white fraction", "occupancy")
    return any(any(k in p for k in fixable) for p in problems)


def _next_steps(slot: str, problems: list[str]) -> list[str]:
    """Concrete choices suggested by the failed checks, never invented by the model.

    Only the image rules are covered today; a slot with no mapping gets no options, and the
    caller asks in plain words instead of listing something it cannot deliver.
    """
    if slot not in slot_registry.IMAGE_SLOT_KEYS:
        return []
    out: list[str] = []
    if any("border white fraction" in p for p in problems):
        out.append("重新生成一张纯白无缝背景（会再生成一版）")
        out.append("保留这一版的构图，只把背景和边缘改成纯白")
    if any("occupancy" in p for p in problems):
        out.append("让商品占画面更多，四周留白更少")
        out.append("保持现在的间距，只调整背景")
    if any("long side" in p for p in problems):
        out.append("提高输出分辨率后重试")
    return out


_MAX_OPTIONS = 3
_MAX_OPTION_CHARS = 80


def _clean_options(raw: Any) -> list[str]:
    """Replies offered as buttons under a question.

    A button is a shortcut for typing one of a few plausible replies, not a menu: keep it
    short, deduplicated, and at most three. Anything longer is dropped rather than shown as
    an unreadable wall of text.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if not text or len(text) > _MAX_OPTION_CHARS or text in out:
            continue
        out.append(text)
        if len(out) >= _MAX_OPTIONS:
            break
    return out


def _call_identity(name: str, args: dict[str, Any], slot: str) -> str:
    """What makes this call the same call again inside one Run.

    A slot is written at most once per Run. A search is once per query: two different
    queries must not collapse into the first result.
    """
    if name == "web_search":
        key = str(args.get("query") or "").strip()
    elif name == "web_fetch":
        key = str(args.get("url") or "").strip()
    else:
        return slot or name
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _version_summary(slot: str, content: dict[str, Any], seq: int) -> str:
    """One line a model can recognise a version by: `标题：xxx`, `图片 1000x1000`."""
    if isinstance(content.get("object_key"), str):
        w, h = content.get("width"), content.get("height")
        return f"图片 {w}x{h}" if w and h else "图片"
    text = content.get("text")
    if isinstance(text, str) and text.strip():
        head = text.strip().replace("\n", " ")[:40]
        return f"{slot}：{head}"
    items = content.get("items")
    if isinstance(items, list) and items:
        return f"{slot}：{len(items)} 条，首条 {str(items[0])[:30]}"
    if isinstance(content.get("filename"), str):
        return f"文件 {content['filename']}"
    if content.get("screens"):
        return f"画布 {len(content['screens'])} 屏"
    return f"v{seq}"


def _slot_of(tool_name: str, args: dict[str, Any]) -> str:
    """The slot a tool call writes. The canvas tools have no `slot` field: they write the board."""
    if tool_name in ("compose_canvas", "generate_variants"):
        return slot_registry.CANVAS_SLOT
    raw = str(args.get("slot") or args.get("path") or "")
    if not raw or "." not in raw:
        return raw
    try:
        return slot_registry.normalize_file_name(raw)
    except ValueError:
        return raw

def _plain(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


def _text(message: Any) -> str:
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _review_context(messages: list[Any], session: Any) -> dict[str, Any]:
    """What the review step needs to answer about the turn that just ran.

    LangGraph hands the model `{phase: after_tools}` and nothing else, so the model knew a
    tool had run but not which one, what it returned, or what the user had asked. That is how
    a run that had just produced a picture ended with "What image should I make, and what
    product is it for?". The facts are already in the graph state; they were simply not passed
    on (docs/architecture/agent-runtime.md).
    """
    request = ""
    for message in messages:
        if getattr(message, "type", "") != "human":
            continue
        raw = getattr(message, "content", "")
        if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        item = payload.get("item")
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            request = item["text"]
    results: list[dict[str, Any]] = []
    for message in reversed(messages):
        if getattr(message, "type", "") != "tool":
            continue
        results.append({
            "tool": getattr(message, "name", ""),
            "result": _text(message)[:600],
        })
        if len(results) >= 4:
            break
    results.reverse()
    out: dict[str, Any] = {"request": request, "tool_results": results}
    if session is not None and session.version_ids:
        out["versions_written"] = list(session.version_ids)
    return out


_MAX_IMAGE_EDGE = 1024

def _shrink(png: bytes) -> bytes:
    """A planner does not need a 2048px picture to answer "what colour is it".

    Sending the stored bytes unchanged multiplies the input cost of every turn that attaches
    a reference, and most vision endpoints downscale anyway. Oversized pictures are re-encoded
    once, here, instead of at each call site.
    """
    try:
        img = Image.open(io.BytesIO(png))
        img.load()
    except Exception:  # noqa: BLE001 - not a decodable image: let the caller skip it
        return png
    if max(img.size) <= _MAX_IMAGE_EDGE:
        return png
    img.thumbnail((_MAX_IMAGE_EDGE, _MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


_CONTENT_KEY = '"content"'


def _partial_content(partial: str) -> str:
    """The `content` string of a half-written plan object, decoded so far.

    The planner streams one JSON object. Everything before the content value is syntax the
    user must not see, and the string itself may be cut mid-escape, so the tail is dropped
    when it would start an escape sequence.
    """
    at = partial.find(_CONTENT_KEY)
    if at < 0:
        return ""
    rest = partial[at + len(_CONTENT_KEY):].lstrip()
    if not rest.startswith(":"):
        return ""
    rest = rest[1:].lstrip()
    if not rest.startswith('"'):
        return ""
    body = rest[1:]
    # Walk the string so an escaped quote does not end it early, and a half-written escape at
    # the tail is dropped instead of being decoded as a broken sequence.
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            if i + 1 >= len(body):
                break  # a lone backslash: the escape has not arrived yet
            nxt = body[i + 1]
            if nxt == "u":
                if i + 5 >= len(body):
                    break  # a partial \uXXXX
                try:
                    out.append(json.loads(f'"{body[i:i + 6]}"'))
                except json.JSONDecodeError:
                    break
                i += 6
                continue
            mapped = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}.get(nxt)
            if mapped is None:
                break
            out.append(mapped)
            i += 2
            continue
        if ch == '"':
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


class LangGraphLoop:
    def __init__(
        self,
        uow_factory: UowFactory,
        registry: Registry,
        evaluators: EvaluatorRegistry,
        gateway: ModelGatewayPort,
        store: ObjectStorePort,
        tool_runner: ToolRunner,
        *,
        database_url: str,
    ) -> None:
        self.uow_factory = uow_factory
        self.registry = registry
        self.evaluators = evaluators
        self.gateway = gateway
        self.store = store
        self.tools = tool_runner
        self.database_url = database_url
        self._checkpointer: Any = None

    def run(self, item: Item, view: TaskView, ctx: LoopContext) -> LoopOutcome:
        with self.uow_factory() as uow:
            profile = uow.profiles.planner_for_agent(ctx.agent_key)
            image = uow.profiles.image_profile()
            max_calls = uow.profiles.max_tool_calls()
            spec = self.registry.agent(ctx.agent_key)
            # The agent's own text is the base; the console overrides it per agent key.
            # `system_prompt_ref` is the name of that text, so the two cannot drift apart.
            template = uow.console.get(
                PROMPT_KEY.format(key=spec.system_prompt_ref),
                default_prompt_for(spec.system_prompt_ref),
            )
            window = profile.context_window_tokens
            profile_key = profile.key
            mode = str((profile.reasoning or {}).get("mode") or "unsupported")
            params = {} if mode == "unsupported" else thinking_params(profile, ctx.reasoning)
            reasoning_on = mode == "required" or (mode == "optional" and ctx.reasoning)
            vision = "vision" in (profile.capabilities or [])
        skills = [s for s in self.registry.skills_for(ctx.agent_key) if s.id in spec.skill_ids]
        if ctx.skill_id:
            skills = [s for s in skills if s.id == ctx.skill_id]
        system = render_prompt(
            template, agent=spec.title,
            tools=list(spec.tool_names),
            skills=[s.id for s in skills],
        )
        # Tool and Skill catalogues follow the role text: the model reads what it can do
        # after it reads what it is for.
        system += (
            "\n<tools_available>\n"
            + ("\n".join(f"- {t}" for t in spec.tool_names) or "- (none)")
            + "\n</tools_available>\n"
        )
        system += (
            "\n<skills_available>\n"
            "Skill bodies load on demand; only their names and one-line purposes are listed.\n"
            + ("\n".join(f"- {s.id}: {s.description}" for s in skills) or "- (none)")
            + "\n</skills_available>\n"
        )
        if ctx.skill_id:
            chosen = next((s for s in skills if s.id == ctx.skill_id), None)
            if chosen is not None:
                system += f"\n<active_skill name=\"{chosen.id}\">\n{chosen.body}\n</active_skill>"
        caps = set(image.capabilities or []) if image is not None else set()
        session = _Session(
            ctx, self.uow_factory, self.tools, self.evaluators, self.store,
            _path_writer(self.uow_factory), caps, max_calls,
            goal=view.goal, facts=dict(view.facts), item=item,
            on_progress=_progress_writer(self.uow_factory),
            on_human_input=_human_input_writer(self.uow_factory),
            on_delta=_answer_delta_writer(self.uow_factory),
            on_tool_start=_tool_start_writer(self.uow_factory),
            on_todos=_todos_writer(self.uow_factory),
            vision=vision,
        )
        model = GatewayChatModel(
            gateway=self.gateway, profile_key=profile_key, purpose="plan",
            call_params=params, reasoning_on=reasoning_on, session=session,
            instructions=system + "\n" + PLAN_CONTRACT,
            profile={"max_input_tokens": window} if window else None,
        )
        # Compaction is ours, not the middleware's: it happens once per turn in the executor
        # and its result is stored, so a later turn reads the same summary instead of
        # re-summarizing (runtime/context.py, runtime/compaction.py).
        agent = create_agent(
            model, _graph_tools(session, spec.tool_names), system_prompt=system,
            checkpointer=self._saver(), name="ecommerce",
        )
        payload: dict[str, Any] = {
            "phase": "plan", "item": _item(item), "view": _view(view, ctx.resume, ctx.client_hint),
        }
        if ctx.client_hint:
            payload["client_hint"] = ctx.client_hint
        if ctx.replying_to:
            # This sentence answers the Agent's own question. Without it the model read an
            # answer ("一个电动剃须刀") as a brand-new brief and drew from scratch.
            payload["replying_to"] = ctx.replying_to
        if ctx.skill_id:
            payload["skill"] = ctx.skill_id
        if ctx.attachments:
            payload["attachments"] = ctx.attachments
        messages: list[Any] = [HumanMessage(content=text) for text in ctx.prior_texts]
        messages.append(HumanMessage(content=json.dumps(payload, ensure_ascii=False)))
        agent.invoke(
            {"messages": messages},
            config={
                "configurable": {"thread_id": ctx.run_id},
                "recursion_limit": 25,
                "max_concurrency": 1,
            },
        )
        session.finish_planning()
        return LoopOutcome(
            session.version_ids, session.declined, session.cost, session.summary_id,
            answer=session.answer, answer_options=session.answer_options,
            human_input_requests=list(session.human_input_requests),
        )

    def _saver(self) -> Any:
        if self._checkpointer is None:
            url = self.database_url
            memory = url in {"sqlite://", "sqlite:///:memory:"} or ":memory:" in url
            if memory:
                from langgraph.checkpoint.memory import MemorySaver

                self._checkpointer = MemorySaver()
            else:
                import sqlite3

                from langgraph.checkpoint.sqlite import SqliteSaver

                path = self._checkpoint_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(path), check_same_thread=False)
                self._checkpointer = SqliteSaver(conn)
        return self._checkpointer

    def _checkpoint_path(self) -> Any:
        from pathlib import Path

        url = self.database_url
        if url.startswith("sqlite:///"):
            parent = Path(url.removeprefix("sqlite:///")).parent
            if str(parent) not in {"", "."}:
                return parent / "checkpoints.sqlite"
        return Path("./data/checkpoints.sqlite")


def _path_writer(uow_factory: UowFactory) -> Any:
    def write(step: str) -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        with uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            path = list(run.path or [])
            if step.startswith("tool:") or step not in path:
                run.path = [*path, step]
            # A `step` event is what the waiting user sees. Without it the only progress was
            # one "已读取偏好与约束" line, so a two-minute image looked hung (docs/architecture/system.md).
            uow.collab.add_event(
                run_id, "step", {"stage": stage_of(step), "detail": step},
            )
            uow.commit()

    return write


def _human_input_payload(tool_call_id: str, question: str, options: list[str]) -> dict[str, Any]:
    opts = [{"id": f"o{i}", "label": o, "value": o} for i, o in enumerate(options)]
    return {
        "version": 1,
        "kind": "human_input_request",
        "source": "ask_question",
        "request_id": tool_call_id,
        "tool_call_id": tool_call_id,
        "question": question,
        "input_mode": "single_choice" if opts else "text",
        "options": opts,
    }


def _human_input_writer(uow_factory: UowFactory) -> Any:
    """Persist and stream a deer-flow-shaped human_input_request."""

    def write(payload: dict[str, Any]) -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        rid = payload.get("request_id")
        with uow_factory() as uow:
            if rid:
                for e in uow.collab.events_after(run_id, 0):
                    if e.type == "human_input_request" and e.data.get("request_id") == rid:
                        return
            uow.collab.add_event(run_id, "human_input_request", payload)
            uow.commit()

    return write


def _todos_writer(uow_factory: UowFactory) -> Any:
    """Persist the visible plan. One event per call: the newest list is the current plan.

    Written as a `todos` event rather than a step so the UI can render a checklist and a
    reconnecting client gets the last complete list, not a replay of every revision.
    """

    def write(items: list[dict[str, Any]]) -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        with uow_factory() as uow:
            uow.collab.add_event(run_id, "todos", {"items": items})
            uow.commit()

    return write


def _progress_writer(uow_factory: UowFactory) -> Any:
    """Append a `step` event so the waiting user sees the phase change.

    Only the event, never `run.path`: the path is the recorded route of a Run and is asserted
    by tests; progress is a live stream that may repeat (`think` happens before every plan).
    """

    def write(stage: str, detail: str = "") -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        with uow_factory() as uow:
            uow.collab.add_event(
                run_id, "step", {"stage": stage, "detail": detail},
            )
            uow.commit()

    return write


def _tool_start_writer(uow_factory: UowFactory) -> Any:
    """Persist `tool_started` so the waiting user sees the call, not just a phase word.

    Written once per (run, tool_call_id): LangGraph may re-enter a step after a worker
    restart, and a resumed Run must not draw the same card a second time.
    """

    def write(payload: dict[str, Any]) -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        rid = payload.get("tool_call_id")
        with uow_factory() as uow:
            if isinstance(rid, str):
                for e in uow.collab.events_after(run_id, 0):
                    if e.type == "tool_started" and e.data.get("tool_call_id") == rid:
                        return
            uow.collab.add_event(run_id, "tool_started", payload)
            uow.commit()

    return write


def _answer_delta_writer(uow_factory: UowFactory) -> Any:
    """Push the reply text as it is written, so the user is not staring at "思考中".

    One event per change would be one row per token. `answer_delta` therefore carries the
    whole text so far, not a fragment: a late subscriber and a reconnecting client both get a
    complete value, and the frontend replaces rather than concatenates. The final, authoritative
    text still arrives as an `answer` event when the Run settles.

    Writes are throttled by growth and by time: a row per token would be thousands of rows for
    one paragraph, and SSE polls four times a second anyway.
    """
    last: dict[str, Any] = {"text": "", "at": 0.0}

    def write(text: str) -> None:
        from app.infrastructure.gateway_logging import current_run_id

        run_id = current_run_id.get()
        if not run_id:
            return
        now = time.monotonic()
        if text == last["text"]:
            return
        if len(text) - len(last["text"]) < 12 and now - last["at"] < 0.9:
            return
        last["text"], last["at"] = text, now
        with uow_factory() as uow:
            uow.collab.add_event(run_id, "answer_delta", {"text": text})
            uow.commit()

    return write


def _graph_tools(session: _Session, allowed: tuple[str, ...]) -> list[StructuredTool]:
    specs: list[tuple[str, type[BaseModel], str]] = [
        ("edit_listing", EditListingInput, "Write or revise one listing text slot."),
        ("generate_product_image", GenerateImageInput, "Generate the first image version."),
        ("edit_product_image", EditImageInput, "Edit an existing image version."),
        ("write_file", WriteFileInput, "Write one text file as a new version."),
        ("read_file", ReadFileInput, "Read the current text of one file."),
        ("web_search", WebSearchInput,
         "Search the public web. Returns titles, urls and snippets. Does not write a Version."),
        ("web_fetch", WebFetchInput,
         "Fetch one public http(s) page as markdown. Does not write a Version."),
        ("read_canvas", ReadCanvasInput, "Read the current canvas board."),
        ("compose_canvas", ComposeCanvasInput, "Write the canvas board as a new version."),
        ("generate_variants", GenerateVariantsInput, "Branch a screen into side-by-side variants."),
        ("ask_question", AskQuestionInput,
         "Ask the user one question with optional reply buttons. Does not write a Version."),
        ("record_constraint", RecordConstraintInput,
         "Record a rule that must keep holding for later turns, or propose a user preference. "
         "The user confirms it before it takes effect; it never writes a Version."),
        ("list_versions", ListVersionsInput, "List the versions this Task already has."),
        ("restore_version", RestoreVersionInput, "Make an earlier version current again."),
        ("inspect_image", InspectImageInput,
         "Measure an image version against the platform rules. Does not write a Version."),
        ("image_variants", GenerateImageVariantsInput,
         "Draw 2-4 alternatives of one picture so the user can pick a direction."),
        ("fix_image", FixImageInput,
         "Repair a picture deterministically (white border, subject size, square padding). "
         "No model call, no credits."),
        ("write_todos", WriteTodosInput, "Show the user the plan you are working through."),
        ("request_upload", RequestUploadInput,
         "Ask the user to upload a picture you need. Does not write a Version."),
    ]
    specs = [item for item in specs if item[0] in allowed]

    def bind(name: str, schema: type[BaseModel], description: str) -> StructuredTool:
        def run(**kwargs: Any) -> str:
            return session.handle(name, kwargs)

        return StructuredTool.from_function(
            run, name=name, description=description, args_schema=schema,
        )

    return [bind(*spec) for spec in specs]


def _item(item: Item) -> dict[str, Any]:
    override = None
    if item.base_override is not None:
        override = {
            "version_id": item.base_override.version_id,
            "content": item.base_override.content,
        }
    return {
        "text": item.text,
        "slot": item.slot,
        "region": item.region,
        "operation": item.operation,
        "base_override": override,
    }


def _view(view: TaskView, resume: bool, client_hint: str = "") -> dict[str, Any]:
    """The Task as the planner sees it: what exists, what may be written, the rules."""
    out = {
        "kind": view.kind,
        "goal": view.goal,
        "current": {
            slot: {"version_id": state.version_id, "content": state.content}
            for slot, state in view.current.items()
        },
        "writable_slots": _writable_slots(view.kind),
        "user_rules": view.user_rules,
        "facts": view.facts,
        "resume": resume,
    }
    if client_hint:
        # A chip on the composer ("写入我的偏好" / a constraint): the user already said what
        # kind of sentence this is, so the model does not have to infer it.
        out["client_hint"] = client_hint
    return out


def _slot_hint(kind: str, key: str, description: str) -> str:
    """Say which image slot this is, because a general Task has two with different meanings.

    Without this the planner picked `main_image` for "生成图片" on a general Task: both are
    images, and nothing in the payload said one belongs to the PDP and one does not.
    """
    if key != "image" or not slot_registry.is_multi_artifact(kind):
        return description
    if kind == "canvas":
        return "Standalone image for the page, not a PDP slot."
    return (
        "Standalone picture in this conversation (not a PDP slot). Use this for a "
        "one-off image request; `main_image` is the PDP main image and changes the PDP."
    )


def _writable_slots(kind: str) -> list[dict[str, Any]]:
    """What `slot` / `path` may be on this Task. The model used to have to guess these.

    Sizes are not repeated here: the constraint pack owns the numbers (docs/architecture/data-and-contracts.md).
    """
    out: list[dict[str, Any]] = []
    if kind == "canvas":
        keys = [slot_registry.CANVAS_SLOT, "image"]
    elif slot_registry.is_multi_artifact(kind):
        keys = [*slot_registry.PDP_SLOT_ORDER, "image", slot_registry.CANVAS_SLOT]
    else:
        keys = list(slot_registry.slots_for_task_kind(kind))
    for key in keys:
        if slot_registry.has_slot(key):
            s = slot_registry.get_slot(key)
            out.append({
                "slot": s.key, "value_type": s.value_type,
                "artifact_kind": s.artifact_kind,
                "description": _slot_hint(kind, key, s.description),
            })
        else:
            out.append({
                "slot": key, "value_type": "image",
                "description": _slot_hint(kind, key, "Standalone image"),
            })
    if kind == "canvas":
        out.append({
            "slot": "canvas_image_N", "value_type": "image",
            "description": "画布里第 N 个图像模块的图，例如 canvas_image_1",
        })
    if kind == "file" or slot_registry.is_multi_artifact(kind):
        out.append({
            "slot": "任意文件名", "value_type": "file",
            "description": "write_file 的 path，例如 page.html、notes.md、table.csv",
        })
    return out

