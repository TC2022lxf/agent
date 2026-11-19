"""RunExecutor: docs/07 steps 6-14 in their thinnest form.

claim -> load context -> interpret -> per item: plan -> ToolRunner -> WriteScopeGuard ->
commit Version -> rule evaluation -> (bind to PDP) -> settle credits.
The database is reached only through UnitOfWork; no vendor SDK is imported here.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.registry import Registry
from app.domain import slots as slot_registry
from app.evaluators.base import EvaluatorRegistry
from app.infrastructure.gateway_logging import (
    current_image_profile,
    current_planner_profile,
    current_run_id,
)
from app.ports import ModelGatewayPort, ObjectStorePort
from app.runtime.compaction import summarize
from app.runtime.context import (
    build_turn_lines,
    prior_messages,
    should_compact,
    task_state,
)
from app.runtime.langgraph_loop import (
    LoopContext,
    RunFailed,
    WorkerStopped,
)
from app.runtime.loop import AgentLoop, Item, SlotState, TaskView, stage_of
from app.runtime.tool_runner import ToolRunner
from app.services import followups
from app.services.profiles import ProfileDisabled
from app.services.uow import UowFactory

log = logging.getLogger(__name__)

_READABLE_EXT = frozenset({
    "txt", "md", "markdown", "csv", "tsv", "json", "yaml", "yml", "html", "htm",
    "css", "js", "ts", "tsx", "jsx", "py", "sql", "log", "xml", "toml", "ini",
})


def _attachment_text(store: ObjectStorePort, key: str) -> str | None:
    """Only decode what we are sure is text; a wrong guess would send bytes to the model."""
    if slot_registry.file_extension(key) not in _READABLE_EXT or not store.exists(key):
        return None
    try:
        text = store.get(key).decode("utf-8")
    except (UnicodeDecodeError, KeyError):
        return None
    return text if len(text) <= 60_000 else text[:60_000] + "\n…（已截断）"


_PROTECT_SLOT = (
    "不要动", "不要改", "别动", "别改", "保持不变", "保持不动", "不动", "其他不变",
    "其它不变", "其余不变", "不用动", "不要碰", "别碰", "原样",
)


def _protects_another_slot(text: str) -> bool:
    """A "leave X alone" clause protects a slot from THIS edit; it never states a rule."""
    return any(w in text for w in _PROTECT_SLOT)


def _operation_of(text: str, payload: dict[str, Any]) -> str:
    """Which image operation this sentence asks for.

    The interpret model used to return this field. It is a keyword question, not a judgement:
    "再大一点 / 放大" is `product_scale` (which `edit_product_image` refuses as unproven), and
    everything else is a free edit. An explicit `operation` in the payload wins.
    """
    explicit = str(payload.get("operation") or "").strip()
    if explicit:
        return explicit
    if any(w in text for w in ("大一点", "放大", "再大", "bigger", "larger")):
        return "product_scale"
    if any(w in text for w in ("去背景", "去掉背景", "remove bg", "remove background")):
        return "remove_bg"
    if any(w in text for w in ("放大清晰", "超分", "upscale")):
        return "upscale"
    return "free"


def _slot_allowed(kind: str, slot: str) -> bool:
    if kind == "file":
        return slot_registry.is_file_slot(slot)
    if slot_registry.is_multi_artifact(kind):
        return slot_registry.allows_slot(kind, slot)
    return slot_registry.has_slot(slot) and slot in slot_registry.slots_for_task_kind(kind)


_RUN_FAILED_TEXT = {
    "run_budget_exceeded": "这次运行的预算用完了。已经产生的部分照常计费，剩余冻结额已退回。"
    "可以缩短要求，或提高这次任务的预算后再试。",
    "resume exhausted": "这次运行中断后没能继续，已停止。冻结的积分已退回。",
}


def _run_failed_text(code: str) -> str:
    """A Run-level failure code is for logs; the user gets a sentence (docs/06)."""
    return _RUN_FAILED_TEXT.get(code, code)


def _readable_error(exc: Exception) -> str:
    """A failure the user can act on, not a class name.

    A vendor read timeout used to surface as "ReadTimeout: The read operation timed out",
    which tells the user nothing and reads like a product bug. Name whose side failed.
    """
    name = type(exc).__name__
    if name in {"ReadTimeout", "ConnectTimeout", "TimeoutException"}:
        return "模型服务响应超时，这一轮没有完成。可以再发一次，或稍后再试。"
    if name in {"ConnectError", "ConnectionError"}:
        return "连不上模型服务，这一轮没有完成。检查网络后重试。"
    text = str(exc)
    if "image_decode" in text or "no image" in text:
        return "模型没有返回可用的图片，这一轮没有产生新版本。换个说法再试。"
    return f"{name}: {text}"


class RunExecutor:
    def __init__(
        self,
        uow_factory: UowFactory,
        registry: Registry,
        evaluators: EvaluatorRegistry,
        gateway: ModelGatewayPort,
        store: ObjectStorePort,
        loop: AgentLoop,
        tool_runner: ToolRunner,
    ) -> None:
        self.uow_factory = uow_factory
        self.registry, self.evaluators = registry, evaluators
        self.gateway, self.store = gateway, store
        self.loop, self.tools = loop, tool_runner

    # ------------------------------------------------------------------
    def execute(self, run_id: str) -> None:
        token = current_run_id.set(run_id)
        planner_token = current_planner_profile.set("")
        image_token = current_image_profile.set("")
        try:
            planner_key, image_key = self._profile_keys(run_id)
            current_planner_profile.reset(planner_token)
            current_image_profile.reset(image_token)
            planner_token = current_planner_profile.set(planner_key)
            image_token = current_image_profile.set(image_key)
            self._execute(run_id)
        except WorkerStopped:
            self._requeue(run_id)
        except RunFailed as exc:
            # Budget or step limit reached: the work that already happened is still charged
            # (docs/11 "用户原因或正常结束：按已发生的成本结算").
            self._finish(run_id, "failed", error=_run_failed_text(exc.message),
                         cost=self._spent(run_id))
        except ProfileDisabled as exc:
            self._finish(run_id, "failed", error=str(exc))
        except Exception as e:
            log.exception("run %s failed", run_id)
            # Anything unclassified is our side (vendor 5xx, timeout, crash), so the user is
            # not charged for it. docs/11 section 3, "失败的规则".
            self._finish(run_id, "failed", error=_readable_error(e), platform_fault=True)
        finally:
            current_run_id.reset(token)
            current_planner_profile.reset(planner_token)
            current_image_profile.reset(image_token)

    def _execute(self, run_id: str) -> None:
        with self.uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            if run.status not in {"queued", "running"}:
                return
            run.status = "running"
            payload, user_id, agent_key = dict(run.input), run.user_id, run.agent_key
            trace_id, held, task_id = run.trace_id, run.held, run.task_id
            task = uow.collab.get_task(task_id)
            kind, goal, task_meta = task.kind, task.goal, dict(task.meta)
            prefs_md, prefs_rev = uow.prefs.current(user_id, agent_key)
            effective = uow.collab.constraints(task_id)["effective"]
            rules = [c.rule for c in effective]
            prior = uow.collab.feedback_for_run(run_id)
            spec = self.registry.agent(agent_key)
            skills = {s.id: s for s in self.registry.skills_for(agent_key)}
            if not run.skill_versions:
                run.skill_versions = {
                    sid: skills[sid].content_hash for sid in spec.skill_ids if sid in skills
                }
            if not run.context_refs:
                run.context_refs = {
                    "preferences_revision": prefs_rev,
                    "constraint_ids": [c.id for c in effective],
                }
            if not prior:
                uow.collab.add_event(run_id, "run_started", {"agent": agent_key})
            uow.commit()
        if not prior:
            self._event(run_id, "context_loaded", {"preferences_revision": prefs_rev})
            self._path(run_id, "load_context")
            # Compact before the planner reads history: the turn that crosses the threshold
            # is the first one working from the summary.
            if self._maybe_compact(run_id, task_id):
                self._path(run_id, "compact")
            items = self._open_utterance(run_id, task_id, payload)
        else:
            self._path(run_id, "resume")
            items = self._open_items(run_id, task_id)
        pending_human = False
        last_answer = ""
        last_fb = ""
        for fb_id, item in items:
            if self._cancel_requested(run_id):
                spent, _vids = self._accounted(run_id)
                self._finish(run_id, "cancelled", cost=spent, held=held, user_id=user_id)
                return
            self._path(run_id, "handle:patch")
            view = self._view(task_id, kind, goal, rules, task_meta.get("facts", {}))
            outcome = self.loop.run(item, view, LoopContext(
                run_id=run_id, task_id=task_id, user_id=user_id, agent_key=agent_key,
                trace_id=trace_id, kind=kind, task_meta=task_meta, rules=rules, held=held,
                spent=self._spent(run_id), preferences_md=prefs_md,
                reasoning=bool(payload.get("reasoning")), resume=bool(prior),
                prior_texts=self._prior_texts(task_id, run_id),
                skill_id=payload.get("skill_id"),
                attachments=self._attachments(payload),
                # The request-level boundary (what the user picked in the UI), not the
                # item's slot: comparing the item to itself can never catch anything.
                target_slot=payload.get("target_slot"),
                target_region=payload.get("target_region"),
                target_version_id=str(payload.get("target_version_id") or ""),
                replying_to=self._question_being_answered(task_id, payload),
                client_hint=str(payload.get("client_hint") or ""),
            ))
            declined = outcome.declined
            if declined:
                self._event(run_id, "tool_declined", {"reason": declined})
            if outcome.answer and outcome.answer != declined:
                self._event(run_id, "answer", {
                    "feedback_id": fb_id,
                    "text": outcome.answer,
                    "options": list(outcome.answer_options),
                })
                last_answer, last_fb = outcome.answer, fb_id
            if outcome.human_input_requests:
                pending_human = True
            if outcome.recorded_constraints:
                self._feedback_status(fb_id, "applied", "constraint recorded")
            self._feedback_status(fb_id, "declined" if declined else "applied", declined)

        # Follow-ups are the last thing a finished turn does. They are a separate, skippable
        # call: they never change what was produced, and they are not asked for while the
        # Agent is waiting on a real question (decisions/0042).
        if last_answer and last_fb and not pending_human and self._followups_on():
            self._suggest_followups(run_id, task_id, agent_key, last_fb, payload.get("text", ""))

        cost, version_ids = self._accounted(run_id)
        self._finish(run_id, "succeeded", cost=cost, held=held, user_id=user_id,
                     version_ids=version_ids, pending_human=pending_human)

    def _followups_on(self) -> bool:
        """Read at call time, so turning the feature off takes effect on the next Run."""
        with self.uow_factory() as uow:
            return uow.profiles.followups_enabled()

    def _suggest_followups(
        self, run_id: str, task_id: str, agent_key: str, feedback_id: str, user_text: str,
    ) -> None:
        """Attach 2-3 next questions to the answer that was just recorded.

        A separate model call on its own budget line, so it can be bound to a cheaper model
        and can fail without touching the Run (docs/06).
        """
        with self.uow_factory() as uow:
            answer = ""
            for e in uow.collab.events_after(run_id, 0):
                if e.type == "answer" and e.data.get("feedback_id") == feedback_id:
                    answer = str(e.data.get("text") or "")
            if not answer:
                return
            profile_key = uow.profiles.followups_model() or (
                uow.profiles.planner_for_agent(agent_key).key
            )
            history = [
                line.render() for line in build_turn_lines(uow, uow.collab.get_task(task_id))
            ]
        try:
            options = followups.suggest(
                self.gateway, profile_key=profile_key, user_query=user_text,
                assistant_answer=answer, context=history,
            )
        except Exception:  # noqa: BLE001 - a suggestion must never fail the Run it follows
            log.exception("follow-up suggestions failed for run %s", run_id)
            return
        if not options:
            return
        self._event(run_id, "followups", {
            "feedback_id": feedback_id,
            "questions": options,
        })

    # ------------------------------------------------------------------
    def _question_being_answered(self, task_id: str, payload: dict[str, Any]) -> str:
        """The `ask_question` text this utterance replies to, or "".

        The composer sends the `request_id` it is answering, which is exact. The fallback is
        the newest still-open request on the Task, so a scripted or older client still gets its
        answer attached to a question instead of arriving as a sentence from nowhere.
        """
        rid = str(payload.get("answers_request_id") or "")
        with self.uow_factory() as uow:
            for run in reversed(uow.collab.runs_of(task_id)):
                for e in uow.collab.events_after(run.id, 0):
                    if e.type != "human_input_request":
                        continue
                    request = str(e.data.get("request_id") or "")
                    if rid and request != rid:
                        continue
                    question = str(e.data.get("question") or "").strip()
                    if question:
                        return question
                    if rid:
                        return ""
        return ""

    def _open_utterance(
        self, run_id: str, task_id: str, payload: dict[str, Any],
    ) -> list[tuple[str, Item]]:
        """The user's sentence becomes ONE Feedback and goes straight into the loop.

        There used to be an `interpret` model call here that split the message into items and
        labelled each one (`parameter_patch` / `new_constraint` / `question` /
        `strategy_switch`). Every one of those decisions is one the agent can make with the
        same context it uses to pick any other tool, and the extra round trip cost 40-50s
        before the first token of the turn:

        - a standing rule is `record_constraint`, a tool, not a label;
        - a question is `ask_question`, a tool;
        - "a different approach" is a different tool call, not a different route.

        Splitting a sentence into several requests is the one capability that was genuinely
        lost, and the loop covers it the way Claude Code does: the model can call several
        tools in one turn, in sequence, and a second request in the same sentence is simply a
        second tool call.

        `interpretation` stays on the row because the UI reads it, but it is a record of what
        happened (`parameter_patch` unless a constraint was recorded), not a decision made in
        advance.
        """
        text = str(payload.get("text") or "").strip()
        region = payload.get("target_region")
        slot = payload.get("target_slot")
        if slot is not None and not _slot_allowed(self._kind_of(task_id), slot):
            slot = None
        reg = region if slot and slot_registry.is_image_slot(str(slot)) else None
        base_override = None
        with self.uow_factory() as uow:
            tv = payload.get("target_version_id")
            if tv and slot:
                v = uow.collab.get_version(tv)
                if uow.collab.slot_artifact(task_id, slot).id == v.artifact_id:
                    base_override = SlotState(v.id, v.content)
            fb = uow.collab.add_feedback(
                task_id=task_id,
                run_id=run_id,
                text=text,
                interpretation="parameter_patch",
                target_slot=slot,
                target_version_id=tv,
                target_region=reg,
                extra={"operation": _operation_of(text, payload)},
            )
            uow.collab.add_event(
                run_id,
                "feedback_interpreted",
                {"items": [{"feedback_id": fb.id, "interpretation": fb.interpretation}]},
            )
            uow.commit()
        self._path(run_id, "interpret", announce=False)
        return [(fb.id, Item(
            text=text,
            interpretation="parameter_patch",
            slot=slot,
            region=reg,
            operation=_operation_of(text, payload),
            base_override=base_override,
            raw={"summary": ""},
        ))]

    def _kind_of(self, task_id: str) -> str:
        with self.uow_factory() as uow:
            return str(uow.collab.get_task(task_id).kind)

    def _view(
        self, task_id: str, kind: str, goal: str, rules: list[dict[str, Any]],
        facts: dict[str, Any],
    ) -> TaskView:
        current: dict[str, SlotState] = {}
        with self.uow_factory() as uow:
            if kind == "file" or slot_registry.is_multi_artifact(kind):
                slots = [
                    a.slot for a in uow.collab.artifacts(task_id)
                    if a.slot and a.kind in {"file", "image", "canvas"}
                ]
            else:
                slots = list(slot_registry.slots_for_task_kind(kind))
            for slot in slots:
                v = uow.collab.current_version(task_id, slot)
                if v is not None:
                    current[slot] = SlotState(v.id, v.content)
        return TaskView(kind=kind, goal=goal, current=current, user_rules=rules, facts=facts)

    def _attachments(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Text uploads are inlined for the planner; bytes-only ones are named."""
        ids = payload.get("attachment_ids") or []
        store = self.store
        out: list[dict[str, Any]] = []
        for key in ids:
            text = _attachment_text(store, str(key))
            out.append({
                "upload_id": key,
                "name": str(key).rsplit("/", 1)[-1],
                "text": text,
            })
        return out

    def _profile_keys(self, run_id: str) -> tuple[str, str]:
        with self.uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            if run.status not in {"queued", "running"}:
                return "", ""
            planner = uow.profiles.planner_for_agent(run.agent_key)
            image = uow.profiles.image_profile()
        return planner.key, image.key if image is not None else ""

    def _requeue(self, run_id: str) -> None:
        with self.uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            if run.resume_count >= 1:
                exhausted = True
            else:
                exhausted = False
                run.resume_count += 1
                run.status = "queued"
                uow.collab.add_event(run_id, "run_resume", {"resume_count": run.resume_count})
            uow.commit()
        if exhausted:
            # Worker restart gave up: our side failed, so nothing is charged.
            self._finish(run_id, "failed", error=_run_failed_text("resume exhausted"),
                         platform_fault=True)

    def _open_items(self, run_id: str, task_id: str) -> list[tuple[str, Item]]:
        out: list[tuple[str, Item]] = []
        with self.uow_factory() as uow:
            for fb in uow.collab.feedback_for_run(run_id):
                if fb.status != "open":
                    continue
                extra = dict(fb.extra or {})
                base_override = None
                if fb.target_version_id and fb.target_slot:
                    version = uow.collab.get_version(fb.target_version_id)
                    art = uow.collab.slot_artifact(task_id, fb.target_slot)
                    if art.id == version.artifact_id:
                        base_override = SlotState(version.id, version.content)
                out.append((fb.id, Item(
                    text=fb.text,
                    interpretation=fb.interpretation,
                    slot=fb.target_slot,
                    region=fb.target_region if isinstance(fb.target_region, dict) else None,
                    operation=str(extra.get("operation") or "free"),
                    base_override=base_override,
                    raw=extra,
                )))
        return out

    def _prior_texts(self, task_id: str, run_id: str) -> list[str]:
        """Conversation so far: the Task's current state, then history.

        The state block comes first and is never compacted (`runtime/context.py`): the
        summary is a lossy rewrite, and the facts a turn depends on most — what exists now,
        which rules are in force, what was just refused — must not depend on one.
        """
        with self.uow_factory() as uow:
            task = uow.collab.get_task(task_id)
            messages, _summary_id = prior_messages(uow, task, run_id)
            state = task_state(uow, task)
        return [f"当前状态（每轮由系统重新生成，不是对话内容）：\n{state}", *messages]

    def _maybe_compact(self, run_id: str, task_id: str) -> str | None:
        """Compact before the turn if history passed the window fraction. Returns the id.

        Runs before the planner sees the context, so the turn that crosses the threshold is
        already the one working from the summary.
        """
        with self.uow_factory() as uow:
            task = uow.collab.get_task(task_id)
            fraction = uow.profiles.summary_fraction()
            keep = uow.profiles.summary_keep()
            planner = uow.profiles.planner_for_agent(task.agent_key)
            window = planner.context_window_tokens
            if not should_compact(uow, task, fraction=fraction, keep=keep, window=window):
                return None
            try:
                result = summarize(
                    uow, self.gateway, task,
                    keep=keep, trigger="auto", profile_key=planner.key, run_id=run_id,
                )
            except Exception:  # noqa: BLE001 - compaction must never fail the run
                log.exception("auto compaction failed; keeping full history")
                return None
            if result is None:
                return None
            run = uow.collab.get_run(run_id)
            refs = dict(run.context_refs or {})
            refs["summary_id"] = result.summary_id
            run.context_refs = refs
            uow.collab.add_event(run_id, "context_compacted", {
                "summary_id": result.summary_id,
                "turns": result.turns,
                "covered_run_id": result.covered_run_id,
            })
            uow.commit()
            return result.summary_id

    def _spent(self, run_id: str) -> int:
        return self._accounted(run_id)[0]

    def _accounted(self, run_id: str) -> tuple[int, list[str]]:
        with self.uow_factory() as uow:
            calls = uow.collab.tool_calls(run_id)
        cost = sum(c.cost for c in calls)
        vids: list[str] = []
        for call in calls:
            vid = (call.output or {}).get("version_id")
            if isinstance(vid, str) and vid not in vids:
                vids.append(vid)
        return cost, vids

    # ---- small persistence helpers (each in its own short transaction) ----
    def _event(self, run_id: str, type_: str, data: dict[str, Any]) -> None:
        with self.uow_factory() as uow:
            uow.collab.add_event(run_id, type_, data)
            uow.commit()

    def _path(self, run_id: str, step: str, *, announce: bool = True) -> None:
        """Record a route step, and (unless already announced) show it to the waiting user.

        `announce=False` is for a phase the caller broadcast *before* the slow call: intent
        analysis takes ~45s, so the line has to appear when the wait starts, not when it ends.
        """
        with self.uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            run.path = [*run.path, step]
            if announce:
                uow.collab.add_event(run_id, "step", {"stage": stage_of(step), "detail": step})
            uow.commit()

    def _feedback_status(self, fb_id: str, status: str, note: str = "") -> None:
        with self.uow_factory() as uow:
            uow.collab.set_feedback_status(fb_id, status, note)
            uow.commit()

    def _cancel_requested(self, run_id: str) -> bool:
        with self.uow_factory() as uow:
            return uow.collab.get_run(run_id).status == "cancel_requested"

    def _finish(
        self,
        run_id: str,
        status: str,
        *,
        error: str | None = None,
        cost: int = 0,
        held: int | None = None,
        user_id: str | None = None,
        version_ids: list[str] | None = None,
        platform_fault: bool = False,
        pending_human: bool = False,
    ) -> None:
        """Settle the hold: charge the real cost, or give it all back on a platform fault.

        A user-caused stop (budget reached, constraint rejection, cancel) still pays for the
        work that actually happened. A vendor timeout or a crash does not.
        """
        with self.uow_factory() as uow:
            run = uow.collab.get_run(run_id)
            held = run.held if held is None else held
            user_id = run.user_id if user_id is None else user_id
            if platform_fault:
                charged = 0
                refunded = uow.credits.refund(user_id, run_id, held)
                overrun = 0
            else:
                result = uow.credits.settle(user_id, run_id, held, cost)
                charged, refunded, overrun = result.charged, result.refunded, result.overrun
            run.status, run.error, run.cost = status, error, charged
            run.overrun = overrun
            run.version_ids = version_ids or []
            task = uow.collab.get_task(run.task_id)
            # Which slots hold a version depends on the Task kind: a `general` Task owns no
            # fixed slots, so its artifacts have to be read instead of derived.
            if slot_registry.is_multi_artifact(task.kind) or task.kind == "file":
                has_any = any(a.current_version_id for a in uow.collab.artifacts(task.id))
            else:
                has_any = any(
                    uow.collab.current_version(task.id, s) is not None
                    for s in slot_registry.slots_for_task_kind(task.kind)
                )
            task.status = "awaiting_user" if (has_any or pending_human) else "draft"
            uow.collab.add_event(
                run_id,
                f"run_{status}",
                {
                    "cost": charged, "refunded": refunded, "held": held,
                    "overrun": overrun, "error": error, "version_ids": run.version_ids,
                    "balance": uow.credits.balance(user_id),
                },
            )
            uow.commit()

