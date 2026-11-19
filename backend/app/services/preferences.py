"""Preferences Markdown (docs/architecture/data-and-contracts.md). Agents may only propose; users own the canonical text."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.models import Preference, PreferenceProposal


class PreferencesService:
    def __init__(self, session: Session) -> None:
        self.s = session

    def current(self, user_id: str, agent_key: str) -> tuple[str, int]:
        row = self.s.scalar(self._latest(user_id, agent_key))
        return (row.body_md, row.revision) if row else ("", 0)

    def save(self, user_id: str, agent_key: str, body_md: str, source: str = "user") -> int:
        _, rev = self.current(user_id, agent_key)
        self.s.add(
            Preference(
                user_id=user_id,
                agent_key=agent_key,
                revision=rev + 1,
                body_md=body_md,
                source=source,
            )
        )
        self.s.flush()
        return rev + 1

    def revisions(self, user_id: str, agent_key: str) -> list[Preference]:
        return list(
            self.s.scalars(
                select(Preference)
                .where(Preference.user_id == user_id, Preference.agent_key == agent_key)
                .order_by(Preference.revision.desc())
            )
        )

    def restore(self, user_id: str, agent_key: str, revision: int) -> int:
        old = self.s.scalar(
            select(Preference).where(
                Preference.user_id == user_id,
                Preference.agent_key == agent_key,
                Preference.revision == revision,
            )
        )
        if old is None:
            raise KeyError(revision)
        return self.save(user_id, agent_key, old.body_md, source="restore")

    def propose(self, user_id: str, agent_key: str, text: str) -> PreferenceProposal:
        p = PreferenceProposal(user_id=user_id, agent_key=agent_key, text=text)
        self.s.add(p)
        self.s.flush()
        return p

    def proposals(self, user_id: str, agent_key: str) -> list[PreferenceProposal]:
        return list(
            self.s.scalars(
                select(PreferenceProposal).where(
                    PreferenceProposal.user_id == user_id,
                    PreferenceProposal.agent_key == agent_key,
                    PreferenceProposal.status == "pending",
                )
            )
        )

    def accept(self, user_id: str, proposal_id: str) -> int:
        p = self._own(user_id, proposal_id)
        body, _ = self.current(user_id, p.agent_key)
        merged = (body.rstrip() + "\n\n" if body.strip() else "") + f"- {p.text}\n"
        p.status = "accepted"
        return self.save(user_id, p.agent_key, merged, source="proposal")

    def reject(self, user_id: str, proposal_id: str) -> None:
        self._own(user_id, proposal_id).status = "rejected"

    def _own(self, user_id: str, proposal_id: str) -> PreferenceProposal:
        p = self.s.get(PreferenceProposal, proposal_id)
        if p is None or p.user_id != user_id or p.status != "pending":
            raise KeyError(proposal_id)
        return p

    @staticmethod
    def _latest(user_id: str, agent_key: str):  # type: ignore[no-untyped-def]
        sub = (
            select(func.max(Preference.revision))
            .where(Preference.user_id == user_id, Preference.agent_key == agent_key)
            .scalar_subquery()
        )
        return select(Preference).where(
            Preference.user_id == user_id,
            Preference.agent_key == agent_key,
            Preference.revision == sub,
        )
