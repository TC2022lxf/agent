"""Auth, account and billing routes (docs/07 "认证与账号", docs/11 section 2-3).

Route bodies stay thin: identity rules live in `services/identity.py`, money rules in
`services/credits.py` and `services/billing.py`. What happens here is HTTP shape only —
cookies, status codes, and turning service errors into the unified error body.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request, Response
from pydantic import BaseModel, Field

from app.api.declare import (
    CSRF_COOKIE,
    CSRF_HEADER,
    SESSION_COOKIE,
    ApiError,
    DeclaredRouter,
    Identity,
    current_identity,
    current_user,
)
from app.container import Container
from app.services.billing import BillingError
from app.services.identity import AuthError
from app.services.uow import UnitOfWork

router = DeclaredRouter()


def _c(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


def _uow(request: Request) -> UnitOfWork:
    return _c(request).uow_factory()


def _translate(exc: Exception) -> ApiError:
    """Service exceptions carry a code and a sentence meant for the user."""
    if isinstance(exc, AuthError):
        status = {
            "BAD_CREDENTIALS": 401,
            "UNAUTHENTICATED": 401,
            "ACCOUNT_DISABLED": 403,
            "CSRF_REQUIRED": 403,
            "NAME_TAKEN": 409,
            "NOT_FOUND": 404,
        }.get(exc.code, 400)
        return ApiError(status, exc.code, exc.message)
    if isinstance(exc, BillingError):
        status = {"NOT_FOUND": 404, "ORDER_CLOSED": 409}.get(exc.code, 400)
        return ApiError(status, exc.code, exc.message)
    return ApiError(400, "BAD_REQUEST", str(exc))


def set_session_cookies(response: Response, token: str, csrf: str, *, secure: bool) -> None:
    """HttpOnly session + a readable CSRF cookie (double submit, docs/11 section 2)."""
    max_age = 14 * 24 * 3600
    response.set_cookie(
        SESSION_COOKIE, token, max_age=max_age, httponly=True, samesite="lax",
        secure=secure, path="/",
    )
    response.set_cookie(
        CSRF_COOKIE, csrf, max_age=max_age, httponly=False, samesite="lax",
        secure=secure, path="/",
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


# ---- schemas ---------------------------------------------------------------
class RegisterIn(BaseModel):
    display_name: str = Field(min_length=2, max_length=40)
    invite_code: str = Field(min_length=4, max_length=200)


class LoginIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=40)
    access_key: str = Field(min_length=8, max_length=200)


class TopupIn(BaseModel):
    amount_cents: int = Field(gt=0, le=10_000_000)


class InviteIn(BaseModel):
    max_uses: int = Field(default=1, ge=1, le=10_000)
    days: int | None = Field(default=30, ge=1, le=3650)
    note: str = ""


class GrantIn(BaseModel):
    user_id: str
    credits: int = Field(gt=0, le=10_000_000)
    reason: str = Field(min_length=1, max_length=500)


class AdjustIn(BaseModel):
    user_id: str
    delta: int = Field(ge=-10_000_000, le=10_000_000)
    reason: str = Field(min_length=1, max_length=500)


class StatusIn(BaseModel):
    status: str = Field(pattern="^(active|disabled)$")


# ---- auth ------------------------------------------------------------------
@router.route("GET", "/auth/status", rate="read", auth=False)
def auth_status(request: Request) -> dict[str, Any]:
    """Public probe: does the browser already have a session, and is dev identity allowed?"""
    c = _c(request)
    try:
        who = current_identity(request)
    except ApiError:
        return {"authenticated": False, "dev_identity": c.settings.auth_mode == "dev"}
    with c.uow_factory() as uow:
        user = uow.identity.get(who.user_id)
        balance = uow.credits.balance(who.user_id)
        uow.commit()
    return {
        "authenticated": True,
        "dev_identity": c.settings.auth_mode == "dev",
        "user": {
            "id": who.user_id,
            "display_name": who.display_name,
            "role": who.role,
            "balance": balance,
            "registered": user is not None,
        },
    }


@router.route("POST", "/auth/register", rate="auth", auth=False)
def register(body: RegisterIn, request: Request, response: Response) -> dict[str, Any]:
    """Invite-only. Returns the access key exactly once; it is never retrievable again."""
    c = _c(request)
    with c.uow_factory() as uow:
        try:
            reg = uow.identity.register(
                display_name=body.display_name,
                invite_code=body.invite_code,
                initial_credits=c.settings.initial_credits,
                ip=_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        except AuthError as e:
            raise _translate(e) from e
        balance = uow.credits.balance(reg.user.id)
        uow.commit()
    set_session_cookies(response, reg.session_token, reg.csrf_token,
                        secure=c.settings.cookie_secure)
    return {
        "access_key": reg.access_key,
        "user": {
            "id": reg.user.id, "display_name": reg.user.display_name,
            "role": reg.user.role, "balance": balance,
        },
        "csrf_token": reg.csrf_token,
    }


@router.route("POST", "/auth/login", rate="auth", auth=False)
def login(body: LoginIn, request: Request, response: Response) -> dict[str, Any]:
    c = _c(request)
    with c.uow_factory() as uow:
        try:
            ok = uow.identity.login(
                display_name=body.display_name,
                access_key=body.access_key,
                ip=_ip(request),
                user_agent=request.headers.get("user-agent", ""),
            )
        except AuthError as e:
            raise _translate(e) from e
        balance = uow.credits.balance(ok.user.id)
        uow.commit()
    set_session_cookies(response, ok.session_token, ok.csrf_token,
                        secure=c.settings.cookie_secure)
    return {
        "user": {
            "id": ok.user.id, "display_name": ok.user.display_name,
            "role": ok.user.role, "balance": balance,
        },
        "csrf_token": ok.csrf_token,
    }


@router.route("POST", "/auth/logout", rate="write")
def logout(request: Request, response: Response) -> dict[str, str]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with _uow(request) as uow:
            uow.identity.revoke(token)
            uow.commit()
    clear_session_cookies(response)
    return {"status": "logged_out"}


# ---- me --------------------------------------------------------------------
@router.route("GET", "/me", rate="read")
def me(request: Request) -> dict[str, Any]:
    who = current_identity(request)
    c = _c(request)
    with c.uow_factory() as uow:
        user = uow.identity.get(who.user_id)
        # The dev header has no user row; give it the signup grant so local use works.
        if user is None:
            uow.credits.ensure_user(who.user_id, c.settings.initial_credits)
        uow.commit()
        return {
            "user_id": who.user_id,
            "display_name": who.display_name,
            "role": who.role,
            "credits": uow.credits.balance(who.user_id),
            "held": uow.credits.held(who.user_id),
            "csrf_token": who.csrf_token,
        }


@router.route("GET", "/me/credits", rate="read")
def my_ledger(request: Request) -> list[dict[str, Any]]:
    user = current_user(request)
    with _uow(request) as uow:
        return [
            {
                "id": e.id, "delta": e.delta, "kind": e.kind, "run_id": e.run_id,
                "balance_after": e.balance_after, "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in uow.credits.ledger(user)
        ]


@router.route("GET", "/auth/sessions", rate="read")
def my_sessions(request: Request) -> list[dict[str, Any]]:
    user = current_user(request)
    with _uow(request) as uow:
        return [
            {
                "id": s.id, "ip": s.ip, "user_agent": s.user_agent,
                "created_at": s.created_at.isoformat(),
                "last_seen_at": s.last_seen_at.isoformat(),
                "revoked": s.revoked_at is not None,
            }
            for s in uow.identity.sessions(user)
        ]


@router.route("POST", "/auth/sessions/revoke", rate="write")
def revoke_my_sessions(request: Request, response: Response) -> dict[str, Any]:
    """Sign out everywhere, including this browser."""
    user = current_user(request)
    with _uow(request) as uow:
        n = uow.identity.revoke_sessions(user)
        uow.commit()
    clear_session_cookies(response)
    return {"revoked": n}


# ---- billing ---------------------------------------------------------------
@router.route("GET", "/billing/pricing", rate="read", auth=False)
def pricing(request: Request) -> dict[str, Any]:
    with _uow(request) as uow:
        return uow.billing.pricing()


@router.route("GET", "/billing/topups", rate="read")
def my_topups(request: Request) -> list[dict[str, Any]]:
    user = current_user(request)
    with _uow(request) as uow:
        return [uow.billing.topup_view(t) for t in uow.billing.topups(user)]


@router.route("POST", "/billing/topups", rate="write", status_code=201)
def create_topup(body: TopupIn, request: Request) -> dict[str, Any]:
    """Create a pending order. Money moves only when the payment is confirmed."""
    user = current_user(request)
    c = _c(request)
    with c.uow_factory() as uow:
        if not uow.billing.topup_enabled():
            raise ApiError(403, "TOPUP_DISABLED", "充值暂未开放")
        try:
            order = uow.billing.create_topup(user, amount_cents=body.amount_cents)
        except BillingError as e:
            raise _translate(e) from e
        uow.commit()
        return {
            **uow.billing.topup_view(order),
            # No provider is wired yet. The client shows this so the flow is testable.
            "payment": {
                "provider": "manual",
                "status": "awaiting_confirmation",
                "note": "还没有接入支付渠道。管理员确认后积分到账。",
            },
        }


# ---- admin: users, invites, grants -----------------------------------------
@router.route("GET", "/admin/users", rate="read", auth="admin")
def list_users(request: Request) -> list[dict[str, Any]]:
    c = _c(request)
    with c.uow_factory() as uow:
        return [
            uow.identity.user_view(u, balance=uow.credits.balance(u.id))
            for u in uow.identity.users()
        ]


@router.route("POST", "/admin/users/{user_id}/grant", rate="write", auth="admin")
def grant_credits(user_id: str, body: GrantIn, request: Request) -> dict[str, Any]:
    who = current_identity(request)
    with _uow(request) as uow:
        if uow.identity.get(user_id) is None and body.user_id != user_id:
            raise ApiError(404, "NOT_FOUND", user_id)
        entry = uow.credits.grant(
            user_id, body.credits, admin_id=who.user_id,
            key=f"grant:{who.user_id}:{user_id}:{body.reason}:{body.credits}",
            note=body.reason,
        )
        uow.identity.audit(
            who.user_id, "credits.grant", "user", user_id,
            {"credits": body.credits, "reason": body.reason}, ip=_ip(request),
        )
        uow.commit()
        return {
            "entry_id": entry.id, "delta": entry.delta,
            "balance": uow.credits.balance(user_id),
        }


@router.route("POST", "/admin/users/{user_id}/adjust", rate="write", auth="admin")
def adjust_credits(user_id: str, body: AdjustIn, request: Request) -> dict[str, Any]:
    who = current_identity(request)
    with _uow(request) as uow:
        if uow.identity.get(user_id) is None:
            raise ApiError(404, "NOT_FOUND", user_id)
        try:
            entry = uow.credits.adjust(
                user_id, body.delta, admin_id=who.user_id,
                key=f"adjust:{who.user_id}:{user_id}:{body.reason}:{body.delta}",
                note=body.reason,
            )
        except Exception as e:  # noqa: BLE001 - insufficient balance becomes a 402
            raise _translate(e) from e
        uow.identity.audit(
            who.user_id, "credits.adjust", "user", user_id,
            {"delta": body.delta, "reason": body.reason}, ip=_ip(request),
        )
        uow.commit()
        return {
            "entry_id": entry.id, "delta": entry.delta,
            "balance": uow.credits.balance(user_id),
        }


@router.route("POST", "/admin/users/{user_id}/status", rate="write", auth="admin")
def set_user_status(user_id: str, body: StatusIn, request: Request) -> dict[str, Any]:
    who = current_identity(request)
    with _uow(request) as uow:
        try:
            user = uow.identity.set_status(user_id, body.status, actor_id=who.user_id)
        except AuthError as e:
            raise _translate(e) from e
        uow.commit()
        return uow.identity.user_view(user)


@router.route("POST", "/admin/users/{user_id}/rotate-key", rate="write", auth="admin")
def rotate_key(user_id: str, request: Request) -> dict[str, str]:
    """Issue a fresh access key and kill that user's sessions. Shown once."""
    who = current_identity(request)
    with _uow(request) as uow:
        try:
            key = uow.identity.rotate_access_key(user_id, actor_id=who.user_id)
        except AuthError as e:
            raise _translate(e) from e
        uow.commit()
    return {"access_key": key}


