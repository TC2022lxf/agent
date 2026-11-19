"""Credits: an append-only ledger is the only source of truth (docs/architecture/data-and-contracts.md, docs/architecture/data-and-contracts.md).

1 credit = 0.01 CNY, integers only. Every write carries an idempotency key, so a retried
request or a replayed payment callback cannot charge twice.

Available balance already excludes outstanding holds, because a hold is a negative ledger
row. A Run's `held` tells settlement how much of that negative row belongs to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.models import Balance, LedgerEntry, Run

KIND_GRANT = "grant"
KIND_TOPUP = "topup"
KIND_HOLD = "hold"
KIND_SETTLE = "settle"
KIND_REFUND = "refund"
KIND_ADJUST = "adjust"
KIND_SPEND = "spend"

CREDITS_PER_YUAN = 100  # 1 credit = 0.01 CNY


class InsufficientCredits(Exception):
    """Not enough available balance to freeze the Run's budget."""

    def __init__(self, needed: int = 0, available: int = 0) -> None:
        self.needed, self.available = needed, available
        super().__init__(f"need {needed}, available {available}")


@dataclass(frozen=True)
class Settlement:
    held: int
    charged: int
    refunded: int
    overrun: int  # actual cost above the hold; the platform absorbs it

    @property
    def delta(self) -> int:
        return self.refunded


def hold_key(run_id: str) -> str:
    return f"hold:{run_id}"


def settle_key(run_id: str) -> str:
    return f"settle:{run_id}"


def refund_key(run_id: str) -> str:
    return f"refund:{run_id}"


