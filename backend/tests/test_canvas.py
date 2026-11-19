"""Canvas: a `canvas` Artifact that is a BOARD of screens (docs/architecture/data-and-contracts.md, 0029).

Modelled on Stitch: several screens on one surface, variants side by side, a theme made of
tokens, and edges describing a clickable flow. Two things these tests protect. A user's drag
is still a Version (so it survives a reload and `make-current` can go back). A picture module
points at a Version, so changing one module never moves another one's pointer.
"""

from __future__ import annotations

from typing import Any

from app.domain import canvas as canvas_domain
from app.domain.canvas import CanvasError
from tests.conftest import Api

FRAME = {"width": 1464, "height": 600}


def _module(mid: str, kind: str = "text", **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": mid, "kind": kind, "name": mid,
        "rect": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.2},
        "style": {"size": 24, "weight": 400, "align": "left", "color": "fg", "font": "body"}
        if kind == "text"
        else {"fit": "contain", "background": "white"},
    }
    if kind == "text":
        base["text"] = "hello"
    else:
        base["slot"] = kw.pop("slot", "canvas_image_1")
    base.update(kw)
    return base


def _screen(
    sid: str = "s1", modules: list[dict[str, Any]] | None = None, **kw: Any,
) -> dict[str, Any]:
    """A screen body. `pos` is only included when given: `add_screen` auto-places otherwise."""
    base: dict[str, Any] = {
        "id": sid, "name": sid, "frame": dict(FRAME),
        "modules": modules if modules is not None else [_module(f"{sid}m1")],
    }
    base.update(kw)
    return base


def _board(*screens: dict[str, Any], **kw: Any) -> dict[str, Any]:
    return {"screens": list(screens) or [_screen()], **kw}


# ---- pure domain ------------------------------------------------------------
def test_a_board_needs_screens_unique_theme_tokens() -> None:
    ok = canvas_domain.validate_board(_board())
    screen = ok["screens"][0]
    assert screen["modules"][0]["style"]["color"] == "fg"
    assert ok["theme"]["colors"]["bg"] == "#FFFFFF"

    for bad, needle in (
        (_board(_screen("s1"), _screen("s1")), "重复"),
        (_board(_screen(modules=[_module("m1"), _module("m1")])), "唯一"),
    ):
        try:
            canvas_domain.validate_board(bad)
        except CanvasError as e:
            assert needle in str(e), (needle, str(e))
        else:  # pragma: no cover
            raise AssertionError(f"accepted: {bad}")


def test_a_blank_screen_is_legal() -> None:
    """A screen may hold nothing: the board starts blank, not with a product-card template."""
    blank = canvas_domain.validate_board(canvas_domain.empty_board())
    assert blank["screens"][0]["modules"] == []
    assert blank["screens"][0]["name"] == "画板 1"
    assert not any("首屏" in str(m.get("text", "")) for m in blank["screens"][0]["modules"])


def test_a_picture_request_becomes_a_board_with_one_prompted_picture() -> None:
    """The canvas exists to make pictures: the sentence is the prompt, not a page brief."""
    board = canvas_domain.validate_board(
        canvas_domain.board_for_picture("一张深色极简的咖啡店海报")
    )
    screen = board["screens"][0]
    assert screen["name"] == "一张深色极简的咖啡店海报"
    (module,) = screen["modules"]
    assert module["kind"] == "image"
    assert module["prompt"] == "一张深色极简的咖啡店海报"
    assert module["slot"] == "canvas_image_1"
    # It covers nearly the whole screen: it IS the design, not a slot on a product page.
    assert module["rect"]["w"] > 0.9


def test_module_ids_are_unique_across_the_whole_board() -> None:
    """Two screens cannot both own `m1`: the manifest is keyed by module id."""
    twin = _module("m1")
    try:
        canvas_domain.validate_board(
            _board(_screen("s1", modules=[twin]), _screen("s2", modules=[dict(twin)]))
        )
    except CanvasError as e:
        assert "唯一" in str(e)
    else:  # pragma: no cover
        raise AssertionError("duplicate module ids across screens accepted")