@router.route("GET", "/admin/invites", rate="read", auth="admin")
def list_invites(request: Request) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [
            {
                "id": i.id, "created_by": i.created_by, "max_uses": i.max_uses,
                "used_count": i.used_count, "revoked": i.revoked, "note": i.note,
                "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                "created_at": i.created_at.isoformat(),
            }
            for i in uow.identity.invites()
        ]


@router.route("POST", "/admin/invites", rate="write", auth="admin", status_code=201)
def create_invite(body: InviteIn, request: Request) -> dict[str, Any]:
    """The code is returned once. Only its hash is stored."""
    who = current_identity(request)
    with _uow(request) as uow:
        invite, code = uow.identity.create_invite(
            created_by=who.user_id, max_uses=body.max_uses, days=body.days, note=body.note
        )
        uow.identity.audit(
            who.user_id, "invite.create", "invite", invite.id,
            {"max_uses": body.max_uses, "days": body.days}, ip=_ip(request),
        )
        uow.commit()
        return {
            "id": invite.id, "code": code, "max_uses": invite.max_uses,
            "expires_at": invite.expires_at.isoformat() if invite.expires_at else None,
        }


@router.route("POST", "/admin/invites/{invite_id}/revoke", rate="write", auth="admin")
def revoke_invite(invite_id: str, request: Request) -> dict[str, str]:
    who = current_identity(request)
    with _uow(request) as uow:
        try:
            uow.identity.revoke_invite(invite_id, actor_id=who.user_id)
        except AuthError as e:
            raise _translate(e) from e
        uow.commit()
    return {"status": "revoked"}


