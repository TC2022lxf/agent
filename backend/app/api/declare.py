"""API declarations and the auth/limit middleware of docs/07 and 11.

Every route must declare its rate class and who may call it, or the app refuses to start.
Cross-cutting concerns live here, not in route bodies:

* identity: session cookie (browser, works for SSE and `<img>`) or the dev identity header
* CSRF: required on writes that authenticated by cookie, so a cross-site form cannot act
* rate limiting: one table, one place
* admin: `role = admin` checked here, never in a handler
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, Request

RATE_LIMITS: dict[str, tuple[int, float]] = {  # class -> (calls, per seconds)
    "auth": (10, 60.0),  # register / login, per IP
    "read": (600, 60.0),
    "write": (240, 60.0),
    "run": (60, 60.0),
    "upload": (60, 60.0),
}

SESSION_COOKIE = "ea_session"
CSRF_COOKIE = "ea_csrf"
CSRF_HEADER = "X-CSRF-Token"
DEV_USER_HEADER = "X-User-Id"
ANONYMOUS = "dev-user"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message


@dataclass(frozen=True)
class Identity:
    """Who is calling. `via` explains how, which decides whether CSRF applies."""

    user_id: str
    display_name: str = ""
    role: str = "user"
    via: str = "anonymous"  # session | header | anonymous
    csrf_token: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@dataclass(frozen=True)
class Decl:
    method: str
    path: str
    rate: str
    auth: str = "user"  # public | user | admin
    audit: bool = False


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def check(self, user: str, rate: str) -> None:
        calls, window = RATE_LIMITS[rate]
        q, now = self._hits[(user, rate)], time.monotonic()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= calls:
            raise ApiError(429, "RATE_LIMITED", f"rate class {rate} exceeded")
        q.append(now)


def _container(request: Request) -> Any:
    return request.app.state.container


def resolve_identity(request: Request) -> Identity:
    """Session cookie first, then the dev header (only when auth_mode is dev).

    Cached on the request so one call costs one lookup, not one per dependency.
    """
    cached: Identity | None = getattr(request.state, "identity", None)
    if cached is not None:
        return cached

    c = _container(request)
    token = request.cookies.get(SESSION_COOKIE)
    csrf = request.cookies.get(CSRF_COOKIE)
    identity: Identity | None = None

    if token:
        with c.uow_factory() as uow:
            try:
                user, _row = uow.identity.session_user(token)
            except Exception:  # noqa: BLE001 - an expired row simply means "not logged in"
                identity = None
            else:
                identity = Identity(
                    user_id=user.id,
                    display_name=user.display_name,
                    role=user.role,
                    via="session",
                    csrf_token=csrf,
                )
            uow.commit()

    if identity is None and c.settings.auth_mode == "dev":
        dev_id = request.headers.get(DEV_USER_HEADER) or ANONYMOUS
        identity = Identity(user_id=dev_id, display_name=dev_id, role="admin", via="header")

    if identity is None:
        raise ApiError(401, "UNAUTHENTICATED", "请先登录")

    request.state.identity = identity
    return identity


def current_user(request: Request) -> str:
    """The user id. Handlers only need this; roles are enforced by the declaration."""
    return resolve_identity(request).user_id


def current_identity(request: Request) -> Identity:
    return resolve_identity(request)


def _check_csrf(request: Request, identity: Identity) -> None:
    """Cookie sessions need the double-submit token on writes (docs/11 section 2)."""
    if identity.via != "session":
        return
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    header = request.headers.get(CSRF_HEADER)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie:
        raise ApiError(403, "CSRF_REQUIRED", f"写操作需要 {CSRF_HEADER} 与 csrf cookie 一致")


class DeclaredRouter:
    def __init__(self) -> None:
        self.router = APIRouter(prefix="/api")
        self.decls: list[Decl] = []

    def route(
        self,
        method: str,
        path: str,
        *,
        rate: str,
        auth: str | bool = "user",
        audit: bool = False,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """`auth` accepts the older boolean form so existing routes keep working."""
        if rate not in RATE_LIMITS:
            raise ValueError(f"{method} {path}: unknown rate class {rate!r}")
        mode = "user" if auth is True else "public" if auth is False else str(auth)
        if mode not in {"public", "user", "admin"}:
            raise ValueError(f"{method} {path}: unknown auth mode {mode!r}")

        def guard(request: Request) -> None:
            if mode == "public":
                who = request.client.host if request.client else "?"
            else:
                identity = resolve_identity(request)
                if mode == "admin" and not identity.is_admin:
                    raise ApiError(403, "FORBIDDEN", "需要管理员权限")
                _check_csrf(request, identity)
                who = identity.user_id
            request.app.state.limiter.check(who, rate)

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.decls.append(Decl(method.upper(), "/api" + path, rate, mode, audit))
            self.router.add_api_route(
                path, fn, methods=[method.upper()], dependencies=[Depends(guard)], **kwargs
            )
            return fn

        return deco
