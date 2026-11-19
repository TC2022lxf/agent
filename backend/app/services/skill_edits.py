"""Skill edits (docs/13). The repo file is the shipped baseline; edits are rows, never file writes.

Why not overwrite `skills/<id>/SKILL.md`:

- two editors would race on the same file with no way to detect it;
- a deploy would wipe or conflict with the edit;
- history would live in git only, which the product does not read.

So each save appends a revision. A save names the revision it started from; a stale
number is rejected with 409 instead of silently replacing someone else's text.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import SkillRevision


class StaleRevision(Exception):
    def __init__(self, current: int) -> None:
        self.current = current
        super().__init__(f"skill changed: current revision is {current}")


class SkillEditService:
    def __init__(self, session: Session) -> None:
        self.s = session

    def latest(self, skill_id: str) -> SkillRevision | None:
        return self.s.scalar(
            select(SkillRevision)
            .where(SkillRevision.skill_id == skill_id)
            .order_by(SkillRevision.revision.desc())
        )

    def history(self, skill_id: str) -> list[SkillRevision]:
        return list(
            self.s.scalars(
                select(SkillRevision)
                .where(SkillRevision.skill_id == skill_id)
                .order_by(SkillRevision.revision.desc())
            )
        )

    def save(
        self, skill_id: str, body: str, *, base_revision: int, edited_by: str,
        description: str = "", audience: str = "general", source: str = "edited",
    ) -> SkillRevision:
        latest = self.latest(skill_id)
        current = latest.revision if latest else 0
        if base_revision != current:
            raise StaleRevision(current)
        row = SkillRevision(
            skill_id=skill_id, revision=current + 1, body=body, description=description,
            audience=audience, edited_by=edited_by, source=source,
        )
        self.s.add(row)
        self.s.flush()
        return row
