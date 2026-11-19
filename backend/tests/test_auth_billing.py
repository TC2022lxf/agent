"""Accounts, sessions, invites, roles and money (docs/architecture/data-and-contracts.md, docs/architecture/agent-runtime.md).

These tests run the real HTTP surface: cookies, CSRF, 401/402/403 codes, and the ledger.
The point is that the infrastructure is closed at one place each, so a test here covers
every route behind it.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.container import Container, build_container
from app.infrastructure.storage import MemoryObjectStore
from app.main import create_app


class Browser:
    """A TestClient that behaves like `src/api/client.ts`: it mirrors the CSRF cookie.

    The server requires the header on writes because a cross-site form can carry the cookie
    but cannot read it. Browsers therefore copy the cookie into a header; this does the same,
    so the tests exercise the real check instead of bypassing it.
    """

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        token = self.client.cookies.get("ea_csrf")
        return {**(extra or {}), **({"X-CSRF-Token": token} if token else {})}

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, headers=self._headers(kw.pop("headers", None)), **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self.client.post(url, headers=self._headers(kw.pop("headers", None)), **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self.client.put(url, headers=self._headers(kw.pop("headers", None)), **kw)

    def clear_session(self) -> None:
        self.client.cookies.clear()

    def json(self, url: str) -> Any:
        r = self.get(url)
        assert r.status_code == 200, r.text
        return r.json()


@pytest.fixture()
def auth_app() -> tuple[Browser, Container]:
    """Session-mode app: no dev header, so only real accounts get in."""
    settings = Settings(database_url="sqlite://", run_worker="off", auth_mode="session")
    c = build_container(settings, store=MemoryObjectStore())
    with TestClient(create_app(c)) as client:
        yield Browser(client), c


def _invite(c: Container, *, uses: int = 5) -> str:
    """Seed an invite directly: admin routes need an admin, and this is about signup."""
    with c.uow_factory() as uow:
        _row, code = uow.identity.create_invite(created_by="test", max_uses=uses)
        uow.commit()
    return code


def _register(browser: Browser, c: Container, name: str) -> dict[str, Any]:
    before = browser.client.cookies.get("ea_session")
    r = browser.post(
        "/api/auth/register", json={"display_name": name, "invite_code": _invite(c)}
    )
    assert r.status_code == 200, r.text
    assert browser.client.cookies.get("ea_session") != before
    return r.json()


def _make_admin(c: Container, user_id: str) -> None:
    with c.uow_factory() as uow:
        user = uow.identity.get(user_id)
        assert user is not None
        user.role = "admin"
        uow.commit()


def _key_for(c: Container, name: str) -> str:
    """Test helper: rotate so the test knows the plaintext of an existing account's key."""
    with c.uow_factory() as uow:
        user = uow.identity.by_name(name)
        assert user is not None
        key = uow.identity.rotate_access_key(user.id, actor_id="test")
        uow.commit()
    return key


def _login(browser: Browser, name: str, key: str) -> None:
    browser.clear_session()
    r = browser.post("/api/auth/login", json={"display_name": name, "access_key": key})
    assert r.status_code == 200, r.text


def _revoke_sessions_of(c: Container, user_id: str) -> None:
    """What an admin's "disable" does to live sessions, for a browser that is already open."""
    with c.uow_factory() as uow:
        uow.identity.revoke_sessions(user_id)
        uow.commit()