class CreditsService:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- reads ------------------------------------------------------------
    def balance(self, user_id: str) -> int:
        """Available points, i.e. ledger sum including the negative hold rows."""
        row = self._row(user_id, create=False)
        if row is not None:
            return int(row.points)
        return self._sum(user_id)

    def held(self, user_id: str) -> int:
        """How much is frozen right now, across still-open Runs. Informational.

        The balance above already excludes it (a hold is a negative ledger row). This cannot
        be derived from kind totals alone: once a Run settles, its hold and release rows
        cancel out and the net looks like a plain charge.
        """
        total = self.s.scalar(
            select(func.coalesce(func.sum(Run.held), 0)).where(
                Run.user_id == user_id,
                Run.status.in_(["queued", "running", "cancel_requested"]),
            )
        )
        return int(total or 0)

    def ledger(self, user_id: str, limit: int = 200) -> list[LedgerEntry]:
        return list(
            self.s.scalars(
                select(LedgerEntry)
                .where(LedgerEntry.user_id == user_id)
                .order_by(LedgerEntry.id.desc())
                .limit(limit)
            )
        )

    def entry(self, idempotency_key: str) -> LedgerEntry | None:
        return self.s.scalar(
            select(LedgerEntry).where(LedgerEntry.idempotency_key == idempotency_key)
        )

    # ---- writes -----------------------------------------------------------
    def ensure_user(self, user_id: str, initial: int) -> None:
        """Idempotent signup grant. A user created by registration already has this."""
        self._row(user_id)
        if initial > 0 and self.entry(f"grant:signup:{user_id}") is None:
            self._add(user_id, initial, KIND_GRANT, key=f"grant:signup:{user_id}",
                      note="注册赠送")

    def hold(self, user_id: str, run_id: str, amount: int) -> LedgerEntry:
        """Freeze the Run budget at enqueue time.

        Raises InsufficientCredits instead of going negative: a zero-balance user must not be
        able to start Run after Run whose cost lands before the first settlement.
        """
        amount = max(0, int(amount))
        existing = self.entry(hold_key(run_id))
        if existing is not None:
            return existing
        available = self.balance(user_id)
        if amount > available:
            raise InsufficientCredits(amount, available)
        return self._add(user_id, -amount, KIND_HOLD, run_id=run_id, key=hold_key(run_id),
                         note="Run 预算冻结")

    def settle(self, user_id: str, run_id: str, held: int, cost: int) -> Settlement:
        """Charge the actual cost, capped at the hold, and return the unused remainder.

        Replaying this for the same Run returns the original rows unchanged.
        """
        held = max(0, int(held))
        cost = max(0, int(cost))
        charge = min(cost, held)
        refund = held - charge
        overrun = max(0, cost - held)
        if self.entry(settle_key(run_id)) is None:
            note = f"结算：实扣 {charge}"
            if overrun:
                note += f"，超支 {overrun} 由平台承担"
            self._add(user_id, refund, KIND_SETTLE, run_id=run_id,
                      key=settle_key(run_id), note=note)
        return Settlement(held=held, charged=charge, refunded=refund, overrun=overrun)

    def refund(self, user_id: str, run_id: str, held: int) -> int:
        """Platform fault (gateway 5xx, timeout, worker crash): give the whole hold back."""
        held = max(0, int(held))
        if self.entry(refund_key(run_id)) is not None:
            return held
        if held:
            self._add(user_id, held, KIND_REFUND, run_id=run_id, key=refund_key(run_id),
                      note="平台原因失败，全额退还")
        return held

    def spend(self, user_id: str, amount: int, *, run_id: str | None = None,
              key: str | None = None, note: str = "") -> LedgerEntry | None:
        """Direct charge outside a Run (console tool trial). Still one ledger row."""
        amount = int(amount)
        if amount <= 0:
            return None
        if key and (existing := self.entry(key)) is not None:
            return existing
        if self.balance(user_id) < amount:
            raise InsufficientCredits(amount, self.balance(user_id))
        return self._add(user_id, -amount, KIND_SPEND, run_id=run_id, key=key, note=note)

    def topup(self, user_id: str, credits: int, *, topup_id: str, note: str = "") -> LedgerEntry:
        """Payment success -> credits. Keyed by the order, so a replayed callback is a no-op."""
        if credits <= 0:
            raise ValueError("topup credits must be positive")
        key = f"topup:{topup_id}"
        existing = self.entry(key)
        if existing is not None:
            return existing
        return self._add(user_id, credits, KIND_TOPUP, key=key, note=note or "充值")

    def grant(self, user_id: str, credits: int, *, admin_id: str, key: str,
              note: str = "") -> LedgerEntry:
        if credits <= 0:
            raise ValueError("grant credits must be positive")
        existing = self.entry(key)
        if existing is not None:
            return existing
        return self._add(user_id, credits, KIND_GRANT, key=key, admin_id=admin_id,
                         note=note or "管理员发放")

    def adjust(self, user_id: str, delta: int, *, admin_id: str, key: str,
               note: str) -> LedgerEntry:
        """Signed correction. Requires a reason; never used to fake a payment."""
        if delta == 0:
            raise ValueError("adjust delta must be non-zero")
        existing = self.entry(key)
        if existing is not None:
            return existing
        if delta < 0 and self.balance(user_id) + delta < 0:
            raise InsufficientCredits(-delta, self.balance(user_id))
        return self._add(user_id, delta, KIND_ADJUST, key=key, admin_id=admin_id, note=note)

    # ---- internals --------------------------------------------------------
    def _sum(self, user_id: str) -> int:
        total = self.s.scalar(
            select(func.coalesce(func.sum(LedgerEntry.delta), 0)).where(
                LedgerEntry.user_id == user_id
            )
        )
        return int(total or 0)

    def _row(self, user_id: str, *, create: bool = True) -> Balance | None:
        """The cached balance row, locked for update on databases that support it."""
        row = self.s.get(Balance, user_id, with_for_update=create)
        if row is None:
            if not create:
                return None
            row = Balance(user_id=user_id, points=self._sum(user_id))
            self.s.add(row)
            self.s.flush()
        return row

    def _add(
        self,
        user_id: str,
        delta: int,
        kind: str,
        *,
        run_id: str | None = None,
        key: str | None = None,
        note: str = "",
        admin_id: str | None = None,
    ) -> LedgerEntry:
        if key:
            existing = self.entry(key)
            if existing is not None:
                return existing
        row = self._row(user_id)
        assert row is not None
        row.points = int(row.points) + delta
        entry = LedgerEntry(
            user_id=user_id,
            delta=delta,
            kind=kind,
            run_id=run_id,
            balance_after=row.points,
            idempotency_key=key,
            note=note,
            admin_id=admin_id,
        )
        self.s.add(entry)
        self.s.flush()
        return entry

    def rebuild(self, user_id: str) -> int:
        """Recompute the cache from the ledger. Used by tests and by a repair task."""
        total = self._sum(user_id)
        row = self._row(user_id)
        assert row is not None
        row.points = total
        self.s.flush()
        return total

    def summary(self, user_id: str) -> dict[str, Any]:
        return {
            "balance": self.balance(user_id),
            "held": self.held(user_id),
            "available": self.balance(user_id),
        }
