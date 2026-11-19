"""AgentLoop port. Production uses LangGraphLoop (app/runtime/langgraph_loop.py).

SimpleLoop remains as the deterministic rule set that scripted_plan mirrors for the
offline gateway. LangChain and LangGraph are not imported from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain import slots as slot_registry

# A Run records every step it took in `run.path`. These few stages are what the UI phrases
# while the Run is still going; a percentage would be a claim the server cannot make.
_RUN_PATH_STAGE: dict[str, str] = {
    "load_context": "context",
    "compact": "compact",
    "interpret": "interpret",
    "resume": "resume",
}


def stage_of(step: str) -> str:
    """Map a recorded path step to a coarse, user-facing stage."""
    if step.startswith("handle:"):
        return "dispatch"
    if step.startswith("tool:"):
        return "tool"
    return _RUN_PATH_STAGE.get(step, "work")


@dataclass(frozen=True)
class SlotState:
    version_id: str
    content: dict[str, Any]


@dataclass(frozen=True)
class TaskView:
    kind: str
    goal: str
    current: dict[str, SlotState]  # slot -> current accepted version
    user_rules: list[dict[str, Any]]
    facts: dict[str, Any] = field(default_factory=dict)  # product facts: all the Agent may use


@dataclass(frozen=True)
class Item:
    text: str
    interpretation: str
    slot: str | None
    region: dict[str, float] | None
    operation: str = "free"
    base_override: SlotState | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedCall:
    tool_name: str
    slot: str
    tool_input: dict[str, Any]
    base_version_id: str | None
    region: dict[str, float] | None


@dataclass
class Plan:
    calls: list[PlannedCall] = field(default_factory=list)
    path_note: str = ""
    declined: str = ""  # non-empty: nothing to run for this item, and why


class AgentLoop(Protocol):
    """The plan-then-act loop the Runtime drives.

    `SimpleLoop` below is the deterministic one-step rule set that `scripted_plan` mirrors for
    the offline gateway; the production loop is `LangGraphLoop`, which runs a graph and is
    typed loosely here because this module must not import LangChain or LangGraph (0015).
    """

    def run(self, item: Item, view: TaskView, ctx: Any) -> Any: ...


class SimpleLoop:
    def plan(self, item: Item, view: TaskView) -> Plan:
        plan = Plan()
        targets: list[str]
        if item.slot:
            targets = [item.slot]
        elif view.kind == "pdp" and not any(
            s in view.current for s in slot_registry.text_slots_for_task_kind("pdp")
        ):
            targets = list(slot_registry.text_slots_for_task_kind("pdp"))  # first draft
            plan.path_note = "first_draft"
        else:
            targets = [s for s in slot_registry.slots_for_task_kind(view.kind)][:1]
        for slot in targets:
            if slot in slot_registry.GALLERY_SLOT_KEYS:
                plan.declined = f"{slot}: 副图的编辑后期开放，目前只展示导入的内容"
                continue
            plan.calls.append(self._call(slot, item, view))
        return plan

    def _call(self, slot: str, item: Item, view: TaskView) -> PlannedCall:
        base = item.base_override if item.slot == slot and item.base_override else None
        base = base or view.current.get(slot)
        if slot in slot_registry.IMAGE_SLOT_KEYS:
            region = item.region
            if base is None:
                return PlannedCall(
                    "generate_product_image",
                    slot,
                    {"slot": slot, "prompt": item.text or view.goal},
                    None,
                    None,
                )
            return PlannedCall(
                "edit_product_image",
                slot,
                {
                    "slot": slot,
                    "base_version_id": base.version_id,
                    "base_object_key": base.content["object_key"],
                    "patch": {"operation": item.operation, "instruction": item.text},
                    "region": region,
                },
                base.version_id,
                region,
            )
        max_chars = next(
            (
                int(r["value"])
                for r in view.user_rules
                if r.get("type") == "max_chars" and r.get("slot") == slot
            ),
            None,
        )
        return PlannedCall(
            "edit_listing",
            slot,
            {
                "slot": slot,
                "goal": view.goal,
                "instruction": item.text if base else "",
                "base_version_id": base.version_id if base else None,
                "base": base.content if base else None,
                "max_chars": max_chars,
                "facts": view.facts,
            },
            base.version_id if base else None,
            None,
        )

