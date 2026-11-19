"""Review-phase context, follow-up suggestions, and streaming (decisions/0041, 0042).

Three separate problems these cover, all of which looked like one bug to the user:

1. After a picture was generated the Run was still "thinking", and the next thing the model
   said was "What image should I make?" — the review step was told `{phase: after_tools}` and
   nothing else, so it did not know what had just happened.
2. A later turn could not describe the picture it was looking at: the object key is a file
   name to the model, so its colour and shape were invisible.
3. A finished answer arrived only at the end, and nothing suggested what to ask next.
"""

from __future__ import annotations

import json

from app.infrastructure.gateway_fake import FakeGateway
from app.services.followups import MAX_CHARS, MAX_QUESTIONS, _clean
from tests.conftest import Api


class _Recorder(FakeGateway):
    """FakeGateway that remembers what each purpose was asked, and the images attached."""

    def __init__(self) -> None:
        self.plan_calls: list[dict[str, object]] = []
        self.followup_calls: list[dict[str, object]] = []

    def chat_json(self, alias, system, user, *, params=None, purpose="", reasoning=False,
                  images=None, on_delta=None):  # type: ignore[no-untyped-def]
        if purpose == "followups":
            self.followup_calls.append({"user": user, "images": len(images or ())})
        elif purpose == "plan":
            self.plan_calls.append({"user": user, "images": len(images or ())})
        return super().chat_json(
            alias, system, user, params=params, purpose=purpose, reasoning=reasoning,
            images=images, on_delta=on_delta,
        )


def _with_recorder(api: Api) -> _Recorder:
    rec = _Recorder()
    api.c.executor.gateway = rec  # type: ignore[assignment]
    api.c.executor.loop.gateway = rec  # type: ignore[assignment]
    return rec


def test_review_step_receives_the_turn_and_its_tool_results(api: Api) -> None:
    """The review plan must say what was asked and what the tool returned, not just "after_tools"."""
    rec = _with_recorder(api)
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    assert run["status"] == "succeeded"
    reviews = [c for c in rec.plan_calls if '"phase": "after_tools"' in str(c["user"])]
    assert reviews, "the graph never ran a review step"
    body = json.loads(str(reviews[0]["user"]))
    assert body["request"], "the review step was not told what the user asked"
    assert body["tool_results"], "the review step was not told what the tool returned"
    assert body["tool_results"][0]["tool"] == "edit_listing"
    assert body.get("versions_written"), "the review step was not told a Version exists"


def test_planner_is_shown_the_picture_when_the_profile_supports_vision(api: Api) -> None:
    """A picture is sent as a picture, so "what colour is it" has an answer."""
    api.http.put(
        "/api/admin/model-profiles/gpt-6.1-sol",
        json={"capabilities": ["plan", "vision"]},
    )
    rec = _with_recorder(api)
    task = api.task("image", kind="image")
    api.say(task["id"], "做一个白底主图", target_slot="image")
    api.say(task["id"], "这个剃须刀是什么颜色", target_slot="image")
    later = [c for c in rec.plan_calls if int(c["images"]) > 0]  # type: ignore[arg-type]
    assert later, "the planner never received the image it was asked about"


def test_planner_without_vision_gets_no_picture(api: Api) -> None:
    """Attaching bytes to a model that cannot decode them would waste the input tokens."""
    api.http.put(
        "/api/admin/model-profiles/gpt-6.1-sol",
        json={"capabilities": ["plan"]},
    )
    rec = _with_recorder(api)
    task = api.task("image", kind="image")
    api.say(task["id"], "做一个白底主图", target_slot="image")
    assert all(int(c["images"]) == 0 for c in rec.plan_calls)  # type: ignore[arg-type]


def test_a_finished_answer_gets_suggested_follow_ups(api: Api) -> None:
    """The chips are a second, independent call after the turn, not part of its answer."""
    rec = _with_recorder(api)
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题")
    assert rec.followup_calls, "no follow-up call was made for a turn that answered"
    turn = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[-1]
    assert turn["answers"], "the turn produced no answer to follow up on"
    assert 1 <= len(turn["follow_ups"]) <= MAX_QUESTIONS


def test_a_question_delays_the_turn_and_asks_for_no_follow_ups(api: Api) -> None:
    """`ask_question` blocks the Run; suggestions for a next turn would be noise on top."""
    rec = _with_recorder(api)
    task = api.task("image", goal="主图")
    run = api.say(task["id"], "太普通了，高级一点")
    assert run["status"] == "succeeded"
    turn = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[-1]
    assert turn["human_input_requests"], "a vague request should have been asked about"
    assert turn["follow_ups"] == []
    assert not rec.followup_calls, "follow-ups were asked for while the Agent waits on a question"


