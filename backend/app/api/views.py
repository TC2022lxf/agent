"""Row -> JSON view helpers."""

from __future__ import annotations

from typing import Any

from app.domain import canvas as canvas_domain
from app.domain import slots as slot_registry
from app.persistence.models import Constraint, Feedback, Product, Run, Task, Version
from app.services.collab import NotFound
from app.services.uow import UnitOfWork


def blob_url(key: str) -> str:
    return f"/api/blobs/{key}"


def version_view(uow: UnitOfWork, v: Version, slot: str | None = None) -> dict[str, Any]:
    content = dict(v.content)
    if "object_key" in content:
        content["url"] = blob_url(content["object_key"])
    if "object_keys" in content:
        content["urls"] = [blob_url(k) for k in content["object_keys"]]
    return {
        "id": v.id,
        "artifact_id": v.artifact_id,
        "task_id": v.task_id,
        "slot": slot,
        "seq": v.seq,
        "parent_version_id": v.parent_version_id,
        "origin": v.origin,
        "created_by": v.created_by,
        "content": content,
        "params": v.params,
        "manifest": v.manifest,
        "status": v.status,
        "user_signal": v.user_signal,
        "run_id": v.run_id,
        "created_at": v.created_at.isoformat(),
        "evaluations": [
            {"evaluator_id": e.evaluator_id, "passed": e.passed, "can_reject": e.can_reject,
             "details": e.details}
            for e in uow.collab.evaluations(v.id)
        ],
    }


def task_view(uow: UnitOfWork, t: Task) -> dict[str, Any]:
    arts = uow.collab.artifacts(t.id)
    current = {a.slot: a.current_version_id for a in arts if a.slot}
    pdp = next((a for a in arts if a.kind == "pdp"), None)
    return {
        "id": t.id,
        "kind": t.kind,
        "agent_key": t.agent_key,
        "goal": t.goal,
        "status": t.status,
        "meta": t.meta,
        "product_id": t.product_id,
        "current": current,
        "pdp_version_id": pdp.current_version_id if pdp else None,
        "canvas_version_id": current.get(slot_registry.CANVAS_SLOT),
        "created_at": t.created_at.isoformat(),
    }


def product_view(p: Product) -> dict[str, Any]:
    assets = p.assets or {}
    return {
        "id": p.id,
        "name": p.name,
        "brand": p.brand,
        "marketplace": p.marketplace,
        "mode": p.mode,
        "facts": p.facts,
        "listing": p.listing,
        "main_url": blob_url(assets["main"]) if assets.get("main") else None,
        "gallery_urls": [blob_url(k) for k in assets.get("gallery", [])],
        "created_at": p.created_at.isoformat(),
    }


def run_view(r: Run) -> dict[str, Any]:
    return {
        "id": r.id,
        "task_id": r.task_id,
        "agent_key": r.agent_key,
        "trigger": r.trigger,
        "status": r.status,
        "path": r.path,
        "version_ids": r.version_ids,
        "error": r.error,
        "held": r.held,
        "cost": r.cost,
        "overrun": r.overrun,
        "trace_id": r.trace_id,
    }


def feedback_view(f: Feedback) -> dict[str, Any]:
    return {
        "id": f.id,
        "run_id": f.run_id,
        "text": f.text,
        "interpretation": f.interpretation,
        "target_slot": f.target_slot,
        "target_version_id": f.target_version_id,
        "target_region": f.target_region,
        "status": f.status,
        "note": f.note,
    }


def constraint_view(c: Constraint) -> dict[str, Any]:
    return {"id": c.id, "text": c.text, "rule": c.rule, "status": c.status,
            "feedback_id": c.feedback_id}


def canvas_view(uow: UnitOfWork, task: Task) -> dict[str, Any]:
    """The board plus every image module's picture and Version (docs/architecture/agent-runtime.md, docs/architecture/data-and-contracts.md, 0027).

    URLs come from the canvas Version's manifest, not from the slot's current pointer: a
    newly generated picture is not on a page until a version points at it. `bounds` is the
    world box of all screens, so the frontend can frame the board without measuring.
    """
    v = uow.collab.canvas_version(task.id)
    if v is None:
        return {"task_id": task.id, "version_id": None, "theme": None, "screens": [],
                "edges": [], "bounds": None, "versions": [], "notes": []}
    body = canvas_domain.upgrade(v.content)
    notes: list[str] = []
    screens: list[dict[str, Any]] = []
    for s in body.get("screens", []):
        modules: list[dict[str, Any]] = []
        for m in s.get("modules", []):
            item = dict(m)
            if m.get("kind") == "image":
                vid = (v.manifest or {}).get(m["id"])
                mod_version = uow.collab.get_version(vid) if vid else None
                item["version_id"] = vid
                item["url"] = blob_url(mod_version.content["object_key"]) if mod_version else None
                item["width"] = mod_version.content.get("width") if mod_version else None
                item["height"] = mod_version.content.get("height") if mod_version else None
                try:
                    art = uow.collab.slot_artifact(task.id, m["slot"])
                except NotFound:
                    item["newer_version"] = None
                else:
                    if art.current_version_id and art.current_version_id != vid:
                        newer = uow.collab.get_version(art.current_version_id)
                        item["newer_version"] = {
                            "version_id": newer.id, "seq": newer.seq,
                            "url": blob_url(newer.content["object_key"]),
                            "status": newer.status,
                        }
                        notes.append(f"{m.get('name') or m['id']}：有更新的图可用")
            modules.append(item)
        screens.append({**{k: val for k, val in s.items() if k != "modules"}, "modules": modules})
    art = uow.collab.canvas_artifact(task.id)
    versions = [
        {"id": x.id, "seq": x.seq, "status": x.status, "created_by": x.created_by,
         "origin": x.origin, "created_at": x.created_at.isoformat(),
         "is_current": x.id == art.current_version_id}
        for x in reversed(uow.collab.versions_of(art.id))
    ]
    return {
        "task_id": task.id,
        "artifact_id": art.id,
        "version_id": v.id,
        "seq": v.seq,
        "theme": body.get("theme"),
        "screens": screens,
        "edges": body.get("edges") or [],
        "bounds": canvas_domain.board_bounds(body),
        "versions": versions,
        "notes": notes,
    }
