"""ask_question: what the next Run is told about the question it answered (decisions/0043).

A Run is not suspended and there is no `tool_result` channel: answering starts a NEW Run. That
is a defensible choice, but it means the question has to travel through the recorded history,
or the answer arrives as a sentence with nothing it is replying to.

Observed before the fix: the next Run's entire history was

    用户：太普通了，高级一点

— the question was gone, and the answer was re-classified as a brand-new request.
"""

from __future__ import annotations

from app.runtime.context import build_turn_lines, prior_messages
from tests.conftest import Api

QUESTION = "想朝哪个方向改？选一个我就按这个做。"


def _ask(api: Api, task_id: str) -> tuple[str, str]:
    """One turn that ends in `ask_question`; returns (run_id, request_id)."""
    run = api.say(task_id, "太普通了，高级一点")
    turns = api.http.get(f"/api/tasks/{task_id}/timeline").json()
    last = next(t for t in turns if t["run_id"] == run["id"])
    request = last["human_input_requests"][-1]
    return run["id"], request["request_id"]


def test_the_question_is_in_the_history_the_next_run_reads(api: Api) -> None:
    """The planner must see what it asked, or the answer has no referent."""
    task = api.task("image", goal="主图")
    run_id, _ = _ask(api, task["id"])
    with api.c.uow_factory() as uow:
        msgs, _ = prior_messages(uow, uow.collab.get_task(task["id"]), "next")
    joined = "\n".join(msgs)
    assert QUESTION in joined, f"the question is missing from the history: {msgs!r}"
    assert run_id  # the turn exists; the problem was only that the question was not in it


def test_the_answer_records_which_question_it_answers(api: Api) -> None:
    """With the request id, the reply is labelled instead of looking like a new brief."""
    task = api.task("image", goal="主图")
    _, request_id = _ask(api, task["id"])
    api.say(
        task["id"], "更突出核心卖点，语气克制",
        target_slot="image", answers_request_id=request_id,
    )
    with api.c.uow_factory() as uow:
        lines = build_turn_lines(uow, uow.collab.get_task(task["id"]))
    reply = lines[-1]
    assert reply.answer_to == QUESTION
    assert "回答上一个问题" in reply.render()


def test_an_older_client_without_the_id_still_gets_the_question_attached(api: Api) -> None:
    """Adjacency is the fallback: the reply directly follows the Run that asked."""
    task = api.task("image", goal="主图")
    _ask(api, task["id"])
    api.say(task["id"], "更突出核心卖点，语气克制", target_slot="image")
    with api.c.uow_factory() as uow:
        lines = build_turn_lines(uow, uow.collab.get_task(task["id"]))
    assert lines[-1].answer_to == QUESTION


def test_a_reply_is_not_reclassified_as_a_new_request(api: Api) -> None:
    """The interpret step is told `replying_to`, so the answer continues the open work."""
    task = api.task("image", goal="主图")
    _, request_id = _ask(api, task["id"])
    api.say(
        task["id"], "更突出核心卖点，语气克制",
        target_slot="image", answers_request_id=request_id,
    )
    turns = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    reply_turn = turns[-1]
    kinds = [i["kind"] for i in reply_turn["interpretations"]]
    assert kinds == ["parameter_patch"], f"the answer was re-classified: {kinds}"
    assert not reply_turn["human_input_requests"], "the answer was answered with another question"


def test_an_unknown_request_id_does_not_invent_a_question(api: Api) -> None:
    """A stale or forged id must not attach someone else's question to this sentence."""
    task = api.task("image", goal="主图")
    _ask(api, task["id"])
    api.say(
        task["id"], "更突出核心卖点", target_slot="image",
        answers_request_id="run_deadbeef:ask_question:ask_question",
    )
    # The fallback still finds the open question on this Task; what must never happen is a
    # reply claiming to answer a Run that does not exist.
    with api.c.uow_factory() as uow:
        lines = build_turn_lines(uow, uow.collab.get_task(task["id"]))
    assert lines[-1].answer_to == QUESTION


def test_ask_question_does_not_suspend_the_run(api: Api) -> None:
    """Documents the current contract, so a later change to it is a visible decision.

    The Run settles; only the Task is marked `awaiting_user`. Nothing is left queued or
    half-finished, and the frozen budget is returned in full.
    """
    task = api.task("image", goal="主图")
    run = api.say(task["id"], "太普通了，高级一点")
    assert run["status"] == "succeeded"
    assert "suspended" not in run["status"]
    assert api.task_state(task["id"])["status"] == "awaiting_user"
    assert run["cost"] == 0
    assert not run["version_ids"]
