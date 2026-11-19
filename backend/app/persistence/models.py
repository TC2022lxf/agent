"""SQLAlchemy models. Only app/persistence and app/services may import SQLAlchemy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy import String as SAString
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class String(SAString):
    """Default length so MySQL accepts VARCHAR. SQLite ignores the length."""

    def __init__(self, length: int = 255) -> None:
        super().__init__(length)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("task"))
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # pdp | image
    agent_key: Mapped[str] = mapped_column(String)
    goal: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="draft")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    product_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Product(Base):
    """A product the user works on: facts the Agent may use, and the imported listing/images."""

    __tablename__ = "products"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("prod"))
    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    brand: Mapped[str] = mapped_column(String, default="")
    marketplace: Mapped[str] = mapped_column(String, default="")
    mode: Mapped[str] = mapped_column(String, default="generate")  # generate | optimize
    sample_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # {"attributes": {..}, "rating": {..}, "price_text": str|None, "category_path": [..]}
    facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # {"title": str|None, "bullets": [..]|None, "description": .., "search_terms": ..}
    listing: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # {"main": object_key|None, "gallery": [object_key, ..]}
    assets: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Artifact(Base):
    """One per slot, plus one `pdp` artifact whose versions are manifests."""

    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("art"))
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # pdp | text | image
    slot: Mapped[str | None] = mapped_column(String, nullable=True)
    current_version_id: Mapped[str | None] = mapped_column(String, nullable=True)


class Version(Base):
    """Immutable once committed (except status/user_signal bookkeeping)."""

    __tablename__ = "versions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ver"))
    artifact_id: Mapped[str] = mapped_column(ForeignKey("artifacts.id"), index=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    parent_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str] = mapped_column(String)  # generated|edited|imported|cloned|user
    created_by: Mapped[str] = mapped_column(String)  # agent | user
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # pdp versions only
    status: Mapped[str] = mapped_column(String, default="candidate")  # candidate|ok|rejected
    user_signal: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("fb"))
    task_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    text: Mapped[str] = mapped_column(Text)
    # exactly one of: parameter_patch | new_constraint | question | strategy_switch
    interpretation: Mapped[str] = mapped_column(String)
    target_slot: Mapped[str | None] = mapped_column(String, nullable=True)
    target_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_region: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|applied|dismissed|declined
    note: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Constraint(Base):
    __tablename__ = "constraints"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("cons"))
    task_id: Mapped[str] = mapped_column(String, index=True)
    feedback_id: Mapped[str | None] = mapped_column(String, nullable=True)
    text: Mapped[str] = mapped_column(Text)
    rule: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|effective|revoked


class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("eval"))
    version_id: Mapped[str] = mapped_column(String, index=True)
    evaluator_id: Mapped[str] = mapped_column(String)
    passed: Mapped[bool] = mapped_column()
    can_reject: Mapped[bool] = mapped_column()
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("run"))
    task_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String)
    agent_key: Mapped[str] = mapped_column(String)
    trigger: Mapped[str] = mapped_column(String, default="utterance")
    # queued|running|succeeded|failed|cancelled  (+ cancel_requested while running)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    path: Mapped[list[Any]] = mapped_column(JSON, default=list)  # actual steps taken
    version_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    held: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[int] = mapped_column(Integer, default=0)
    # Actual cost above the hold, absorbed by the platform. A monitor reads this.
    overrun: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String, default=lambda: uuid4().hex)
    # Skill content hashes and what this run read (summary id, preference revision).
    skill_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    context_refs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resume_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    type: Mapped[str] = mapped_column(String)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("run_id", "tool_call_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    tool_call_id: Mapped[str] = mapped_column(String)
    agent_key: Mapped[str] = mapped_column(String)
    tool_name: Mapped[str] = mapped_column(String)
    tool_version: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # ok | error
    input: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[int] = mapped_column(Integer, default=0)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    alias: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # chat | image_generate | image_edit
    model: Mapped[str] = mapped_column(String, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="ok")
    profile_key: Mapped[str] = mapped_column(String, default="")
    purpose: Mapped[str] = mapped_column(String, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reasoning: Mapped[bool] = mapped_column(default=False)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_key: Mapped[str | None] = mapped_column(String, nullable=True)


class LedgerEntry(Base):
    """Append-only. Balance is the sum of `delta`; never updated in place.

    `idempotency_key` makes hold/settle/topup safe to retry: a replayed write is a no-op
    instead of a second charge. Kinds follow docs/architecture/data-and-contracts.md: grant | topup | hold | settle |
    refund | adjust | spend.
    """

    __tablename__ = "credit_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    delta: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    note: Mapped[str] = mapped_column(Text, default="")
    admin_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class User(Base):
    """An account. `display_name` is the login name; the access key is the credential."""

    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("usr"))
    display_name: Mapped[str] = mapped_column(String, unique=True, index=True)
    role: Mapped[str] = mapped_column(String, default="user")  # user | admin
    status: Mapped[str] = mapped_column(String, default="active")  # active | disabled
    access_key_hash: Mapped[str] = mapped_column(String, default="")
    invite_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Invite(Base):
    """Invite-only registration. The code is stored hashed; plaintext shows once."""

    __tablename__ = "invites"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("inv"))
    code_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    created_by: Mapped[str] = mapped_column(String, default="")
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked: Mapped[bool] = mapped_column(default=False)
    note: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Session(Base):
    """Server-side session. The cookie carries a random token; only its hash is stored."""

    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("ses"))
    user_id: Mapped[str] = mapped_column(String, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    csrf_hash: Mapped[str] = mapped_column(String, default="")
    ip: Mapped[str] = mapped_column(String, default="")
    user_agent: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)
    last_seen_at: Mapped[datetime] = mapped_column(default=now)
    expires_at: Mapped[datetime] = mapped_column(default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)


class AuditLog(Base):
    """Append-only record of privileged writes (docs/architecture/data-and-contracts.md). Never updated, never deleted."""

    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str] = mapped_column(String, index=True)
    action: Mapped[str] = mapped_column(String, index=True)
    target_type: Mapped[str] = mapped_column(String, default="")
    target_id: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str] = mapped_column(String, default="")
    trace_id: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class Balance(Base):
    """Cache of `sum(ledger.delta)`. Locked on write; can always be rebuilt from the ledger."""

    __tablename__ = "user_balances"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    points: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(default=now)


class Topup(Base):
    """A recharge order. 1 credit = 0.01 CNY, so credits == amount in fen.

    `pending` orders do not move money. Only `paid` writes a ledger row, which makes the
    gateway callback (or a manual confirmation) safe to replay.
    """

    __tablename__ = "topups"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("top"))
    user_id: Mapped[str] = mapped_column(String, index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    credits: Mapped[int] = mapped_column(Integer)
    method: Mapped[str] = mapped_column(String, default="manual")  # manual | simulated
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    paid_at: Mapped[datetime | None] = mapped_column(nullable=True)


class Preference(Base):
    __tablename__ = "preferences"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    agent_key: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    body_md: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String, default="user")  # user | proposal | restore


class AppSetting(Base):
    """Console-edited values (model alias, system prompt). Not a substitute for .env secrets."""

    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class ModelProfile(Base):
    """Console-edited model catalog. Tools and the graph never hard-code vendor model names."""

    __tablename__ = "model_profiles"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    upstream_model: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # planner | image
    context_window_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    when_thinking_enabled: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    when_thinking_disabled: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list)
    price: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    param_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(default=True)


class ContextSummary(Base):
    """Append-only compaction of what the planner is allowed to see. The timeline is unchanged."""

    __tablename__ = "context_summaries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("sum"))
    task_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    trigger: Mapped[str] = mapped_column(String)  # auto | manual
    # How far this summary reaches: runs at or before this one are considered covered.
    covered_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=now)


class PreferenceProposal(Base):
    __tablename__ = "preference_proposals"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("prop"))
    user_id: Mapped[str] = mapped_column(String, index=True)
    agent_key: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending|accepted|rejected


class SkillRevision(Base):
    """Edited Skill text. The repo file stays as shipped; the newest row wins at load time.

    Saving requires the revision you started from, so two editors cannot silently overwrite.
    """

    __tablename__ = "skill_revisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    skill_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(String, default="")
    audience: Mapped[str] = mapped_column(String, default="general")
    edited_by: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="edited")  # edited | restored
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (UniqueConstraint("skill_id", "revision"),)
