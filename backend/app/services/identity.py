"""Identity: accounts, invite codes, sessions, roles (docs/11 section 2).

Two credentials, on purpose:

* The **access key** proves who you are. A display name alone would let anyone log in as
  anyone who shares a name, so the name is only ever a lookup key. The plaintext is shown
  once, at registration or reset; the database keeps a scrypt hash.
* A **session cookie** keeps you logged in. It is HttpOnly + SameSite=Lax, and every write
  also needs the CSRF header, so a cross-site form cannot act for you.

Nothing here imports FastAPI: routes translate HTTP into calls on this service.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import AuditLog, Invite, User, new_id
from app.persistence.models import Session as SessionRow

SESSION_TTL = timedelta(days=14)
SESSION_TOUCH = timedelta(minutes=10)
KEY_PREFIX = "ek_"  # makes a leaked key recognisable in a log or a screenshot
INVITE_PREFIX = "iv_"
MIN_KEY_LEN = 24
_NAME_RE = re.compile(r"^[\w\u4e00-\u9fff][\w\u4e00-\u9fff .@-]{0,39}$")
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


class AuthError(Exception):
    """Bad credentials, disabled account, or a dead session. The message is user-facing."""

    def __init__(self, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


class RegistrationClosed(AuthError):
    def __init__(self, message: str = "邀请码无效或已用完") -> None:
        super().__init__("INVITE_INVALID", message)


@dataclass(frozen=True)
class Registration:
    user: User
    access_key: str  # plaintext, returned to the caller exactly once
    session_token: str
    csrf_token: str


@dataclass(frozen=True)
class Login:
    user: User
    session_token: str
    csrf_token: str


def _hash_secret(secret: str, *, salt: bytes | None = None) -> str:
    """scrypt for access keys. Format: scrypt$n$r$p$salt$hash (salt and hash hex)."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_secret(secret: str, stored: str) -> bool:
    """Constant-time check against a stored scrypt hash. Unknown format never verifies."""
    try:
        algo, n, r, p, salt_hex, digest_hex = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    try:
        digest = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n), r=int(r), p=int(p), dklen=len(bytes.fromhex(digest_hex)),
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


