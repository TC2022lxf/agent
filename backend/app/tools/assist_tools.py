"""Image-slot variants, a visible plan, and asking the user for a picture.

`generate_variants` already existed for the canvas, where a "variant" means a copy of a
screen. On an image Task the same sentence ("给我三个方向") had no tool at all: the only
option was to call `generate_product_image` three times, which produces three unrelated
pictures that cost three times as much and carry no record of being alternatives.

`write_todos` exists for the user, not for the model. A multi-step turn (a canvas of five
screens, a whole PDP) shows one `step` event at a time and no plan, so the user cannot tell
what is still coming.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.tools.base import Tool, ToolContext, ToolError, ToolMeta


class VariantPicture(BaseModel):
    prompt: str = Field(
        min_length=1, max_length=2000,
        description="What makes THIS direction different. Keep the shared subject words in "
        "every prompt; only the direction changes.",
    )
    object_key: str = ""


class GenerateImageVariantsInput(BaseModel):
    slot: str
    base_version_id: str = Field(
        default="",
        description="The picture to branch from. Every variant keeps this subject.",
    )
    prompts: list[VariantPicture] = Field(
        min_length=2, max_length=4,
        description="Two to four directions. Two is usually the right number.",
    )

    @field_validator("prompts")
    @classmethod
    def distinct(cls, value: list[VariantPicture]) -> list[VariantPicture]:
        seen: set[str] = set()
        for p in value:
            key = p.prompt.strip().lower()
            if key in seen:
                raise ValueError("two variants have the same prompt")
            seen.add(key)
        return value


class VariantRow(BaseModel):
    prompt: str
    object_key: str
    width: int
    height: int


class GenerateImageVariantsOutput(BaseModel):
    slot: str
    variants: list[VariantRow]
    params: dict[str, Any]


class GenerateImageVariantsTool(Tool):
    meta = ToolMeta(
        name="image_variants",
        version="1",
        description=(
            "Draw 2-4 alternative pictures of the same subject so the user can pick a "
            "direction. Each picture is stored as a version of the slot, all sharing the same "
            "base, and marked as siblings. Use this instead of calling generate_product_image "
            "several times when the user asks for options."
        ),
        side_effect="write_blob",
        cost_credits=15,
        timeout_s=300,
        idempotent=False,
    )
    input_model = GenerateImageVariantsInput
    output_model = GenerateImageVariantsOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = GenerateImageVariantsInput.model_validate(input)
        reference = ctx.extras.get("reference_png")
        rows: list[VariantRow] = []
        for item in i.prompts:
            res = ctx.gateway.image_generate(
                "image_generate", item.prompt, ctx.extras.get("size", 1000),
                ctx.extras.get("aspect_ratio"),
                reference if isinstance(reference, bytes) else None,
            )
            import io
            from uuid import uuid4

            from PIL import Image

            key = f"images/{uuid4().hex}.png"
            ctx.store.put(key, res.png)
            w, h = Image.open(io.BytesIO(res.png)).size
            rows.append(VariantRow(prompt=item.prompt, object_key=key, width=w, height=h))
        if not rows:
            raise ToolError("image_failed", "没有生成任何变体")
        return GenerateImageVariantsOutput(
            slot=i.slot,
            variants=rows,
            params={
                "operation": "variants",
                "base_version_id": i.base_version_id,
                "variant_of": i.base_version_id,
                "prompts": [r.prompt for r in rows],
            },
        )


class TodoItem(BaseModel):
    text: str = Field(min_length=1, max_length=200)
    status: str = Field(default="pending", pattern="^(pending|in_progress|done)$")


class WriteTodosInput(BaseModel):
    items: list[TodoItem] = Field(
        min_length=1, max_length=8,
        description="The steps of the work, in order. Rewrite the whole list each time.",
    )


class WriteTodosOutput(BaseModel):
    items: list[TodoItem]
    done: int
    total: int


class WriteTodosTool(Tool):
    meta = ToolMeta(
        name="write_todos",
        version="1",
        description=(
            "Show the user the steps you are working through, and update them as you go. "
            "Send the whole list each time; it replaces the previous one. Use it for work with "
            "three or more steps. Does not write a Version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=5,
        writes_version=False,
    )
    input_model = WriteTodosInput
    output_model = WriteTodosOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del ctx
        i = WriteTodosInput.model_validate(input)
        return WriteTodosOutput(
            items=i.items,
            done=sum(1 for it in i.items if it.status == "done"),
            total=len(i.items),
        )


class RequestUploadInput(BaseModel):
    what: str = Field(
        min_length=1, max_length=300,
        description="What picture you need and why, in the user's language, e.g. "
        "「这个产品的一张实物照，白底或浅色背景最好」.",
    )
    for_slot: str = Field(
        default="", description="Which slot the picture would go into, when there is one."
    )


class RequestUploadOutput(BaseModel):
    what: str
    for_slot: str
    status: str = "awaiting_user"


class RequestUploadTool(Tool):
    meta = ToolMeta(
        name="request_upload",
        version="1",
        description=(
            "Ask the user to upload a picture you need (a product photo, a reference). Use it "
            "when a picture would change the result and you cannot proceed well without it. "
            "Does not write a Version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=5,
        writes_version=False,
    )
    input_model = RequestUploadInput
    output_model = RequestUploadOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del ctx
        i = RequestUploadInput.model_validate(input)
        return RequestUploadOutput(what=i.what, for_slot=i.for_slot)
