"""Recharge orders and the Run budget policy (docs/11 sections 3 and 4).

Two things live here that look similar but are not:

* **Topup** is money in. It stays `pending` until a payment provider (or an admin in test
  mode) confirms it. Only then does a ledger row exist, and the row is keyed by the order id,
  so a replayed provider callback cannot credit twice.
* **RunBudget** is money at risk. Every Run freezes a ceiling when it is enqueued. The
  executor stops when it reaches that ceiling. Settlement charges the real cost and returns
  the rest, so a cheap run does not cost the ceiling.

The ceiling is per Run *kind*, configured by operations, not hard-coded in a tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import Topup
from app.services.console import ConsoleService
from app.services.credits import CREDITS_PER_YUAN, CreditsService

# Setting keys. Numbers are set by operations, never in code branches.
SETTING_BUDGET = "credits.budget.{kind}"
SETTING_MULTIPLIER = "credits.price_multiplier"
SETTING_MAX_TOPUP = "credits.max_topup_cents"
SETTING_TOPUP_ENABLED = "credits.topup_enabled"

DEFAULT_BUDGETS = {
    "pdp": 120,
    "image": 80,
    "general": 120,
    "file": 60,
    "canvas": 100,
}
MIN_TOPUP_CENTS = 100  # 1 CNY
DEFAULT_MAX_TOPUP_CENTS = 100_000  # 1000 CNY


def _now() -> datetime:
    return datetime.now(UTC)


class BillingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


@dataclass(frozen=True)
class Budget:
    kind: str
    credits: int


class BillingService:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.console = ConsoleService(session)
        self.credits = CreditsService(session)

    # ---- budget -----------------------------------------------------------
    def budget_for(self, task_kind: str) -> int:
        """Credits to freeze for one Run of this Task kind. Falls back to the general value."""
        raw = self.console.get(SETTING_BUDGET.format(kind=task_kind), "")
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
        return DEFAULT_BUDGETS.get(task_kind, DEFAULT_BUDGETS["general"])

    def budgets(self) -> dict[str, int]:
        return {k: self.budget_for(k) for k in [*DEFAULT_BUDGETS, "other"]}

    def price_multiplier(self) -> float:
        raw = self.console.get(SETTING_MULTIPLIER, "1.0") or "1.0"
        try:
            return max(0.0, float(raw))
        except ValueError:
            return 1.0

    def points_from_micro_cny(self, cost_micro_cny: int) -> int:
        """docs/11: points = ceil(cost_micro_cny * multiplier / 10000)."""
        if cost_micro_cny <= 0:
            return 0
        import math

        return max(0, math.ceil(cost_micro_cny * self.price_multiplier() / 10_000))

    # ---- topups -----------------------------------------------------------
    def topup_enabled(self) -> bool:
        return (self.console.get(SETTING_TOPUP_ENABLED, "1") or "1") not in {"0", "false", ""}

    def max_topup_cents(self) -> int:
        raw = self.console.get(SETTING_MAX_TOPUP, "") or ""
        try:
            return max(MIN_TOPUP_CENTS, int(raw)) if raw else DEFAULT_MAX_TOPUP_CENTS
        except ValueError:
            return DEFAULT_MAX_TOPUP_CENTS

    def create_topup(
        self, user_id: str, *, amount_cents: int, method: str = "manual", note: str = ""
    ) -> Topup:
        """Create a pending order. Credits are 1:1 with fen, so no rounding surprises.

        Money only moves in `mark_paid`; creating an order must never add credits.
        """
        amount_cents = int(amount_cents)
        if amount_cents < MIN_TOPUP_CENTS:
            raise BillingError("AMOUNT_TOO_SMALL", f"最少充值 {MIN_TOPUP_CENTS / 100:.0f} 元")
        if amount_cents > self.max_topup_cents():
            raise BillingError(
                "AMOUNT_TOO_LARGE", f"单次最多 {self.max_topup_cents() / 100:.0f} 元"
            )
        order = Topup(
            user_id=user_id,
            amount_cents=amount_cents,
            credits=amount_cents,  # 1 credit = 0.01 CNY = 1 fen
            method=method,
            note=note,
        )
        self.s.add(order)
        self.s.flush()
        return order

    def mark_paid(self, topup_id: str, *, external_ref: str | None = None) -> Topup:
        """Confirm an order and credit the account. Idempotent: replaying returns the order."""
        order = self.s.get(Topup, topup_id)
        if order is None:
            raise BillingError("NOT_FOUND", "订单不存在")
        if order.status == "paid":
            return order
        if order.status != "pending":
            raise BillingError("ORDER_CLOSED", f"订单状态是 {order.status}，不能支付")
        self.credits.topup(
            order.user_id,
            order.credits,
            topup_id=order.id,
            note=f"充值 {order.amount_cents / 100:.2f} 元",
        )
        order.status = "paid"
        order.paid_at = _now()
        order.external_ref = external_ref
        self.s.flush()
        return order

    def cancel_topup(self, topup_id: str, *, actor_id: str) -> Topup:
        order = self.s.get(Topup, topup_id)
        if order is None:
            raise BillingError("NOT_FOUND", "订单不存在")
        if order.status != "pending":
            raise BillingError("ORDER_CLOSED", f"订单状态是 {order.status}，不能取消")
        order.status = "cancelled"
        order.note = (order.note + f" · 由 {actor_id} 取消").strip(" ·")
        self.s.flush()
        return order

    def topup(self, topup_id: str) -> Topup | None:
        return self.s.get(Topup, topup_id)

    def topups(self, user_id: str | None = None, limit: int = 50) -> list[Topup]:
        q = select(Topup).order_by(Topup.created_at.desc()).limit(limit)
        if user_id:
            q = q.where(Topup.user_id == user_id)
        return list(self.s.scalars(q))

    # ---- views ------------------------------------------------------------
    def topup_view(self, order: Topup) -> dict[str, Any]:
        return {
            "id": order.id,
            "user_id": order.user_id,
            "amount_cents": order.amount_cents,
            "amount_yuan": round(order.amount_cents / 100, 2),
            "credits": order.credits,
            "method": order.method,
            "status": order.status,
            "note": order.note,
            "created_at": order.created_at.isoformat(),
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
        }

    def pricing(self) -> dict[str, Any]:
        return {
            "credits_per_yuan": CREDITS_PER_YUAN,
            "min_topup_cents": MIN_TOPUP_CENTS,
            "max_topup_cents": self.max_topup_cents(),
            "topup_enabled": self.topup_enabled(),
            "price_multiplier": self.price_multiplier(),
            "budgets": self.budgets(),
        }
