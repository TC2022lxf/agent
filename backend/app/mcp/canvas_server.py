"""MCP server: let an external agent (Claude Code, Codex) read and change a canvas.

Modelled on infinite-canvas' canvas-agent, minus the browser relay: our board lives in the
database, so the server talks to the same services the HTTP API uses instead of proxying tool
calls into a page. That means an external write obeys the same rules as a drag in our UI — a
new Version, never an overwrite, and the write boundary still checked.

Scope is deliberately narrow (docs/architecture/system.md): read the board, read every picture and prompt,
apply ops, compose a whole board. No generation, no plugins, no site navigation.

Run it with:
    python -m app.mcp.canvas_server            # stdio, for `claude mcp add` / `codex mcp add`

The user is identified by `CANVAS_MCP_USER` (defaults to the dev identity, like the HTTP API).
Tool functions are plain functions with annotated parameters: the MCP SDK derives each tool's
input schema from that signature, so nothing may wrap them in `*args, **kwargs`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from app.config import Settings
from app.container import Container, build_container
from app.persistence.models import Task, Version
from app.services import canvas_edits

INSTRUCTIONS = """\
You are connected to an e-commerce design canvas. A board holds screens; each screen holds
modules (text and picture) with a position and a size, and a theme that owns every colour.

Rules the server enforces, so you do not have to guess:
- Every change creates a NEW version. Nothing is overwritten, and a refused change changes
  nothing. Call canvas_get_state again after an error.
- Call canvas_get_state before you edit: it returns the version_id to pass as base_version_id.
  If the user kept editing, the server answers STALE_CANVAS; re-read and retry.
- Text colours and fonts are THEME TOKENS (names), never #RRGGBB. The theme is the only place
  a colour is defined.
- Picture modules point at an image version; you cannot invent a picture. Put what the picture
  should be in the module's prompt, and tell the user it needs generating.
- Change only what the user asked about. Do not re-lay out other screens to "improve" them.

Start with canvas_list_tasks if you do not know which canvas to work on.
"""


def _user_id() -> str:
    return os.environ.get("CANVAS_MCP_USER", "").strip() or "dev-user"


def build_server(container: Container | None = None) -> MCPServer:
    c = container or build_container(Settings.from_env())
    server = MCPServer(name="ecommerce-canvas", instructions=INSTRUCTIONS, version="1")

    @contextmanager
    def scope() -> Iterator[Any]:
        """One transaction per tool call. Committed only if the body returns without error."""
        with c.uow_factory() as uow:
            yield uow
            uow.commit()

    def task_of(uow: Any, task_id: str) -> Task:
        task: Task = uow.collab.get_task(task_id, _user_id())
        return task

    def _list_tasks() -> dict[str, Any]:
        with scope() as uow:
            rows = []
            for task in uow.collab.list_tasks(_user_id()):
                if not c.registry.has_agent(task.agent_key):
                    continue
                if "canvas" not in c.registry.agent(task.agent_key).artifact_kinds:
                    continue
                version = uow.collab.canvas_version(task.id)
                rows.append({
                    "task_id": task.id,
                    "goal": task.goal,
                    "kind": task.kind,
                    "status": task.status,
                    "has_canvas": version is not None,
                    "version_id": version.id if version is not None else None,
                    "screens": len(
                        canvas_edits.canvas_snapshot(uow, task)["screens"]
                    ) if version is not None else 0,
                })
            return {"tasks": rows}

    def _get_state(task_id: str) -> dict[str, Any]:
        with scope() as uow:
            return canvas_edits.canvas_snapshot(uow, task_of(uow, task_id))

    def _get_images(task_id: str) -> dict[str, Any]:
        with scope() as uow:
            snapshot = canvas_edits.canvas_snapshot(uow, task_of(uow, task_id))
            return {
                "task_id": task_id,
                "version_id": snapshot["version_id"],
                "images": snapshot["images"],
            }

    def _apply_ops(
        task_id: str,
        ops: list[dict[str, Any]],
        base_version_id: str | None = None,
    ) -> dict[str, Any]:
        with scope() as uow:
            task = task_of(uow, task_id)
            try:
                version: Version = canvas_edits.apply_canvas_ops(
                    uow, task=task, base_version_id=base_version_id, ops=ops,
                    created_by="agent", origin="edited", expected_revision=base_version_id,
                )
            except canvas_edits.CanvasEditError as e:
                # ToolError, not RuntimeError: the message must reach the model so it can fix
                # its own call, instead of the SDK reporting an opaque server crash.
                raise ToolError(f"{e.code}: {e.message}") from e
            return {
                "version_id": version.id,
                "seq": version.seq,
                "changed": len(ops),
                "screens": len(canvas_edits.canvas_snapshot(uow, task)["screens"]),
            }

    def _compose(
        task_id: str,
        content: dict[str, Any],
        base_version_id: str | None = None,
        pointers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with scope() as uow:
            task = task_of(uow, task_id)
            if base_version_id:
                current = uow.collab.canvas_version(task.id)
                if current is not None and current.id != base_version_id:
                    raise ToolError("STALE_CANVAS: 画布已经变了，请重新读取后再写")
            try:
                version: Version = canvas_edits.compose_canvas(
                    uow, task=task, content=content, base_version_id=base_version_id,
                    pointers=pointers, created_by="agent", origin="edited",
                )
            except canvas_edits.CanvasEditError as e:
                raise ToolError(f"{e.code}: {e.message}") from e
            return {"version_id": version.id, "seq": version.seq}

    _list_tasks.__name__ = "_list_tasks"
    server.add_tool(_list_tasks, name="canvas_list_tasks",
                    description="List tasks this user owns that can hold a canvas.")
    server.add_tool(_get_state, name="canvas_get_state",
                    description="Read the whole board: theme, screens, module text and prompts, "
                                "edges, image URLs. Call before editing.")
    server.add_tool(_get_images, name="canvas_get_images",
                    description="Read every picture on the board with its module, prompt, "
                                "version and URL.")
    server.add_tool(_apply_ops, name="canvas_apply_ops",
                    description="Apply a batch of changes to the board as one new version. "
                                "Ops: move_module, resize_module, set_text, set_style, "
                                "set_prompt, add_module, delete_module, move_screen, "
                                "rename_screen, resize_screen, add_screen, delete_screen, "
                                "keep_variant, link_screens, unlink_screens, set_theme.")
    server.add_tool(_compose, name="canvas_compose",
                    description="Write the whole board as one new version. Prefer "
                                "canvas_apply_ops for ordinary edits.")
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
