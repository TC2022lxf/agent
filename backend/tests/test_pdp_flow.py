"""Acceptance themes from docs/10: feedback -> new Version, slots not overwritten,
hard constraints block, constraint confirm flow, imported baseline."""

from __future__ import annotations

from tests.conftest import Api


def test_first_run_creates_text_slot_versions_and_a_pdp_version(api: Api) -> None:
    t = api.task()
    run = api.say(t["id"], "帮我做第一版")
    assert run["status"] == "succeeded"
    assert "first_draft" in run["path"]
    state = api.task_state(t["id"])
    assert state["status"] == "awaiting_user"
    for slot in ("title", "bullets", "description"):
        assert len(api.slot_versions(t["id"], slot)) == 1
    assert state["current"]["main_image"] is None
    assert state["pdp_version_id"]


def test_feedback_creates_new_version_and_does_not_touch_other_slots(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    before = api.task_state(t["id"])
    run = api.say(t["id"], "标题更突出防水")
    assert run["status"] == "succeeded"
    titles = api.slot_versions(t["id"], "title")
    assert [v["seq"] for v in titles] == [1, 2]
    assert titles[1]["parent_version_id"] == titles[0]["id"]
    assert titles[0]["content"] != titles[1]["content"]  # old version kept, not overwritten
    after = api.task_state(t["id"])
    assert after["current"]["title"] == titles[1]["id"]
    assert after["current"]["bullets"] == before["current"]["bullets"]
    assert after["current"]["description"] == before["current"]["description"]
    pdp = api.http.get(f"/api/versions/{after['pdp_version_id']}").json()
    assert pdp["manifest"]["bullets"] == before["current"]["bullets"]
    assert pdp["manifest"]["title"] == titles[1]["id"]
    assert pdp["parent_version_id"] == before["pdp_version_id"]


def test_one_utterance_is_one_feedback_and_a_question_is_a_tool(api: Api) -> None:
    """One sentence, one Feedback; a question inside it is `ask_question`, not a label.

    The old route split a sentence into several Feedback rows and typed each one. Splitting
    now happens inside the loop as several tool calls, so there is nothing to split here.
    """
    t = api.task()
    api.say(t["id"], "第一版")
    before = len(api.http.get(f"/api/tasks/{t['id']}/feedback").json())
    api.say(t["id"], "标题更突出防水；为什么描述这么短？")
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()
    assert len(fb) - before == 1
    assert fb[-1]["interpretation"] == "parameter_patch"


def test_constraint_is_pending_until_confirmed_then_enforced(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题不要超过 20 个字符")
    cons = api.http.get(f"/api/tasks/{t['id']}/constraints").json()
    assert len(cons["pending"]) == 1 and cons["effective"] == []
    assert len(api.slot_versions(t["id"], "title")) == 1  # a constraint is not an edit
    # not confirmed -> a later title edit is NOT limited to 20
    api.say(t["id"], "标题加上充电信息")
    assert len(api.slot_versions(t["id"], "title")[-1]["content"]["text"]) > 20
    cid = cons["pending"][0]["id"]
    assert api.http.post(f"/api/constraints/{cid}/confirm").status_code == 200
    api.say(t["id"], "标题再改一下")
    assert len(api.slot_versions(t["id"], "title")[-1]["content"]["text"]) <= 20
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()
    assert next(f for f in fb if f["text"].startswith("标题不要超过"))["status"] == "applied"


def test_revoking_pending_constraint_dismisses_feedback(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题不要超过 20 个字符")
    cid = api.http.get(f"/api/tasks/{t['id']}/constraints").json()["pending"][0]["id"]
    api.http.post(f"/api/constraints/{cid}/revoke")
    cons = api.http.get(f"/api/tasks/{t['id']}/constraints").json()
    assert cons["pending"] == [] and cons["effective"] == []


def test_hard_rule_failure_does_not_become_current(api: Api) -> None:
    """An over-limit imported baseline is accepted as the first version, but an agent edit
    that still violates the platform rule is rejected and never becomes current."""
    t = api.task(import_listing={"title": "x" * 300, "bullets": ["b"] * 5})
    v1 = api.slot_versions(t["id"], "title")
    assert v1[0]["origin"] == "imported"  # non-compliant baseline is accepted as first version
    run = api.say(t["id"], "标题改短一点")
    assert run["status"] == "succeeded"
    titles = api.slot_versions(t["id"], "title")
    assert titles[-1]["parent_version_id"] == titles[0]["id"]
    # the fake model keeps the 300-char base -> platform rule (200) fails -> rejected
    assert titles[-1]["status"] == "rejected"
    assert api.task_state(t["id"])["current"]["title"] == titles[0]["id"]
    assert any(not e["passed"] for e in titles[-1]["evaluations"])


def test_imported_listing_is_origin_imported_and_edits_follow_edit_listing(api: Api) -> None:
    t = api.task(import_listing={"title": "Old title", "bullets": ["a"] * 5, "description": "d"})
    assert api.task_state(t["id"])["status"] == "awaiting_user"
    api.say(t["id"], "标题更突出防水")
    assert [v["origin"] for v in api.slot_versions(t["id"], "title")] == ["imported", "edited"]
    with api.c.uow_factory() as uow:
        run_id = api.http.get(f"/api/tasks/{t['id']}/feedback").json()[0]["run_id"]
        assert [c.tool_name for c in uow.collab.tool_calls(run_id)] == ["edit_listing"]


def test_make_current_on_slot_version_creates_pdp_version_for_that_slot_only(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题更突出防水")
    titles = api.slot_versions(t["id"], "title")
    r = api.http.post(f"/api/versions/{titles[0]['id']}/make-current")
    assert r.status_code == 200
    state = api.task_state(t["id"])
    assert state["current"]["title"] == titles[0]["id"]
    pdp = api.http.get(f"/api/versions/{state['pdp_version_id']}").json()
    assert pdp["created_by"] == "user" and pdp["manifest"]["title"] == titles[0]["id"]


def test_accept_requires_awaiting_user(api: Api) -> None:
    t = api.task()
    assert api.http.post(f"/api/tasks/{t['id']}/accept").status_code == 409
    api.say(t["id"], "第一版")
    assert api.http.post(f"/api/tasks/{t['id']}/accept").status_code == 200
    r = api.http.post(
        f"/api/tasks/{t['id']}/utterances",
        json={"text": "再改"},
        headers={"Idempotency-Key": "late"},
    )
    assert r.status_code == 409
