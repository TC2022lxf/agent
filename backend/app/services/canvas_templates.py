"""Open a canvas template as a real Task: finished pictures are Versions, not decorations.

The board's prompts and `ref` links are the template. The picture bytes are drawn here and
stored like any other image Version, so the workspace shows them the same way it shows a
picture the Agent just generated.
"""

from __future__ import annotations

import copy
import io
from uuid import uuid4

from PIL import Image, ImageDraw

from app.domain import canvas as canvas_domain
from app.domain.canvas_templates import PictureSpec, get_template
from app.persistence.models import Task
from app.ports import ObjectStorePort
from app.services.uow import UnitOfWork


class UnknownTemplate(KeyError):
    """No template with this id."""


def instantiate(uow: UnitOfWork, store: ObjectStorePort, user_id: str, template_id: str) -> Task:
    try:
        spec = get_template(template_id)
    except KeyError as exc:
        raise UnknownTemplate(template_id) from exc
    task = uow.collab.create_task(
        user_id, "canvas", "canvas", spec.goal, {"template": spec.id},
    )
    pointers: dict[str, str] = {}
    for picture in spec.pictures:
        png = _draw(picture)
        key = f"images/template-{spec.id}-{picture.module_id}-{uuid4().hex}.png"
        store.put(key, png)
        width, height = Image.open(io.BytesIO(png)).size
        version = uow.collab.commit_candidate(
            task_id=task.id,
            slot=_slot(spec.board, picture.module_id),
            content={"object_key": key, "width": width, "height": height},
            params={"prompt": picture.prompt, "template": spec.id},
            origin="generated",
            created_by="user",
            run_id=None,
            parent_version_id=None,
        )
        uow.collab.finalize_version(version, accepted=True)
        pointers[picture.module_id] = version.id
    uow.collab.commit_canvas_version(
        task_id=task.id,
        content=canvas_domain.validate_board(copy.deepcopy(spec.board)),
        base_version_id=None,
        created_by="user",
        run_id=None,
        origin="generated",
        pointers=pointers,
    )
    task.status = "awaiting_user"
    return task


def _slot(board: dict, module_id: str) -> str:
    for screen in board["screens"]:
        for module in screen["modules"]:
            if module["id"] == module_id:
                slot = module.get("slot")
                if isinstance(slot, str):
                    return slot
    raise UnknownTemplate(module_id)


def _draw(picture: PictureSpec) -> bytes:
    """A small stand-in picture. Distinct colours so two modules are not the same image."""
    size = 768
    img = Image.new("RGB", (size, size), picture.swatch)
    draw = ImageDraw.Draw(img)
    margin = 72
    draw.rounded_rectangle(
        (margin, margin, size - margin, size - margin), radius=48, fill=picture.accent,
    )
    draw.ellipse((size * 0.34, size * 0.34, size * 0.66, size * 0.66), fill=picture.swatch)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
