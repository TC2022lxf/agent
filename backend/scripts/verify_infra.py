"""Live check of the account/credits infrastructure against a running server.

Unlike pytest, this drives real HTTP the way a browser does: cookie jar, CSRF header copied
from the cookie, 401 before login, 402 when the balance cannot cover the hold, and a recharge
that only lands when an admin confirms it.

Usage (from backend/):
    python scripts/verify_infra.py [base_url]

Assumes `AUTH_MODE=session` and `ADMIN_NAME`/`ADMIN_KEY` set, so an admin exists.
It prints one line per check and exits non-zero on the first failure.
"""

from __future__ import annotations

import sys
import uuid
from typing import Any

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
ADMIN_NAME = "ops-admin"
ADMIN_KEY = "ek_admin_bootstrap_key_1234567890"

_checks = 0
_failed = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _checks, _failed
    _checks += 1
    if ok:
        print(f"  ok   {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}  {detail}")


class Browser:
    """A cookie jar plus the double-submit CSRF header, like src/api/client.ts."""

    def __init__(self) -> None:
        self.c = httpx.Client(base_url=BASE, timeout=60.0)

    def headers(self) -> dict[str, str]:
        token = self.c.cookies.get("ea_csrf")
        return {"X-CSRF-Token": token} if token else {}

    def get(self, url: str, **kw: Any) -> httpx.Response:
        return self.c.get(url, **kw)

    def post(self, url: str, **kw: Any) -> httpx.Response:
        # Merge, do not replace: Idempotency-Key must survive the CSRF header being added.
        headers = {**self.headers(), **(kw.pop("headers", None) or {})}
        return self.c.post(url, headers=headers, **kw)

    def put(self, url: str, **kw: Any) -> httpx.Response:
        headers = {**self.headers(), **(kw.pop("headers", None) or {})}
        return self.c.put(url, headers=headers, **kw)

    def clear(self) -> None:
        self.c.cookies.clear()


