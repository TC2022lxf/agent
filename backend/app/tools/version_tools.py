"""Version history, self-inspection and deterministic repair for image slots.

Three gaps this closes, all of them "the agent had no way to look before acting":

- `list_versions` / `restore_version`: the version history existed in the database but no
  tool could read or return to it, so "用回第 2 版" could only be answered by drawing again.
- `inspect_image`: the rule evaluator computes measurable numbers and then shows them to the
  *user* — the model never saw them. It could submit a picture that fails, be told "完成",
  and never learn why.
- `fix_image`: two of the three main-image rules (border whiteness, subject occupancy) are
  fixable with PIL in milliseconds. Redrawing costs 15-20 credits and 180 seconds.

None of these call a model. `fix_image` writes a Version; the other two do not.
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image
from pydantic import BaseModel, Field

from app.constraints import load_pack
from app.domain import image_metrics
from app.tools.base import Tool, ToolContext, ToolError, ToolMeta


class VersionRow(BaseModel):
    version_id: str
    seq: int
    status: str
    origin: str
    created_by: str
    is_current: bool
    summary: str


class ListVersionsInput(BaseModel):
    slot: str = Field(default="", description="Only this slot. Omit for every artifact.")


class ListVersionsOutput(BaseModel):
    slot: str
    versions: list[VersionRow]
    current_version_id: str = ""


class ListVersionsTool(Tool):
    meta = ToolMeta(
        name="list_versions",
        version="1",
        description=(
            "List the versions a slot already has, newest first, with which one is current. "
            "Use it before 'go back to an earlier version' or when the user refers to '上一版'. "
            "Does not write a Version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=5,
        writes_version=False,
    )
    input_model = ListVersionsInput
    output_model = ListVersionsOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = ListVersionsInput.model_validate(input)
        rows = ctx.extras.get("versions") or []
        out: list[VersionRow] = []
        for row in rows:
            if i.slot and row.get("slot") != i.slot:
                continue
            out.append(VersionRow(**row))
        if i.slot and not out:
            raise ToolError("not_found", f"{i.slot} 还没有任何版本")
        return ListVersionsOutput(
            slot=i.slot,
            versions=out,
            current_version_id=str(ctx.extras.get("current_version_id") or ""),
        )


class RestoreVersionInput(BaseModel):
    slot: str
    version_id: str = Field(
        description="The version to bring back, from `list_versions`. A seq like '2' also works."
    )


class RestoreVersionOutput(BaseModel):
    slot: str
    content: dict[str, Any]
    params: dict[str, Any]


class RestoreVersionTool(Tool):
    meta = ToolMeta(
        name="restore_version",
        version="1",
        description=(
            "Make an earlier version of a slot current again by writing its content as a NEW "
            "version. Nothing is deleted and no vendor is called. Use it when the user says "
            "to go back to an earlier version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=10,
    )
    input_model = RestoreVersionInput
    output_model = RestoreVersionOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = RestoreVersionInput.model_validate(input)
        wanted = i.version_id.strip()
        rows: list[dict[str, Any]] = ctx.extras.get("versions") or []
        target = next(
            (
                r
                for r in rows
                if r.get("version_id") == wanted
                or (wanted.isdigit() and str(r.get("seq")) == wanted and r.get("slot") == i.slot)
            ),
            None,
        )
        if target is None:
            raise ToolError(
                "not_found",
                f"没有找到这一版：{wanted}。先用 list_versions 看有哪些。",
            )
        content = (ctx.extras.get("contents") or {}).get(str(target["version_id"]))
        if not isinstance(content, dict):
            raise ToolError("not_found", "这一版的内容读不出来")
        return RestoreVersionOutput(
            slot=i.slot,
            content=dict(content),
            params={"restored_from": str(target["version_id"]), "restored_seq": target["seq"]},
        )


class InspectImageInput(BaseModel):
    slot: str
    version_id: str = Field(
        default="", description="Defaults to the current version of the slot."
    )


class InspectImageOutput(BaseModel):
    slot: str
    version_id: str
    metrics: dict[str, Any]
    problems: list[str]
    passed: bool
    thresholds: dict[str, Any]


class InspectImageTool(Tool):
    meta = ToolMeta(
        name="inspect_image",
        version="1",
        description=(
            "Measure an image version against the platform main-image rules: long side, white "
            "border fraction, subject occupancy. Returns the exact numbers the rule check uses "
            "and what would fail. Call it before submitting if the picture must pass; it costs "
            "nothing and does not write a Version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=20,
        writes_version=False,
    )
    input_model = InspectImageInput
    output_model = InspectImageOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = InspectImageInput.model_validate(input)
        png, version_id = _png_of(i.slot, i.version_id, ctx)
        cfg = load_pack()["main_image"]
        m = image_metrics.measure(png, background_min_channel=cfg["background_min_channel"])
        found = image_metrics.problems(m, cfg)
        return InspectImageOutput(
            slot=i.slot,
            version_id=version_id,
            metrics=m.as_dict(),
            problems=found,
            passed=not found,
            thresholds={
                "min_long_side_px": cfg["min_long_side_px"],
                "border_white_fraction": cfg["background_border_fraction"],
                "occupancy_min": cfg["occupancy_min"],
            },
        )


class FixImageInput(BaseModel):
    slot: str
    base_version_id: str = Field(
        default="", description="Defaults to the current version of the slot."
    )
    square: bool = Field(
        default=True,
        description="Pad to a square canvas. Amazon's main image is square; keep true unless "
        "the slot is not the main image.",
    )


class FixImageOutput(BaseModel):
    slot: str
    object_key: str
    width: int
    height: int
    params: dict[str, Any]


class FixImageTool(Tool):
    meta = ToolMeta(
        name="fix_image",
        version="1",
        description=(
            "Repair a picture WITHOUT a model: crop to the subject, scale it to the required "
            "occupancy and place it on a pure-white square. Fixes 'border not white' and "
            "'subject too small', which are two of the three main-image rules. Costs nothing "
            "and takes milliseconds. It cannot change what the product looks like; use "
            "edit_product_image for that."
        ),
        side_effect="write_blob",
        cost_credits=0,
        timeout_s=30,
        idempotent=False,
    )
    input_model = FixImageInput
    output_model = FixImageOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = FixImageInput.model_validate(input)
        png, version_id = _png_of(i.slot, i.base_version_id, ctx)
        cfg = load_pack()["main_image"]
        fixed, notes = image_metrics.repair(
            png,
            background_min_channel=cfg["background_min_channel"],
            target_occupancy=cfg["occupancy_min"],
            target_white_fraction=cfg["background_border_fraction"],
            min_side=int(cfg["min_long_side_px"]),
            square=i.square,
        )
        from uuid import uuid4

        key = f"images/{uuid4().hex}.png"
        ctx.store.put(key, fixed)
        w, h = Image.open(io.BytesIO(fixed)).size
        return FixImageOutput(
            slot=i.slot,
            object_key=key,
            width=w,
            height=h,
            params={
                "operation": "deterministic_fix",
                "base_version_id": version_id,
                "metrics": notes,
                "prompt": "deterministic repair: white canvas, subject occupancy",
            },
        )


def _png_of(slot: str, version_id: str, ctx: ToolContext) -> tuple[bytes, str]:
    """The stored bytes of one image Version. Empty version_id means the current one."""
    wanted = version_id.strip()
    contents: dict[str, dict[str, Any]] = ctx.extras.get("contents") or {}
    keys: dict[str, str] = ctx.extras.get("object_keys") or {}
    if not wanted:
        wanted = str(ctx.extras.get("current_version_id") or "")
    key = keys.get(wanted)
    if not key:
        raise ToolError(
            "not_found",
            f"{slot} 还没有图片版本。先画一张（generate_product_image），或换一个 slot。",
        )
    if not ctx.store.exists(key):
        raise ToolError("not_found", "这一版的图片文件不在存储里")
    return ctx.store.get(key), wanted