def test_text_colour_and_font_must_be_theme_tokens() -> None:
    """A raw hex on a module would be unenforceable: the theme owns colour."""
    for style, needle in (
        ({"color": "#ff0000"}, "主题令牌"),
        ({"font": "Comic Sans"}, "主题令牌"),
    ):
        mod = _module("m1", style={**{"size": 24, "weight": 400, "align": "left"}, **style})
        try:
            canvas_domain.validate_board(_board(_screen(modules=[mod])))
        except CanvasError as e:
            assert needle in str(e)
        else:  # pragma: no cover
            raise AssertionError(f"accepted style {style}")


def test_a_theme_needs_bg_and_fg_and_real_hex() -> None:
    try:
        canvas_domain.validate_board(_board(theme={"colors": {"accent": "#123456"}}))
    except CanvasError as e:
        assert "bg" in str(e)
    else:  # pragma: no cover
        raise AssertionError("theme without bg/fg accepted")
    try:
        canvas_domain.validate_board(_board(theme={"colors": {"bg": "white", "fg": "#000000"}}))
    except CanvasError as e:
        assert "#RRGGBB" in str(e)
    else:  # pragma: no cover
        raise AssertionError("named colour accepted")


def test_a_rect_outside_the_frame_is_rejected_and_a_drag_is_clamped() -> None:
    far = _module("m1", rect={"x": 0.9, "y": 0, "w": 0.3, "h": 0.2})
    try:
        canvas_domain.validate_board(_board(_screen(modules=[far])))
    except CanvasError as e:
        assert "超出" in str(e)
    else:  # pragma: no cover
        raise AssertionError("out-of-frame rect accepted")

    body = _board()
    moved = canvas_domain.apply_ops(
        body, [{"op": "move_module", "screen": "s1", "id": "s1m1", "dx": 5, "dy": -5}],
    )
    rect = moved["screens"][0]["modules"][0]["rect"]
    assert rect["x"] == 0.7 and rect["y"] == 0.0  # clamped, not an error
    assert body["screens"][0]["modules"][0]["rect"]["x"] == 0.1  # the input is untouched


def test_only_the_named_module_changes() -> None:
    a = _module("m1")
    b = _module("m2", "image")
    c = _module("m3", rect={"x": 0.6, "y": 0.6, "w": 0.2, "h": 0.2})
    body = _board(_screen(modules=[a, b, c]))
    out = canvas_domain.apply_ops(body, [{"op": "set_text", "id": "m1", "text": "新标题"}])
    modules = out["screens"][0]["modules"]
    assert modules[0]["text"] == "新标题"
    assert modules[1] == body["screens"][0]["modules"][1]
    assert modules[2] == body["screens"][0]["modules"][2]


def test_screens_can_be_added_moved_and_deleted_but_not_all_of_them() -> None:
    body = _board()
    added = canvas_domain.apply_ops(body, [{"op": "add_screen", "screen": _screen("s2")}])
    assert [s["id"] for s in added["screens"]] == ["s1", "s2"]
    # The new screen is placed to the right, not on top of the first one.
    assert added["screens"][1]["pos"]["x"] > added["screens"][0]["frame"]["width"]

    moved = canvas_domain.apply_ops(
        added, [{"op": "move_screen", "id": "s2", "dx": 40, "dy": 20}],
    )
    assert moved["screens"][1]["pos"] == {
        "x": added["screens"][1]["pos"]["x"] + 40,
        "y": added["screens"][1]["pos"]["y"] + 20,
    }

    back = canvas_domain.apply_ops(added, [{"op": "delete_screen", "id": "s2"}])
    assert [s["id"] for s in back["screens"]] == ["s1"]
    try:
        canvas_domain.apply_ops(_board(), [{"op": "delete_screen", "id": "s1"}])
    except CanvasError as e:
        assert "保留一屏" in str(e)
    else:  # pragma: no cover
        raise AssertionError("deleted the only screen")


def test_edges_are_a_flow_between_existing_screens() -> None:
    body = _board(_screen("s1"), _screen("s2"))
    linked = canvas_domain.apply_ops(
        body, [{"op": "link_screens", "from": "s1", "to": "s2", "label": "开始选购"}],
    )
    assert linked["edges"] == [{"from": "s1", "to": "s2", "label": "开始选购"}]
    # Linking twice does not duplicate the edge.
    again = canvas_domain.apply_ops(
        linked, [{"op": "link_screens", "from": "s1", "to": "s2"}],
    )
    assert len(again["edges"]) == 1
    unlinked = canvas_domain.apply_ops(
        again, [{"op": "unlink_screens", "from": "s1", "to": "s2"}],
    )
    assert unlinked["edges"] == []

    for bad, needle in (
        ({"op": "link_screens", "from": "s1", "to": "s1"}, "连到自己"),
        ({"op": "link_screens", "from": "s1", "to": "nope"}, "已有的两屏"),
    ):
        try:
            canvas_domain.apply_ops(body, [bad])
        except CanvasError as e:
            assert needle in str(e)
        else:  # pragma: no cover
            raise AssertionError(f"accepted {bad}")


