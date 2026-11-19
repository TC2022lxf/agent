"""FastAPI application factory. Run: `uvicorn app.main:create_app --factory --port 8000`."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.auth_routes import router as auth_router
from app.api.declare import ApiError, RateLimiter
from app.api.routes import api
from app.config import Settings
from app.container import Container, build_container
from app.services.billing import BillingError
from app.services.collab import Conflict, NotFound
from app.services.credits import InsufficientCredits
from app.services.identity import AuthError

log = logging.getLogger(__name__)


def create_app(container: Container | None = None) -> FastAPI:
    settings = Settings.from_env()
    c = container or build_container(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        _bootstrap(c)
        if c.settings.run_worker == "inline":
            c.worker.start()
        yield
        c.worker.stop()

    app = FastAPI(title="Ecommerce AI", lifespan=lifespan)
    app.state.container = c
    app.state.limiter = RateLimiter()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        # Cookies must be allowed for the session to travel on XHR and on SSE.
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def err(status: int, code: str, message: str) -> JSONResponse:
        body = {"error": {"code": code, "message": message}}
        return JSONResponse(status_code=status, content=body)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, e: ApiError) -> JSONResponse:
        return err(e.status, e.code, e.message)

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, e: AuthError) -> JSONResponse:
        status = 401 if e.code in {"BAD_CREDENTIALS", "UNAUTHENTICATED"} else 403
        return err(status, e.code, e.message)

    @app.exception_handler(BillingError)
    async def _billing(_: Request, e: BillingError) -> JSONResponse:
        return err(400, e.code, e.message)

    @app.exception_handler(NotFound)
    async def _nf(_: Request, e: NotFound) -> JSONResponse:
        return err(404, "NOT_FOUND", str(e))

    @app.exception_handler(Conflict)
    async def _conflict(_: Request, e: Conflict) -> JSONResponse:
        return err(409, "CONFLICT", str(e))

    @app.exception_handler(InsufficientCredits)
    async def _credits(_: Request, e: InsufficientCredits) -> JSONResponse:
        return err(402, "INSUFFICIENT_CREDITS", "积分不足，请先充值")

    app.include_router(auth_router.router)
    app.include_router(api.router)
    _verify_declarations(app, [*auth_router.decls, *api.decls])
    return app


def _bootstrap(c: Container) -> None:
    """First boot: create the configured admin and print one invite code.

    Without this, a session-only deployment has no way in: registration needs an invite and
    invites need an admin. Idempotent, so a restart does not mint a second one.
    """
    s = c.settings
    if not s.admin_name:
        return
    with c.uow_factory() as uow:
        is_first = not uow.identity.users()
        if not any(u.role == "admin" for u in uow.identity.users()):
            key = s.admin_key or ""
            created = uow.identity.ensure_admin(s.admin_name, key or "change-me-please-123456")
            if not key:
                uow.identity.audit(created.id, "user.admin_bootstrap", "user", created.id,
                                   {"note": "no ADMIN_KEY set; key is the default value"})
                log.warning(
                    "Admin %r created with a default key. Set ADMIN_KEY, or rotate the key "
                    "in the console.", s.admin_name,
                )
            if is_first and not uow.identity.invites():
                _invite, code = uow.identity.create_invite(
                    created_by=created.id, max_uses=5, days=30, note="首次启动自动生成"
                )
                log.warning("First invite code (shows once): %s", code)
                print(f"\n=== 首次启动：邀请码 {code}（只显示这一次）===\n", flush=True)
            uow.commit()
        # The admin also uses the workbench, so it needs credits like anyone else. Without
        # this the very first account can sign in and then be refused by every Run.
        admin = uow.identity.by_name(s.admin_name)
        if admin is not None and admin.role == "admin":
            uow.credits.ensure_user(admin.id, s.initial_credits)
            uow.commit()


def _verify_declarations(app: FastAPI, decls: list) -> None:  # type: ignore[type-arg]
    declared = {(d.method, d.path) for d in decls}
    for r in app.routes:
        path = getattr(r, "path", "")
        if path.startswith("/api"):
            for m in getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}:
                if (m, path) not in declared:
                    raise RuntimeError(f"route {m} {path} has no API declaration")