def test_follow_ups_can_be_switched_off(api: Api) -> None:
    api.http.put("/api/admin/runtime", json={"followups_enabled": False})
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题")
    turn = api.http.get(f"/api/tasks/{task['id']}/timeline").json()[-1]
    assert turn["answers"] and turn["follow_ups"] == []


def test_follow_up_shape_is_cleaned_not_trusted() -> None:
    """A model's list is a suggestion: no numbering, no repeats, no paragraphs."""
    out = _clean(
        ["1. 换个背景看看", "换个背景看看", "  ", "x" * (MAX_CHARS + 1), "再加一张场景图"],
        asked={"换个背景看看"},
    )
    assert out == ["再加一张场景图"]


def test_reply_text_streams_before_the_run_ends(api: Api) -> None:
    """`answer_delta` carries the text while it is written; `answer` is the final record."""
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    with api.c.uow_factory() as uow:
        events = uow.collab.events_after(run["id"], 0)
    kinds = [e.type for e in events]
    assert "answer" in kinds, "the finished answer was not recorded"
    deltas = [e.data.get("text") for e in events if e.type == "answer_delta"]
    assert deltas and all(isinstance(d, str) and d for d in deltas)
    # Each delta is the WHOLE text so far, so a late subscriber never sees a fragment.
    assert all(len(deltas[i]) <= len(deltas[i + 1]) for i in range(len(deltas) - 1))
    # It streams before the record: a reader watching should not wait for the last event.
    assert kinds.index("answer_delta") < kinds.index("answer")


def test_a_post_tool_reply_reaches_the_user(api: Api) -> None:
    """The words after a Tool call are the answer, not a footnote the runtime drops.

    This is what made a delivered image look like a still-thinking model: the Version existed,
    and the sentence explaining it never became an `answer` event.
    """
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    turns = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    turn = next(t for t in turns if t["run_id"] == run["id"])
    assert turn["answers"], "a turn that wrote a Version said nothing to the user"
    assert turn["answers"][-1].strip() != "", "the answer was blank"


def test_follow_up_failure_does_not_fail_the_run(api: Api) -> None:
    """A decorative call must never turn a delivered artifact into a failed Run."""
    class Broken(_Recorder):
        def chat_json(self, alias, system, user, **kw):  # type: ignore[no-untyped-def]
            if kw.get("purpose") == "followups":
                raise RuntimeError("vendor down")
            return super().chat_json(alias, system, user, **kw)

    rec = Broken()
    api.c.executor.gateway = rec  # type: ignore[assignment]
    api.c.executor.loop.gateway = rec  # type: ignore[assignment]
    task = api.task("amazon_pdp", goal="剃须刀")
    run = api.say(task["id"], "写标题")
    assert run["status"] == "succeeded"
    assert len(api.slot_versions(task["id"], "title")) == 1


def test_planner_profile_declares_vision_by_default(api: Api) -> None:
    """The bound planner can see; a profile that does not say so never gets a picture.

    Verified against the vendor (scripts/probe_vision.py), not assumed from the model name.
    Without the flag the planner answered "I cannot read the picture" about the image it had
    just generated (decisions/0041).
    """
    with api.c.uow_factory() as uow:
        planner = uow.profiles.planner_for_agent("image")
    assert "vision" in (planner.capabilities or [])
    assert "plan" in (planner.capabilities or [])


def test_vision_flag_alone_does_not_change_the_reply_contract() -> None:
    """`images` is an optional argument: a caller that passes none still gets a plain string."""
    from app.infrastructure.gateway_openai import _user_content

    assert _user_content("hi", None) == "hi"
    assert _user_content("hi", []) == "hi"
    parts = _user_content("hi", [b"\x89PNG"])
    assert isinstance(parts, list) and parts[0] == {"type": "text", "text": "hi"}
    assert str(parts[1]["image_url"]["url"]).startswith("data:image/png;base64,")


def test_delta_extraction_ignores_json_syntax() -> None:
    from app.runtime.langgraph_loop import _partial_content

    assert _partial_content('{"content": "正在') == "正在"
    assert _partial_content('{"content": "好了"}') == "好了"
    assert _partial_content('{"tool_calls": [') == ""
    assert _partial_content('{"content": "转义\\"引号') == '转义"引号'