def test_deleting_a_screen_drops_its_edges() -> None:
    body = _board(_screen("s1"), _screen("s2"))
    linked = canvas_domain.apply_ops(body, [{"op": "link_screens", "from": "s1", "to": "s2"}])
    out = canvas_domain.apply_ops(linked, [{"op": "delete_screen", "id": "s2"}])
    assert out["edges"] == []


def test_variants_copy_a_screen_side_by_side_and_are_tagged() -> None:
    body = canvas_domain.validate_board(_board())
    copies = canvas_domain.variants_of(body, "s1", 3)
    assert [c["id"] for c in copies] == ["s1-v1", "s1-v2", "s1-v3"]
    assert all(c["variant_of"] == "s1" for c in copies)
    assert len({c["pos"]["x"] for c in copies}) == 3  # side by side, not stacked
    module_ids = {m["id"] for c in copies for m in c["modules"]}
    assert len(module_ids) == 3  # one per copy: ids stay unique
    assert not module_ids & {m["id"] for m in body["screens"][0]["modules"]}


def test_keeping_one_variant_drops_its_siblings() -> None:
    base = _board()
    body = canvas_domain.validate_board(
        {**base, "screens": [*base["screens"], *canvas_domain.variants_of(base, "s1", 3)]}
    )
    assert len(body["screens"]) == 4
    kept = canvas_domain.apply_ops(body, [{"op": "keep_variant", "id": "s1-v2"}])
    # The survivor keeps the ORIGINAL screen id, so edges pointing at `s1` keep working; the
    # chosen variant's content is what stays.
    assert [s["id"] for s in kept["screens"]] == ["s1"]
    assert "variant_of" not in kept["screens"][0]
    try:
        canvas_domain.apply_ops(_board(), [{"op": "keep_variant", "id": "s1"}])
    except CanvasError as e:
        assert "变体" in str(e)
    else:  # pragma: no cover
        raise AssertionError("kept a screen with no variants")


def test_an_old_single_page_body_is_read_as_one_screen() -> None:
    """A Version written before the board shape must still open, not 500."""
    old = {"frame": FRAME, "modules": [_module("m1")]}
    body = canvas_domain.upgrade(old)
    assert [s["id"] for s in body["screens"]] == ["s1"]
    assert body["screens"][0]["modules"][0]["id"] == "m1"
    validated = canvas_domain.validate_board(old)
    assert validated["screens"][0]["frame"] == FRAME


def test_an_image_module_must_use_an_canvas_image_slot() -> None:
    image = _module("m1", "image", slot="image")
    try:
        canvas_domain.validate_board(_board(_screen(modules=[image])))
    except CanvasError as e:
        assert "canvas_image" in str(e)
    else:  # pragma: no cover
        raise AssertionError("accepted a foreign image slot")


def test_manifest_covers_image_modules_only() -> None:
    body = _board(_screen(modules=[_module("m1"), _module("m2", "image")]))
    assert canvas_domain.manifest_for(body, {"m2": "ver_x"}) == {"m2": "ver_x"}
    assert canvas_domain.manifest_for(body, {"canvas_image_1": "ver_y"}) == {"m2": "ver_y"}


def test_bounds_cover_every_screen() -> None:
    body = _board(
        _screen("s1"),
        _screen("s2", pos={"x": 1600, "y": 40}),
    )
    bounds = canvas_domain.board_bounds(body)
    assert bounds["x"] == 0 and bounds["y"] == 0
    assert bounds["width"] == 1600 + FRAME["width"]
    assert bounds["height"] == 40 + FRAME["height"]


