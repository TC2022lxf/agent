"""The MVP agents plus the canvas specialist (docs/architecture/system.md, 0025).

One registration each; `general` only aggregates, and file tools are a grant, not a fifth agent.
"""

from __future__ import annotations

from pathlib import Path

from app.agents.registry import AgentSpec, Registry
from app.evaluators.base import EvaluatorRegistry
from app.evaluators.listing_rules import ListingRulesEvaluator
from app.evaluators.main_image_rules import MainImageRulesEvaluator
from app.tools.canvas_tools import (
    ComposeCanvasTool,
    GenerateVariantsTool,
    ReadCanvasTool,
)
from app.tools.edit_listing import EditListingTool
from app.tools.file_tools import ReadFileTool, WriteFileTool
from app.tools.image_tools import EditProductImageTool, GenerateProductImageTool
from app.tools.ask_tools import AskQuestionTool
from app.tools.assist_tools import (
    GenerateImageVariantsTool,
    RequestUploadTool,
    WriteTodosTool,
)
from app.tools.constraint_tools import RecordConstraintTool
from app.tools.version_tools import (
    FixImageTool,
    InspectImageTool,
    ListVersionsTool,
    RestoreVersionTool,
)
from app.tools.web_tools import WebFetchTool, WebSearchTool

SKILLS_DIR = Path(__file__).resolve().parents[3] / "skills"

# Tools every Agent has: reading history, a visible plan, asking for a missing picture, and
# recording a standing rule instead of only promising to follow it (docs/architecture/agent-runtime.md).
_COMMON = ("ask_question", "record_constraint", "list_versions", "write_todos", "request_upload")
# Only agents that write pictures can measure, repair or branch one.
_IMAGE = ("inspect_image", "fix_image", "image_variants")


def build_registry(skills_dir: Path = SKILLS_DIR) -> Registry:
    r = Registry()
    r.register_tool(EditListingTool())
    r.register_tool(GenerateProductImageTool())
    r.register_tool(EditProductImageTool())
    r.register_tool(WriteFileTool())
    r.register_tool(ReadFileTool())
    r.register_tool(WebSearchTool())
    r.register_tool(WebFetchTool())
    r.register_tool(ReadCanvasTool())
    r.register_tool(ComposeCanvasTool())
    r.register_tool(GenerateVariantsTool())
    r.register_tool(AskQuestionTool())
    r.register_tool(RecordConstraintTool())
    r.register_tool(ListVersionsTool())
    r.register_tool(RestoreVersionTool())
    r.register_tool(InspectImageTool())
    r.register_tool(FixImageTool())
    r.register_tool(GenerateImageVariantsTool())
    r.register_tool(WriteTodosTool())
    r.register_tool(RequestUploadTool())
    r.load_skills(skills_dir)
    r.register_agent(
        AgentSpec(
            key="amazon_pdp",
            title="PDP Agent",
            description="Create and refine an Amazon product detail page slot by slot.",
            system_prompt_ref="amazon_pdp",
            tool_names=(
                "edit_listing", "generate_product_image", "edit_product_image",
                "restore_version", *_COMMON, *_IMAGE,
            ),
            skill_ids=(
                "listing-first-draft", "pdp-listing-optimize",
                "pdp-compliance-review", "pdp-search-terms", "image-local-edit",
            ),
            artifact_kinds=("pdp", "text", "image"),
            workbench="pdp",
            task_kind="pdp",
        )
    )
    r.register_agent(
        AgentSpec(
            key="image",
            title="Image Agent",
            description="Focus on one image: circle a region, describe the change, get a version.",
            system_prompt_ref="image",
            tool_names=(
                "generate_product_image", "edit_product_image", "restore_version",
                *_COMMON, *_IMAGE,
            ),
            skill_ids=("image-first-draft", "image-local-edit", "image-secondary"),
            artifact_kinds=("image",),
            workbench="image",
            task_kind="image",
        )
    )
    r.register_agent(
        AgentSpec(
            key="canvas",
            title="Canvas Agent",
            description=(
                "Lay out an A+ page: modules with position, size and copy; pictures stay "
                "pointers to image versions. Not a free whiteboard (decisions/0025)."
            ),
            system_prompt_ref="canvas",
            tool_names=(
                "read_canvas", "compose_canvas", "generate_variants",
                "generate_product_image", "edit_product_image", "read_file",
                "restore_version", *_COMMON, *_IMAGE,
            ),
            skill_ids=("canvas-first-draft", "canvas-layout-edit", "canvas-explore-variants"),
            artifact_kinds=("canvas", "image", "file"),
            workbench="canvas",
            task_kind="canvas",
        )
    )
    r.register_aggregate(
        "general",
        "General Agent",
        "One conversation for any artifact: writes files and images, opens the matching preview.",
        ("amazon_pdp", "image", "canvas"),
    )
    # File tools and web tools are not another specialist. See docs/architecture/agent-runtime.md and 0035.
    r.grant(
        "general",
        tools=("write_file", "read_file", "web_search", "web_fetch", "restore_version"),
        skills=("file-draft",),
        kinds=("file",),
    )
    return r


def build_evaluators() -> EvaluatorRegistry:
    ev = EvaluatorRegistry()
    ev.register(ListingRulesEvaluator())
    ev.register(MainImageRulesEvaluator())
    return ev