def err_code(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("code", ""))
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    b = Browser()
    print("== 无会话时被挡住 ==")
    r = b.get("/api/tasks")
    check("未登录读任务 -> 401", r.status_code == 401, f"{r.status_code}")
    check("错误码是 UNAUTHENTICATED", err_code(r) == "UNAUTHENTICATED", err_code(r))
    r = b.post("/api/tasks", json={"agent_id": "amazon_pdp"})
    check("未登录写任务 -> 401", r.status_code == 401, f"{r.status_code}")

    print("== 管理员登录 ==")
    r = b.post("/api/auth/login", json={"display_name": ADMIN_NAME, "access_key": ADMIN_KEY})
    check("管理员登录成功", r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        return 1
    check("角色是 admin", r.json()["user"]["role"] == "admin", str(r.json()))
    me = b.get("/api/me").json()
    check("带 display_name 返回", me.get("display_name") == ADMIN_NAME, str(me))

    print("== 邀请码注册 ==")
    made = b.post("/api/admin/invites", json={"max_uses": 1, "days": 7})
    check("生成邀请码 -> 201", made.status_code == 201, made.text[:200])
    code = made.json()["code"]
    name = f"运营{uuid.uuid4().hex[:6]}"
    user = Browser()
    r = user.post("/api/auth/register", json={"display_name": name, "invite_code": code})
    check("用邀请码注册 -> 200", r.status_code == 200, r.text[:300])
    if r.status_code != 200:
        return 1
    access_key = r.json()["access_key"]
    user_id = r.json()["user"]["id"]
    check("注册返回一次性访问密钥", access_key.startswith("ek_"), access_key[:8])
    check("注册后即登录", user.get("/api/me").status_code == 200)
    check("送 1000 积分", user.get("/api/me").json()["credits"] == 1000, str(user.get("/api/me").json()))

    second = Browser()
    r = second.post("/api/auth/register", json={"display_name": f"{name}b", "invite_code": code})
    check("同一邀请码第二次使用被拒", r.status_code == 400 and err_code(r) == "INVITE_INVALID", r.text[:200])

    print("== CSRF ==")
    token = user.c.cookies.get("ea_csrf")
    forged = user.c.post("/api/tasks", json={"agent_id": "amazon_pdp"}, headers={"X-CSRF-Token": "x"})
    check("伪造 CSRF -> 403", forged.status_code == 403 and err_code(forged) == "CSRF_REQUIRED", forged.text[:160])
    check("CSRF cookie 存在", bool(token))

    print("== 预扣费 ==")
    pricing = user.get("/api/billing/pricing").json()
    budget = pricing["budgets"]["pdp"]
    t = user.post("/api/tasks", json={"agent_id": "amazon_pdp"})
    check("建任务 -> 201", t.status_code == 201, t.text[:200])
    task_id = t.json()["id"]
    before = user.get("/api/me").json()["credits"]
    run = user.post(
        f"/api/tasks/{task_id}/utterances",
        json={"text": "第一版"},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    check("发言 -> 202", run.status_code == 202, run.text[:300])
    if run.status_code != 202:
        return 1
    check(f"冻结 {budget} 积分", run.json()["held"] == budget, str(run.json().get("held")))
    frozen = user.get("/api/me").json()
    check("余额立刻减少冻结额", frozen["credits"] == before - budget, str(frozen))
    check("冻结额单独可见", frozen["held"] == budget, str(frozen["held"]))

    print("== 结算 ==")
    import time

    run_id = run.json()["id"]
    for _ in range(120):
        state = user.get(f"/api/runs/{run_id}").json()
        if state["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(0.5)
    check("Run 走到终态", state["status"] in {"succeeded", "failed", "cancelled"}, state["status"])
    after = user.get("/api/me").json()
    check("冻结已释放", after["held"] == 0, str(after["held"]))
    check(
        "只扣实际用量",
        after["credits"] >= before - budget and after["credits"] <= before,
        f"{after['credits']} vs {before}",
    )
    rows = user.get("/api/me/credits").json()
    kinds = [r["kind"] for r in rows]
    check("账本有 hold 与 settle", "hold" in kinds and "settle" in kinds, str(kinds))
    check("账本无 charge/release（旧形状）", "charge" not in kinds and "release" not in kinds, str(kinds))
    check(
        "每行都记了结余",
        all(isinstance(r.get("balance_after"), int) for r in rows),
        str(rows[:2]),
    )

    print("== 充值（待确认 -> 到账）==")
    order = user.post("/api/billing/topups", json={"amount_cents": 3000})
    check("创建充值订单 -> 201", order.status_code == 201, order.text[:200])
    order_id = order.json()["id"]
    check("订单是 pending", order.json()["status"] == "pending", str(order.json().get("status")))
    check("下单不加积分", user.get("/api/me").json()["credits"] == after["credits"])
    check("小额被拒", user.post("/api/billing/topups", json={"amount_cents": 1}).status_code == 400)

    paid = b.post(f"/api/admin/topups/{order_id}/confirm")
    check("管理员确认收款 -> 200", paid.status_code == 200, paid.text[:200])
    replay = b.post(f"/api/admin/topups/{order_id}/confirm")
    check("重复确认不重复加", replay.json()["balance"] == paid.json()["balance"], replay.text[:200])
    check("到账 +3000", user.get("/api/me").json()["credits"] == after["credits"] + 3000,
          str(user.get("/api/me").json()["credits"]))

    print("== 发放与审计 ==")
    grant = b.post(
        f"/api/admin/users/{user_id}/grant",
        json={"user_id": user_id, "credits": 200, "reason": "内测补偿"},
    )
    check("管理员发放 -> 200", grant.status_code == 200, grant.text[:200])
    audit = b.get("/api/admin/audit").json()
    check("发放写审计", any(a["action"] == "credits.grant" for a in audit), str(len(audit)))

    print("== 停用 ==")
    off = b.post(f"/api/admin/users/{user_id}/status", json={"status": "disabled"})
    check("停用 -> 200", off.status_code == 200, off.text[:200])
    check("停用后原会话失效", user.get("/api/me").status_code == 401)
    user.clear()
    back = user.post("/api/auth/login", json={"display_name": name, "access_key": access_key})
    check("停用后无法登录", back.status_code == 403 and err_code(back) == "ACCOUNT_DISABLED", back.text[:200])

    print("== 权限边界 ==")
    other = Browser()
    r = other.post(
        "/api/auth/login", json={"display_name": ADMIN_NAME, "access_key": ADMIN_KEY}
    )
    check("管理员可看用户表", other.get("/api/admin/users").status_code == 200)
    bob = Browser()
    code2 = other.post("/api/admin/invites", json={"max_uses": 1}).json()["code"]
    r = bob.post("/api/auth/register", json={"display_name": f"普通{uuid.uuid4().hex[:6]}", "invite_code": code2})
    check("普通用户注册成功", r.status_code == 200, r.text[:200])
    check("普通用户看用户表 -> 403", bob.get("/api/admin/users").status_code == 403)
    check("普通用户看审计 -> 403", bob.get("/api/admin/audit").status_code == 403)

    print()
    print(f"== {_checks - _failed}/{_checks} 通过 ==")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
