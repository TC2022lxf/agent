"""Canvas edits as one operation: validate against the current Version, commit a new one.

Two callers need this and must not drift apart: the HTTP route a user's drag posts to, and the
MCP server an external agent drives (decisions/0030). Both go through `CanvasEditor`, so a
write from Claude Code obeys exactly the same version rules as a drag in the browser.
"""

from __future__ import annotations

import json
from typing import Any

from app.domain import canvas as canvas_domain
from app.persistence.models import Task, Version
from app.services.collab import NotFound
from app.services.uow import UnitOfWork


class CanvasEditError(Exception):
    """A refused edit. `code` mirrors the API error codes so both callers report the same thing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.message = code, message


def canvas_snapshot(uow: UnitOfWork, task: Task) -> dict[str, Any]:
    """The board as an outside agent needs to see it: screens, text, prompts, image URLs.

    Image modules report both the Version the board points at and the URL to fetch the bytes,
    because an agent that only got ids could not look at the picture it is asked to change.
    """
    version = uow.collab.canvas_version(task.id)
    if version is None:
        return {
            "task_id": task.id, "task_kind": task.kind, "goal": task.goal,
            "version_id": None, "seq": None, "theme": None,
            "screens": [], "edges": [], "images": [], "versions": [],
        }
    body = canvas_domain.upgrade(version.content)
    screens: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for screen in body.get("screens", []):
        modules: list[dict[str, Any]] = []
        for module in screen.get("modules", []):
            item = dict(module)
            if module.get("kind") == "image":
                vid = (version.manifest or {}).get(module["id"])
                pic = uow.collab.get_version(vid) if vid else None
                item["version_id"] = vid
                item["url"] = (
                    _blob_url(str(pic.content["object_key"]))
                    if pic is not None and pic.content.get("object_key") else None
                )
                item["width"] = pic.content.get("width") if pic is not None else None
                item["height"] = pic.content.get("height") if pic is not None else None
                images.append({
                    "module_id": module["id"],
                    "screen_id": screen["id"],
                    "slot": module.get("slot"),
                    "name": module.get("name") or "",
                    "prompt": module.get("prompt") or "",
                    "ref": module.get("ref") or None,
                    "version_id": vid,
                    "url": item["url"],
                })
            modules.append(item)
        screens.append({**{k: v for k, v in screen.items() if k != "modules"}, "modules": modules})
    artifact = uow.collab.canvas_artifact(task.id)
    versions = [
        {"id": v.id, "seq": v.seq, "status": v.status, "created_by": v.created_by,
         "origin": v.origin, "is_current": v.id == artifact.current_version_id}
        for v in uow.collab.versions_of(artifact.id)
    ]
    return {
        "task_id": task.id,
        "task_kind": task.kind,
        "goal": task.goal,
        "version_id": version.id,
        "seq": version.seq,
        "theme": body.get("theme"),
        "screens": screens,
        "edges": body.get("edges") or [],
        "bounds": canvas_domain.board_bounds(body),
        "images": images,
        "versions": versions,
    }


def apply_canvas_ops(
    uow: UnitOfWork,
    *,
    task: Task,
    base_version_id: str | None,
    ops: list[dict[str, Any]],
    created_by: str,
    origin: str = "user",
    run_id: str | None = None,
    expected_revision: str | None = None,
) -> Version:
    """Apply `ops` onto the current board and commit the result as one new Version.

    `expected_revision` is the opt-in concurrency check for callers that had to read the board
    first (an external agent, or a slow request): if the board moved on, refuse instead of
    silently applying a stale edit. A browser drag omits it, because the gesture is instant.
    """
    artifact = uow.collab.canvas_artifact(task.id, create=True)
    current = (
        uow.collab.get_version(artifact.current_version_id)
        if artifact.current_version_id else None
    )
    base = base_version_id or (current.id if current is not None else None)
    if expected_revision and current is not None and expected_revision != current.id:
        raise CanvasEditError("STALE_CANVAS", "画布已经变了，请重新读取后再改")
    if base_version_id and (current is None or current.id != base_version_id):
        raise CanvasEditError("STALE_CANVAS", "从最新一版继续，才能保存这次改动")
    if current is None and ops:
        # The first edit of an empty board must say what the board is; ops alone cannot.
        raise CanvasEditError(
            "EMPTY_CANVAS", "画布还没有第一版，先用 compose_canvas 或 POST 建一版",
        )
    try:
        content = canvas_domain.apply_ops(current.content if current is not None else {}, ops)
    except canvas_domain.CanvasError as e:
        raise CanvasEditError("BAD_CANVAS", str(e)) from e
    _check_module_versions(uow, task.id, content)
    return uow.collab.commit_canvas_version(
        task_id=task.id,
        content=content,
        base_version_id=base,
        created_by=created_by,
        run_id=run_id,
        origin=origin,
    )


def compose_canvas(
    uow: UnitOfWork,
    *,
    task: Task,
    content: dict[str, Any],
    base_version_id: str | None,
    pointers: dict[str, str] | None = None,
    created_by: str,
    origin: str = "user",
    run_id: str | None = None,
) -> Version:
    """Write a whole board (first draft or a rewrite) as one new Version."""
    try:
        body = canvas_domain.validate_board(content)
    except canvas_domain.CanvasError as e:
        raise CanvasEditError("BAD_CANVAS", str(e)) from e
    _check_module_versions(uow, task.id, body)
    return uow.collab.commit_canvas_version(
        task_id=task.id,
        content=body,
        base_version_id=base_version_id,
        created_by=created_by,
        run_id=run_id,
        origin=origin,
        pointers=pointers,
    )


def _check_module_versions(uow: UnitOfWork, task_id: str, content: dict[str, Any]) -> None:
    """An image module may only point at a picture of this Task (AGENTS.md write boundary)."""
    for slot in canvas_domain.module_slots(content):
        try:
            art = uow.collab.slot_artifact(task_id, slot)
        except NotFound:
            continue
        if art.task_id != task_id:  # pragma: no cover - slot_artifact is scoped by task
            raise CanvasEditError("BAD_CANVAS", f"模块图片不属于这个任务：{slot}")


def _blob_url(key: str) -> str:
    return f"/api/blobs/{key}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)
