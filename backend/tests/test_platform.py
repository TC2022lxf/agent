"""Run mechanics (202, idempotency, SSE, credits) and preferences."""

from __future__ import annotations

from tests.conftest import Api


def _post(api: Api, task_id: str, key: str, text: str = "第一版"):  # type: ignore[no-untyped-def]
    return api.http.post(
        f"/api/tasks/{task_id}/utterances", json={"text": text}, headers={"Idempotency-Key": key}
    )


def test_utterance_returns_202_queued_and_does_not_run_inline(api: Api) -> None:
    t = api.task()
    r = _post(api, t["id"], "a")
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert api.task_state(t["id"])["status"] == "running"
    assert api.slot_versions(t["id"], "title") == []  # nothing executed yet
    api.c.worker.drain()
    assert len(api.slot_versions(t["id"], "title")) == 1


def test_idempotency_key_required_and_deduplicates(api: Api) -> None:
    t = api.task()
    assert api.http.post(f"/api/tasks/{t['id']}/utterances", json={"text": "x"}).status_code == 400
    a, b = _post(api, t["id"], "same"), _post(api, t["id"], "same")
    assert a.json()["id"] == b.json()["id"]
    api.c.worker.drain()
    assert len(api.slot_versions(t["id"], "title")) == 1


def test_second_run_on_active_task_conflicts(api: Api) -> None:
    t = api.task()
    assert _post(api, t["id"], "a").status_code == 202
    assert _post(api, t["id"], "b").status_code == 409


def test_credits_are_held_then_settled_through_the_ledger(api: Api) -> None:
    t = api.task()
    assert api.http.get("/api/me").json()["credits"] == 1000
    # The ceiling is per Task kind, not one global number (docs/11 section 3).
    budget = api.http.get("/api/billing/pricing").json()["budgets"]["pdp"]
    assert budget > 0
    r = _post(api, t["id"], "a")
    frozen = api.http.get("/api/me").json()
    assert frozen["credits"] == 1000 - budget  # frozen at creation
    assert frozen["held"] == budget
    api.c.worker.drain()
    run = api.http.get(f"/api/runs/{r.json()['id']}").json()
    assert run["cost"] == 20  # four text slots, one edit_listing call each x 5
    assert run["held"] == budget and run["overrun"] == 0
    after = api.http.get("/api/me").json()
    assert after["credits"] == 1000 - 20  # only the real cost was kept
    assert after["held"] == 0
    rows = api.http.get("/api/me/credits").json()
    # Append-only, and the unused part of the hold came back in the same settle row.
    assert [e["kind"] for e in rows][0] == "settle"
    assert sorted({e["kind"] for e in rows}) == ["grant", "hold", "settle"]
    assert sum(e["delta"] for e in rows) == 1000 - 20
    assert rows[0]["balance_after"] == 1000 - 20  # cached balance matches the ledger


def test_settling_the_same_run_twice_does_not_charge_twice(api: Api) -> None:
    """A retried worker must not bill the user for work they already paid for."""
    t = api.task()
    r = _post(api, t["id"], "a")
    api.c.worker.drain()
    before = api.http.get("/api/me").json()["credits"]
    run = api.http.get(f"/api/runs/{r.json()['id']}").json()
    with api.c.uow_factory() as uow:
        again = uow.credits.settle("dev-user", run["id"], run["held"], run["cost"])
        uow.commit()
    assert again.charged == run["cost"]
    assert api.http.get("/api/me").json()["credits"] == before


def test_a_platform_fault_refunds_the_whole_hold(api: Api) -> None:
    """Vendor timeout or a crash is our side: the user keeps their credits (docs/11)."""
    t = api.task()
    r = _post(api, t["id"], "a")
    run_id = r.json()["id"]
    before = api.http.get("/api/me").json()["credits"]
    api.c.executor._finish(run_id, "failed", error="模型服务响应超时", platform_fault=True)
    after = api.http.get("/api/me").json()
    assert after["credits"] == before + 120  # the pdp hold came back in full
    assert after["held"] == 0
    assert api.http.get(f"/api/runs/{run_id}").json()["cost"] == 0


def test_cancel_queued_run_returns_hold(api: Api) -> None:
    t = api.task()
    r = _post(api, t["id"], "a")
    assert api.http.post(f"/api/runs/{r.json()['id']}/cancel").json()["status"] == "cancelled"
    assert api.http.get("/api/me").json()["credits"] == 1000
    assert api.c.worker.drain() == 0


def test_insufficient_credits_returns_402_and_creates_no_run(api: Api) -> None:
    # a tiny balance is enough to make the hold fail
    with api.c.uow_factory() as uow:
        uow.credits.ensure_user("poor", 10)
        uow.commit()
    t = api.http.post(
        "/api/tasks", json={"agent_id": "amazon_pdp"}, headers={"X-User-Id": "poor"}
    ).json()
    r = api.http.post(
        f"/api/tasks/{t['id']}/utterances",
        json={"text": "x"},
        headers={"Idempotency-Key": "k", "X-User-Id": "poor"},
    )
    assert r.status_code == 402 and r.json()["error"]["code"] == "INSUFFICIENT_CREDITS"
    assert api.c.worker.drain() == 0


def test_sse_streams_events_to_terminal_state(api: Api) -> None:
    t = api.task()
    r = _post(api, t["id"], "a")
    api.c.worker.drain()
    with api.http.stream("GET", f"/api/runs/{r.json()['id']}/events") as s:
        body = "".join(s.iter_text())
    assert "event: run_started" in body and "event: version_created" in body
    assert body.rstrip().endswith("}") and "event: run_succeeded" in body
    ids = [int(line.split(": ")[1]) for line in body.splitlines() if line.startswith("id: ")]
    assert ids == sorted(ids)
    with api.http.stream(
        "GET", f"/api/runs/{r.json()['id']}/events", headers={"Last-Event-ID": str(ids[-1])}
    ) as s:
        assert "".join(s.iter_text()) == ""  # resume after the last event: nothing new


