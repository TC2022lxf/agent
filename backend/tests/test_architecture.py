"""Layering and registration rules enforced as tests (docs/11 CI checks, AGENTS.md)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.builtin import build_registry
from app.agents.registry import AgentSpec, Registry
from app.evaluators.base import EvaluatorRegistry
from app.main import create_app
from app.runtime.guards import ScopeViolation, WriteScopeGuard
from app.tools.base import Tool, ToolMeta
from app.tools.image_tools import ImageOutput, NormRect
from tests.conftest import Api

APP = Path(__file__).resolve().parents[1] / "app"
DB_AND_VENDOR = {"sqlalchemy", "psycopg2", "psycopg", "boto3", "openai", "langgraph", "httpx"}
# LangGraph is the production loop, and only this adapter may import it (0015).
_LANGGRAPH_ADAPTER = "langgraph_loop.py"
_LANGGRAPH_ROOTS = {"langgraph", "langchain", "langchain_core", "langchain_openai"}


def _imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _files(pkg: str) -> list[Path]:
    return list((APP / pkg).rglob("*.py"))


@pytest.mark.parametrize("pkg", ["runtime", "tools", "agents", "evaluators", "image", "domain"])
def test_core_packages_do_not_import_db_or_vendor_sdks(pkg: str) -> None:
    for f in _files(pkg):
        roots = {i.split(".")[0] for i in _imports(f)}
        bad = roots & DB_AND_VENDOR
        if f.name == _LANGGRAPH_ADAPTER:
            bad -= {"langgraph"}
        else:
            bad |= roots & _LANGGRAPH_ROOTS
        assert not bad, f"{f.name} imports {bad}"


def test_tools_and_engines_never_import_collaboration_or_persistence() -> None:
    for pkg in ("tools", "image", "evaluators"):
        for f in _files(pkg):
            bad = {i for i in _imports(f) if i.startswith(("app.services", "app.persistence"))}
            assert not bad, f"{f.name} imports {bad}"


def test_only_infrastructure_talks_to_model_vendors() -> None:
    for f in APP.rglob("*.py"):
        if "infrastructure" in f.parts:
            continue
        assert "httpx" not in {i.split(".")[0] for i in _imports(f)}, f.name


def test_every_api_route_has_a_declaration(container) -> None:  # type: ignore[no-untyped-def]
    app = create_app(container)
    from app.api.routes import api

    declared = {(d.method, d.path) for d in api.decls}
    for r in app.routes:
        if getattr(r, "path", "").startswith("/api"):
            for m in r.methods - {"HEAD", "OPTIONS"}:  # type: ignore[attr-defined]
                assert (m, r.path) in declared  # type: ignore[attr-defined]
    assert all(d.rate for d in api.decls)


def test_rate_limit_returns_429(container, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.api import declare

    monkeypatch.setitem(declare.RATE_LIMITS, "read", (2, 60.0))
    with TestClient(create_app(container)) as c:
        codes = [c.get("/api/slots").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_tool_without_description_fails_registration() -> None:
    class Bad(Tool):
        meta = ToolMeta("bad", "1", " ", "none", 1, 5)
        input_model = ImageOutput
        output_model = ImageOutput

        def execute(self, input, ctx):  # type: ignore[no-untyped-def]
            return input

    with pytest.raises(ValueError, match="description"):
        Registry().register_tool(Bad())


def test_evaluator_without_description_fails_registration() -> None:
    from app.evaluators.base import Evaluator

    class Bad(Evaluator):
        id, description, can_reject = "bad", "", False

        def applies_to(self, subject):  # type: ignore[no-untyped-def]
            return False

        def evaluate(self, subject):  # type: ignore[no-untyped-def]
            raise NotImplementedError

    with pytest.raises(ValueError, match="description"):
        EvaluatorRegistry().register(Bad())


def test_general_agent_aggregates_without_copying() -> None:
    r = build_registry()
    g, pdp, img = r.agent("general"), r.agent("amazon_pdp"), r.agent("image")
    assert set(pdp.tool_names) | set(img.tool_names) <= set(g.tool_names)
    assert {"write_file", "read_file"} <= set(g.tool_names)
    assert "write_file" not in pdp.tool_names
    assert {"pdp-listing-optimize", "pdp-compliance-review"} <= set(pdp.skill_ids)
    assert {"image-first-draft", "image-secondary"} <= set(img.skill_ids)
    assert set(g.skill_ids) == {s.id for s in r.skills()}
    assert set(pdp.skill_ids) | set(img.skill_ids) <= set(g.skill_ids)
    assert {"pdp", "image", "file"} <= set(g.artifact_kinds)
    assert len(g.tool_names) == len(set(g.tool_names))


def test_specialist_cannot_take_another_audience_skill() -> None:
    r = build_registry()
    with pytest.raises(ValueError, match="another audience"):
        r.register_agent(
            AgentSpec(
                "image", "Image", "d", "image", (), ("pdp-search-terms",), (), "image", "image",
            )
        )


def test_agent_with_unknown_tool_fails_registration() -> None:
    r = build_registry()
    with pytest.raises(ValueError, match="unknown tool"):
        r.register_agent(AgentSpec("x", "x", "x", "x", ("nope",), (), (), "pdp", None))


def test_agent_cannot_call_tool_outside_its_list(api: Api) -> None:
    from app.runtime.tool_runner import ToolRunner

    runner = ToolRunner(api.c.registry, api.c.gateway, api.c.store)
    res = runner.call(
        agent_key="image", tool_name="edit_listing", raw_input={"slot": "title"}, run_id="r",
        trace_id="t", user_id="u", tool_call_id="r:0", budget_left=100,
    )
    assert res.error is not None and res.error.code == "tool_not_allowed" and res.cost == 0


def test_tool_runner_validates_input_and_budget(api: Api) -> None:
    from app.runtime.tool_runner import ToolRunner

    runner = ToolRunner(api.c.registry, api.c.gateway, api.c.store)
    common = {"agent_key": "amazon_pdp", "run_id": "r", "trace_id": "t", "user_id": "u",
                  "tool_call_id": "r:0"}
    bad = runner.call(tool_name="edit_listing", raw_input={}, budget_left=100, **common)
    assert bad.error is not None and bad.error.code == "invalid_input"
    broke = runner.call(tool_name="edit_listing", raw_input={"slot": "title"}, budget_left=1,
                        **common)
    assert broke.error is not None and broke.error.code == "budget_exceeded"


def _out(slot: str, region: NormRect | None) -> ImageOutput:
    return ImageOutput(slot=slot, object_key="k", width=1, height=1, changed_region=region,
                       params={})


def test_write_scope_guard_blocks_out_of_scope_slot_and_region() -> None:
    reg = {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}
    WriteScopeGuard.check(_out("image", NormRect(**reg)), {"image"}, reg)
    with pytest.raises(ScopeViolation):
        WriteScopeGuard.check(_out("title", None), {"image"}, None)
    with pytest.raises(ScopeViolation):
        WriteScopeGuard.check(_out("image", NormRect(x=0, y=0, w=1, h=1)), {"image"}, reg)


def test_slots_come_from_the_registry(api: Api) -> None:
    slots = {s["key"] for s in api.http.get("/api/slots").json()}
    assert {"title", "bullets", "description", "main_image", "image"} <= slots
    agents = {a["key"]: a for a in api.http.get("/api/agents").json()}
    assert agents["general"]["workbench"] == "general" and agents["image"]["task_kind"] == "image"


def test_upload_rejects_non_images(api: Api) -> None:
    r = api.http.post("/api/uploads", files={"file": ("a.png", b"not an image", "image/png")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "BAD_IMAGE"


def test_generated_docs_are_up_to_date() -> None:
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "gen_docs.py"
    r = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, f"run `python scripts/gen_docs.py`: {r.stdout}{r.stderr}"