def test_a_closed_slot_cannot_receive_an_artifact() -> None:
    """docs/architecture/data-and-contracts.md: a registered but closed type cannot get an Artifact. `enabled` must mean that."""
    from dataclasses import replace

    from app.domain import slots as registry

    closed = replace(registry.get_slot("canvas"), enabled=False)
    original = registry._SLOTS["canvas"]  # the registry is module state, as in production
    registry._SLOTS["canvas"] = closed
    try:
        assert not registry.is_open("canvas")
        assert "canvas" not in registry.open_slots_for_task_kind("canvas")
        assert not registry.allows_slot("canvas", "canvas")
        assert not registry.allows_slot("general", "canvas")
        # A name that is not a registered slot is governed elsewhere, not by `enabled`.
        assert registry.is_open("canvas_image_1")
        assert registry.is_open("notes.md")
    finally:
        registry._SLOTS["canvas"] = original


# ---- the Task ---------------------------------------------------------------
def test_a_canvas_task_starts_blank_and_a_picture_request_draws_one(api: Api) -> None:
    task = api.task("canvas")
    empty = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert empty["version_id"] is None and empty["screens"] == []

    api.say(task["id"], "一张深色极简的咖啡店海报")
    board = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert board["version_id"]
    assert [s["id"] for s in board["screens"]] == ["s1"]
    screen = board["screens"][0]
    assert screen["name"] == "一张深色极简的咖啡店海报"
    # The sentence became the picture, not a product page: one image module, prompt kept.
    (module,) = screen["modules"]
    assert module["kind"] == "image"
    assert module["prompt"] == "一张深色极简的咖啡店海报"
    assert module["url"], "the picture should be drawn in the same turn"
    assert board["theme"]["colors"]["bg"] == "#FFFFFF"

    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    assert any(a["kind"] == "canvas" and a["slot"] == "canvas" for a in arts)
    assert api.task_state(task["id"])["status"] == "awaiting_user"