def _token_hash(token: str) -> str:
    """Session and CSRF tokens are high-entropy already; a plain SHA-256 is enough.

    scrypt here would add ~90ms to every request and buy nothing: the token is not a
    low-entropy password that could be guessed offline.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes. Compare in UTC rather than crashing on a tz mismatch."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class IdentityService:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---- lookup -----------------------------------------------------------
    def by_name(self, display_name: str) -> User | None:
        return self.s.scalar(
            select(User).where(User.display_name == display_name.strip())
        )

    def get(self, user_id: str) -> User | None:
        return self.s.get(User, user_id)

    def require_active(self, user_id: str) -> User:
        user = self.get(user_id)
        if user is None:
            raise AuthError("UNAUTHENTICATED", "账号不存在")
        if user.status != "active":
            raise AuthError("ACCOUNT_DISABLED", "账号已被停用")
        return user

    def validate_name(self, display_name: str) -> str:
        name = display_name.strip()
        if not _NAME_RE.match(name):
            raise AuthError(
                "BAD_NAME", "名字需为 2–40 个字符，可用中英文、数字、空格、点、@ 和连字符"
            )
        if len(name) < 2:
            raise AuthError("BAD_NAME", "名字至少 2 个字符")
        return name

    # ---- invites ----------------------------------------------------------
    def create_invite(
        self, *, created_by: str, max_uses: int = 1, days: int | None = 30, note: str = ""
    ) -> tuple[Invite, str]:
        max_uses = max(1, min(int(max_uses), 10_000))
        code = INVITE_PREFIX + secrets.token_urlsafe(18)
        invite = Invite(
            code_hash=_token_hash(code),
            created_by=created_by,
            max_uses=max_uses,
            expires_at=_now() + timedelta(days=days) if days else None,
            note=note,
        )
        self.s.add(invite)
        self.s.flush()
        return invite, code

    def invite_by_code(self, code: str) -> Invite | None:
        return self.s.scalar(select(Invite).where(Invite.code_hash == _token_hash(code.strip())))

    def _consume_invite(self, code: str, user_id: str) -> Invite:
        invite = self.invite_by_code(code)
        if invite is None:
            raise RegistrationClosed()
        expires = _aware(invite.expires_at)
        if invite.revoked:
            raise RegistrationClosed("邀请码已撤销")
        if expires is not None and expires <= _now():
            raise RegistrationClosed("邀请码已过期")
        if invite.used_count >= invite.max_uses:
            raise RegistrationClosed()
        invite.used_count += 1
        invite_id = invite.id
        # Stamp the consuming user so a support question ("which invite?") is answerable.
        user = self.s.get(User, user_id)
        if user is not None:
            user.invite_id = invite_id
        return invite

    def revoke_invite(self, invite_id: str, *, actor_id: str) -> Invite:
        invite = self.s.get(Invite, invite_id)
        if invite is None:
            raise AuthError("NOT_FOUND", "邀请码不存在")
        invite.revoked = True
        self.audit(actor_id, "invite.revoke", "invite", invite_id)
        self.s.flush()
        return invite

    def invites(self) -> list[Invite]:
        return list(self.s.scalars(select(Invite).order_by(Invite.created_at.desc())))

    # ---- registration & login ---------------------------------------------
    def register(
        self,
        *,
        display_name: str,
        invite_code: str,
        initial_credits: int = 0,
        ip: str = "",
        user_agent: str = "",
        role: str = "user",
    ) -> Registration:
        name = self.validate_name(display_name)
        if self.by_name(name) is not None:
            raise AuthError("NAME_TAKEN", "这个名字已被占用，换一个")
        if self.invite_by_code(invite_code) is None:
            raise RegistrationClosed()

        access_key = KEY_PREFIX + secrets.token_urlsafe(32)
        user = User(
            display_name=name,
            role=role,
            access_key_hash=_hash_secret(access_key),
        )
        self.s.add(user)
        self.s.flush()
        self._consume_invite(invite_code, user.id)
        if initial_credits > 0:
            # Imported here to avoid a cycle: credits reads Run, identity does not need it.
            from app.services.credits import CreditsService

            CreditsService(self.s).ensure_user(user.id, initial_credits)
        token, csrf = self._open_session(user, ip=ip, user_agent=user_agent)
        user.last_login_at = _now()
        self.audit(user.id, "user.register", "user", user.id, {"invite": invite_code[:6] + "…"})
        self.s.flush()
        return Registration(user=user, access_key=access_key, session_token=token, csrf_token=csrf)

    def login(
        self, *, display_name: str, access_key: str, ip: str = "", user_agent: str = ""
    ) -> Login:
        user = self.by_name(display_name)
        # Verify against a dummy hash when the name is unknown so timing does not reveal
        # whether the account exists.
        stored = user.access_key_hash if user is not None else _DUMMY_HASH
        ok = verify_secret(access_key, stored)
        if user is None or not ok:
            raise AuthError("BAD_CREDENTIALS", "名字或访问密钥不正确")
        if user.status != "active":
            raise AuthError("ACCOUNT_DISABLED", "账号已被停用")
        token, csrf = self._open_session(user, ip=ip, user_agent=user_agent)
        user.last_login_at = _now()
        self.s.flush()
        return Login(user=user, session_token=token, csrf_token=csrf)

    def rotate_access_key(self, user_id: str, *, actor_id: str) -> str:
        """Issue a new key and kill every session: the old key is presumed leaked."""
        user = self.s.get(User, user_id)
        if user is None:
            raise AuthError("NOT_FOUND", "账号不存在")
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        user.access_key_hash = _hash_secret(key)
        self.revoke_sessions(user_id)
        self.audit(actor_id, "user.rotate_key", "user", user_id)
        self.s.flush()
        return key

    def set_status(self, user_id: str, status: str, *, actor_id: str) -> User:
        if status not in {"active", "disabled"}:
            raise AuthError("BAD_STATUS", "status 只能是 active 或 disabled")
        user = self.s.get(User, user_id)
        if user is None:
            raise AuthError("NOT_FOUND", "账号不存在")
        user.status = status
        user.disabled_at = _now() if status == "disabled" else None
        if status == "disabled":
            self.revoke_sessions(user_id)  # a disabled account must not keep working
        self.audit(actor_id, f"user.{status}", "user", user_id)
        self.s.flush()
        return user

    # ---- sessions ---------------------------------------------------------
    def _open_session(self, user: User, *, ip: str, user_agent: str) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        self.s.add(
            SessionRow(
                user_id=user.id,
                token_hash=_token_hash(token),
                csrf_hash=_token_hash(csrf),
                ip=ip[:64],
                user_agent=user_agent[:255],
                expires_at=_now() + SESSION_TTL,
            )
        )
        self.s.flush()
        return token, csrf

    def session_user(self, token: str, *, touch: bool = True) -> tuple[User, SessionRow]:
        row = self.s.scalar(select(SessionRow).where(SessionRow.token_hash == _token_hash(token)))
        if row is None or row.revoked_at is not None:
            raise AuthError("UNAUTHENTICATED", "请重新登录")
        expires = _aware(row.expires_at)
        if expires is not None and expires <= _now():
            raise AuthError("UNAUTHENTICATED", "登录已过期，请重新登录")
        user = self.s.get(User, row.user_id)
        if user is None or user.status != "active":
            raise AuthError("UNAUTHENTICATED", "账号不可用")
        if touch:
            last = _aware(row.last_seen_at)
            if last is None or _now() - last > SESSION_TOUCH:
                row.last_seen_at = _now()
        return user, row

    def check_csrf(self, row: SessionRow, csrf_token: str | None) -> None:
        if not csrf_token or not hmac.compare_digest(_token_hash(csrf_token), row.csrf_hash or ""):
            raise AuthError("CSRF_REQUIRED", "缺少或错误的 X-CSRF-Token")

    def revoke(self, token: str) -> None:
        row = self.s.scalar(select(SessionRow).where(SessionRow.token_hash == _token_hash(token)))
        if row is not None and row.revoked_at is None:
            row.revoked_at = _now()

    def revoke_sessions(self, user_id: str) -> int:
        rows = list(
            self.s.scalars(
                select(SessionRow).where(
                    SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None)
                )
            )
        )
        for row in rows:
            row.revoked_at = _now()
        return len(rows)

    def sessions(self, user_id: str) -> list[SessionRow]:
        return list(
            self.s.scalars(
                select(SessionRow)
                .where(SessionRow.user_id == user_id)
                .order_by(SessionRow.created_at.desc())
            )
        )

    # ---- admin ------------------------------------------------------------
    def users(self, limit: int = 200) -> list[User]:
        return list(
            self.s.scalars(select(User).order_by(User.created_at.desc()).limit(limit))
        )

    def ensure_admin(self, display_name: str, access_key: str) -> User:
        """Bootstrap: an admin named in the environment. Idempotent; does not reset a key."""
        user = self.by_name(display_name)
        if user is None:
            user = User(
                display_name=display_name,
                role="admin",
                access_key_hash=_hash_secret(access_key),
            )
            self.s.add(user)
            self.s.flush()
        elif user.role != "admin":
            user.role = "admin"
            self.s.flush()
        return user

    def user_view(self, user: User, *, balance: int = 0) -> dict[str, Any]:
        return {
            "id": user.id,
            "display_name": user.display_name,
            "role": user.role,
            "status": user.status,
            "invite_id": user.invite_id,
            "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "balance": balance,
        }

    # ---- audit ------------------------------------------------------------
    def audit(
        self,
        actor_id: str,
        action: str,
        target_type: str = "",
        target_id: str = "",
        detail: dict[str, Any] | None = None,
        *,
        ip: str = "",
        trace_id: str = "",
    ) -> None:
        self.s.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                detail=detail or {},
                ip=ip,
                trace_id=trace_id,
            )
        )

    def audit_logs(self, *, limit: int = 100, action: str | None = None) -> list[AuditLog]:
        q = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
        if action:
            q = q.where(AuditLog.action == action)
        return list(self.s.scalars(q))


_DUMMY_HASH = _hash_secret("not-a-real-key")


def new_session_id() -> str:
    return new_id("ses")
