"""API reference must describe the actual application, not just a self-consistent snapshot."""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

from app.api.auth_routes import router as auth_api
from app.api.declare import Decl
from app.api.routes import api
from app.main import create_app

SPEC = importlib.util.spec_from_file_location(
    "documentation_generator", Path(__file__).resolve().parents[1] / "scripts/gen_docs.py"
)
assert SPEC is not None and SPEC.loader is not None
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def _rows(text: str) -> dict[tuple[str, str], str]:
    return {(method, path): auth for method, path, auth in re.findall(
        r"^\| (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) \| `([^`]+)` \| ([^ |]+) \|", text, re.M
    )}


def _keys(text: str) -> set[tuple[str, str]]:
    # OpenAPI removes Starlette converters, e.g. {key:path} becomes {key}.
    return {(method, re.sub(r":[^}]+(?=})", "", path)) for method, path in _rows(text)}


def _operations(container) -> set[tuple[str, str]]:
    schema = create_app(container).openapi()
    return {(method.upper(), path) for path, item in schema["paths"].items()
            if path.startswith("/api") for method in item
            if method in {"get", "post", "put", "patch", "delete"}}


def test_api_reference_covers_every_openapi_operation(container) -> None:
    assert _keys(generator.api_md()) == _operations(container)


def test_api_reference_preserves_auth_modes() -> None:
    rows = _rows(generator.api_md())
    for decl in [*api.decls, *auth_api.decls]:
        assert rows[(decl.method, decl.path)] == decl.auth
    assert rows[("GET", "/api/agents")] == "public"
    assert rows[("GET", "/api/admin/users")] == "admin"
    assert rows[("GET", "/api/me")] == "user"


@pytest.mark.parametrize("second_auth", ["public", "admin"])
def test_collect_api_declarations_rejects_duplicate_operation(second_auth: str) -> None:
    first = Decl("GET", "/api/example", "read", "public")
    duplicate = Decl("GET", "/api/example", "read", second_auth)
    with pytest.raises(ValueError, match="duplicate"):
        generator.collect_api_declarations([[first], [duplicate]])


def test_collect_api_declarations_sorts_and_keeps_methods() -> None:
    one = Decl("GET", "/api/z", "read", "public")
    two = Decl("POST", "/api/a", "write", "user")
    three = Decl("GET", "/api/a", "read", "public")
    assert generator.collect_api_declarations([[one, two], [three]]) == (three, two, one)


def test_api_reference_detects_removed_auth_row(container) -> None:
    full = generator.api_md()
    assert _keys(full) == _operations(container)
    incomplete = "\n".join(line for line in full.splitlines()
                           if not line.startswith("| POST | `/api/auth/login`"))
    assert _keys(incomplete) != _operations(container)


def test_generate_creates_output_and_check_is_read_only(tmp_path, monkeypatch) -> None:
    out = tmp_path / "generated"
    monkeypatch.setattr(generator, "OUT", out)
    monkeypatch.setattr(sys, "argv", ["gen_docs.py", "--check"])
    assert generator.main() == 1
    assert not out.exists()
    monkeypatch.setattr(sys, "argv", ["gen_docs.py"])
    assert generator.main() == 0
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in out.iterdir()}
    monkeypatch.setattr(sys, "argv", ["gen_docs.py", "--check"])
    assert generator.main() == 0
    assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in out.iterdir()}
    (out / "api.md").write_text("stale", encoding="utf-8")
    assert generator.main() == 1
    assert (out / "api.md").read_text(encoding="utf-8") == "stale"
