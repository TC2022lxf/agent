"""Conversation context for the planner (docs/architecture/agent-runtime.md). Compaction, Cursor-style.

What the planner sees on a turn is not the raw chat log:

    [summary of older turns]  +  [recent turns verbatim]

The summary is stored in `context_summaries` and reused on later turns, so the same history
is not compacted twice. `Run.context_refs.summary_id` records which one a run read, and
`covered_run_id` marks how far the summary reaches.

Why not keep the whole log: a Task can run for hundreds of turns, and the planner needs the
decisions and the artifacts, not every sentence. Why not compact at a fixed message count:
the trigger uses the model's own `context_window_tokens`, so switching the bound model
changes when compaction happens.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import slots as slot_registry
from app.persistence.models import ContextSummary, Run, Task
from app.services.uow import UnitOfWork

# Rough token estimate: mixed Chinese and English prose lands near three characters per token.
CHARS_PER_TOKEN = 3
# Never send a single turn longer than this; a huge paste is truncated, not dropped.
MAX_TURN_CHARS = 6000


@dataclass(frozen=True)
class ToolLine:
    """One tool call from a finished turn: what was called and how it ended."""

    name: str
    slot: str
    status: str  # ok | error | rejected
    detail: str = ""  # a failure message or a rejected rule's problem, when there is one


@dataclass(frozen=True)
class TurnLine:
    """One finished turn, flattened for the prompt. Not a message object.

    Structured rather than prose because the planner needs to distinguish things a sentence
    loses: WHICH tool ran, WHICH slot it wrote, whether it failed and why. A rejected Version
    flattened into "助手：已完成" is how a later turn redoes work that was already refused.
    """

    run_id: str
    user: str
    agent_said: str
    versions: list[str]
    asked: str = ""  # the question the Agent put to the user (ask_question)
    answer_to: str = ""  # the question this turn's user sentence was answering
    tools: tuple[ToolLine, ...] = ()

    def render(self) -> str:
        parts = [f"用户：{self.user}"]
        if self.answer_to:
            parts.append(f"（这句是在回答上一个问题：{self.answer_to}）")
        if self.agent_said:
            parts.append(f"助手：{self.agent_said}")
        if self.asked:
            parts.append(f"助手提问：{self.asked}")
        if self.tools:
            parts.append("调用：" + "；".join(_tool_text(t) for t in self.tools))
        if self.versions:
            parts.append(f"产出：{'、'.join(self.versions)}")
        text = "\n".join(parts)
        return text if len(text) <= MAX_TURN_CHARS else text[:MAX_TURN_CHARS] + "\n…（已截断）"


def _tool_text(t: ToolLine) -> str:
    head = f"{t.name}({t.slot})" if t.slot else t.name
    if t.status == "ok":
        return head
    return f"{head} {t.status}: {t.detail[:120]}" if t.detail else f"{head} {t.status}"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _version_labels(uow: UnitOfWork, run: Run, slots: dict[str, str | None]) -> list[str]:
    """A stable, readable label per Version: `PDP P2（3 个槽位）`, `图片 v1 被拒`."""
    out: list[str] = []
    for v in uow.collab.versions_of_run(run.id):
        if v.manifest:
            out.append(f"PDP P{v.seq}（{len(v.manifest)} 个槽位）")
            continue
        slot = slots.get(v.artifact_id)
        label = slot or "文件"
        if slot and slot_registry.has_slot(slot):
            label = slot_registry.get_slot(slot).description
        mark = " 被拒" if v.status == "rejected" else ""
        out.append(f"{label} v{v.seq}{mark}")
    return out


def build_turn_lines(uow: UnitOfWork, task: Task) -> list[TurnLine]:
    """Every finished turn of this Task, oldest first.

    A turn records two things the planner needs and cannot infer: the question it asked
    (`ask_question`), and — when this turn is the user replying to one — which question the
    sentence answers. Leaving the question out meant the next Run saw a bare "一个电动剃须刀"
    with nothing it was replying to, which is a context break, not a follow-up
    (docs/architecture/agent-runtime.md, 0043).
    """
    slots = {a.id: a.slot for a in uow.collab.artifacts(task.id)}
    stated: dict[str, list[str]] = {}
    for fb in uow.collab.feedback_list(task.id):
        stated.setdefault(fb.run_id or "", []).append(fb.text)
    said: dict[str, str] = {}
    asked: dict[str, str] = {}
    by_request: dict[str, str] = {}  # request_id -> question
    tools: dict[str, list[ToolLine]] = {}
    runs = uow.collab.runs_of(task.id)
    for run in runs:
        answers: list[str] = []
        for e in uow.collab.events_after(run.id, 0):
            if e.type == "answer":
                text = str(e.data.get("text") or "")
                if text:
                    answers.append(text)
            elif e.type == "human_input_request":
                question = str(e.data.get("question") or "").strip()
                if question:
                    asked[run.id] = question
                    rid = str(e.data.get("request_id") or "")
                    if rid:
                        by_request[rid] = question
        joined = " ".join(answers)
        if joined:
            said[run.id] = joined
        # Which tool ran, on which slot, and whether the result survived the rules. A turn
        # that flattened to "助手：已完成" is exactly what made a later turn redo refused work.
        for tc in uow.collab.tool_calls(run.id):
            status = tc.status
            detail = str(tc.error or "")
            vid = (tc.output or {}).get("version_id")
            if status == "ok" and isinstance(vid, str):
                try:
                    if uow.collab.get_version(vid).status == "rejected":
                        status = "rejected"
                        detail = _reject_detail(uow, vid)
                except NotFound:
                    pass
            slot = str((tc.input or {}).get("slot") or (tc.input or {}).get("path") or "")
            tools.setdefault(run.id, []).append(
                ToolLine(name=tc.tool_name, slot=slot, status=status, detail=detail)
            )
    # A reply carries the question it is answering. The explicit id wins; adjacency is the
    # fallback for clients that do not send one (an older composer, a scripted call).
    answered: dict[str, str] = {}
    for i, run in enumerate(runs):
        rid = str((run.input or {}).get("answers_request_id") or "")
        if rid and rid in by_request:
            answered[run.id] = by_request[rid]
        elif i > 0 and runs[i - 1].id in asked:
            answered[run.id] = asked[runs[i - 1].id]
    lines: list[TurnLine] = []
    for run in runs:
        text = " ".join(stated.get(run.id, []))
        if not text:
            continue
        lines.append(TurnLine(
            run_id=run.id,
            user=text,
            agent_said=said.get(run.id, ""),
            versions=_version_labels(uow, run, slots),
            asked=asked.get(run.id, ""),
            answer_to=answered.get(run.id, ""),
            tools=tuple(tools.get(run.id, ())),
        ))
    return lines


def _reject_detail(uow: UnitOfWork, version_id: str) -> str:
    """The failed rule checks of a rejected Version, as one short line for the prompt."""
    problems = [
        p
        for e in uow.collab.evaluations(version_id)
        if not e.passed
        for p in (e.details or {}).get("problems", [])
    ]
    return "；".join(problems)[:200] or "未通过规则检查"


def latest_summary(uow: UnitOfWork, task_id: str) -> ContextSummary | None:    return uow.collab.latest_summary(task_id)


def _covered_run_ids(uow: UnitOfWork, task_id: str, summary: ContextSummary) -> set[str]:
    """Runs at or before the summary's watermark. Empty when the watermark is unset."""
    if not summary.covered_run_id:
        return set()
    out: set[str] = set()
    for run in uow.collab.runs_of(task_id):
        out.add(run.id)
        if run.id == summary.covered_run_id:
            return out
    return set()


