"""Commit a tool output as a Version and run rule evaluators. Used by the graph's tool wrapper."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.domain import slots as slot_registry
from app.evaluators.base import EvalSubject, EvaluatorRegistry
from app.ports import ObjectStorePort
from app.services.uow import UnitOfWork, UowFactory


def commit_output(
    uow_factory: UowFactory,
    evaluators: EvaluatorRegistry,
    store: ObjectStorePort,
    *,
    run_id: str,
    task_id: str,
    kind: str,
    task_meta: dict[str, Any],
    rules: list[dict[str, Any]],
    slot: str,
    output: BaseModel,
    base_version_id: str | None,
    variants: list[BaseModel] | None = None,
) -> str:
    """Commit one version, or one per variant when `variants` is given.

    `image_variants` draws several pictures in one call. They are alternatives, not a history:
    each becomes its own Version with `variant_of` set, and the first one becomes current so
    the slot is never left pointing at an older picture. The return value is the first
    variant's id, which is what `tool_calls.output.version_id` records.
    """
    if slot_registry.is_image_slot(slot):
        # `restore_version` hands back the stored dict itself rather than typed width/height,
        # and an `image_variants` row carries only object_key/size. Both must produce a Version
        # whose blob really exists, so read whatever shape arrived.
        source = output.content if isinstance(getattr(output, "content", None), dict) else {}
        content = {
            "object_key": getattr(output, "object_key", None) or source.get("object_key"),
            "width": getattr(output, "width", None) or source.get("width"),
            "height": getattr(output, "height", None) or source.get("height"),
        }
        content = {k: v for k, v in content.items() if v is not None}
        if "object_key" not in content:
            raise ValueError(f"{slot}: image output has no object_key")
    else:
        content = output.content  # type: ignore[attr-defined]
    params = dict(getattr(output, "params", None) or {})
    with uow_factory() as uow:
        if slot_registry.is_canvas_slot(slot):
            return _commit_canvas(
                uow, evaluators, store, run_id=run_id, task_id=task_id, task_meta=task_meta,
                rules=rules, content=content, params=params, base_version_id=base_version_id,
            )
        version = uow.collab.commit_candidate(
            task_id=task_id,
            slot=slot,
            content=content,
            params=params,
            origin="edited" if base_version_id else "generated",
            created_by="agent",
            run_id=run_id,
            parent_version_id=base_version_id,
        )
        subject = EvalSubject(slot, content, task_meta, rules, store)
        hard_fail = False
        summary = []
        for ev in evaluators.all():
            if not ev.applies_to(subject):
                continue
            result = ev.evaluate(subject)
            uow.collab.add_evaluation(
                version.id, ev.id, result.passed, ev.can_reject, result.details,
            )
            summary.append({"evaluator": ev.id, "passed": result.passed})
            hard_fail = hard_fail or (not result.passed and ev.can_reject)
        uow.collab.finalize_version(version, accepted=not hard_fail)
        if not hard_fail and slot_registry.is_pdp_slot(slot):
            uow.collab.bind_to_pdp(
                task_id, slot, version.id, run_id, "agent",
                create=slot_registry.is_multi_artifact(kind),
            )
        uow.collab.add_event(
            run_id,
            "version_created",
            {
                "version_id": version.id, "slot": slot, "status": version.status,
                "evaluations": summary,
            },
        )
        uow.commit()
        return version.id


def _commit_canvas(
    uow: UnitOfWork,
    evaluators: EvaluatorRegistry,
    store: ObjectStorePort,
    *,
    run_id: str,
    task_id: str,
    task_meta: dict[str, Any],
    rules: list[dict[str, Any]],
    content: dict[str, Any],
    params: dict[str, Any],
    base_version_id: str | None,
) -> str:
    """The canvas decides image module pointers, so it commits through its own path.

    A rejected page must not move any pointer: the check runs before activation
    (decisions/0025). Everything else matches `commit_output`.
    """
    subject = EvalSubject(slot_registry.CANVAS_SLOT, content, task_meta, rules, store)
    hard_fail = False
    results: list[tuple[str, bool, bool, dict[str, Any]]] = []
    for ev in evaluators.all():
        if not ev.applies_to(subject):
            continue
        result = ev.evaluate(subject)
        results.append((ev.id, result.passed, ev.can_reject, result.details))
        hard_fail = hard_fail or (not result.passed and ev.can_reject)

    version = uow.collab.commit_canvas_version(
        task_id=task_id,
        content=content,
        base_version_id=base_version_id,
        created_by="agent",
        run_id=run_id,
        accepted=not hard_fail,
        pointers={str(k): str(v) for k, v in (params.get("pointers") or {}).items()},
    )
    for ev_id, passed, can_reject, details in results:
        uow.collab.add_evaluation(version.id, ev_id, passed, can_reject, details)
    uow.collab.add_event(
        run_id,
        "version_created",
        {
            "version_id": version.id, "slot": slot_registry.CANVAS_SLOT,
            "status": version.status,
            "evaluations": [{"evaluator": r[0], "passed": r[1]} for r in results],
        },
    )
    uow.commit()
    return version.id