# ---- identity --------------------------------------------------------------
def test_registration_requires_a_valid_invite(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, _c = auth_app
    r = browser.post("/api/auth/register", json={"display_name": "x1", "invite_code": "iv_nope"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVITE_INVALID"


def test_an_invite_can_only_be_used_as_often_as_allowed(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    code = _invite(c, uses=1)
    assert browser.post(
        "/api/auth/register", json={"display_name": "first", "invite_code": code}
    ).status_code == 200
    browser.clear_session()
    again = browser.post(
        "/api/auth/register", json={"display_name": "second", "invite_code": code}
    )
    assert again.status_code == 400 and again.json()["error"]["code"] == "INVITE_INVALID"


def test_registration_issues_a_key_once_and_it_logs_in(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    made = _register(browser, c, "alice")
    key = made["access_key"]
    assert key.startswith("ek_") and len(key) > 30
    me = browser.json("/api/me")
    assert key not in str(me)  # the plaintext is never readable again

    browser.clear_session()
    assert browser.get("/api/me").status_code == 401  # no session, and no dev header here
    _login(browser, "alice", key)
    assert browser.json("/api/me")["display_name"] == "alice"


def test_a_wrong_key_is_refused(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "bob")
    browser.clear_session()
    r = browser.post("/api/auth/login", json={"display_name": "bob", "access_key": "ek_wrong"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "BAD_CREDENTIALS"


def test_a_display_name_cannot_be_reused(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "carol")
    dup = browser.post(
        "/api/auth/register", json={"display_name": "carol", "invite_code": _invite(c)}
    )
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "NAME_TAKEN"


def test_cookie_writes_require_the_csrf_header(auth_app) -> None:  # type: ignore[no-untyped-def]
    """A cross-site form can send the cookie; it cannot read the CSRF token."""
    browser, c = auth_app
    _register(browser, c, "dana")
    assert browser.post("/api/tasks", json={"agent_id": "amazon_pdp"}).status_code == 201

    forged = browser.client.post(
        "/api/tasks", json={"agent_id": "amazon_pdp"}, headers={"X-CSRF-Token": "forged"}
    )
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "CSRF_REQUIRED"
    missing = browser.client.post("/api/tasks", json={"agent_id": "amazon_pdp"})
    assert missing.status_code == 403


def test_losing_the_session_means_401_not_403(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "erin")
    browser.clear_session()
    r = browser.get("/api/tasks")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_disabled_session_stops_working(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    boss_key = _key_for(c, "boss")
    victim = _register(browser, c, "eve")
    victim_key = _key_for(c, "eve")

    # Eve is signed in and working.
    _login(browser, "eve", victim_key)
    assert browser.get("/api/tasks").status_code == 200

    _login(browser, "boss", boss_key)
    r = browser.post(f"/api/admin/users/{victim['user']['id']}/status", json={"status": "disabled"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disabled"

    # Her key cannot open a new session either.
    browser.clear_session()
    blocked = browser.post(
        "/api/auth/login", json={"display_name": "eve", "access_key": victim_key}
    )
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_revoking_sessions_invalidates_the_cookie_immediately(auth_app) -> None:  # type: ignore[no-untyped-def]
    """`revoke_sessions` is what disable calls; the very next request must be rejected."""
    browser, c = auth_app
    made = _register(browser, c, "joe")
    assert browser.get("/api/tasks").status_code == 200
    _revoke_sessions_of(c, made["user"]["id"])
    r = browser.get("/api/tasks")
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_a_disabled_user_cannot_log_back_in(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    victim = _register(browser, c, "eve")
    key = _key_for(c, "eve")

    _login(browser, "boss", _key_for(c, "boss"))
    browser.post(f"/api/admin/users/{victim['user']['id']}/status", json={"status": "disabled"})

    browser.clear_session()
    blocked = browser.post("/api/auth/login", json={"display_name": "eve", "access_key": key})
    assert blocked.status_code == 403
    assert blocked.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_a_non_admin_cannot_reach_admin_routes(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "frank")
    r = browser.get("/api/admin/users")
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_an_admin_sees_users_and_invites(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    _register(browser, c, "grace")

    # Registering grace replaced this browser's session; the admin signs back in.
    _login(browser, "boss", _key_for(c, "boss"))
    users = browser.json("/api/admin/users")
    assert {u["display_name"] for u in users} == {"boss", "grace"}
    assert next(u for u in users if u["display_name"] == "grace")["balance"] == 1000

    made = browser.post("/api/admin/invites", json={"max_uses": 2, "days": 7})
    assert made.status_code == 201, made.text
    code = made.json()["code"]
    assert code.startswith("iv_")
    listed = browser.json("/api/admin/invites")
    assert any(i["id"] == made.json()["id"] and i["max_uses"] == 2 for i in listed)
    # The plaintext code is never listed again.
    assert code not in str(listed)


# ---- money -----------------------------------------------------------------
def test_a_grant_needs_a_reason_and_writes_an_audit_row(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    target = _register(browser, c, "gina")["user"]["id"]
    _login(browser, "boss", _key_for(c, "boss"))

    # A grant with no reason is not a grant: the schema refuses it before any money moves.
    blank = browser.post(
        f"/api/admin/users/{target}/grant", json={"user_id": target, "credits": 50, "reason": ""}
    )
    assert blank.status_code == 422

    ok = browser.post(
        f"/api/admin/users/{target}/grant",
        json={"user_id": target, "credits": 50, "reason": "内测补偿"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["balance"] == 1050
    # Replaying the same grant is a no-op, not a second payout.
    again = browser.post(
        f"/api/admin/users/{target}/grant",
        json={"user_id": target, "credits": 50, "reason": "内测补偿"},
    )
    assert again.json()["balance"] == 1050

    audit = browser.json("/api/admin/audit")
    assert any(a["action"] == "credits.grant" and a["target_id"] == target for a in audit)


def test_a_topup_moves_no_money_until_it_is_confirmed(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    hank = _register(browser, c, "hank")["user"]["id"]
    start = browser.json("/api/me")["credits"]

    order = browser.post("/api/billing/topups", json={"amount_cents": 3000})
    assert order.status_code == 201, order.text
    body = order.json()
    assert body["status"] == "pending" and body["credits"] == 3000
    assert browser.json("/api/me")["credits"] == start  # nothing yet

    _login(browser, "boss", _key_for(c, "boss"))
    paid = browser.post(f"/api/admin/topups/{body['id']}/confirm")
    assert paid.status_code == 200 and paid.json()["status"] == "paid"
    # A replayed confirmation must not credit twice.
    again = browser.post(f"/api/admin/topups/{body['id']}/confirm")
    assert again.status_code == 200 and again.json()["balance"] == start + 3000

    _login(browser, "hank", _key_for(c, "hank"))
    assert browser.json("/api/me")["credits"] == start + 3000
    kinds = [r["kind"] for r in browser.json("/api/me/credits")]
    assert kinds.count("topup") == 1
    assert hank


def test_a_cancelled_topup_never_credits(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    boss = _register(browser, c, "boss")
    _make_admin(c, boss["user"]["id"])
    _register(browser, c, "ivy")
    order = browser.post("/api/billing/topups", json={"amount_cents": 1000}).json()

    _login(browser, "boss", _key_for(c, "boss"))
    assert browser.post(f"/api/admin/topups/{order['id']}/cancel").status_code == 200
    refused = browser.post(f"/api/admin/topups/{order['id']}/confirm")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ORDER_CLOSED"

    _login(browser, "ivy", _key_for(c, "ivy"))
    assert browser.json("/api/me")["credits"] == 1000  # only the signup grant


def test_a_topup_below_the_minimum_is_refused(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "iris")
    r = browser.post("/api/billing/topups", json={"amount_cents": 1})
    assert r.status_code == 400 and r.json()["error"]["code"] == "AMOUNT_TOO_SMALL"


def test_the_run_hold_uses_the_task_kind_budget(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    _register(browser, c, "jane")
    budgets = browser.json("/api/billing/pricing")["budgets"]
    task = browser.post("/api/tasks", json={"agent_id": "amazon_pdp"}).json()
    r = browser.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "第一版"},
        headers={"Idempotency-Key": "k1"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["held"] == budgets["pdp"]
    me = browser.json("/api/me")
    assert me["credits"] == 1000 - budgets["pdp"]
    assert me["held"] == budgets["pdp"]


def test_a_user_without_credits_cannot_start_a_run(auth_app) -> None:  # type: ignore[no-untyped-def]
    browser, c = auth_app
    user = _register(browser, c, "kyle")["user"]["id"]
    with c.uow_factory() as uow:
        uow.credits.adjust(
            user, -(uow.credits.balance(user) - 10), admin_id="test", key="drain", note="test"
        )
        uow.commit()
    task = browser.post("/api/tasks", json={"agent_id": "amazon_pdp"}).json()
    r = browser.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "第一版"},
        headers={"Idempotency-Key": "k2"},
    )
    assert r.status_code == 402
    body = r.json()["error"]
    assert body["code"] == "INSUFFICIENT_CREDITS" and "10" in body["message"]


def test_the_ledger_is_append_only_and_the_cache_matches(api) -> None:  # type: ignore[no-untyped-def]
    """Every row records the balance after it; replaying it must equal the cached balance."""
    task = api.task()
    api.say(task["id"], "第一版")
    rows = api.http.get("/api/me/credits").json()
    assert rows
    with api.c.uow_factory() as uow:
        rebuilt = uow.credits.rebuild("dev-user")
        uow.commit()
    assert rebuilt == api.http.get("/api/me").json()["credits"]
    assert rows[0]["balance_after"] == rebuilt
