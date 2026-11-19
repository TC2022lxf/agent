"""LangGraph loop: profiles, resume, summary, reasoning, image capability (plan L1-L4)."""

from __future__ import annotations

from sqlalchemy import select

from app.persistence.models import LlmCall
from app.runtime.langgraph_loop import StopAfter, stop_after
from tests.conftest import Api

REGION = {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}


def _calls(api: Api, run_id: str) -> list[LlmCall]:
    with api.c.uow_factory() as uow:
        return list(uow.collab.s.scalars(
            select(LlmCall).where(LlmCall.run_id == run_id).order_by(LlmCall.id)
        ))


def _prompt(api: Api, agent: str = "amazon_pdp") -> str:
    cfg = api.http.get("/api/admin/config").json()
    return next(a["system_prompt"] for a in cfg["agents"] if a["key"] == agent)


def test_unknown_model_string_saves_and_disabled_profile_does_not(api: Api) -> None:
    ok = api.http.put(
        "/api/admin/config/amazon_pdp",
        json={"model": "gpt-test", "system_prompt": _prompt(api)},
    )
    assert ok.status_code == 200
    created = api.http.put(
        "/api/admin/model-profiles/planner-b",
        json={"upstream_model": "planner-b", "kind": "planner", "context_window_tokens": 8000,
              "enabled": True},
    )
    assert created.status_code == 200
    api.http.put(
        "/api/admin/config/amazon_pdp",
        json={"model": "planner-b", "system_prompt": _prompt(api)},
    )
    api.http.put("/api/admin/model-profiles/planner-b", json={"enabled": False})
    denied = api.http.put(
        "/api/admin/config/amazon_pdp",
        json={"model": "planner-b", "system_prompt": _prompt(api)},
    )
    assert denied.status_code == 400
    run = api.say(api.task()["id"], "第一版")
    assert run["status"] == "failed" and "disabled" in (run["error"] or "")


def test_rebinding_changes_the_profile_on_the_next_run(api: Api) -> None:
    api.http.put(
        "/api/admin/model-profiles/planner-b",
        json={"upstream_model": "planner-b", "kind": "planner", "context_window_tokens": 8000,
              "reasoning": {"mode": "optional"}, "enabled": True},
    )
    saved = api.http.put(
        "/api/admin/config/amazon_pdp",
        json={"model": "planner-b", "system_prompt": _prompt(api)},
    )
    assert saved.status_code == 200
    run = api.say(api.task()["id"], "第一版")
    assert run["status"] == "succeeded"
    planned = [r for r in _calls(api, run["id"]) if r.purpose == "plan"]
    assert planned and all(r.profile_key == "planner-b" for r in planned)


def test_resume_does_not_create_a_second_version(api: Api) -> None:
    token = stop_after.set(StopAfter(2))
    try:
        task = api.task()
        run = api.say(task["id"], "第一版")
    finally:
        stop_after.reset(token)
    assert run["status"] == "succeeded"
    assert "first_draft" in run["path"]
    for slot in ("title", "bullets", "description", "search_terms"):
        assert len(api.slot_versions(task["id"], slot)) == 1
    with api.c.uow_factory() as uow:
        rows = uow.collab.tool_calls(run["id"])
        assert len(rows) == 4
        assert len({r.tool_call_id for r in rows}) == 4
        stored = uow.collab.get_run(run["id"])
        assert stored.resume_count == 1
        assert stored.skill_versions
        assert "preferences_revision" in (stored.context_refs or {})


def test_summary_runs_before_plan_when_the_window_is_full(api: Api) -> None:
    task = api.task()
    api.say(task["id"], "第一版")
    api.say(task["id"], "标题更突出")
    api.http.put("/api/admin/model-profiles/gpt-6.1-sol", json={"context_window_tokens": 64})
    api.http.put("/api/admin/runtime", json={"summary_keep": 1, "summary_fraction": 0.8})
    run = api.say(task["id"], "标题更突出防水")
    assert run["status"] == "succeeded"
    # Compaction happens in the executor before the planner reads history, so it is a path
    # step rather than a middleware call.
    assert "compact" in run["path"]
    rows = _calls(api, run["id"])
    summary = next(r for r in rows if r.purpose == "summary")
    plan = next(r for r in rows if r.purpose == "plan")
    assert summary.id < plan.id
    with api.c.uow_factory() as uow:
        stored = uow.collab.get_run(run["id"])
        assert stored.context_refs.get("summary_id")


