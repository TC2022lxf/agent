"""Collaboration service: tasks, artifacts, versions, feedback, constraints, runs.

Invariants live here (docs/03): versions are never overwritten, slot pointers move one
at a time, rejected versions never become current, one active Run per Task.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain import canvas as canvas_domain
from app.domain import slots as slot_registry
from app.persistence.models import (
    Artifact,
    Constraint,
    ContextSummary,
    Evaluation,
    Feedback,
    LlmCall,
    Run,
    RunEvent,
    Task,
    ToolCall,
    Version,
)

TERMINAL_RUN = {"succeeded", "failed", "cancelled"}
ACTIVE_RUN = {"queued", "running", "cancel_requested"}


def _artifact_kind_for(slot: str) -> str | None:
    """Artifacts a Task gains while it runs. A general Task may hold files and images."""
    if slot_registry.is_file_slot(slot):
        return "file"
    if slot_registry.canvas_module_index(slot) is not None:
        return "image"
    if slot in slot_registry.IMAGE_SLOT_KEYS:
        return "image"
    if slot_registry.is_canvas_slot(slot):
        return "canvas"
    if slot in slot_registry.PDP_SLOT_KEYS:
        return slot_registry.get_slot(slot).artifact_kind
    return None


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class CollabService:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- tasks & artifacts -------------------------------------------------
    def create_task(
        self, user_id: str, kind: str, agent_key: str, goal: str, meta: dict[str, Any]
    ) -> Task:
        task = Task(user_id=user_id, kind=kind, agent_key=agent_key, goal=goal, meta=meta)
        self.s.add(task)
        self.s.flush()
        if kind == "pdp":
            self.s.add(Artifact(task_id=task.id, kind="pdp", slot=None))
        for key in slot_registry.open_slots_for_task_kind(kind):
            self.s.add(
                Artifact(task_id=task.id, kind=slot_registry.get_slot(key).artifact_kind, slot=key)
            )
        self.s.flush()
        return task

    def get_task(self, task_id: str, user_id: str | None = None) -> Task:
        t = self.s.get(Task, task_id)
        if t is None or (user_id is not None and t.user_id != user_id):
            raise NotFound(task_id)
        return t

    def list_tasks(self, user_id: str) -> list[Task]:
        return list(
            self.s.scalars(
                select(Task).where(Task.user_id == user_id).order_by(Task.created_at.desc())
            )
        )

    def artifacts(self, task_id: str) -> list[Artifact]:
        return list(self.s.scalars(select(Artifact).where(Artifact.task_id == task_id)))

    def artifact(self, artifact_id: str) -> Artifact:
        a = self.s.get(Artifact, artifact_id)
        if a is None:
            raise NotFound(artifact_id)
        return a

    def slot_artifact(self, task_id: str, slot: str) -> Artifact:
        a = self.s.scalar(
            select(Artifact).where(Artifact.task_id == task_id, Artifact.slot == slot)
        )
        if a is None:
            raise NotFound(f"slot {slot}")
        return a

    def pdp_artifact(self, task_id: str, *, create: bool = False) -> Artifact:
        a = self.s.scalar(
            select(Artifact).where(Artifact.task_id == task_id, Artifact.kind == "pdp")
        )
        if a is None:
            if not create:
                raise NotFound("pdp artifact")
            a = Artifact(task_id=task_id, kind="pdp", slot=None)
            self.s.add(a)
            self.s.flush()
        return a

    # ---- canvas (decisions/0025) -------------------------------------------
    def canvas_artifact(self, task_id: str, *, create: bool = False) -> Artifact:
        a = self.s.scalar(
            select(Artifact).where(
                Artifact.task_id == task_id, Artifact.kind == "canvas", Artifact.slot == "canvas",
            )
        )
        if a is None:
            if not create:
                raise NotFound("canvas artifact")
            a = Artifact(task_id=task_id, kind="canvas", slot=slot_registry.CANVAS_SLOT)
            self.s.add(a)
            self.s.flush()
        return a

    def canvas_version(self, task_id: str) -> Version | None:
        """The current canvas, or None when the Task has not written one yet."""
        try:
            art = self.canvas_artifact(task_id)
        except NotFound:
            return None
        return self.s.get(Version, art.current_version_id) if art.current_version_id else None

    def commit_canvas_version(
        self,
        *,
        task_id: str,
        content: dict[str, Any],
        base_version_id: str | None,
        created_by: str,
        run_id: str | None,
        origin: str | None = None,
        accepted: bool = True,
        pointers: dict[str, str] | None = None,
    ) -> Version:
        """One new canvas Version; image module pointers come from `content` + base manifest.

        The canvas is the only place where a Version decides the current pointer of other
        artifacts (`canvas_image_N`). That is done in `activate_canvas_version`, not by
        `commit_output`, so PDP binding keeps its own rule (decisions/0025).
        """
        art = self.canvas_artifact(task_id, create=True)
        prev = self.s.get(Version, art.current_version_id) if art.current_version_id else None
        previous = dict(prev.manifest) if prev and prev.manifest else {}
        merged = dict(previous)
        merged.update(pointers or {})
        manifest = canvas_domain.manifest_for(content, merged)
        # A pointer that is not this Task's own Version is dropped, and the module falls back to
        # the picture it already showed: refusing a foreign id must not blank an existing one.
        kept = self._only_own_versions(task_id, content, manifest)
        manifest = {
            module_id: vid
            for module_id, vid in manifest.items()
            if module_id in kept
        }
        for module_id, vid in previous.items():
            manifest.setdefault(module_id, vid)
        v = Version(
            artifact_id=art.id,
            task_id=task_id,
            seq=self._next_seq(art.id),
            parent_version_id=base_version_id or (prev.id if prev else None),
            origin=origin or ("edited" if base_version_id else "generated"),
            created_by=created_by,
            content=content,
            manifest=manifest,
            status="candidate",
            run_id=run_id,
        )
        self.s.add(v)
        self.s.flush()
        if accepted:
            self.activate_canvas_version(v.id)
        else:
            v.status = "rejected"
            self.s.flush()
        return v

    def _only_own_versions(
        self, task_id: str, content: dict[str, Any], manifest: dict[str, str],
    ) -> dict[str, str]:
        """Drop pointers that are not a Version of this Task's own module slot.

        The board is a list of screens, so modules live under `screens[].modules`. Reading the
        old top-level `modules` key made this return {} and silently discard every pointer.
        """
        body = canvas_domain.upgrade(content)
        slots = {
            m["id"]: m["slot"]
            for screen in body.get("screens", [])
            for m in screen.get("modules", [])
            if m.get("kind") == "image"
        }
        out: dict[str, str] = {}
        for module_id, vid in manifest.items():
            slot = slots.get(module_id)
            if slot is None:
                continue
            try:
                art = self.slot_artifact(task_id, slot)
            except NotFound:
                continue
            v = self.s.get(Version, vid)
            if v is not None and v.artifact_id == art.id:
                out[module_id] = vid
        return out

    def activate_canvas_version(self, version_id: str) -> Version:
        """Make a canvas Version current and sync the image module slots it points at.

        A pointer is only honoured when it names a Version of *this* Task's slot artifact.
        Otherwise the module keeps an empty frame rather than borrowing another Task's picture
        (AGENTS.md write boundary).
        """
        v = self.get_version(version_id)
        if v.status == "rejected":
            raise Conflict("rejected versions cannot become current")
        art = self.s.get_one(Artifact, v.artifact_id)
        art.current_version_id = v.id
        v.status = "ok"
        by_slot = {
            m["slot"]: m["id"] for m in v.content.get("modules", []) if m.get("kind") == "image"
        }
        for slot, module_id in by_slot.items():
            vid = (v.manifest or {}).get(module_id)
            if not vid:
                continue
            try:
                slot_art = self.slot_artifact(task_id=v.task_id, slot=slot)
            except NotFound:
                continue
            pointer = self.s.get(Version, vid)
            if pointer is not None and pointer.artifact_id == slot_art.id:
                slot_art.current_version_id = pointer.id
        self.s.flush()
        return v

    def set_task_status(self, task: Task, status: str) -> None:
        task.status = status

    # ---- versions ---------------------------------------------------------
    def get_version(self, version_id: str) -> Version:
        v = self.s.get(Version, version_id)
        if v is None:
            raise NotFound(version_id)
        return v

    def versions_of(self, artifact_id: str) -> list[Version]:
        return list(
            self.s.scalars(
                select(Version).where(Version.artifact_id == artifact_id).order_by(Version.seq)
            )
        )

    def current_version(self, task_id: str, slot: str) -> Version | None:
        a = self.slot_artifact(task_id, slot)
        return self.s.get(Version, a.current_version_id) if a.current_version_id else None

    def commit_candidate(
        self,
        *,
        task_id: str,
        slot: str,
        content: dict[str, Any],
        params: dict[str, Any],
        origin: str,
        created_by: str,
        run_id: str | None,
        parent_version_id: str | None,
    ) -> Version:
        """Always a NEW row. Never overwrites a previous version."""
        try:
            art = self.slot_artifact(task_id, slot)
        except NotFound:
            kind = _artifact_kind_for(slot)
            if kind is None:
                raise
            art = Artifact(task_id=task_id, kind=kind, slot=slot)
            self.s.add(art)
            self.s.flush()
        seq = self._next_seq(art.id)
        v = Version(
            artifact_id=art.id,
            task_id=task_id,
            seq=seq,
            parent_version_id=parent_version_id,
            origin=origin,
            created_by=created_by,
            content=content,
            params=params,
            status="candidate",
            run_id=run_id,
        )
        self.s.add(v)
        self.s.flush()
        return v

    def import_slot(
        self, task: Task, slot: str, content: dict[str, Any], *, bind: bool = True
    ) -> Version:
        """Imported content is the first Version (origin=imported), current regardless of
        rule results: the baseline may be non-compliant and that is what we optimise."""
        v = self.commit_candidate(
            task_id=task.id,
            slot=slot,
            content=content,
            params={},
            origin="imported",
            created_by="user",
            run_id=None,
            parent_version_id=None,
        )
        self.finalize_version(v, accepted=True)
        if bind and slot_registry.is_pdp_slot(slot):
            self.bind_to_pdp(
                task.id, slot, v.id, None, "user", "imported",
                create=slot_registry.is_multi_artifact(task.kind),
            )
        return v

    def add_evaluation(
        self, version_id: str, evaluator_id: str, passed: bool, can_reject: bool, details: Any
    ) -> None:
        self.s.add(
            Evaluation(
                version_id=version_id,
                evaluator_id=evaluator_id,
                passed=passed,
                can_reject=can_reject,
                details=details,
            )
        )
        self.s.flush()

    def evaluations(self, version_id: str) -> list[Evaluation]:
        return list(self.s.scalars(select(Evaluation).where(Evaluation.version_id == version_id)))

    def finalize_version(self, v: Version, accepted: bool) -> None:
        """Hard-constraint failures arrive here with accepted=False: never current."""
        v.status = "ok" if accepted else "rejected"
        if accepted:
            self.s.get_one(Artifact, v.artifact_id).current_version_id = v.id
        self.s.flush()

    def bind_to_pdp(self, task_id: str, slot: str, version_id: str, run_id: str | None,
                    created_by: str, origin: str = "edited", *,
                    create: bool = False) -> Version:
        """New PDP Version pointing at the new slot version; other pointers unchanged."""
        return self.bind_many_to_pdp(
            task_id, {slot: version_id}, run_id, created_by, origin, create=create,
        )

    def bind_many_to_pdp(self, task_id: str, updates: dict[str, str], run_id: str | None,
                         created_by: str, origin: str = "edited", *,
                         create: bool = False) -> Version:
        """One new PDP Version for several slot pointers (e.g. importing a whole listing).

        `create` lets a general Task gain its `pdp` artifact on first use; a pdp Task always
        has one already.
        """
        pdp = self.pdp_artifact(task_id, create=create)
        prev = self.s.get(Version, pdp.current_version_id) if pdp.current_version_id else None
        manifest = dict(prev.manifest) if prev else {}
        manifest.update(updates)
        v = Version(
            artifact_id=pdp.id,
            task_id=task_id,
            seq=self._next_seq(pdp.id),
            parent_version_id=prev.id if prev else None,
            origin=origin if prev else "generated",
            created_by=created_by,
            manifest=manifest,
            status="ok",
            run_id=run_id,
        )
        self.s.add(v)
        self.s.flush()
        pdp.current_version_id = v.id
        return v

    def make_current(self, version_id: str, user_id: str) -> Version:
        v = self.get_version(version_id)
        task = self.get_task(v.task_id, user_id)
        if task.status in {"accepted", "abandoned"}:
            raise Conflict("task is terminal")
        if v.status == "rejected":
            raise Conflict("rejected versions cannot become current")
        art = self.s.get_one(Artifact, v.artifact_id)
        if art.kind == "pdp":
            art.current_version_id = v.id
            for slot, vid in v.manifest.items():
                self.slot_artifact(task.id, slot).current_version_id = vid
            return v
        if art.kind == "canvas":
            return self.activate_canvas_version(v.id)
        art.current_version_id = v.id
        if slot_registry.is_pdp_slot(art.slot or "") or task.kind == "pdp":
            return self.bind_to_pdp(
                task.id, art.slot or "", v.id, None, "user", "user",
                create=slot_registry.is_multi_artifact(task.kind),
            )
        return v

    def set_signal(self, version_id: str, user_id: str, signal: str) -> Version:
        v = self.get_version(version_id)
        self.get_task(v.task_id, user_id)
        v.user_signal = signal
        return v

    def _next_seq(self, artifact_id: str) -> int:
        m = self.s.scalar(select(func.max(Version.seq)).where(Version.artifact_id == artifact_id))
        return (m or 0) + 1

    # ---- feedback & constraints --------------------------------------------
    def add_feedback(
        self,
        *,
        task_id: str,
        run_id: str,
        text: str,
        interpretation: str,
        target_slot: str | None,
        target_version_id: str | None,
        target_region: dict[str, float] | None,
        extra: dict[str, Any] | None = None,
    ) -> Feedback:
        fb = Feedback(
            task_id=task_id,
            run_id=run_id,
            text=text,
            interpretation=interpretation,
            target_slot=target_slot,
            target_version_id=target_version_id,
            target_region=target_region,
            extra=extra or {},
        )
        self.s.add(fb)
        self.s.flush()
        return fb

    def feedback_list(self, task_id: str) -> list[Feedback]:
        return list(self.s.scalars(select(Feedback).where(Feedback.task_id == task_id)))

    def feedback_for_run(self, run_id: str) -> list[Feedback]:
        return list(self.s.scalars(select(Feedback).where(Feedback.run_id == run_id)))

    def get_feedback(self, fb_id: str) -> Feedback:
        return self.s.get_one(Feedback, fb_id)

    def set_feedback_status(self, fb_id: str, status: str, note: str = "") -> None:
        fb = self.s.get_one(Feedback, fb_id)
        fb.status = status
        if note:
            fb.note = note

    def dismiss_feedback(self, task_id: str, fb_id: str) -> None:
        fb = self.s.get(Feedback, fb_id)
        if fb is None or fb.task_id != task_id:
            raise NotFound(fb_id)
        fb.status = "dismissed"

    def add_constraint_draft(
        self, task_id: str, feedback_id: str | None, text: str, rule: dict[str, Any]
    ) -> Constraint:
        c = Constraint(task_id=task_id, feedback_id=feedback_id, text=text, rule=rule)
        self.s.add(c)
        self.s.flush()
        return c

    def constraints(self, task_id: str) -> dict[str, list[Constraint]]:
        rows = list(self.s.scalars(select(Constraint).where(Constraint.task_id == task_id)))
        return {
            "effective": [c for c in rows if c.status == "effective"],
            "pending": [c for c in rows if c.status == "pending"],
        }

    def confirm_constraint(self, constraint_id: str, user_id: str) -> Constraint:
        c = self._constraint(constraint_id, user_id)
        if c.status != "pending":
            raise Conflict("not pending")
        c.status = "effective"
        if c.feedback_id:
            self.set_feedback_status(c.feedback_id, "applied")
        return c

    def revoke_constraint(self, constraint_id: str, user_id: str) -> Constraint:
        c = self._constraint(constraint_id, user_id)
        was_pending = c.status == "pending"
        c.status = "revoked"
        if was_pending and c.feedback_id:
            self.set_feedback_status(c.feedback_id, "dismissed")
        return c

    def _constraint(self, constraint_id: str, user_id: str) -> Constraint:
        c = self.s.get(Constraint, constraint_id)
        if c is None:
            raise NotFound(constraint_id)
        task = self.get_task(c.task_id, user_id)
        if task.status in {"accepted", "abandoned"}:
            raise Conflict("task is terminal")
        return c

    # ---- runs ---------------------------------------------------------------
    def create_run(
        self,
        *,
        task: Task,
        trigger: str,
        payload: dict[str, Any],
        idempotency_key: str,
        held: int,
        agent_key: str | None = None,
    ) -> tuple[Run, bool]:
        """Returns (run, created). Same idempotency key -> same run, no second row."""
        existing = self.s.scalar(
            select(Run).where(Run.user_id == task.user_id, Run.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing, False
        active = self.s.scalar(
            select(Run.id).where(Run.task_id == task.id, Run.status.in_(ACTIVE_RUN))
        )
        if active is not None:
            raise Conflict("task already has an active run")
        run = Run(
            task_id=task.id,
            user_id=task.user_id,
            agent_key=agent_key or task.agent_key,
            trigger=trigger,
            input=payload,
            idempotency_key=idempotency_key,
            held=held,
        )
        self.s.add(run)
        try:
            self.s.flush()
        except IntegrityError as e:  # pragma: no cover - race on idempotency key
            raise Conflict("duplicate idempotency key") from e
        task.status = "running"
        self.add_event(run.id, "run_queued", {"run_id": run.id})
        return run, True

    def runs_of(self, task_id: str) -> list[Run]:
        return list(
            self.s.scalars(select(Run).where(Run.task_id == task_id).order_by(Run.created_at))
        )

    def versions_of_run(self, run_id: str) -> list[Version]:
        return list(
            self.s.scalars(
                select(Version).where(Version.run_id == run_id).order_by(Version.created_at)
            )
        )

    def all_constraints(self, task_id: str) -> list[Constraint]:
        return list(self.s.scalars(select(Constraint).where(Constraint.task_id == task_id)))

    def get_run(self, run_id: str, user_id: str | None = None) -> Run:
        r = self.s.get(Run, run_id)
        if r is None or (user_id is not None and r.user_id != user_id):
            raise NotFound(run_id)
        return r

    def claim_next_run(self) -> str | None:
        """Postgres will use SKIP LOCKED; here an optimistic UPDATE keeps one winner."""
        for rid in self.s.scalars(
            select(Run.id).where(Run.status == "queued").order_by(Run.created_at).limit(5)
        ).all():
            res = self.s.execute(
                update(Run).where(Run.id == rid, Run.status == "queued").values(status="running")
            )
            if res.rowcount == 1:  # type: ignore[attr-defined]
                self.s.expire_all()
                return rid
        return None

    def cancel_run(self, run_id: str, user_id: str) -> Run:
        run = self.get_run(run_id, user_id)
        if run.status == "queued":
            run.status = "cancelled"
            self.add_event(run.id, "run_cancelled", {})
        elif run.status == "running":
            run.status = "cancel_requested"
        elif run.status in TERMINAL_RUN:
            raise Conflict("run already finished")
        return run

    def add_event(self, run_id: str, type_: str, data: dict[str, Any]) -> int:
        e = RunEvent(run_id=run_id, type=type_, data=data)
        self.s.add(e)
        self.s.flush()
        return e.id

    def events_after(self, run_id: str, after_id: int) -> list[RunEvent]:
        return list(
            self.s.scalars(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.id > after_id)
                .order_by(RunEvent.id)
            )
        )

    def add_tool_call(self, **kw: Any) -> None:
        self.s.add(ToolCall(**kw))
        self.s.flush()

    def tool_calls(self, run_id: str) -> list[ToolCall]:
        return list(self.s.scalars(select(ToolCall).where(ToolCall.run_id == run_id)))

    def tool_call(self, run_id: str, tool_call_id: str) -> ToolCall | None:
        return self.s.scalar(
            select(ToolCall).where(
                ToolCall.run_id == run_id, ToolCall.tool_call_id == tool_call_id,
            )
        )

    def add_summary(
        self, task_id: str, run_id: str | None, body: str, tokens: int, trigger: str,
        covered_run_id: str | None = None,
    ) -> ContextSummary:
        row = ContextSummary(
            task_id=task_id, run_id=run_id, body=body, tokens=tokens, trigger=trigger,
            covered_run_id=covered_run_id,
        )
        self.s.add(row)
        self.s.flush()
        return row

    def latest_summary(self, task_id: str) -> ContextSummary | None:
        """The most recent compaction. Older ones stay for tracing, newest is what runs read."""
        return self.s.scalar(
            select(ContextSummary)
            .where(ContextSummary.task_id == task_id)
            .order_by(ContextSummary.created_at.desc())
            .limit(1)
        )

    def has_active_run(self, task_id: str) -> bool:
        return self.s.scalar(
            select(Run.id).where(Run.task_id == task_id, Run.status.in_(ACTIVE_RUN))
        ) is not None

    def add_llm_call(self, **kw: Any) -> None:
        self.s.add(LlmCall(**kw))
        self.s.flush()

    def llm_calls_of_run(self, run_id: str) -> list[LlmCall]:
        return list(
            self.s.scalars(
                select(LlmCall).where(LlmCall.run_id == run_id).order_by(LlmCall.id)
            )
        )

    def accept_task(self, task_id: str, user_id: str) -> Task:
        t = self.get_task(task_id, user_id)
        if t.status != "awaiting_user":
            raise Conflict("task is not awaiting_user")
        t.status = "accepted"
        if t.kind == "pdp":
            art_id = self.pdp_artifact(t.id).current_version_id
        elif t.kind == "canvas":
            art_id = self.canvas_artifact(t.id, create=True).current_version_id
        else:
            art_id = self.slot_artifact(t.id, "image").current_version_id
        if art_id:
            self.s.get_one(Version, art_id).user_signal = "accept"
        return t

    def abandon_task(self, task_id: str, user_id: str) -> Task:
        t = self.get_task(task_id, user_id)
        if t.status == "running":
            raise Conflict("cancel the run first")
        if t.status not in {"draft", "awaiting_user"}:
            raise Conflict("task cannot be abandoned")
        t.status = "abandoned"
        return t
