"""WriteScopeGuard: `target_slot` is the write boundary (AGENTS.md)."""

from __future__ import annotations

from pydantic import BaseModel


class ScopeViolation(Exception):
    pass


class WriteScopeGuard:
    @staticmethod
    def check(
        output: BaseModel,
        allowed_slots: set[str],
        requested_region: dict[str, float] | None,
    ) -> None:
        slot = getattr(output, "slot", None)
        if slot not in allowed_slots:
            raise ScopeViolation(f"output slot {slot!r} outside {sorted(allowed_slots)}")
        if requested_region is not None:
            got = getattr(output, "changed_region", None)
            got_d = got.model_dump() if got is not None else None
            if got_d is None or any(
                abs(got_d[k] - requested_region[k]) > 1e-6 for k in ("x", "y", "w", "h")
            ):
                raise ScopeViolation("changed region differs from the requested region")
