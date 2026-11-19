"""Compaction prompt and call (docs/07). Shared by the automatic trigger and `/compact`.

DeerFlow's summarization prompt asks for four sections and this keeps that shape, because
the failure mode it prevents is specific: after compaction the planner forgets which
Versions already exist and redoes work. `ARTIFACTS` is the section that stops that.

The summary is the only thing carrying earlier turns forward, so it is written as facts the
planner can act on, not as prose about the conversation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.persistence.models import Task
from app.ports import ModelGatewayPort
from app.runtime.context import estimate_tokens, summary_source, versions_digest
from app.services.uow import UnitOfWork

SUMMARY_SYSTEM = """\
You compress the earlier part of a working conversation so it can be dropped from context.
The summary replaces those turns; whatever you leave out is lost to the next turn.

Write in the language the user writes in. Use these four sections, each one populated or
marked 无:

## 会话意图
What the user is trying to produce, in one or two sentences.

## 已决定
Decisions that still apply: choices the user accepted, constraints they stated, approaches
they rejected and why. Include numbers only if the user gave them.

## 已有产物
Which slots or files already have Versions, and at what version. This is how the next turn
knows what exists and does not recreate it.

## 待办
What is still open or was explicitly deferred.

Rules:
- Record only what the conversation or the supplied artifact list supports.
- Never invent product facts, numbers or decisions.
- Do not describe the conversation ("the user then said..."); state the resulting facts.
- Keep it under 400 words.
"""


@dataclass(frozen=True)
class SummaryResult:
    summary_id: str
    body: str
    covered_run_id: str | None
    turns: int


def summarize(
    uow: UnitOfWork,
    gateway: ModelGatewayPort,
    task: Task,
    *,
    keep: int,
    trigger: str,
    profile_key: str,
    run_id: str | None = None,
) -> SummaryResult | None:
    """Summarize all but the newest `keep` turns. Returns None when there is nothing to do.

    The caller commits. Artifacts already produced are listed explicitly so the summary
    cannot silently drop them.
    """
    source, covered, turns = summary_source(uow, task, keep=keep)
    if not source:
        return None
    artifacts = versions_digest(uow, task)
    user: dict[str, object] = {
        "task_goal": task.goal,
        "task_kind": task.kind,
        "current_versions": artifacts,
        "conversation": source,
    }
    res = gateway.chat_json(
        profile_key, _json_mode(SUMMARY_SYSTEM), _json(user), purpose="summary",
    )
    body = str(res.data.get("summary") or res.data.get("content") or "").strip()
    if not body:
        return None
    row = uow.collab.add_summary(
        task.id, run_id, body, estimate_tokens(body), trigger, covered_run_id=covered,
    )
    return SummaryResult(summary_id=row.id, body=body, covered_run_id=covered, turns=turns)


def _json_mode(system: str) -> str:
    """Vendors enforce that a `json_object` request mentions JSON somewhere in the prompt.

    The summary prompt is prose; the required shape is added here so the constraint is
    satisfied once, in one place, rather than by wording every prompt to mention JSON.
    """
    if "json" in system.lower():
        return system
    return system + '\n\nReturn one JSON object: {"summary": "<the four sections as text>"}.'


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False)
