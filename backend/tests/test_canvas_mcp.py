"""Canvas over MCP (decisions/0030): an external agent reads and writes the same board.

The point is not that the tools exist, it is that a write from outside obeys the rules the UI
obeys: a new Version, never an overwrite, a stale read refused, and the write boundary checked.
The tests call the registered tools, so the schema/description wiring is covered too.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.mcp.canvas_server import build_server
from tests.conftest import Api


def call(server: Any, name: str, **args: Any) -> dict[str, Any]:
    """Invoke a registered MCP tool the way a client would, and unwrap its JSON content.

    A refused tool raises `ToolError` whose message is exactly what a model sees (the SDK's
    own layer does the same over the wire), so the tests assert on that text.
    """
    import json

    try:
        result = asyncio.run(server.call_tool(name, args))
    except Exception as e:  # ToolError from the SDK wrapper
        return {"text": str(e), "error": str(e)}
    blocks = getattr(result, "content", None)
    if blocks is None:
        blocks = result[0]
    text = blocks[0].text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"text": text, "error": text}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def refused(result: dict[str, Any], code: str) -> bool:
    """Did the tool refuse with `code`? The SDK prefixes the message, so match inside it."""
    return code in str(result.get("text", "")) or code in str(result.get("error", ""))


class Mcp:
    def __init__(self, api: Api) -> None:
        self.server = build_server(api.c)

    def __call__(self, name: str, **args: Any) -> dict[str, Any]:
        return call(self.server, name, **args)


def test_the_five_tools_are_registered_with_descriptions(api: Api) -> None:
    names = {t.name for t in asyncio.run(build_server(api.c).list_tools())}
    assert names == {
        "canvas_list_tasks", "canvas_get_state", "canvas_get_images",
        "canvas_apply_ops", "canvas_compose",
    }
    for tool in asyncio.run(build_server(api.c).list_tools()):
        assert (tool.description or "").strip(), tool.name


def test_an_agent_sees_the_board_and_a_picture_prompt(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    mcp = Mcp(api)

    state = mcp("canvas_get_state", task_id=task["id"])
    assert state["version_id"]
    assert [s["id"] for s in state["screens"]] == ["s1"]
    assert state["theme"]["colors"]["bg"] == "#FFFFFF"
    (module,) = state["screens"][0]["modules"]
    assert module["kind"] == "image"
    assert module["prompt"] == "一张深色极简的咖啡店海报"

    # The picture is reported with its prompt and a URL, so the agent can look at it.
    images = mcp("canvas_get_images", task_id=task["id"])["images"]
    assert len(images) == 1
    assert images[0]["module_id"] == module["id"]
    assert images[0]["prompt"] == "一张深色极简的咖啡店海报"
    assert images[0]["url"]


def test_listing_tasks_only_shows_ones_that_can_hold_a_canvas(api: Api) -> None:
    canvas = api.task("canvas")
    api.task("amazon_pdp")
    rows = Mcp(api)("canvas_list_tasks")["tasks"]
    assert [r["task_id"] for r in rows] == [canvas["id"]]
    assert rows[0]["has_canvas"] is False  # nothing written yet

    api.say(canvas["id"], "一张深色极简的咖啡店海报")
    rows = Mcp(api)("canvas_list_tasks")["tasks"]
    assert rows[0]["has_canvas"] is True
    assert rows[0]["screens"] == 1


def test_an_external_write_makes_a_new_version_by_the_agent(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    mcp = Mcp(api)
    before = mcp("canvas_get_state", task_id=task["id"])
    credits = api.http.get("/api/me").json()["credits"]
    module_id = before["screens"][0]["modules"][0]["id"]

    made = mcp(
        "canvas_apply_ops",
        task_id=task["id"],
        base_version_id=before["version_id"],
        ops=[
            {"op": "set_prompt", "screen": "s1", "id": module_id, "prompt": "深色，居中，无文字"},
        ],
    )
    assert made["seq"] == before["seq"] + 1

    after = mcp("canvas_get_state", task_id=task["id"])
    assert after["version_id"] == made["version_id"]
    modules = {m["id"]: m for m in after["screens"][0]["modules"]}
    assert modules[module_id]["prompt"] == "深色，居中，无文字"
    # The old version still opens: this is a version, not an overwrite.
    old = api.http.get(f"/api/versions/{before['version_id']}").json()
    assert old["status"] == "ok"
    # And it is attributed to the agent, not to the user.
    latest = api.http.get(f"/api/versions/{made['version_id']}").json()
    assert latest["created_by"] == "agent"
    # No Run was created and nothing was charged: an MCP write is a gesture, not a turn.
    assert len(api.http.get(f"/api/tasks/{task['id']}/timeline").json()) == 1
    assert api.http.get("/api/me").json()["credits"] == credits


def test_a_stale_read_is_refused_and_changes_nothing(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    mcp = Mcp(api)
    first = mcp("canvas_get_state", task_id=task["id"])

    mcp("canvas_apply_ops", task_id=task["id"], base_version_id=first["version_id"],
        ops=[{"op": "move_module", "screen": "s1", "id": "m1", "dx": 0.05, "dy": 0}])
    again = mcp("canvas_apply_ops", task_id=task["id"], base_version_id=first["version_id"],
                ops=[{"op": "move_module", "screen": "s1", "id": "m1", "dx": 0.05, "dy": 0}])
    assert refused(again, "STALE_CANVAS")

    state = mcp("canvas_get_state", task_id=task["id"])
    assert state["version_id"] != first["version_id"]


def test_bad_ops_and_an_empty_board_are_explained(api: Api) -> None:
    task = api.task("canvas")
    mcp = Mcp(api)
    empty = mcp("canvas_apply_ops", task_id=task["id"],
                ops=[{"op": "move_module", "id": "m1", "dx": 0.1, "dy": 0}])
    assert refused(empty, "EMPTY_CANVAS")

    api.say(task["id"], "一张深色极简的咖啡店海报")
    state = mcp("canvas_get_state", task_id=task["id"])
    bad = mcp("canvas_apply_ops", task_id=task["id"], base_version_id=state["version_id"],
              ops=[{"op": "set_text", "id": "nope", "text": "x"}])
    assert refused(bad, "BAD_CANVAS")
    assert mcp("canvas_get_state", task_id=task["id"])["version_id"] == state["version_id"]


def test_a_picture_module_refuses_text_style_over_mcp(api: Api) -> None:
    """A picture has no colour of its own; saying so beats silently ignoring the request."""
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    mcp = Mcp(api)
    state = mcp("canvas_get_state", task_id=task["id"])
    module_id = state["screens"][0]["modules"][0]["id"]

    refused_write = mcp(
        "canvas_apply_ops", task_id=task["id"], base_version_id=state["version_id"],
        ops=[{"op": "set_style", "screen": "s1", "id": module_id, "style": {"color": "accent"}}],
    )
    assert refused(refused_write, "图片模块")
    # A refused write changes nothing.
    assert mcp("canvas_get_state", task_id=task["id"])["version_id"] == state["version_id"]

    allowed = mcp(
        "canvas_apply_ops", task_id=task["id"], base_version_id=state["version_id"],
        ops=[{"op": "set_style", "screen": "s1", "id": module_id, "style": {"fit": "cover"}}],
    )
    assert allowed["version_id"]
    after = mcp("canvas_get_state", task_id=task["id"])
    assert after["screens"][0]["modules"][0]["style"]["fit"] == "cover"


def test_theme_tokens_are_enforced_for_text_modules(api: Api) -> None:
    """A raw hex from an external agent is refused: the theme owns colour."""
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    mcp = Mcp(api)
    state = mcp("canvas_get_state", task_id=task["id"])
    screen_id = state["screens"][0]["id"]

    # Give the board a text module, then try to set a raw hex on it.
    made = mcp(
        "canvas_apply_ops", task_id=task["id"], base_version_id=state["version_id"],
        ops=[{"op": "add_module", "screen": screen_id, "module": {
            "id": "t1", "kind": "text", "name": "标题",
            "rect": {"x": 0.06, "y": 0.06, "w": 0.4, "h": 0.12},
            "style": {"size": 32, "weight": 600, "align": "left",
                      "color": "fg", "font": "display"},
            "text": "深夜咖啡",
        }}],
    )
    assert made["version_id"]

    refused_write = mcp(
        "canvas_apply_ops", task_id=task["id"], base_version_id=made["version_id"],
        ops=[{"op": "set_style", "screen": screen_id, "id": "t1", "style": {"color": "#ff0000"}}],
    )
    assert refused(refused_write, "主题令牌")


def test_an_agent_can_compose_a_whole_board(api: Api) -> None:
    task = api.task("canvas")
    mcp = Mcp(api)
    board = {
        "theme": {"colors": {"bg": "#FFFFFF", "fg": "#111111"}, "fonts": {"body": "Inter"}},
        "screens": [
            {"id": "s1", "name": "首屏", "pos": {"x": 0, "y": 0},
             "frame": {"width": 1200, "height": 500},
             "modules": [{"id": "a", "kind": "text", "name": "标题",
                          "rect": {"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.2},
                          "style": {"size": 40, "weight": 600, "align": "left",
                                    "color": "fg", "font": "body"},
                          "text": "外部 Agent 起草"}],
             },
        ],
        "edges": [],
    }
    made = mcp("canvas_compose", task_id=task["id"], content=board)
    assert made["version_id"]
    state = mcp("canvas_get_state", task_id=task["id"])
    assert state["screens"][0]["name"] == "首屏"
    assert state["screens"][0]["modules"][0]["text"] == "外部 Agent 起草"
