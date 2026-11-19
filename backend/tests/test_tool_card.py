"""The Tool execution card exists while the Tool runs (docs/06).

A Tool's durable record is written only after it returns, so a 180s image had no presence in
the chat until it was already over: the thread showed one frozen sentence, and a working call
looked exactly like a hung one. `tool_started` is written before the call, keyed by the same
`tool_call_id` the record uses, so the UI can draw one card that later fills in its result.
"""

from __future__ import annotations

import pytest

from tests.conftest import Api


def _events(api: Api, run_id: str) -> list[dict[str, object]]:
    return [
        {"type": e.type, "data": e.data}
        for e in api.c.uow_factory().collab.events_after(run_id, 0)
    ]


def test_a_tool_call_is_announced_before_its_record_exists(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    assert run["status"] == "succeeded"

    events = _events(api, run["id"])
    started = [e for e in events if e["type"] == "tool_started"]
    assert started, "no tool_started event was written"
    payload = started[0]["data"]
    assert isinstance(payload, dict)
    assert payload["tool"] == "edit_listing"
    assert payload["slot"] == "title"
    assert payload["tool_call_id"], "the card cannot be matched to its record without an id"
    assert payload["cost"] > 0, "the card should say what the call costs"

    # The announcement comes BEFORE the call that produced the version.
    names = [e["type"] for e in events]
    assert names.index("tool_started") < names.index("version_created")


def test_the_announcement_and_the_record_share_one_id(api: Api) -> None:
    """One card per call: the id the timeline exposes must match the announced one."""
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")

    started = [
        e["data"]["tool_call_id"]  # type: ignore[index]
        for e in _events(api, run["id"])
        if e["type"] == "tool_started"
    ]
    steps = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[0]["steps"]
    recorded = [s["tool_call_id"] for s in steps]
    assert started == recorded


def test_timeline_exposes_what_the_card_needs(api: Api) -> None:
    """A card is only useful if it can show the arguments and the produced version."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题")

    steps = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[0]["steps"]
    step = next(s for s in steps if s["tool"] == "edit_listing")
    assert step["tool_call_id"]
    assert step["input"]["slot"] == "title"
    assert step["output"]["version_id"], "the card should name the Version it produced"


def test_arguments_are_trimmed_for_the_card(api: Api) -> None:
    """A long body is not shipped to the UI whole; the head and a count are enough."""
    task = api.task("general", kind="general", goal="写文件")
    long_text = "A" * 1200
    api.say(task["id"], f"写一个 notes.md，内容是 {long_text}")

    steps = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[0]["steps"]
    assert steps, "the run produced no tool call"
    for s in steps:
        for value in (s.get("input") or {}).values():
            if isinstance(value, str):
                assert len(value) < 1200, "an untrimmed body was sent to the UI"


def test_announcing_the_same_call_twice_writes_one_event(api: Api) -> None:
    """LangGraph may re-enter a step after a worker restart; the card must not duplicate.

    The guard lives in the writer, so it is tested there: two announcements for one
    `tool_call_id` must leave exactly one `tool_started` row.
    """
    from app.infrastructure.gateway_logging import current_run_id
    from app.runtime.langgraph_loop import _tool_start_writer

    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")

    writer = _tool_start_writer(api.c.uow_factory)
    token = current_run_id.set(run["id"])
    try:
        payload = {
            "tool_call_id": f"{run['id']}:edit_listing:title",
            "tool": "edit_listing", "slot": "title", "cost": 5, "args": {"slot": "title"},
        }
        writer(payload)
        writer(payload)
    finally:
        current_run_id.reset(token)

    started = [e for e in _events(api, run["id"]) if e["type"] == "tool_started"]
    matching = [e for e in started if e["data"]["tool_call_id"] == payload["tool_call_id"]]  # type: ignore[index]
    assert len(matching) == 1


@pytest.mark.parametrize("text", ["写标题", "把标题改短一点"])
def test_every_writing_turn_announces_its_call(api: Api, text: str) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题")
    run = api.say(task["id"], text)
    started = [e for e in _events(api, run["id"]) if e["type"] == "tool_started"]
    assert started, f"no card was announced for {text!r}"


def test_ask_question_is_not_announced_as_a_card(api: Api) -> None:
    """A question has its own interactive panel; announcing it would draw the same text twice.

    `ask_question` is handled before the generic tool path in `_Session._handle`, so it never
    reaches `_announce_tool`. This pins that: the panel is the only surface for a question.
    """
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    run = api.say(task["id"], "太普通了，高级一点")
    events = _events(api, run["id"])
    assert [e for e in events if e["type"] == "human_input_request"], "no question was asked"
    started = [e for e in events if e["type"] == "tool_started"]
    assert all(e["data"]["tool"] != "ask_question" for e in started), (  # type: ignore[index]
        "ask_question should not get a tool card"
    )
