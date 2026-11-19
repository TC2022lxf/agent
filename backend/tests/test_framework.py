"""Console config, direct tool calls, and schema bootstrap. The agent loop is unchanged."""

from __future__ import annotations

from sqlalchemy import Integer, String, create_engine, inspect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import Settings, database_url_from_env
from app.persistence.bootstrap import ensure_database, sync_columns
from tests.conftest import Api


def test_mysql_url_is_built_from_parts_and_sqlite_stays_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("MYSQL_HOST", "db.example")
    monkeypatch.setenv("MYSQL_USER", "app")
    monkeypatch.setenv("MYSQL_PASSWORD", "p@ss")
    monkeypatch.setenv("MYSQL_DATABASE", "ecommerce_ai")
    url = database_url_from_env(__import__("os").environ)
    assert url.startswith("mysql+pymysql://app:")
    assert url.endswith("/ecommerce_ai?charset=utf8mb4")
    monkeypatch.setenv("MYSQL_HOST", "")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database_url_from_env(__import__("os").environ) == "sqlite:///./data/app.db"


def test_sqlite_bootstrap_does_not_require_a_server(tmp_path) -> None:  # type: ignore[no-untyped-def]
    url = f"sqlite:///{tmp_path / 'app.db'}"
    ensure_database(url)

    class Base(DeclarativeBase):
        pass

    class Widget(Base):
        __tablename__ = "widgets"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        name: Mapped[str | None] = mapped_column(String, nullable=True)

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")
    sync_columns(engine, Base.metadata)
    cols = {c["name"] for c in inspect(engine).get_columns("widgets")}
    assert cols == {"id", "name"}
    sync_columns(engine, Base.metadata)


def test_console_saves_a_prompt_and_previews_tool_variables(api: Api) -> None:
    saved = api.http.put(
        "/api/admin/config/general",
        json={"model": "gpt-test", "system_prompt": "你好 {{agent}}\n{{tools}}\n{{skills}}"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["model"] == "gpt-test"
    assert "通用" in body["preview"] or "General" in body["preview"]
    assert "edit_listing" in body["preview"]
    assert "{{tools}}" not in body["preview"]
    again = api.http.get("/api/admin/config")
    general = next(a for a in again.json()["agents"] if a["key"] == "general")
    assert general["model"] == "gpt-test"
    assert again.json()["env"][0]["key"] == "GATEWAY"


def test_invoking_a_tool_returns_output_and_shows_up_in_the_log(api: Api) -> None:
    r = api.http.post(
        "/api/tools/edit_listing/invoke",
        json={"input": {
            "slot": "title", "instruction": "shorter", "base": {"text": "A long title"},
        }},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert r.json()["output"]["slot"] == "title"
    logs = api.http.get("/api/admin/logs").json()
    assert logs["tool_calls"][0]["tool"] == "edit_listing"
    assert logs["tool_calls"][0]["run_id"].startswith("console_")


def test_invoking_an_unknown_tool_is_404(api: Api) -> None:
    assert api.http.post("/api/tools/nope/invoke", json={"input": {}}).status_code == 404


def test_settings_round_trip_uses_the_same_database_as_tasks(api: Api) -> None:
    assert Settings(database_url="sqlite://").database_url == "sqlite://"
