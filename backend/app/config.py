"""Process settings, read from environment and .env. No business rules here."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import URL

DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"


def load_dotenv() -> None:
    """Fill unset variables from the repo .env and backend/.env. Does not override the process."""
    here = Path(__file__).resolve()
    for path in (here.parents[2] / ".env", here.parents[1] / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url_from_env(env: Mapping[str, str]) -> str:
    """MYSQL_HOST switches the app to MySQL. Empty host keeps SQLite (or DATABASE_URL)."""
    host = env.get("MYSQL_HOST", "").strip()
    if not host:
        return env.get("DATABASE_URL", "sqlite:///./data/app.db")
    url = URL.create(
        "mysql+pymysql",
        username=env.get("MYSQL_USER", "root") or "root",
        password=env.get("MYSQL_PASSWORD", ""),
        host=host,
        port=int(env.get("MYSQL_PORT", "3306") or "3306"),
        database=env.get("MYSQL_DATABASE", "ecommerce_ai") or "ecommerce_ai",
        query={"charset": "utf8mb4"},
    )
    return url.render_as_string(hide_password=False)


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./data/app.db"
    storage_dir: Path = Path("./data/blobs")
    skill_dir: Path = Path("../skills")
    gateway: str = "fake"  # fake | openai
    openai_base_url: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    # Profile keys and upstream model ids on the relay (dmxapi / OpenAI-compatible).
    planner_model: str = ""
    image_model: str = ""
    run_worker: str = "inline"  # inline (thread in API process) | off (separate worker process)
    initial_credits: int = 1000
    # auth_mode = dev keeps the X-User-Id header, which the scripts and tests rely on.
    # auth_mode = session is production: cookie only, and no header is trusted.
    auth_mode: str = "dev"
    cookie_secure: bool = False  # set true behind HTTPS
    admin_name: str = ""  # bootstrap admin, created on first boot if set
    admin_key: str = ""

    @staticmethod
    def from_env() -> Settings:
        load_dotenv()
        e = os.environ
        return Settings(
            database_url=database_url_from_env(e),
            storage_dir=Path(e.get("STORAGE_DIR", "./data/blobs")),
            skill_dir=Path(e.get("SKILL_DIR", str(DEFAULT_SKILLS_DIR))),
            gateway=e.get("GATEWAY", "fake"),
            openai_base_url=e.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            openai_api_key=e.get("OPENAI_API_KEY", ""),
            planner_model=e.get("PLANNER_MODEL", "").strip(),
            image_model=e.get("IMAGE_MODEL", "").strip(),
            run_worker=e.get("RUN_WORKER", "inline"),
            initial_credits=int(e.get("INITIAL_CREDITS", "1000")),
            auth_mode=e.get("AUTH_MODE", "dev"),
            cookie_secure=e.get("COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
            admin_name=e.get("ADMIN_NAME", ""),
            admin_key=e.get("ADMIN_KEY", ""),
        )
