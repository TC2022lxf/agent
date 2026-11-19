"""Web search and fetch belong to the general agent and do not write a Version."""

from __future__ import annotations

import pytest

from app.tools.base import ToolContext, ToolError
from app.tools.web_tools import (
    WebFetchInput,
    WebFetchTool,
    WebSearchInput,
    WebSearchTool,
    public_http_url,
)
from tests.conftest import Api


def _tools(api: Api, run_id: str) -> list:
    with api.c.uow_factory() as uow:
        return list(uow.collab.tool_calls(run_id))


def test_only_the_general_agent_may_search(api: Api) -> None:
    agents = {a["key"]: a for a in api.http.get("/api/agents").json()}
    assert {"web_search", "web_fetch"} <= set(agents["general"]["tool_names"])
    for key in ("amazon_pdp", "image", "canvas"):
        assert "web_search" not in agents[key]["tool_names"]
        assert "web_fetch" not in agents[key]["tool_names"]


def test_search_answers_without_creating_an_artifact(api: Api) -> None:
    task = api.task("general", kind="general", goal="调研")
    run = api.say(task["id"], "搜索一下 DMXAPI 是什么")
    assert run["status"] == "succeeded"
    calls = _tools(api, run["id"])
    assert [c.tool_name for c in calls] == ["web_search"]
    assert calls[0].status == "ok"
    assert calls[0].cost == 1
    results = calls[0].output["content"]["results"]
    assert results[0]["url"] == "https://example.com/dmxapi"
    assert "content" not in results[0]
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    assert arts == []


def test_a_keyword_request_is_still_a_listing_slot(api: Api) -> None:
    """「关键词」is a PDP slot. It must not be read as a web search."""
    task = api.task("general", kind="general", goal="PDP")
    run = api.say(task["id"], "写关键词")
    assert [c.tool_name for c in _tools(api, run["id"])] == ["edit_listing"]
    assert len(api.slot_versions(task["id"], "search_terms")) == 1


def test_fetch_returns_markdown_and_truncates(api: Api) -> None:
    task = api.task("general", kind="general", goal="读文档")
    run = api.say(task["id"], "抓取网页 https://example.com/docs")
    calls = _tools(api, run["id"])
    assert [c.tool_name for c in calls] == ["web_fetch"]
    body = calls[0].output["content"]
    assert body["url"] == "https://example.com/docs"
    assert body["truncated"] is True
    assert body["content"].endswith("…（已截断）")
    assert len(body["content"]) < 9000


def test_need_content_is_truncated() -> None:
    tool = WebSearchTool()
    ctx = ToolContext("r", "t", "u", _Gateway(), None)  # type: ignore[arg-type]
    out = tool.execute(WebSearchInput(query="DMXAPI", need_content=True), ctx)
    content = out.content["results"][0]["content"]  # type: ignore[attr-defined]
    assert content.endswith("…（已截断）")
    assert len(content) < 3000


def test_internal_and_credentialed_urls_are_refused() -> None:
    tool = WebFetchTool()
    ctx = ToolContext("r", "t", "u", _Gateway(), None)  # type: ignore[arg-type]
    for url in (
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5/secret",
        "http://localhost/x",
        "https://user:pass@example.com/a",
        "file:///etc/passwd",
    ):
        with pytest.raises(ToolError):
            tool.execute(WebFetchInput(url=url), ctx)
    assert public_http_url("https://example.com/a") == "https://example.com/a"


def test_image_agent_cannot_search(api: Api) -> None:
    from app.runtime.tool_runner import ToolRunner

    runner = ToolRunner(api.c.registry, api.c.gateway, api.c.store)
    res = runner.call(
        agent_key="image", tool_name="web_search",
        raw_input={"query": "DMXAPI"},
        run_id="r", trace_id="t", user_id="u", tool_call_id="r:web_search:x",
        budget_left=10,
    )
    assert res.error is not None
    assert res.error.code == "tool_not_allowed"


class _Gateway:
    def web_search(self, query: str, *, count: int = 5, need_content: bool = False,
                   ori_question: str | None = None) -> dict:
        del query, count, ori_question
        return {
            "results": [{
                "title": "t", "url": "https://example.com", "snippet": "s",
                "content": "c" * 5000 if need_content else "",
            }]
        }

    def web_fetch(self, url: str) -> dict:
        del url
        return {"title": "t", "content": "body"}
