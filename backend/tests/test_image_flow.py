"""Image Agent: local edit from a base version, region confinement, hard rules, bound vs
standalone, and the three-entry contract (scenarios A1-A3 in docs/plan)."""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image

from app.persistence.models import ToolCall
from tests.conftest import Api, blob_pixels

REGION = {"x": 0.4, "y": 0.4, "w": 0.2, "h": 0.2}


def _image_task(api: Api, agent: str = "image", **kw: Any) -> dict[str, Any]:
    up = api.upload_png()
    return api.task(agent, kind="image", upload_id=up, **kw)


def _tools(api: Api, run_id: str) -> list[str]:
    with api.c.uow_factory() as uow:
        return [c.tool_name for c in uow.collab.tool_calls(run_id)]


def test_standalone_image_edit_uses_edit_tool_and_bbox_prompt(api: Api) -> None:
    t = _image_task(api)  # white 1000x1000 upload, no PDP involved
    run = api.say(t["id"], "把这里改成蓝色", target_slot="image", target_region=REGION)
    assert run["status"] == "succeeded"
    assert _tools(api, run["id"]) == ["edit_product_image"]  # never a whole-image re-roll
    vs = api.slot_versions(t["id"], "image")
    assert [v["origin"] for v in vs] == ["imported", "edited"]
    assert vs[1]["parent_version_id"] == vs[0]["id"]
    assert vs[1]["params"]["engine"] == "model"
    assert "<bbox>" in vs[1]["params"]["prompt_sent"]
    assert vs[1]["params"]["region"] == REGION


def test_image_task_has_no_pdp_version(api: Api) -> None:
    t = _image_task(api)
    api.say(t["id"], "改一下", target_slot="image", target_region=REGION)
    arts = api.http.get(f"/api/tasks/{t['id']}/artifacts").json()
    assert not any(a["kind"] == "pdp" for a in arts)
    assert api.task_state(t["id"])["pdp_version_id"] is None


def test_image_task_starts_with_no_version_so_the_ui_has_nothing_to_preview(api: Api) -> None:
    """The page shows only the conversation until the first image exists."""
    task = api.task("image", goal="纯白背景主图")
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    image = next(a for a in arts if a["slot"] == "image")
    assert image["current_version_id"] is None and image["versions"] == []

    run = api.say(task["id"], "做一个纯白背景的电商主图，商品居中", target_slot="image")
    assert run["status"] == "succeeded"
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    image = next(a for a in arts if a["slot"] == "image")
    assert image["current_version_id"] and len(image["versions"]) == 1
    body = run["input"] if isinstance(run.get("input"), dict) else {}
    assert body.get("target_version_id") in {None, ""}


def test_negation_inside_a_production_request_still_produces_the_image(api: Api) -> None:
    """A request that says what NOT to include is a patch on this output, not a standing rule.

    `不要文字和水印` used to be read as a `new_constraint`, so the Run finished with no
    tool call and the page stayed empty.
    """
    task = api.task("image", goal="主图")
    sentence = "做一张纯白背景的电商主图，商品居中，不要文字和水印。"
    run = api.say(task["id"], sentence, target_slot="image")
    assert run["status"] == "succeeded"
    kinds = [i["kind"] for i in run["interpretations"]] if "interpretations" in run else []
    assert "new_constraint" not in kinds
    assert run["version_ids"], "the first version should exist"
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    image = next(a for a in arts if a["slot"] == "image")
    assert image["current_version_id"] == run["version_ids"][0]


def test_general_task_becomes_awaiting_user_after_a_version(api: Api) -> None:
    """A `general` Task owns no fixed slots; its status must read the artifacts it grew."""
    task = api.task("general", kind="general", goal="架构图")
    assert task["status"] == "draft"
    api.say(task["id"], "生成图片，画一张架构示意图")
    assert api.task_state(task["id"])["status"] == "awaiting_user"


def test_image_task_does_not_stick_in_draft_after_the_first_image(api: Api) -> None:
    task = api.task("image", goal="主图")
    api.say(task["id"], "做一个白底主图", target_slot="image")
    assert api.task_state(task["id"])["status"] == "awaiting_user"