def prior_messages(
    uow: UnitOfWork, task: Task, exclude_run_id: str,
) -> tuple[list[str], str | None]:
    """`(messages for the planner, summary_id used)`. The newest summary wins.

    Order: the summary first, then only the turns it does not already cover. A summary whose
    watermark no longer matches the history is ignored rather than trusted.
    """
    lines = [line for line in build_turn_lines(uow, task) if line.run_id != exclude_run_id]
    summary = latest_summary(uow, task.id)
    if summary is None:
        return [line.render() for line in lines], None
    covered = _covered_run_ids(uow, task.id, summary)
    if not covered:
        return [line.render() for line in lines], None
    tail = [line for line in lines if line.run_id not in covered]
    head = "此前对话摘要（更早的回合已压缩）：\n" + summary.body
    return [head, *(line.render() for line in tail)], summary.id


def should_compact(
    uow: UnitOfWork, task: Task, *, fraction: float, keep: int, window: int,
) -> bool:
    """Compact when the history we would send passes `fraction` of the model window.

    Measured two ways and the larger one wins:

    1. The last Run's real `tokens_in` from `llm_calls`. That is the only honest number: it
       counts the system prompt, the contract, the payload and the images, not just the
       transcript. The old `len(text) // 3` estimate ignored all of those, so a Task with a
       large file could be at 90% of the window while the estimate said 40%.
    2. The estimate of the transcript, for the very first turn (no call has happened yet) and
       for the turns after a compaction dropped the history that produced the real number.
    """
    if window <= 0 or fraction <= 0:
        return False
    lines = build_turn_lines(uow, task)
    if len(lines) <= keep:
        return False
    estimated = sum(estimate_tokens(line.render()) for line in lines)
    measured = _last_prompt_tokens(uow, task.id)
    used = max(estimated, measured)
    return used >= int(window * fraction)


