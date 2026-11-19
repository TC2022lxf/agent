"""Canvas tools (decisions/0025, 0029). One writer, one reader, one variant maker.

`compose_canvas` writes the whole board in one Version: the planner sees the board, decides
what changes, and sends the new board. Pictures are never drawn here; an image module points
at an existing image Version. `generate_variants` copies a screen so the planner can explore
directions in parallel, the way Stitch does.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain import canvas as canvas_domain
from app.domain import slots as slot_registry
from app.tools.base import Tool, ToolContext, ToolError, ToolMeta


class ReadCanvasInput(BaseModel):
    pass


class ComposeCanvasInput(BaseModel):
    content: dict[str, Any] = Field(
        description=(
            "The whole board: {theme: {colors, fonts, radius}, screens: [...], edges: [...]}. "
            "Each screen needs id, frame {width, height}, pos {x, y} and modules. Each module "
            "needs id, kind (text|image), rect {x,y,w,h} as fractions of ITS SCREEN and style; "
            "text modules need text and a theme token for color/font; image modules need "
            "slot canvas_image_N, a prompt, and ref (another image module id) when this "
            "picture was made from that one. Edges are {from, to, label} between screen ids."
        )
    )
    base_version_id: str | None = Field(
        default=None,
        description="The canvas version you are editing. Omit only for the first draft.",
    )
    pointers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "module_id -> image version_id, for modules whose picture you just changed. "
            "Omitted modules keep the picture they already point at."
        ),
    )


class GenerateVariantsInput(BaseModel):
    screen_id: str = Field(description="The screen to branch from.")
    count: int = Field(default=3, ge=2, le=4, description="How many copies to place.")
    base_version_id: str = Field(description="The canvas version to write on top of.")


class CanvasOutput(BaseModel):
    slot: str
    content: dict[str, Any]
    params: dict[str, Any]


class ReadCanvasOutput(BaseModel):
    slot: str = ""
    content: dict[str, Any]
    params: dict[str, Any]


class ReadCanvasTool(Tool):
    meta = ToolMeta(
        name="read_canvas",
        version="2",
        description=(
            "Read the current canvas board: theme, screens (with position, frame and modules) "
            "and the clickable flow between screens. Does not write a new Version."
        ),
        side_effect="none",
        cost_credits=0,
        timeout_s=10,
        writes_version=False,
    )
    input_model = ReadCanvasInput
    output_model = ReadCanvasOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del input
        current = ctx.extras.get("canvas")
        if not isinstance(current, dict):
            raise ToolError("not_found", "这个任务还没有画布")
        return ReadCanvasOutput(content=current, params={})


class ComposeCanvasTool(Tool):
    meta = ToolMeta(
        name="compose_canvas",
        version="2",
        description=(
            "Write the canvas board as a new Version: several screens laid out on a surface, "
            "each with modules that have position, size, style and copy, plus the clickable "
            "flow between them. Image modules point at an existing image Version; this tool "
            "never generates pictures. Text colours and fonts must be theme tokens."
        ),
        side_effect="none",
        cost_credits=5,
        timeout_s=30,
    )
    input_model = ComposeCanvasInput
    output_model = CanvasOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        del ctx
        i = ComposeCanvasInput.model_validate(input)
        try:
            content = canvas_domain.validate_board(i.content)
        except canvas_domain.CanvasError as e:
            raise ToolError("bad_canvas", str(e)) from e
        params: dict[str, Any] = {"pointers": dict(i.pointers)}
        if i.base_version_id:
            params["base_version_id"] = i.base_version_id
        return CanvasOutput(
            slot=slot_registry.CANVAS_SLOT, content=content, params=params,
        )


class GenerateVariantsTool(Tool):
    meta = ToolMeta(
        name="generate_variants",
        version="1",
        description=(
            "Branch one screen into 2-4 side-by-side variants that share its content. The "
            "copies start identical: edit each with compose_canvas, then the user keeps one. "
            "Use this when the user wants to explore directions instead of one fix."
        ),
        side_effect="none",
        cost_credits=2,
        timeout_s=20,
    )
    input_model = GenerateVariantsInput
    output_model = CanvasOutput

    def execute(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        i = GenerateVariantsInput.model_validate(input)
        current = ctx.extras.get("canvas")
        if not isinstance(current, dict) or not isinstance(current.get("screens"), list):
            raise ToolError("not_found", "这个任务还没有画布，先出一版再分变体")
        board = {
            "theme": current.get("theme"),
            "screens": current["screens"],
            "edges": current.get("edges") or [],
        }
        try:
            valid = canvas_domain.validate_board(board)
            copies = canvas_domain.variants_of(valid, i.screen_id, i.count)
            valid = canvas_domain.validate_board({
                **valid, "screens": [*valid["screens"], *copies],
            })
        except canvas_domain.CanvasError as e:
            raise ToolError("bad_canvas", str(e)) from e
        return CanvasOutput(
            slot=slot_registry.CANVAS_SLOT,
            content=valid,
            params={"base_version_id": i.base_version_id, "variant_count": len(copies)},
        )