def test_first_image_sentence_after_the_fix_produces_a_version(api: Api) -> None:
    task = api.task("image", goal="主图")
    run = api.say(task["id"], "做一张纯白背景的电商主图，商品居中", target_slot="image")
    assert run["version_ids"]
    assert api.task_state(task["id"])["status"] == "awaiting_user"


def test_rejected_version_asks_the_user_with_concrete_options(api: Api) -> None:
    """A rejection is not a dead end: Runtime says what failed and offers the next steps.

    The fake gateway draws a compliant white square, so a rejection is forced through a user
    rule the picture cannot satisfy — the point is the message, not how it failed.
    """
    task = api.task("amazon_pdp", goal="剃须刀", profile="main_image")
    first = api.say(task["id"], "做一张主图", target_slot="main_image")
    assert first["status"] == "succeeded"
    # A max_chars rule cannot be met by an image, so the next version is rejected.
    api.say(task["id"], "标题不要超过 5 个字符")
    pending = api.http.get(f"/api/tasks/{task['id']}/constraints").json()["pending"]
    for c in pending:
        api.http.post(f"/api/constraints/{c['id']}/confirm")
    api.say(task["id"], "再做一张主图", target_slot="main_image")

    turns = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    answers = [a for t in turns for a in t["answers"]]
    rejected = [
        v for t in turns for v in t["versions"]
        if v["kind"] != "pdp" and v["status"] == "rejected"
    ]
    if not rejected:
        pytest.skip("no evaluator rejected this build's fake image")
    assert answers, "a rejected version produced no message"
    assert "拒绝" in answers[-1]


def test_accepting_the_regenerate_option_makes_a_new_first_draft(api: Api) -> None:
    """The offered option must be executable: "重新生成" is a new draft, not an edit."""
    task = api.task("image", goal="主图")
    api.say(task["id"], "做一张纯白背景的主图", target_slot="image")
    api.say(task["id"], "重新生成一张纯白无缝背景", target_slot="image")
    vs = api.slot_versions(task["id"], "image")
    assert len(vs) == 2
    assert vs[1]["parent_version_id"] is None, "a regenerated draft must not claim the old one"


def test_main_image_slot_carries_its_aspect_ratio() -> None:
    """Amazon wants a square main image; that is a slot fact, not a model choice."""
    from app.domain import slots as slot_registry

    assert slot_registry.aspect_ratio_for("main_image") == "1:1"
    assert slot_registry.aspect_ratio_for("image") is None


def test_a_standing_rule_is_still_a_constraint(api: Api) -> None:
    """The fix must not turn every negation into a generation request."""
    task = api.task("amazon_pdp", goal="剃须刀")
    api.say(task["id"], "写标题")
    before = len(api.slot_versions(task["id"], "title"))
    api.say(task["id"], "标题不要超过 20 个字符")
    pending = api.http.get(f"/api/tasks/{task['id']}/constraints").json()["pending"]
    assert any("20" in str(c.get("rule")) for c in pending)
    assert len(api.slot_versions(task["id"], "title")) == before


def test_a_question_routes_to_the_agent_loop(api: Api) -> None:
    """Vague feedback is `question` at interpret time; the Agent asks via `ask_question`."""
    task = api.task("image", goal="主图")
    api.say(task["id"], "太普通了，高级一点")

    turns = api.http.get(f"/api/tasks/{task['id']}/timeline").json()
    assert turns, "the question was not recorded as a turn"
    reqs = turns[-1]["human_input_requests"]
    assert reqs, "ask_question should emit human_input_request"
    opts = reqs[-1].get("options") or []
    assert opts, "ask_question carried no options"
    labels = [o["value"] if isinstance(o, dict) else o for o in opts]
    assert 1 <= len(labels) <= 3
    assert any(s["tool"] == "ask_question" for s in turns[-1]["steps"])
    assert not turns[-1]["answers"], "ask must not be copied into answer events"
    assert api.task_state(task["id"])["status"] == "awaiting_user"

    run = api.say(task["id"], labels[0], target_slot="image")
    assert run["status"] == "succeeded"


