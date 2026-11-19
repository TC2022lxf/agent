"""Drive the new sign-in / account / admin screens in a real browser.

    python scripts/verify_auth_ui.py [frontend_base]

Uses Playwright against the Vite dev server (which proxies /api). It registers through the
real form with an invite code minted by the admin API, checks that the access key is shown
once and gated behind a confirmation, signs out, signs back in, then reads the account page
and the admin table. Screenshots land in `data/verify/` for eyeballing.

Nothing here calls the model, so it is cheap to run repeatedly.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import httpx
from playwright.sync_api import Page, sync_playwright

UI = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
API = "http://127.0.0.1:8001"
ADMIN_NAME = "ops-admin"
ADMIN_KEY = "ek_admin_bootstrap_key_1234567890"
OUT = Path("data/verify")

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


def admin_invite() -> str:
    """Mint an invite through the API; the UI cannot create one before anyone is logged in."""
    c = httpx.Client(base_url=API, timeout=30.0)
    c.post("/api/auth/login", json={"display_name": ADMIN_NAME, "access_key": ADMIN_KEY})
    csrf = c.cookies.get("ea_csrf")
    r = c.post(
        "/api/admin/invites",
        json={"max_uses": 1, "days": 7},
        headers={"X-CSRF-Token": csrf} if csrf else {},
    )
    r.raise_for_status()
    return str(r.json()["code"])


def shot(page: Page, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)


def main() -> int:
    invite = admin_invite()
    name = f"运营{uuid.uuid4().hex[:5]}"

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(UI, wait_until="networkidle")

        print("== 登录页 ==")
        check("显示登录标题", page.get_by_role("heading", name="登录").is_visible())
        check("看不到侧栏", page.get_by_role("button", name="通用 Agent").count() == 0)
        shot(page, "01-login")

        print("== 邀请码注册 ==")
        page.get_by_role("button", name="我有邀请码，去注册").click()
        page.get_by_label("名字").fill(name)
        page.get_by_label("邀请码").fill(invite)
        page.get_by_role("button", name="注册").click()

        key_box = page.get_by_test_id("issued-key")
        key_box.wait_for(timeout=15000)
        access_key = (key_box.text_content() or "").strip()
        check("注册后显示一次性密钥", access_key.startswith("ek_"), access_key[:10])
        shot(page, "02-key-once")
        go_on = page.get_by_role("button", name="我已保存，去登录")
        check("未勾选保存时不能继续", go_on.is_disabled())
        page.get_by_label("我已经把密钥保存到安全的地方").check()
        check("勾选后可以继续", not go_on.is_disabled())

        print("== 登录 ==")
        go_on.click()
        page.get_by_label("密码" if False else "访问密钥").fill(access_key)
        page.get_by_role("button", name="登录").click()
        page.get_by_role("button", name="通用 Agent").wait_for(timeout=15000)
        check("登录后进入工作台", page.get_by_role("button", name="通用 Agent").is_visible())
        shot(page, "03-signed-in")

        print("== 账户页 ==")
        page.get_by_role("button", name="积分 1000").click()
        page.get_by_test_id("balance").wait_for(timeout=10000)
        check("余额显示 1000", (page.get_by_test_id("balance").text_content() or "") == "1000",
              page.get_by_test_id("balance").text_content() or "")
        check("流水表存在", page.get_by_test_id("ledger").is_visible())
        check("显示注册赠送", "注册赠送" in (page.get_by_test_id("ledger").text_content() or ""))
        shot(page, "04-account")

        print("== 充值订单 ==")
        page.get_by_role("button", name="创建充值订单").click()
        page.get_by_text("待确认").first.wait_for(timeout=10000)
        check("订单显示待确认", page.get_by_text("待确认").first.is_visible())
        shot(page, "05-topup-pending")

        print("== 普通用户看不到管理台 ==")
        check("没有用户与积分入口", page.get_by_role("button", name="用户与积分").count() == 0)

        print("== 退出与管理员登录 ==")
        page.get_by_role("button", name="退出").click()
        try:
            page.get_by_role("heading", name="登录").wait_for(timeout=15000)
        except Exception:
            shot(page, "05b-logout-failed")
            print("  debug:", (page.content()[:800]))
            raise
        check("退出回到登录页", page.get_by_role("heading", name="登录").is_visible())

        page.get_by_label("名字").fill(ADMIN_NAME)
        page.get_by_label("访问密钥").fill(ADMIN_KEY)
        page.get_by_role("button", name="登录").click()
        try:
            page.get_by_role("button", name="用户与积分").wait_for(timeout=15000)
        except Exception:
            shot(page, "05c-admin-login-failed")
            print("  debug role:", page.evaluate(
                "fetch('/api/auth/status').then(r=>r.json())"
            ))
            raise
        check("管理员看到用户与积分入口", page.get_by_role("button", name="用户与积分").is_visible())
        page.get_by_role("button", name="用户与积分").click()
        table_loc = page.get_by_test_id("admin-users")
        table_loc.wait_for(timeout=10000)
        # The header paints before the query resolves; wait for a row, then assert.
        page.get_by_text(name).first.wait_for(timeout=15000)
        table = table_loc.text_content() or ""
        check("用户表里有刚注册的人", name in table, table[:120])
        shot(page, "06-admin-users")

        print("== 确认充值 ==")
        confirm = page.get_by_role("button", name="确认收款")
        before_count = confirm.count()
        check("有待确认的充值", before_count > 0)
        if before_count > 0:
            confirm.first.click()
            # The queue refetches; one fewer button is the real signal that it landed.
            for _ in range(50):
                if confirm.count() < before_count:
                    break
                page.wait_for_timeout(300)
            check("确认后待确认少了一条", confirm.count() == before_count - 1,
                  f"{before_count} -> {confirm.count()}")
        shot(page, "07-admin-confirmed")

        browser.close()

    print()
    print(f"== {_checks - _failed}/{_checks} 通过 ==")
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
