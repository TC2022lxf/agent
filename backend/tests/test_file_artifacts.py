"""File versions from the general agent, and the preview payload they carry."""

from __future__ import annotations

import pytest

from app.tools.base import ToolContext, ToolError
from app.tools.file_tools import ReadFileInput, ReadFileTool, WriteFileInput, WriteFileTool
from tests.conftest import Api


def test_general_owns_file_tools_without_copying_them(api: Api) -> None:
    agents = {a["key"]: a for a in api.http.get("/api/agents").json()}
    assert "write_file" in agents["general"]["tool_names"]
    assert "read_file" in agents["general"]["tool_names"]
    assert "file" in agents["general"]["artifact_kinds"]
    assert "write_file" not in agents["amazon_pdp"]["tool_names"]
    assert "write_file" not in agents["image"]["tool_names"]


def test_html_write_is_a_new_version_and_a_revision_does_not_overwrite(api: Api) -> None:
    task = api.task("general", kind="file", goal="活动页")
    run = api.say(task["id"], "写一个商品营销活动倒计时 HTML 页面")
    assert run["status"] == "succeeded"
    versions = api.slot_versions(task["id"], "page.html")
    assert len(versions) == 1
    body = versions[0]["content"]
    assert body["media"] == "html"
    assert body["filename"] == "page.html"
    assert "<h1>活动页</h1>" in body["text"]
    assert versions[0]["status"] == "ok"

    api.say(task["id"], "把标题改成夏季促销")
    versions = api.slot_versions(task["id"], "page.html")
    assert len(versions) == 2
    assert versions[0]["content"]["text"] == body["text"]
    assert versions[1]["parent_version_id"] == versions[0]["id"]
    assert "夏季促销" in versions[1]["content"]["text"]
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    files = [a for a in arts if a["kind"] == "file"]
    assert len(files) == 1
    assert files[0]["current_version_id"] == versions[1]["id"]

    api.say(task["id"], "输出剃须刀参数对比表格")
    assert len(api.slot_versions(task["id"], "page.html")) == 2
    csv = api.slot_versions(task["id"], "table.csv")
    assert len(csv) == 1 and csv[0]["content"]["media"] == "table"


def test_table_and_markdown_media(api: Api) -> None:
    table = api.task("general", kind="file", goal="对比")
    api.say(table["id"], "输出剃须刀参数对比表格")
    csv = api.slot_versions(table["id"], "table.csv")[0]["content"]
    assert csv["media"] == "table"
    assert csv["text"].startswith("item,note")

    notes = api.task("general", kind="file", goal="说明")
    api.say(notes["id"], "写一份 markdown 卖点说明")
    md = api.slot_versions(notes["id"], "notes.md")[0]["content"]
    assert md["media"] == "markdown"
    assert md["text"].startswith("# 笔记")


def test_bad_write_does_not_create_a_version() -> None:
    tool = WriteFileTool()
    ctx = ToolContext("r", "t", "u", None, None)  # type: ignore[arg-type]
    with pytest.raises(ToolError, match="empty_file"):
        tool.execute(WriteFileInput(path="page.html", content="  "), ctx)
    with pytest.raises(ToolError, match="binary_file"):
        tool.execute(WriteFileInput(path="poster.pdf", content="not a pdf"), ctx)
    with pytest.raises(ToolError, match="bad_path"):
        tool.execute(WriteFileInput(path="../secret.html", content="<p>x</p>"), ctx)


def test_read_file_returns_text_and_does_not_write(api: Api) -> None:
    assert ReadFileTool.meta.writes_version is False
    task = api.task("general", kind="file", goal="笔记")
    api.say(task["id"], "写一份 markdown 说明")
    current = api.slot_versions(task["id"], "notes.md")[0]
    ctx = ToolContext(
        "r", "t", "u", api.c.gateway, api.c.store, extras={"text": current["content"]["text"]},
    )
    out = ReadFileTool().execute(ReadFileInput(path="notes.md"), ctx)
    assert out.content["text"] == current["content"]["text"]  # type: ignore[attr-defined]
    assert len(api.slot_versions(task["id"], "notes.md")) == 1


def test_image_agent_cannot_write_a_file(api: Api) -> None:
    from app.runtime.tool_runner import ToolRunner

    runner = ToolRunner(api.c.registry, api.c.gateway, api.c.store)
    res = runner.call(
        agent_key="image", tool_name="write_file",
        raw_input={"path": "page.html", "content": "<p>x</p>"},
        run_id="r", trace_id="t", user_id="u", tool_call_id="r:write_file:page.html",
        budget_left=10,
    )
    assert res.error is not None
    assert res.error.code == "tool_not_allowed"