def test_a_drag_becomes_a_user_version_without_a_run(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    before = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    runs_before = len(api.http.get(f"/api/tasks/{task['id']}/timeline").json())
    credits_before = api.http.get("/api/me").json()["credits"]
    start_x = before["screens"][0]["modules"][0]["rect"]["x"]

    r = api.http.post(
        f"/api/versions/{before['version_id']}/canvas-patches",
        json={"ops": [{"op": "move_module", "screen": "s1", "id": "m1", "dx": 0.1, "dy": 0.05}]},
    )
    assert r.status_code == 200, r.text
    made = r.json()
    assert made["created_by"] == "user" and made["origin"] == "user"
    rect = made["content"]["screens"][0]["modules"][0]["rect"]
    # The module nearly fills the screen, so a +0.1 move is clamped to the right edge.
    assert rect["x"] == round(min(start_x + 0.1, 1 - rect["w"]), 6)

    after = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert after["version_id"] == made["id"]
    assert len(api.http.get(f"/api/tasks/{task['id']}/timeline").json()) == runs_before
    assert api.http.get("/api/me").json()["credits"] == credits_before

    # The old board is still openable and can be made current again.
    old = api.http.get(f"/api/versions/{before['version_id']}").json()
    assert old["status"] == "ok"
    again = api.http.post(f"/api/versions/{before['version_id']}/make-current").json()
    assert again["id"] == before["version_id"]


def test_the_user_can_add_a_screen_and_link_it_with_one_patch(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "做一版 A+ 首屏")
    base = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    second = {
        "id": "s2", "name": "卖点", "frame": dict(FRAME),
        "modules": [_module("s2m1")],
    }
    r = api.http.post(
        f"/api/versions/{base['version_id']}/canvas-patches",
        json={"ops": [{"op": "add_screen", "screen": second}]},
    )
    assert r.status_code == 200, r.text
    made = r.json()
    assert len(made["content"]["screens"]) == 2
    linked = api.http.post(
        f"/api/versions/{made['id']}/canvas-patches",
        json={"ops": [{"op": "link_screens", "from": "s1", "to": "s2", "label": "了解更多"}]},
    )
    assert linked.status_code == 200, linked.text
    board = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert board["edges"] == [{"from": "s1", "to": "s2", "label": "了解更多"}]
    assert len(board["screens"]) == 2


def test_a_stale_base_is_refused(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "做一版 A+ 首屏")
    first = api.http.get(f"/api/tasks/{task['id']}/canvas").json()["version_id"]
    api.http.post(
        f"/api/versions/{first}/canvas-patches",
        json={"ops": [{"op": "move_module", "screen": "s1", "id": "m1", "dx": 0.05, "dy": 0}]},
    )
    stale = api.http.post(
        f"/api/versions/{first}/canvas-patches",
        json={"ops": [{"op": "move_module", "screen": "s1", "id": "m1", "dx": 0.05, "dy": 0}]},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_CANVAS"


def test_bad_ops_are_refused_without_a_version(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "做一版 A+ 首屏")
    vid = api.http.get(f"/api/tasks/{task['id']}/canvas").json()["version_id"]
    bad = api.http.post(
        f"/api/versions/{vid}/canvas-patches",
        json={"ops": [{"op": "move_module", "screen": "s1", "id": "nope", "dx": 0.1, "dy": 0}]},
    )
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "BAD_CANVAS"
    assert api.http.get(f"/api/tasks/{task['id']}/canvas").json()["version_id"] == vid


def test_a_general_task_gains_a_canvas_on_first_use(api: Api) -> None:
    task = api.task("general", kind="general", goal="给这把剃须刀做 A+ 和 PDP")
    before = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    assert not any(a["kind"] == "canvas" for a in before)

    api.say(task["id"], "做一版 A+ 首屏")
    arts = api.http.get(f"/api/tasks/{task['id']}/artifacts").json()
    canvas = next(a for a in arts if a["kind"] == "canvas")
    assert canvas["current_version_id"]
    body = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert body["version_id"] == canvas["current_version_id"]

    # The same conversation can still write a PDP slot: the canvas did not become the Task.
    api.say(task["id"], "写标题")
    assert len(api.slot_versions(task["id"], "title")) == 1
    later = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert later["version_id"] == body["version_id"]


def test_asking_for_variants_puts_screens_side_by_side(api: Api) -> None:
    task = api.task("canvas")
    api.say(task["id"], "做一版 A+ 首屏")
    api.say(task["id"], "给我三个不同风格的方案")
    board = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    assert len(board["screens"]) == 4  # the original plus three copies
    assert {s.get("variant_of") for s in board["screens"] if s.get("variant_of")} == {"s1"}
    assert board["bounds"]["width"] > FRAME["width"] * 2

    kept = api.http.post(
        f"/api/versions/{board['version_id']}/canvas-patches",
        json={"ops": [{"op": "keep_variant", "id": "s1-v2"}]},
    )
    assert kept.status_code == 200, kept.text
    after = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    # Converged to one screen: the chosen variant's content under the original id, so a
    # clickable flow that points at `s1` still resolves.
    assert [s["id"] for s in after["screens"]] == ["s1"]


def test_a_picture_pointer_from_another_task_is_dropped(api: Api) -> None:
    """A module may only point at this Task's picture. A foreign version id is ignored."""
    canvas_task = api.task("canvas")
    api.say(canvas_task["id"], "一张深色极简的咖啡店海报")
    other = api.task("image", kind="image", upload_id=api.upload_png())
    foreign = api.slot_versions(other["id"], "image")[0]["id"]

    with api.c.uow_factory() as uow:
        task = uow.collab.get_task(canvas_task["id"])
        current = uow.collab.canvas_version(task.id)
        assert current is not None
        module = current.content["screens"][0]["modules"][0]
        made = uow.collab.commit_canvas_version(
            task_id=task.id, content=current.content, base_version_id=current.id,
            created_by="agent", run_id=None,
            pointers={module["id"]: foreign, module["slot"]: foreign},
        )
        uow.commit()
        # The pointer is not this task's Version, so the board keeps the picture it had.
        assert made.manifest == current.manifest
        assert module["id"] not in made.manifest or made.manifest[module["id"]] != foreign


def test_a_rejected_canvas_does_not_move_the_pointer(api: Api) -> None:
    """No layout evaluator is registered yet, so this checks the path with a stand-in."""
    from app.evaluators.base import EvalResult, Evaluator, EvaluatorRegistry
    from app.runtime.commit import commit_output
    from app.tools.canvas_tools import CanvasOutput

    task = api.task("canvas")
    api.say(task["id"], "一张深色极简的咖啡店海报")
    body = api.http.get(f"/api/tasks/{task['id']}/canvas").json()
    good = body["version_id"]

    class AlwaysFails(Evaluator):
        id = "canvas_stand_in"
        description = "stand-in: refuses every canvas Version"
        can_reject = True

        def applies_to(self, subject: Any) -> bool:
            return subject.slot == "canvas"

        def evaluate(self, subject: Any) -> EvalResult:
            return EvalResult(passed=False, details={"problems": ["test rule"]})

    ev = EvaluatorRegistry()
    ev.register(AlwaysFails())
    current = api.http.get(f"/api/versions/{good}").json()["content"]
    new_body = canvas_domain.apply_ops(
        current, [{"op": "move_module", "screen": "s1", "id": "m1", "dx": -0.02, "dy": 0}],
    )
    vid = commit_output(
        api.c.uow_factory, ev, api.c.store, run_id="run_x", task_id=task["id"], kind="canvas",
        task_meta={}, rules=[], slot="canvas",
        output=CanvasOutput(slot="canvas", content=new_body, params={}),
        base_version_id=good,
    )
    assert api.http.get(f"/api/versions/{vid}").json()["status"] == "rejected"
    assert api.http.get(f"/api/tasks/{task['id']}/canvas").json()["version_id"] == good


def test_a_reference_must_be_another_picture_on_the_board() -> None:
    morning = _module("m-morning", "image", slot="canvas_image_1", prompt="晨光")
    night = _module("m-night", "image", slot="canvas_image_2", prompt="夜景", ref="m-morning")
    board = canvas_domain.validate_board(_board(_screen(modules=[morning, night])))
    assert board["screens"][0]["modules"][1]["ref"] == "m-morning"

    cases = (
        _board(_screen(modules=[
            morning, _module("m-night", "image", slot="canvas_image_2", ref="missing"),
        ])),
        _board(_screen(modules=[
            _module("m-morning", "image", slot="canvas_image_1", ref="m-morning"),
        ])),
    )
    for bad in cases:
        try:
            canvas_domain.validate_board(bad)
        except CanvasError as e:
            assert "参考图" in str(e)
        else:  # pragma: no cover
            raise AssertionError("accepted a dangling or self reference")


def test_deleting_the_reference_picture_clears_the_link() -> None:
    morning = _module("m-morning", "image", slot="canvas_image_1")
    night = _module("m-night", "image", slot="canvas_image_2", ref="m-morning")
    title = _module("m-title", "image", slot="canvas_image_3")
    board = canvas_domain.validate_board(_board(_screen(modules=[morning, night, title])))
    out = canvas_domain.apply_ops(
        board, [{"op": "delete_module", "screen": "s1", "id": "m-morning"}],
    )
    left = {m["id"]: m for m in out["screens"][0]["modules"]}
    assert "ref" not in left["m-night"]


def test_reference_of_follows_another_modules_picture_not_a_self_edit() -> None:
    content = {"screens": [{"modules": [
        {"id": "a", "kind": "image"}, {"id": "b", "kind": "image"},
    ]}]}
    manifest = {"a": "v-a", "b": "v-old"}

    def content_of(vid: str) -> dict[str, str] | None:
        return {"object_key": "k-a"} if vid == "v-a" else None

    assert canvas_domain.reference_of(
        content, manifest, content_of,
        reference_object_key="k-a", base_version_id=None, self_id="b",
    ) == "a"
    assert canvas_domain.reference_of(
        content, manifest, content_of,
        reference_object_key=None, base_version_id="v-a", self_id="b",
    ) == "a"
    # Editing b from its own previous picture is not a line back to itself.
    assert canvas_domain.reference_of(
        content, manifest, content_of,
        reference_object_key=None, base_version_id="v-old", self_id="b",
    ) is None


def test_opening_a_template_seeds_finished_pictures_and_a_placeholder(api: Api) -> None:
    listed = api.http.get("/api/canvas-templates").json()
    assert {row["id"] for row in listed} >= {"morning-night", "three-frames"}

    opened = api.http.post("/api/canvas-templates/morning-night")
    assert opened.status_code == 201, opened.text
    task_id = opened.json()["id"]
    board = api.http.get(f"/api/tasks/{task_id}/canvas").json()
    modules = {m["id"]: m for s in board["screens"] for m in s["modules"]}
    assert modules["m-morning"]["url"]
    assert "拿铁" in modules["m-morning"]["prompt"]
    assert modules["m-night"]["ref"] == "m-morning"
    assert modules["m-night"]["url"]
    assert "夜晚" in modules["m-night"]["prompt"]
    assert modules["m-title"]["url"] is None
    assert "Morning" in modules["m-title"]["prompt"]
    assert api.http.post("/api/canvas-templates/no-such").status_code == 404