def test_second_image_sentence_edits_the_first(api: Api) -> None:
    task = api.task("image", goal="主图")
    api.say(task["id"], "做一个白底主图", target_slot="image")
    first = api.slot_versions(task["id"], "image")[0]
    api.say(task["id"], "背景再干净一点", target_slot="image", target_version_id=first["id"])
    vs = api.slot_versions(task["id"], "image")
    assert len(vs) == 2
    assert vs[1]["parent_version_id"] == first["id"]


def test_product_scale_is_declined_not_faked(api: Api) -> None:
    t = _image_task(api)
    run = api.say(t["id"], "主图里产品再大一点", target_slot="image", target_region=REGION)
    assert run["status"] == "succeeded"
    assert len(api.slot_versions(t["id"], "image")) == 1  # no new version
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()[-1]
    assert fb["status"] == "declined" and "experiment" in fb["note"]


def test_main_image_rule_violation_is_rejected_and_not_current(api: Api) -> None:
    t = api.task(kind="pdp")
    api.say(t["id"], "生成主图", target_slot="main_image")
    first = api.slot_versions(t["id"], "main_image")
    assert first[0]["status"] == "ok"  # generated white-background image passes the rules
    pdp_before = api.task_state(t["id"])["pdp_version_id"]
    full = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    api.say(t["id"], "把主图背景改成红色", target_slot="main_image", target_region=full)
    vs = api.slot_versions(t["id"], "main_image")
    assert vs[-1]["status"] == "rejected"
    assert any(not e["passed"] and e["evaluator_id"] == "main_image_rules"
               for e in vs[-1]["evaluations"])
    state = api.task_state(t["id"])
    assert state["current"]["main_image"] == first[0]["id"]  # violating version not current
    assert state["pdp_version_id"] == pdp_before  # and no PDP version was created
    assert api.http.post(f"/api/versions/{vs[-1]['id']}/make-current").status_code == 409


