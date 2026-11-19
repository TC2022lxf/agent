"""A general Task: one conversation, several artifact kinds (docs/architecture/data-and-contracts.md).

The point of the test is that the picture and the written file live in the same Task and
share the same context; nothing is moved to a second Task.
"""

from __future__ import annotations

from tests.conftest import Api


def test_same_task_can_hold_a_file_and_an_image(api: Api) -> None:
    task = api.task("general", kind="general", goal="做一张架构图并写说明")
    assert task["kind"] == "general"

    api.say(task["id"], "写一份 markdown 说明")
    api.say(task["id"], "生成图片，把架构画出来")

    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    kinds = {(a["kind"], a["slot"]) for a in arts if a["slot"]}
    assert ("file", "notes.md") in kinds
    assert ("image", "image") in kinds
    assert len(api.http.get(f"/api/tasks/{task['id']}/timeline").json()) == 2


def test_general_task_can_write_pdp_slots_and_lazily_creates_the_pdp_artifact(api: Api) -> None:
    task = api.task("general", kind="general", goal="给这把剃须刀做一套 PDP")
    before = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    assert not any(a["kind"] == "pdp" for a in before)

    api.say(task["id"], "写标题")
    assert len(api.slot_versions(task["id"], "title")) == 1

    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    pdp = next(a for a in arts if a["kind"] == "pdp")
    assert pdp["current_version_id"]
    title_id = api.slot_versions(task["id"], "title")[0]["id"]
    manifest = next(v for v in pdp["versions"] if v["id"] == pdp["current_version_id"])["manifest"]
    assert manifest["title"] == title_id


def test_general_pdp_slot_keeps_the_same_conversation_and_context(api: Api) -> None:
    task = api.task("general", kind="general", goal="剃须刀详情页")
    api.say(task["id"], "写标题")
    api.say(task["id"], "再写五点")
    api.say(task["id"], "生成图片，做主图")

    timeline = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    assert len(timeline) == 3
    assert {t["task_id"] if "task_id" in t else task["id"] for t in timeline} == {task["id"]}
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    slots = {a["slot"] for a in arts if a["slot"]}
    assert {"title", "bullets", "main_image"} <= slots
    assert any(a["kind"] == "pdp" for a in arts)


def test_each_pdp_slot_version_gets_its_own_pdp_version(api: Api) -> None:
    task = api.task("general", kind="general")
    api.say(task["id"], "写标题")
    api.say(task["id"], "再写五点")
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    pdp = next(a for a in arts if a["kind"] == "pdp")
    assert len(pdp["versions"]) == 2
    assert len(api.slot_versions(task["id"], "title")) == 1
    assert len(api.slot_versions(task["id"], "bullets")) == 1


def test_general_task_keeps_the_conversation_so_a_second_image_is_an_edit(api: Api) -> None:
    task = api.task("general", kind="general", goal="架构图")
    api.say(task["id"], "生成图片，画一张架构示意图")
    images = api.slot_versions(task["id"], "image")
    assert len(images) == 1

    api.say(task["id"], "再生成图片，把交付层放到最上面")
    images = api.slot_versions(task["id"], "image")
    assert len(images) == 2
    assert images[1]["parent_version_id"] == images[0]["id"]
    assert images[1]["params"]["base_version_id"] == images[0]["id"]


def test_file_keeps_its_own_version_when_a_picture_is_added(api: Api) -> None:
    task = api.task("general", kind="general")
    api.say(task["id"], "写一份 markdown 说明")
    before = api.slot_versions(task["id"], "notes.md")
    api.say(task["id"], "生成图片，画架构图")
    after = api.slot_versions(task["id"], "notes.md")
    assert len(after) == len(before)
    assert after[0]["id"] == before[0]["id"]


def test_target_slot_image_on_a_general_task_is_accepted(api: Api) -> None:
    task = api.task("general", kind="general")
    run = api.say(task["id"], "生成图片，画一张海报", target_slot="image")
    assert run["status"] == "succeeded"
    assert len(api.slot_versions(task["id"], "image")) == 1


def test_pdp_task_still_refuses_an_image_slot_from_another_agent(api: Api) -> None:
    """Scope stays: a PDP Task has its own slots; the general kind is the multi-artifact one."""
    task = api.task("amazon_pdp", goal="剃须刀")
    r = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "画一张图", "target_slot": "image"},
        headers={"Idempotency-Key": "gen-1"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_SLOT"


def test_specialist_cannot_run_a_general_task(api: Api) -> None:
    task = api.task("general", kind="general")
    r = api.http.post(
        f"/api/tasks/{task['id']}/utterances",
        json={"text": "画一张图", "agent_id": "image"},
        headers={"Idempotency-Key": "gen-2"},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "AGENT_CANNOT_HANDLE"


def test_a_wrong_slot_from_the_planner_is_refused_before_the_vendor_is_paid(api: Api) -> None:
    """The real planner once wrote a first main image to `slot: "image"` on a pdp Task.

    The picture was drawn, charged 20 credits, and landed on an Artifact no preview shows;
    `main_image` stayed empty. The write boundary has to be enforced before the Tool runs.
    """
    task = api.task("amazon_pdp", goal="剃须刀")
    # A plan that ignores both the Task kind and the turn's boundary. Only the first call is
    # bad; after the refusal the model has to stop, or the graph would retry forever.
    calls: list[dict[str, object]] = [{
        "name": "generate_product_image", "id": "bad",
        "args": {"slot": "image", "prompt": "主图"},
    }]

    def plan(payload: dict[str, object]) -> dict[str, object]:
        del payload
        return {
            "content": "这一版没有生成。",
            "tool_calls": [calls.pop(0)] if calls else [],
            "path_note": "",
            "declined": "",
        }

    api.c.gateway._inner._plan = plan  # type: ignore[attr-defined]
    run = api.say(task["id"], "生成主图", target_slot="main_image")
    assert run["status"] == "succeeded"
    assert run["version_ids"] == [] and run["cost"] == 0  # nothing was drawn or charged
    with api.c.uow_factory() as uow:
        calls = uow.collab.tool_calls(run["id"])
        assert [c.status for c in calls] == ["error"]
        assert "image" in (calls[0].error or "")
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    assert next(a for a in arts if a["slot"] == "main_image")["versions"] == []
    # The user is told, rather than being left with a blank screen.
    turns = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    assert any(t["answers"] or t["declined"] for t in turns)