def test_unsupported_reasoning_sends_no_thinking_fields(api: Api) -> None:
    api.http.put(
        "/api/admin/model-profiles/gpt-6.1-sol",
        json={
            "reasoning": {"mode": "unsupported"},
            "when_thinking_enabled": {"reasoning_effort": "high"},
        },
    )
    run = api.say(api.task()["id"], "第一版", reasoning=True)
    assert run["status"] == "succeeded"
    planned = [r for r in _calls(api, run["id"]) if r.purpose == "plan"]
    assert planned and all("reasoning_effort" not in (r.params or {}) for r in planned)
    assert all(r.reasoning is False for r in planned)


def test_optional_reasoning_is_logged_on_the_planner_only(api: Api) -> None:
    run = api.say(api.task()["id"], "第一版", reasoning=True)
    planned = [r for r in _calls(api, run["id"]) if r.purpose == "plan"]
    assert planned and all(r.params.get("reasoning_effort") == "medium" for r in planned)


def test_image_calls_do_not_receive_the_reasoning_switch(api: Api) -> None:
    up = api.upload_png()
    task = api.task("image", kind="image", upload_id=up)
    run = api.say(task["id"], "把背景换成浅灰", target_slot="image", reasoning=True)
    assert run["status"] == "succeeded"
    image_rows = [r for r in _calls(api, run["id"]) if r.purpose == "image"]
    assert image_rows and all("reasoning_effort" not in (r.params or {}) for r in image_rows)


def test_missing_image_edit_refuses_without_a_version(api: Api) -> None:
    api.http.put(
        "/api/admin/model-profiles/gemini-3.1-flash-image",
        json={"capabilities": ["image.generate"]},
    )
    up = api.upload_png()
    task = api.task("image", kind="image", upload_id=up)
    run = api.say(task["id"], "把这里改成蓝色", target_slot="image", target_region=REGION)
    assert run["status"] == "succeeded"
    versions = api.slot_versions(task["id"], "image")
    assert [v["origin"] for v in versions] == ["imported"]
    fb = api.http.get(f"/api/tasks/{task['id']}/feedback").json()[-1]
    assert fb["status"] == "declined" and "image.edit" in fb["note"]


def test_manual_compact_does_not_change_the_image(api: Api) -> None:
    up = api.upload_png()
    task = api.task("image", kind="image", upload_id=up)
    early = api.http.post(f"/api/tasks/{task['id']}/compact")
    assert early.status_code == 200 and early.json()["status"] == "skipped"
    api.say(task["id"], "把背景换成浅灰", target_slot="image")
    api.say(task["id"], "再亮一点", target_slot="image")
    # Keep fewer turns than the history, so there is something to compact.
    api.http.put("/api/admin/runtime", json={"summary_keep": 1})
    before = [v["id"] for v in api.slot_versions(task["id"], "image")]
    done = api.http.post(f"/api/tasks/{task['id']}/compact")
    assert done.status_code == 200
    body = done.json()
    assert body["status"] == "ok" and body["trigger"] == "manual" and body["versions_unchanged"]
    assert [v["id"] for v in api.slot_versions(task["id"], "image")] == before


def test_compact_while_a_run_is_queued_conflicts(api: Api) -> None:
    task = api.task()
    api.say(task["id"], "第一版")
    api.say(task["id"], "标题更突出防水")
    queued = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "再改一次标题"},
        headers={"Idempotency-Key": "still-queued"},
    )
    assert queued.status_code == 202
    busy = api.http.post(f"/api/tasks/{task['id']}/compact")
    assert busy.status_code == 409
    api.c.worker.drain()
