"""The planner payload must name the slots it is allowed to write (docs/architecture/agent-runtime.md, 07).

Before this, `slot` was something the model had to guess from the Skill name. These tests
pin the list down for each Task kind, including the general one that spans three shapes.
"""

from __future__ import annotations

from app.runtime.langgraph_loop import _view
from app.runtime.loop import SlotState, TaskView


def _slots(kind: str, current: dict[str, SlotState] | None = None) -> list[str]:
    view = _view(TaskView(kind=kind, goal="g", current=current or {}, user_rules=[]), False)
    return [s["slot"] for s in view["writable_slots"]]


def test_pdp_task_lists_its_six_slots() -> None:
    slots = _slots("pdp")
    assert slots == [
        "title", "bullets", "description", "search_terms", "main_image", "secondary_image",
    ]


def test_general_task_lists_pdp_slots_plus_image_canvas_and_files() -> None:
    slots = _slots("general")
    # Order is the order the planner reads; `title` first because a PDP starts there.
    assert slots == [
        "title", "bullets", "description", "search_terms", "main_image", "secondary_image",
        "image", "canvas", "任意文件名",
    ]


def test_a_canvas_task_lists_its_page_and_module_slots() -> None:
    assert _slots("canvas") == ["canvas", "image", "canvas_image_N", "任意文件名"]


def test_image_and_file_tasks_list_their_own_shape() -> None:
    assert _slots("image") == ["image"]
    assert _slots("file") == ["任意文件名"]


def test_each_slot_carries_its_purpose_not_a_hard_coded_limit() -> None:
    """Numbers live in the constraint pack; the payload only says what a slot is for."""
    view = _view(TaskView(kind="pdp", goal="g", current={}, user_rules=[]), False)
    title = next(s for s in view["writable_slots"] if s["slot"] == "title")
    assert title["description"] == "PDP title"
    assert title["value_type"] == "text"
    assert "max_chars" not in title


def test_current_versions_are_reported_so_a_second_edit_has_a_base() -> None:
    view = _view(
        TaskView(
            kind="general", goal="g", user_rules=[],
            current={"notes.md": SlotState("ver_1", {"text": "# 笔记"})},
        ),
        False,
    )
    assert view["current"]["notes.md"]["version_id"] == "ver_1"
