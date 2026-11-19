"""Context compaction (docs/architecture/agent-runtime.md, docs/architecture/data-and-contracts.md).

What is pinned here is the contract that was broken before:

- the planner sees assistant turns and artifacts, not only the user's sentences;
- a compaction produces a summary that later turns actually read;
- the trigger is a fraction of the model's own window, so a 1M model compacts later than a
  10k one with the same history;
- compaction never fails the run and never changes a Version.
"""

from __future__ import annotations

from typing import Any

from app.runtime.context import (
    build_turn_lines,
    estimate_tokens,
    prior_messages,
    should_compact,
    summary_source,
)
from tests.conftest import Api

SLOTS = {"target_slot": "title"}


def _small_keep(api: Api, keep: int) -> None:
    """The default keep is 20 turns; tests use a short history, so lower it."""
    with api.c.uow_factory() as uow:
        uow.console.put("summary.keep_messages", str(keep))
        uow.commit()


def _make_turns(api: Api, task_id: str, count: int, text: str = "再改一下标题") -> None:
    for i in range(count):
        api.say(task_id, f"{text} {i}", **SLOTS)


def test_prior_context_includes_what_the_agent_said_and_produced(api: Api) -> None:
    """Only user sentences used to reach the planner; the agent's reply was lost."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题", target_slot="title")
    with api.c.uow_factory() as uow:
        t = uow.collab.get_task(task["id"])
        lines = build_turn_lines(uow, t)
    assert lines, "no turn captured"
    assert lines[0].user
    assert lines[0].versions, "the Version produced in this turn is missing"
    assert "title" in lines[0].versions[0] or "标题" in lines[0].versions[0]


def test_compaction_writes_a_summary_the_next_turn_reads(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    _small_keep(api, keep=2)
    _make_turns(api, task["id"], 4)
    r = api.http.post(f"/api/tasks/{task['id']}/compact")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["summary_id"]
    assert body["versions_unchanged"] is True

    with api.c.uow_factory() as uow:
        t = uow.collab.get_task(task["id"])
        messages, summary_id = prior_messages(uow, t, exclude_run_id="no-such-run")
    assert summary_id == body["summary_id"]
    assert messages[0].startswith("此前对话摘要")
    # The newest `keep` turns stay verbatim after the summary.
    assert len(messages) == 1 + 2


def test_manual_compaction_keeps_the_recent_turns_verbatim(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    _small_keep(api, keep=2)
    _make_turns(api, task["id"], 6)
    with api.c.uow_factory() as uow:
        t = uow.collab.get_task(task["id"])
        source, watermark, turns = summary_source(uow, t, keep=2)
        total = len(build_turn_lines(uow, t))
    assert total == 6
    assert turns == 4
    assert watermark
    assert "再改一下标题" in source


def test_trigger_scales_with_the_model_window(api: Api) -> None:
    """Same history, different window: a small window compacts, a huge one does not."""
    task = api.task("amazon_pdp", goal="剃须刀")
    _make_turns(api, task["id"], 4)
    with api.c.uow_factory() as uow:
        t = uow.collab.get_task(task["id"])
        small = should_compact(uow, t, fraction=0.7, keep=1, window=60)
        large = should_compact(uow, t, fraction=0.7, keep=1, window=1_000_000)
    assert small is True
    assert large is False


def test_compaction_does_nothing_when_history_is_shorter_than_keep(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    _small_keep(api, keep=5)
    api.say(task["id"], "写标题", target_slot="title")
    r = api.http.post(f"/api/tasks/{task['id']}/compact")
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"


def test_auto_compaction_runs_inside_a_turn_and_records_it(api: Api) -> None:
    """The trigger is checked by the executor, not only by the manual endpoint."""
    task = api.task("amazon_pdp", goal="剃须刀")
    _small_keep(api, keep=1)
    _make_turns(api, task["id"], 5)
    with api.c.uow_factory() as uow:
        uow.console.put("summary.fraction", "0.000001")
        uow.commit()
    run = api.say(task["id"], "再改一下标题", **SLOTS)
    assert run["status"] == "succeeded"
    assert "compact" in (run.get("path") or []), "the run did not record the compaction step"
    with api.c.uow_factory() as uow:
        summary = uow.collab.latest_summary(task["id"])
    assert summary is not None, "auto compaction never wrote a summary"
    assert summary.trigger == "auto"
    assert summary.covered_run_id


def test_a_failing_summary_does_not_fail_the_run(api: Api) -> None:
    """Compaction is an optimisation; losing it must not cost the user a turn."""
    task = api.task("amazon_pdp", goal="剃须刀")
    _small_keep(api, keep=1)
    _make_turns(api, task["id"], 3)
    with api.c.uow_factory() as uow:
        uow.console.put("summary.fraction", "0.000001")
        uow.commit()

    original = api.c.gateway.chat_json

    def boom(alias: str, system: str, user: str, **kw: Any):  # type: ignore[no-untyped-def]
        if kw.get("purpose") == "summary":
            raise RuntimeError("vendor down")
        return original(alias, system, user, **kw)

    api.c.gateway.chat_json = boom  # type: ignore[method-assign,assignment]
    run = api.say(task["id"], "再改一下标题", **SLOTS)
    api.c.gateway.chat_json = original  # type: ignore[method-assign,assignment]
    assert run["status"] == "succeeded"


def test_token_estimate_is_three_characters_per_token() -> None:
    assert estimate_tokens("abcdef") == 2
    assert estimate_tokens("") == 1
