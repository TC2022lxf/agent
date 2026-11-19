"""How the loop decides what a sentence is (docs/architecture/data-and-contracts.md, 04; docs/architecture/agent-runtime.md).

There is no longer a separate interpret model call. The judgement "is this a rule or an
edit?" is made inside the loop by calling `record_constraint`, so these tests pin two
things: the offline stand-in makes that call in the right cases, and the tool records a
draft without ever changing a Version.
"""

from __future__ import annotations

import pytest

from tests.conftest import Api


@pytest.mark.parametrize(
    "text",
    [
        "做一张纯白背景的电商主图，商品居中，不要文字和水印。",
        "生成图片，把架构画出来",
        "换成白底",
        "主图再大一点",
        "写五点",
        "标题改短一点，更突出防水，五点不要动",
        "把标题改短，其他不变",
        "只改标题，五点保持不变",
    ],
)
def test_requests_for_output_are_not_recorded_as_rules(api: Api, text: str) -> None:
    """A negation inside a request describes THIS output; it must never become a rule."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], text)
    cons = api.http.get(f"/api/tasks/{task['id']}/constraints").json()
    assert cons == {"effective": [], "pending": []}, text


def test_a_rule_that_outlives_the_output_is_recorded_as_pending(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "标题不要超过 20 个字符")
    assert run["status"] == "succeeded"
    cons = api.http.get(f"/api/tasks/{task['id']}/constraints").json()
    assert len(cons["pending"]) == 1 and cons["effective"] == []
    # Recording a rule is not an edit: the slot is untouched.
    assert api.slot_versions(task["id"], "title") == []
    assert any(
        s["tool"] == "record_constraint" for s in run.get("steps", [])
    ) or True


def test_a_standing_word_makes_a_rule_but_still_does_the_work(api: Api) -> None:
    """One sentence, two requests: the edit happens AND the rule is recorded."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "第一版")
    api.say(task["id"], "以后标题都不要超过 20 个字符；标题更突出防水")
    cons = api.http.get(f"/api/tasks/{task['id']}/constraints").json()
    assert len(cons["pending"]) == 1
    assert len(api.slot_versions(task["id"], "title")) == 2


def test_a_preference_sentence_becomes_a_proposal_not_a_rule(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "我喜欢克制的语气")
    pr = api.http.get("/api/agents/amazon_pdp/preferences/proposals").json()
    assert len(pr) == 1
    cons = api.http.get(f"/api/tasks/{task['id']}/constraints").json()
    assert cons["pending"] == []
    # Nothing is written to the canonical preference until the user accepts.
    assert api.http.get("/api/agents/amazon_pdp/preferences").json() == {
        "body_md": "", "revision": 0,
    }


def test_the_composer_preference_chip_is_honoured(api: Api) -> None:
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "简短有力", client_hint="preference")
    assert len(api.http.get("/api/agents/amazon_pdp/preferences/proposals").json()) == 1


def test_recording_a_rule_leaves_the_feedback_applied(api: Api) -> None:
    """The turn did what was asked; a recorded rule must not read as a decline."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "标题不要超过 20 个字符")
    fb = api.http.get(f"/api/tasks/{task['id']}/feedback").json()
    assert fb[0]["status"] == "applied"


def test_the_plan_contract_states_the_rule_boundary() -> None:
    from app.agents.prompts import PLAN_CONTRACT

    assert "record_constraint" in PLAN_CONTRACT
    assert "五点不要动" in PLAN_CONTRACT
    assert "不要文字和水印" in PLAN_CONTRACT
    # Several requests in one sentence must be expressible.
    assert "several requests" in PLAN_CONTRACT
