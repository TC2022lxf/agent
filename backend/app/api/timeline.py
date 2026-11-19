"""Conversation timeline of a Task, rebuilt from Runs (docs/architecture/agent-runtime.md). The chat shows what the
Runtime recorded: nothing here is stored separately, so it cannot drift from the facts."""

from __future__ import annotations

from typing import Any

from app.api.views import blob_url
from app.persistence.models import Run, Task
from app.services.uow import UnitOfWork

_MAX_ARG_CHARS = 400


def _brief(value: Any, depth: int = 0) -> Any:
    """A Tool's input or output, trimmed for a card's disclosure.

    A `write_file` body or a generated prompt can be thousands of characters, and the whole
    point of the card is to say what happened in one glance. Long strings keep their head so
    the reader can recognise them; nothing is silently dropped (the count says how much).
    """
    if isinstance(value, str):
        if len(value) <= _MAX_ARG_CHARS:
            return value
        return f"{value[:_MAX_ARG_CHARS]}…（共 {len(value)} 字符）"
    if depth >= 3:
        return "…"
    if isinstance(value, dict):
        return {str(k): _brief(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [_brief(v, depth + 1) for v in value[:20]]
    return value


def _brief_args(args: dict[str, Any]) -> dict[str, Any]:
    """The call as the card shows it: no empty defaults, no internal bookkeeping."""
    out: dict[str, Any] = {}
    for key, value in args.items():
        if value in (None, "", [], {}):
            continue
        out[key] = _brief(value)
    return out


def _version_kind(v: Any, artifact_kind: str | None) -> str:
    if artifact_kind == "canvas":
        return "canvas"
    if v.manifest:
        return "pdp"
    content = v.content or {}
    if content.get("filename") or content.get("media"):
        return "file"
    if "object_key" in content:
        return "image"
    return "text"


def build_timeline(uow: UnitOfWork, task: Task) -> list[dict[str, Any]]:
    arts = uow.collab.artifacts(task.id)
    current = {a.id: a.current_version_id for a in arts}
    slot_of = {a.id: a.slot for a in arts}
    kind_of = {a.id: a.kind for a in arts}
    fb_by_run: dict[str, list[Any]] = {}
    for f in uow.collab.feedback_list(task.id):
        fb_by_run.setdefault(f.run_id, []).append(f)
    cons_by_fb = {c.feedback_id: c for c in uow.collab.all_constraints(task.id) if c.feedback_id}
    return [
        _turn(uow, r, fb_by_run.get(r.id, []), cons_by_fb, current, slot_of, kind_of)
        for r in uow.collab.runs_of(task.id)
    ]


def _turn(
    uow: UnitOfWork,
    r: Run,
    feedback: list[Any],
    cons_by_fb: dict[str, Any],
    current: dict[str, str | None],
    slot_of: dict[str, str | None],
    kind_of: dict[str, str],
) -> dict[str, Any]:
    events = uow.collab.events_after(r.id, 0)
    answers = [e.data.get("text", "") for e in events if e.type == "answer"]
    # A question may carry replies the user could send verbatim. They are attached to the
    # answer they belong to, so a turn with two questions does not mix up two option sets.
    answer_options = [
        [str(o) for o in (e.data.get("options") or []) if isinstance(o, str)]
        for e in events if e.type == "answer"
    ]
    human_input_requests = [
        dict(e.data) for e in events if e.type == "human_input_request"
    ]
    # Follow-up chips are a UI hint about a finished turn, not an answer and not a Tool call
    # (docs/architecture/agent-runtime.md). One turn has one set: they are written after the last answer.
    follow_ups: list[str] = []
    for e in events:
        if e.type == "followups":
            follow_ups = [str(q) for q in (e.data.get("questions") or []) if isinstance(q, str)]
    proposals = [e.data.get("proposal_id") for e in events if e.type == "preference_proposed"]
    # The newest plan replaces the older ones: a checklist is a state, not a log.
    todos: list[dict[str, Any]] = []
    for e in events:
        if e.type == "todos":
            items = e.data.get("items")
            if isinstance(items, list):
                todos = [dict(it) for it in items if isinstance(it, dict)]
    declined = [e.data for e in events if e.type in {"tool_declined", "scope_rejected"}]
    steps = []
    for tc in uow.collab.tool_calls(r.id):
        inp = tc.input or {}
        steps.append({
            # The card in the chat is keyed by this id, so the row that arrives when a Tool
            # finishes lands on the card `tool_started` already drew for it.
            "tool_call_id": tc.tool_call_id,
            "tool": tc.tool_name,
            "slot": inp.get("slot"),
            "ok": tc.status == "ok",
            "error": tc.error,
            "duration_ms": tc.duration_ms,
            "cost": tc.cost,
            "base_version_id": inp.get("base_version_id"),
            "patch": inp.get("patch"),
            "path": inp.get("path") or inp.get("slot"),
            # What the Tool was asked to do and what it produced. Kept out of the chat body
            # (it can be a paragraph) and shown behind the card's disclosure.
            "input": _brief_args(inp),
            "output": dict(tc.output or {}),
            "draft": inp.get("content") if (
                tc.tool_name == "write_file" and tc.status != "ok"
                and isinstance(inp.get("content"), str)
            ) else None,
        })
    versions = []
    for v in uow.collab.versions_of_run(r.id):
        parent = uow.collab.get_version(v.parent_version_id) if v.parent_version_id else None
        content = dict(v.content)
        if "object_key" in content:
            content["url"] = blob_url(content["object_key"])
        versions.append({
            "id": v.id,
            "slot": slot_of.get(v.artifact_id),
            "seq": v.seq,
            "kind": _version_kind(v, kind_of.get(v.artifact_id)),
            "status": v.status,
            "is_current": current.get(v.artifact_id) == v.id,
            "content": content,
            "parent_content": parent.content if parent else None,
            "params": v.params,
            "evaluations": [
                {"evaluator_id": e.evaluator_id, "passed": e.passed,
                 "problems": e.details.get("problems", [])}
                for e in uow.collab.evaluations(v.id)
            ],
        })
    inp = r.input or {}
    return {
        "run_id": r.id,
        "agent_key": r.agent_key,
        "status": r.status,
        "error": r.error,
        "cost": r.cost,
        "held": r.held,
        "created_at": r.created_at.isoformat(),
        "user": {
            "text": inp.get("text", ""),
            "target_slot": inp.get("target_slot"),
            "target_region": inp.get("target_region"),
            "target_version_id": inp.get("target_version_id"),
        },
        "interpretations": [
            {
                "feedback_id": f.id, "kind": f.interpretation, "text": f.text,
                "slot": f.target_slot, "region": f.target_region, "status": f.status,
                "note": f.note,
                "constraint_id": cons_by_fb[f.id].id if f.id in cons_by_fb else None,
                "constraint_status": cons_by_fb[f.id].status if f.id in cons_by_fb else None,
            }
            for f in feedback
        ],
        "answers": answers,
        # Index-aligned with `answers`; empty list when the question had no canned replies.
        "answer_options": answer_options,
        "human_input_requests": human_input_requests,
        # Calls announced before they ran but whose result never arrived (a crashed worker).
        # Without them the cards for those calls would only appear once the row was written.
        "tool_started": [
            dict(e.data) for e in events if e.type == "tool_started"
        ],
        # Suggestions for the NEXT turn, never answers to this one. Same order as `answers`.
        "follow_ups": follow_ups,
        "preference_proposals": proposals,
        # The visible plan from `write_todos`, so a finished turn still shows what was done.
        "todos": todos,
        "declined": declined,
        "steps": steps,
        "versions": versions,
    }