@router.route("GET", "/admin/audit", rate="read", auth="admin")
def audit_logs(request: Request, action: str | None = None) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [
            {
                "id": a.id, "actor_id": a.actor_id, "action": a.action,
                "target_type": a.target_type, "target_id": a.target_id,
                "detail": a.detail, "ip": a.ip, "created_at": a.created_at.isoformat(),
            }
            for a in uow.identity.audit_logs(action=action)
        ]


@router.route("GET", "/admin/topups", rate="read", auth="admin")
def admin_topups(request: Request, user_id: str | None = None) -> list[dict[str, Any]]:
    with _uow(request) as uow:
        return [uow.billing.topup_view(t) for t in uow.billing.topups(user_id)]


@router.route("POST", "/admin/topups/{topup_id}/confirm", rate="write", auth="admin")
def confirm_topup(topup_id: str, request: Request) -> dict[str, Any]:
    """Confirm a manual payment. Replaying is safe: the ledger row is keyed by order id."""
    who = current_identity(request)
    with _uow(request) as uow:
        try:
            order = uow.billing.mark_paid(topup_id, external_ref=f"admin:{who.user_id}")
        except BillingError as e:
            raise _translate(e) from e
        uow.identity.audit(
            who.user_id, "topup.confirm", "topup", topup_id,
            {"credits": order.credits}, ip=_ip(request),
        )
        uow.commit()
        return {**uow.billing.topup_view(order), "balance": uow.credits.balance(order.user_id)}


@router.route("POST", "/admin/topups/{topup_id}/cancel", rate="write", auth="admin")
def cancel_topup(topup_id: str, request: Request) -> dict[str, Any]:
    who = current_identity(request)
    with _uow(request) as uow:
        try:
            order = uow.billing.cancel_topup(topup_id, actor_id=who.user_id)
        except BillingError as e:
            raise _translate(e) from e
        uow.identity.audit(who.user_id, "topup.cancel", "topup", topup_id, ip=_ip(request))
        uow.commit()
        return uow.billing.topup_view(order)


@router.route("GET", "/admin/billing", rate="read", auth="admin")
def admin_billing(request: Request) -> dict[str, Any]:
    with _uow(request) as uow:
        return {
            "pricing": uow.billing.pricing(),
            "recent_topups": [uow.billing.topup_view(t) for t in uow.billing.topups(limit=20)],
        }


__all__ = [
    "CSRF_HEADER",
    "Identity",
    "router",
    "set_session_cookies",
    "clear_session_cookies",
]