def test_run_records_actual_path_and_llm_calls(api: Api) -> None:
    t = api.task()
    run = api.say(t["id"], "第一版")
    assert run["path"][0] == "load_context" and "interpret" in run["path"]
    assert run["path"].count("tool:edit_listing") == 4
    from sqlalchemy import select

    from app.persistence.models import LlmCall

    with api.c.uow_factory() as uow:
        rows = list(uow._session.scalars(select(LlmCall).where(LlmCall.run_id == run["id"])))
    aliases = {r.alias for r in rows}
    # No `interpret` call: the one that used to route the sentence is gone (decisions/0044).
    # Only the planner and the tools' own model calls are billed.
    assert "listing_edit" in aliases and "interpret" not in aliases
    assert any(r.purpose == "plan" for r in rows)
    assert all(r.profile_key == "gpt-6.1-sol" for r in rows)


def test_users_cannot_read_each_others_tasks(api: Api) -> None:
    t = api.task()
    assert api.http.get(f"/api/tasks/{t['id']}", headers={"X-User-Id": "other"}).status_code == 404


# ---- preferences -------------------------------------------------------------
def test_preference_proposal_does_not_write_the_canonical_text(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "我喜欢简短有力的标题")
    pr = api.http.get("/api/agents/amazon_pdp/preferences/proposals").json()
    assert len(pr) == 1
    empty = api.http.get("/api/agents/amazon_pdp/preferences").json()
    assert empty == {"body_md": "", "revision": 0}
    api.http.post(f"/api/agents/amazon_pdp/preferences/proposals/{pr[0]['id']}/accept")
    cur = api.http.get("/api/agents/amazon_pdp/preferences").json()
    assert "简短有力" in cur["body_md"] and cur["revision"] == 1


def test_rejected_proposal_never_applies(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "我喜欢简短有力的标题")
    pr = api.http.get("/api/agents/amazon_pdp/preferences/proposals").json()[0]
    api.http.post(f"/api/agents/amazon_pdp/preferences/proposals/{pr['id']}/reject")
    assert api.http.get("/api/agents/amazon_pdp/preferences").json()["revision"] == 0


def test_next_run_reads_the_users_edited_preferences(api: Api) -> None:
    t = api.task()
    api.http.put("/api/agents/amazon_pdp/preferences", json={"body_md": "# 我\n- 少确认"})
    r1 = api.say(t["id"], "第一版")
    api.http.put("/api/agents/amazon_pdp/preferences", json={"body_md": "# 我\n- 多确认"})
    r2 = api.say(t["id"], "标题更突出防水")
    with api.c.uow_factory() as uow:
        revs = []
        for r in (r1, r2):
            ev = [e for e in uow.collab.events_after(r["id"], 0) if e.type == "context_loaded"]
            revs.append(ev[0].data["preferences_revision"])
    assert revs == [1, 2]


def test_progress_events_describe_each_phase(api: Api) -> None:
    """A waiting user needs to see the phase change, not one static line (docs/06)."""
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "第一版")
    with api.c.uow_factory() as uow:
        events = uow.collab.events_after(run["id"], 0)
    steps = [e.data for e in events if e.type == "step"]
    stages = [s.get("stage") for s in steps]
    assert "context" in stages, stages
    assert "tool" in stages, stages
    # The tool step names the tool so the UI can say "正在写文案" rather than "正在处理".
    assert any("edit_listing" in str(s.get("detail")) for s in steps), steps


def test_progress_does_not_change_the_recorded_path(api: Api) -> None:
    """`run.path` is the route a Run took and is asserted elsewhere; progress is a stream.

    Every `step` event must be derived from the path, never added to it: `think`/`running`
    fire before each plan and would otherwise duplicate path entries.
    """
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "第一版")
    assert "interpret" in run["path"]
    with api.c.uow_factory() as uow:
        events = uow.collab.events_after(run["id"], 0)
    steps = [e.data for e in events if e.type == "step"]
    # Progress-only stages never land in the path.
    assert "think" not in run["path"] and "running" not in run["path"], run["path"]
    # Path-derived stages and progress-only stages are both legal, and every step names one.
    from_path = {"context", "compact", "interpret", "resume", "dispatch", "tool", "work"}
    progress_only = {"think", "running"}
    assert steps, "no progress was reported"
    assert all(s.get("stage") in from_path | progress_only for s in steps), steps
    # The interesting part: the phases the user complained were missing actually appear.
    stages = [s.get("stage") for s in steps]
    # There is no "正在分析意图" moment any more: routing is a tool call inside the loop, so the
    # first thing the user sees is the model thinking (decisions/0044).
    assert "interpret" not in stages, "a separate interpret call came back"
    assert "running" in stages, "no '正在生成/正在写文案' moment"
    assert "think" in stages, "no '正在思考' moment while the model is called"


def test_a_queued_utterance_still_reports_queued_first(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    r = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "第一版"},
        headers={"Idempotency-Key": "progress-queued"},
    )
    assert r.status_code == 202
    with api.c.uow_factory() as uow:
        events = uow.collab.events_after(r.json()["id"], 0)
    assert events[0].type == "run_queued", [e.type for e in events]
    api.c.worker.drain()
    with api.c.uow_factory() as uow:
        events = uow.collab.events_after(r.json()["id"], 0)
    types = [e.type for e in events]
    assert "step" in types and "run_succeeded" in types, types