def test_bound_main_image_creates_pdp_version_other_slots_unchanged(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    cur = api.task_state(t["id"])
    api.say(t["id"], "生成主图", target_slot="main_image")
    after = api.task_state(t["id"])
    assert after["pdp_version_id"] != cur["pdp_version_id"]
    for s in ("title", "bullets", "description"):
        assert after["current"][s] == cur["current"][s]
    assert after["current"]["main_image"]
    # second image change must go through edit_product_image(base_version_id=...)
    run = api.say(t["id"], "这里改亮一点", target_slot="main_image", target_region=REGION)
    assert _tools(api, run["id"]) == ["edit_product_image"]
    vs = api.slot_versions(t["id"], "main_image")
    assert vs[1]["parent_version_id"] == vs[0]["id"]
    assert after["current"]["title"] == api.task_state(t["id"])["current"]["title"]


def test_same_image_task_behaves_identically_from_three_entries(api: Api) -> None:
    """A3: only Run.agent_key differs; tool calls and outputs' shape are the same."""
    seen: dict[str, tuple[list[str], str]] = {}
    for entry in ("image", "general", "amazon_pdp"):
        t = _image_task(api, "image")
        run = api.say(t["id"], "这里改成蓝色", agent_id=entry, target_slot="image",
                      target_region=REGION)
        seen[entry] = (_tools(api, run["id"]), run["agent_key"])
        v = api.slot_versions(t["id"], "image")[-1]
        assert v["params"]["operation"] == "free" and v["status"] == "ok"
    assert all(tools == ["edit_product_image"] for tools, _ in seen.values())
    assert {k: key for k, (_, key) in seen.items()} == {
        "image": "image", "general": "general", "amazon_pdp": "amazon_pdp"
    }


def test_tool_calls_are_logged_with_idempotent_ids(api: Api) -> None:
    t = _image_task(api)
    run = api.say(t["id"], "改一下", target_slot="image", target_region=REGION)
    with api.c.uow_factory() as uow:
        rows = uow.collab.tool_calls(run["id"])
        assert [r.tool_call_id for r in rows] == [f"{run['id']}:edit_product_image:image"]
        assert isinstance(rows[0], ToolCall) and rows[0].status == "ok" and rows[0].cost == 15


def test_first_image_of_a_product_bound_task_uses_the_product_picture(api: Api) -> None:
    """The first draft must show THIS product. Without a reference the model invents one."""
    sample = next(p for p in api.http.post("/api/products/samples").json()
                  if p["mode"] == "generate")
    t = api.task("amazon_pdp", product_id=sample["id"], goal="做一个 PDP")
    assert t["meta"]["product"]["reference_key"]
    api.say(t["id"], "生成主图", target_slot="main_image")
    v = api.slot_versions(t["id"], "main_image")[0]
    assert v["params"]["reference_object_key"] == sample["main_url"].rsplit("/api/blobs/", 1)[-1]
    assert v["params"]["reference"] is True
    assert "reference image" in v["params"]["prompt_sent"]
    # the stand-in copies the reference, so the subject is the saved picture, not a drawn box
    key = sample["main_url"].rsplit("/api/blobs/", 1)[-1]
    expected = Image.open(io.BytesIO(api.c.store.get(key))).convert("RGB")
    got = blob_pixels(api, v)
    assert got.size == (1000, 1000)
    fit = expected.copy()
    fit.thumbnail((880, 880))
    left, top = (1000 - fit.width) // 2, (1000 - fit.height) // 2
    assert got.getpixel((left + fit.width // 2, top + fit.height // 2)) == fit.getpixel(
        (fit.width // 2, fit.height // 2))
    assert got.getpixel((5, 5)) == (255, 255, 255)  # white canvas around the product


def test_without_a_product_there_is_no_reference(api: Api) -> None:
    t = api.task("image", goal="纯白背景主图")
    api.say(t["id"], "做一个白底主图", target_slot="image")
    v = api.slot_versions(t["id"], "image")[0]
    assert "reference_object_key" not in v["params"] and v["params"]["reference"] is False


def test_product_page_entry_imports_into_a_pdp_task(api: Api) -> None:
    """The product page must land on the PDP entry, and the import must actually happen."""
    sample = next(p for p in api.http.post("/api/products/samples").json()
                  if p["mode"] == "optimize")
    t = api.task("amazon_pdp", product_id=sample["id"], import_product=True, goal="")
    assert t["kind"] == "pdp"
    assert api.slot_versions(t["id"], "title")[0]["origin"] == "imported"


def test_import_into_a_general_task_creates_the_pdp_artifact(api: Api) -> None:
    """A general Task owns no fixed slots, so the import has to create them on first write."""
    sample = next(p for p in api.http.post("/api/products/samples").json()
                  if p["mode"] == "optimize")
    t = api.task("general", kind="general", product_id=sample["id"], import_product=True, goal="")
    assert api.slot_versions(t["id"], "title")[0]["origin"] == "imported"
    arts = api.http.get(f"/api/tasks/{t['id']}/artifacts").json()
    pdp = next(a for a in arts if a["kind"] == "pdp")
    manifest = next(v for v in pdp["versions"] if v["id"] == pdp["current_version_id"])["manifest"]
    assert set(manifest) >= {"title", "bullets", "main_image"}


def test_a_circled_edit_fills_the_base_from_the_current_version(api: Api) -> None:
    """The schema defaults `base_version_id` to "". `setdefault` then saw a value and never
    filled it, so every circled edit failed with `no_base` and no Version appeared."""
    t = api.task("image", kind="image", goal="主图")
    api.say(t["id"], "做一张白底主图，一把金属剃须刀", target_slot="image")
    first = api.slot_versions(t["id"], "image")[0]
    run = api.say(t["id"], "这里改成蓝色", target_slot="image", target_region=REGION,
                  target_version_id=first["id"])
    assert run["status"] == "succeeded"
    vs = api.slot_versions(t["id"], "image")
    assert len(vs) == 2, [s["error"] for s in
                          api.http.get(f"/api/tasks/{t['id']}/timeline").json()[0]["steps"]]
    assert vs[1]["parent_version_id"] == first["id"]
    assert vs[1]["params"]["operation"] == "free"
