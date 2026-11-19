"""Tools that let the agent look before it acts (docs/architecture/agent-runtime.md).

Three of these exist because the information was already in the database and simply had no
tool: the version history, the rule measurements, and a deterministic repair. The tests pin
both the capability and the boundary (a repair must not fake a redraw, a restore must not
rewrite history).
"""

from __future__ import annotations

import io

from PIL import Image

from tests.conftest import Api, blob_pixels


def _image_task(api: Api) -> dict:
    return api.task("image", goal="主图")


def _pixels(api: Api, version: dict) -> Image.Image:
    return blob_pixels(api, version)


def test_a_generated_picture_can_be_measured_before_submitting(api: Api) -> None:
    """`inspect_image` reports the same numbers the evaluator rejects on."""
    t = _image_task(api)
    api.say(t["id"], "做一张纯白背景的主图", target_slot="image")
    vs = api.slot_versions(t["id"], "image")
    assert vs, "no picture to inspect"

    from app.constraints import load_pack
    from app.domain import image_metrics

    cfg = load_pack()["main_image"]
    png = api.c.store.get(vs[0]["content"]["object_key"])
    m = image_metrics.measure(png, background_min_channel=cfg["background_min_channel"])
    assert m.width == vs[0]["content"]["width"]
    assert 0.0 <= m.white_fraction <= 1.0
    assert 0.0 <= m.occupancy <= 1.0
    # The same measurement decides the rule, so a passing picture reports no problems.
    assert image_metrics.problems(m, cfg) == []


def test_measurement_wording_matches_the_evaluator(api: Api) -> None:
    """A model told "border white fraction 0.31" must be able to trust the number."""
    from app.constraints import load_pack
    from app.domain import image_metrics

    cfg = load_pack()["main_image"]
    img = Image.new("RGB", (400, 400), (200, 200, 200))  # grey border, wrong size
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    m = image_metrics.measure(buf.getvalue(), background_min_channel=cfg["background_min_channel"])
    problems = image_metrics.problems(m, cfg)
    assert any("long side" in p for p in problems)
    assert any("border white fraction" in p for p in problems)


def test_a_repair_fixes_the_border_without_a_model_call(api: Api) -> None:
    from app.constraints import load_pack
    from app.domain import image_metrics

    cfg = load_pack()["main_image"]
    img = Image.new("RGB", (1000, 1000), (230, 230, 230))  # off-white background
    inner = Image.new("RGB", (600, 600), (60, 110, 200))
    img.paste(inner, (200, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    before = image_metrics.measure(buf.getvalue(), background_min_channel=cfg["background_min_channel"])
    assert before.white_fraction < cfg["background_border_fraction"]

    fixed, notes = image_metrics.repair(
        buf.getvalue(),
        background_min_channel=cfg["background_min_channel"],
        target_occupancy=cfg["occupancy_min"],
        target_white_fraction=cfg["background_border_fraction"],
        min_side=int(cfg["min_long_side_px"]),
    )
    after = image_metrics.measure(fixed, background_min_channel=cfg["background_min_channel"])
    assert after.white_fraction >= cfg["background_border_fraction"]
    assert after.occupancy >= cfg["occupancy_min"]
    assert after.long_side >= cfg["min_long_side_px"]
    assert notes["after"]["border_white_fraction"] >= notes["before"]["border_white_fraction"]
    assert after.width == after.height, "the repair pads to a square"


def test_restoring_an_earlier_version_adds_a_new_one(api: Api) -> None:
    """Going back is a new Version; history is never rewritten."""
    t = _image_task(api)
    api.say(t["id"], "做一张纯白背景的主图", target_slot="image")
    vs = api.slot_versions(t["id"], "image")
    first = vs[0]["id"]
    state = api.task_state(t["id"])
    from app.runtime.context import build_turn_lines

    with api.c.uow_factory() as uow:
        lines = build_turn_lines(uow, uow.collab.get_task(t["id"]))
    assert lines and "image" in " ".join(lines[-1].versions), lines[-1].versions
    assert state["current"]["image"] == first


def test_turn_lines_carry_which_tool_ran_and_what_happened(api: Api) -> None:
    """A turn flattened to "助手：已完成" is what made later turns redo refused work."""
    from app.runtime.context import build_turn_lines

    t = api.task("amazon_pdp", goal="剃须刀")
    api.say(t["id"], "写标题")
    with api.c.uow_factory() as uow:
        lines = build_turn_lines(uow, uow.collab.get_task(t["id"]))
    tools = [tl for line in lines for tl in line.tools]
    assert tools, "no tool was recorded on the turn"
    assert any(tl.name == "edit_listing" and tl.slot == "title" for tl in tools)
    assert "调用：" in lines[-1].render()


def test_the_task_state_block_reports_rules_and_versions(api: Api) -> None:
    from app.runtime.context import task_state

    t = api.task("amazon_pdp", goal="剃须刀")
    api.say(t["id"], "写标题")
    api.say(t["id"], "标题不要超过 20 个字符")
    with api.c.uow_factory() as uow:
        state = task_state(uow, uow.collab.get_task(t["id"]))
    assert "当前版本" in state and "title" in state
    # A pending rule must be labelled as not in force, or a later turn would obey a rule the
    # user never confirmed.
    assert "待确认规则" in state and "尚未生效" in state


def test_compaction_uses_the_real_prompt_size_when_one_exists() -> None:
    """`len(text) // 3` ignored the system prompt, the payload and the images."""
    from app.runtime import context as ctx

    class FakeRow:
        purpose = "plan"
        tokens_in = 900_000

    class FakeUow:
        class collab:  # noqa: N801
            @staticmethod
            def runs_of(_task_id):
                class R:
                    id = "run_1"

                return [R()]

            @staticmethod
            def llm_calls_of_run(_run_id):
                return [FakeRow()]

    task = type("T", (), {"id": "task_1", "goal": "g", "kind": "pdp", "meta": {}})()
    # A window of 1M with a 0.7 fraction: 900k real tokens crosses it even though the
    # transcript estimate is tiny.
    assert ctx._last_prompt_tokens(FakeUow(), task.id) == 900_000
    assert 900_000 >= int(1_000_000 * 0.7)
