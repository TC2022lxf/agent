from __future__ import annotations

import io
from typing import Any, Literal
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, Field

from app.domain import slots as slot_registry
from app.image.engines import DEFAULT_ENGINE, ImageEditEngine, edit_prompt
from app.tools.base import Tool, ToolContext, ToolError, ToolMeta


class NormRect(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


def _readable(exc: Exception) -> ToolError:
    """Turn a vendor refusal into something a user can act on.

    A model that declines to draw is not a bug: the prompt asked for something it will not
    render. The message has to say "rephrase", not "image_decode".
    """
    text = str(exc)
    if "IMAGE_RECITATION" in text or "image_refused" in text:
        return ToolError(
            "image_refused",
            "模型拒绝按这个描述出图（可能涉及受保护的画面）。换个说法或提供商品参考图后再试。",
        )
    if "IMAGE_SAFETY" in text or "SAFETY" in text:
        return ToolError("image_blocked", "这个描述被安全策略拦截了，换一种说法再试。")
    return ToolError("image_failed", f"生图失败：{text[:200]}")


class ImageOutput(BaseModel):
    slot: str
    object_key: str
    width: int
    height: int
    changed_region: NormRect | None = None
    params: dict[str, Any]


# A reference picture is only useful if the model is told to keep it. Without this line the
# vendor treats it as loose inspiration and redraws a different-looking subject.
_KEEP_PRODUCT = (
    "Use the subject of the reference image: keep its shape, proportions, colour, materials "
    "and any visible details exactly. Do not invent a different subject, brand or text."
)


class GenerateImageInput(BaseModel):
    slot: str
    prompt: str
    size: int = Field(default=1000, ge=256, le=2048)
    aspect_ratio: str | None = Field(
        default=None,
        description=(
            "Optional ratio like 1:1 or 16:9. Omit to use the slot's own ratio (the main image "
            "is square); a canvas module may ask for its frame's shape instead."
        ),
    )


class GenerateProductImageTool(Tool):
    meta = ToolMeta(
        name="generate_product_image",
        version="3",
        description=(
            "Draw a picture from a prompt and store it as the first Version of an image slot. "
            "When the Task is bound to a product with a saved picture, that picture is passed "
            "as the reference so the subject is the real product, not an invented one. Later "
            "changes use edit_product_image on a base version, not this tool."
        ),
        side_effect="write_blob",
        cost_credits=20,
        timeout_s=180,
        idempotent=False,
    )
    input_model = GenerateImageInput
    output_model = ImageOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = GenerateImageInput.model_validate(input)
        ratio = i.aspect_ratio or slot_registry.aspect_ratio_for(i.slot)
        reference_key = ctx.extras.get("product_image_key")
        reference: bytes | None = None
        if isinstance(reference_key, str) and reference_key and ctx.store.exists(reference_key):
            reference = ctx.store.get(reference_key)
        prompt = f"{_KEEP_PRODUCT}\n\n{i.prompt}" if reference is not None else i.prompt
        try:
            res = ctx.gateway.image_generate("image_generate", prompt, i.size, ratio, reference)
        except Exception as exc:  # noqa: BLE001 - vendor failure kinds are not ours to type
            raise _readable(exc) from exc
        key = f"images/{uuid4().hex}.png"
        ctx.store.put(key, res.png)
        w, h = Image.open(io.BytesIO(res.png)).size
        return ImageOutput(
            slot=i.slot,
            object_key=key,
            width=w,
            height=h,
            params={
                "prompt": i.prompt,
                "prompt_sent": prompt,
                **({"aspect_ratio": ratio} if ratio else {}),
                **({"reference_object_key": reference_key} if reference is not None else {}),
                **(res.params or {}),
            },
        )

# Operations whose quality has not passed the M0-A experiment. Refused, not faked.
_EXPERIMENTAL = {"product_scale", "upscale", "remove_bg"}


class ImagePatch(BaseModel):
    operation: Literal["free", "product_scale", "upscale", "remove_bg"] = "free"
    instruction: str = ""


class EditImageInput(BaseModel):
    slot: str
    base_version_id: str = Field(
        default="", description="Required: edits always start from a version"
    )
    # Server state, not model input. The planner cannot know an object key, and demanding one
    # made it abandon the edit and answer in words instead. Runtime fills both from the
    # current Version (`_fill_image_base`) when they are empty.
    base_object_key: str = ""
    patch: ImagePatch
    region: NormRect | None = None


class EditProductImageTool(Tool):
    meta = ToolMeta(
        name="edit_product_image",
        version="1",
        description=(
            "Edit an existing image version. When `region` is set, the prompt includes a "
            "pixel `<bbox>`; the stored Version is whatever the image model returns."
        ),
        side_effect="write_blob",
        cost_credits=15,
        timeout_s=180,
        idempotent=False,
    )
    input_model = EditImageInput
    output_model = ImageOutput

    def __init__(self, engine: ImageEditEngine | None = None) -> None:
        self._engine = engine or DEFAULT_ENGINE

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = EditImageInput.model_validate(input)
        if i.patch.operation in _EXPERIMENTAL:
            raise ToolError(
                "capability_experimental",
                f"{i.patch.operation} has not passed the image experiment (docs/10); not enabled",
            )
        if not i.base_version_id or not i.base_object_key:
            raise ToolError(
                "no_base", "edit_product_image needs a base Version; run it as a follow-up",
            )
        src = ctx.store.get(i.base_object_key)
        region = (i.region.x, i.region.y, i.region.w, i.region.h) if i.region else None
        # What the vendor is actually asked, kept on the Version. Without it a later turn (and
        # the user) can only guess why a local edit changed the neighbouring pixels; the
        # `<bbox>` is part of the request, so it has to be part of the record.
        sent = edit_prompt(i.patch.instruction, src, region)
        out = self._engine.edit(ctx.gateway, src, i.patch.instruction, region)
        key = f"images/{uuid4().hex}.png"
        ctx.store.put(key, out)
        w, h = Image.open(io.BytesIO(out)).size
        return ImageOutput(
            slot=i.slot,
            object_key=key,
            width=w,
            height=h,
            changed_region=i.region,
            params={
                "base_version_id": i.base_version_id,
                "operation": i.patch.operation,
                "instruction": i.patch.instruction,
                "prompt_sent": sent,
                "engine": self._engine.name,
                **({"region": i.region.model_dump()} if i.region else {}),
            },
        )
