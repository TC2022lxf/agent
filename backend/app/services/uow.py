"""Unit of work: the only thing Runtime and API see of the database."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import TracebackType
from typing import Self

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.persistence.bootstrap import ensure_database, sync_columns
from app.persistence.models import Base
from app.services.billing import BillingService
from app.services.collab import CollabService
from app.services.console import ConsoleService
from app.services.credits import CreditsService
from app.services.identity import IdentityService
from app.services.preferences import PreferencesService
from app.services.products import ProductService
from app.services.profiles import ProfileService
from app.services.skill_edits import SkillEditService


class UnitOfWork:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self._session = factory()
        self.collab = CollabService(self._session)
        self.credits = CreditsService(self._session)
        self.billing = BillingService(self._session)
        self.identity = IdentityService(self._session)
        self.prefs = PreferencesService(self._session)
        self.products = ProductService(self._session)
        self.console = ConsoleService(self._session)
        self.profiles = ProfileService(self._session)
        self.skill_edits = SkillEditService(self._session)

    def commit(self) -> None:
        self._session.commit()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            self._session.rollback()
        self._session.close()


UowFactory = Callable[[], UnitOfWork]


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        db_file = make_url(url).database
        if db_file and db_file != ":memory:":
            Path(db_file).parent.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url or url == "sqlite://":
            kwargs["poolclass"] = StaticPool
        engine = create_engine(url, **kwargs)

        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _rec):  # type: ignore[no-untyped-def]
            dbapi_conn.execute("PRAGMA journal_mode=WAL")
            dbapi_conn.execute("PRAGMA busy_timeout=5000")

        return engine
    return create_engine(url, pool_pre_ping=True)


def make_uow_factory(url: str) -> UowFactory:
    ensure_database(url)
    engine = make_engine(url)
    sync_columns(engine, Base.metadata)
    factory = sessionmaker(engine, expire_on_commit=False)
    return lambda: UnitOfWork(factory)