def _last_prompt_tokens(uow: UnitOfWork, task_id: str) -> int:
    """`tokens_in` of the newest planner call on this Task, or 0 when there is none."""
    for run in reversed(uow.collab.runs_of(task_id)):
        rows = uow.collab.llm_calls_of_run(run.id)
        for row in reversed(rows):
            if row.purpose == "plan" and row.tokens_in:
                return int(row.tokens_in)
    return 0


def summary_source(uow: UnitOfWork, task: Task, *, keep: int) -> tuple[str, str | None, int]:
    """Text to summarize, the watermark run id, and how many turns were included.

    Everything except the newest `keep` turns goes in; those stay verbatim so the planner
    still sees the immediate back-and-forth exactly as the user wrote it. A history that is
    not longer than `keep` yields nothing: compacting it would replace the whole conversation
    with a summary of itself.
    """
    lines = build_turn_lines(uow, task)
    if keep and len(lines) <= keep:
        return "", None, 0
    older = lines[:-keep] if keep else lines
    if not older:
        return "", None, 0
    body = "\n\n".join(line.render() for line in older)
    return body, older[-1].run_id, len(older)


def versions_digest(uow: UnitOfWork, task: Task) -> list[str]:
    """Current Version per slot, for the ARTIFACTS section of a summary."""
    out: list[str] = []
    for art in uow.collab.artifacts(task.id):
        if art.kind == "pdp" or not art.slot:
            continue
        current = uow.collab.current_version(task.id, art.slot)
        if current is not None:
            out.append(f"{art.slot} v{current.seq}")
    return out


def task_state(uow: UnitOfWork, task: Task) -> str:
    """A short, always-current block injected every turn and never compacted.

    A summary is a lossy rewrite: it is regenerated, it can drop a constraint the user is
    still relying on, and it says nothing about what FAILED. This block is different in the
    one way that matters: it is derived from the database on every turn, so it cannot drift,
    and it is never fed through a model.

    It exists because the planner could not answer "what is the state of this Task" from the
    transcript alone — the current picture, the rules in force, and the last refusal are
    facts, not conversation.
    """
    parts: list[str] = [f"目标：{task.goal or '（未设定）'}", f"类型：{task.kind}"]
    current = {
        a.slot: uow.collab.current_version(task.id, a.slot)
        for a in uow.collab.artifacts(task.id)
        if a.slot and a.kind != "pdp"
    }
    have = [f"{slot} v{v.seq}" for slot, v in current.items() if v is not None]
    parts.append("当前版本：" + ("、".join(have) if have else "（还没有任何版本）"))
    cons = uow.collab.constraints(task.id)
    if cons["effective"]:
        parts.append(
            "已生效规则：" + "；".join(c.text for c in cons["effective"])
        )
    if cons["pending"]:
        parts.append(
            "待确认规则（尚未生效，不要当成约束）："
            + "；".join(c.text for c in cons["pending"])
        )
    last_reject = _last_rejection(uow, task.id)
    if last_reject:
        parts.append(f"上一次被拒：{last_reject}")
    return "\n".join(parts)


def _last_rejection(uow: UnitOfWork, task_id: str) -> str:
    """The newest rejected Version's slot and problems, or ""."""
    for run in reversed(uow.collab.runs_of(task_id)):
        for v in reversed(uow.collab.versions_of_run(run.id)):
            if v.status != "rejected":
                continue
            slot = str(getattr(uow.collab.artifact(v.artifact_id), "slot", "") or "")
            return f"{slot or '版本'} — {_reject_detail(uow, v.id)}"
    return ""
