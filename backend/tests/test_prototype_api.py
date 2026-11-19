"""API behind the prototype views: products, timeline, registry pages, gallery slot."""

from __future__ import annotations

from typing import Any

from tests.conftest import Api


def _samples(api: Api) -> dict[str, dict[str, Any]]:
    r = api.http.post("/api/products/samples")
    assert r.status_code == 200, r.text
    return {p["brand"]: p for p in r.json()}


def test_samples_are_real_listings_and_loading_twice_does_not_duplicate(api: Api) -> None:
    first = _samples(api)
    assert set(first) == {"EchoByte", "NKTMXY"}
    assert first["NKTMXY"]["mode"] == "optimize" and first["EchoByte"]["mode"] == "generate"
    assert first["EchoByte"]["facts"]["attributes"]["Colour"] == "Gunmetal Grey"
    assert len(first["EchoByte"]["gallery_urls"]) == 7
    again = _samples(api)
    assert {p["id"] for p in again.values()} == {p["id"] for p in first.values()}
    assert len(api.http.get("/api/products").json()) == 2
    blob = api.http.get(first["NKTMXY"]["main_url"])
    assert blob.status_code == 200 and blob.content[:4] == b"\x89PNG"


def test_import_product_makes_imported_first_versions_and_edits_stay_in_their_slot(
    api: Api,
) -> None:
    nk = _samples(api)["NKTMXY"]
    t = api.task(product_id=nk["id"], import_product=True, goal="")
    assert t["product_id"] == nk["id"] and "导入优化" in t["goal"]
    assert t["meta"]["product"]["brand"] == "NKTMXY"
    state = api.task_state(t["id"])
    assert state["status"] == "awaiting_user"
    for slot in ("title", "bullets", "main_image", "secondary_image"):
        vs = api.slot_versions(t["id"], slot)
        assert [v["origin"] for v in vs] == ["imported"], slot
    assert state["current"]["description"] is None  # the saved listing has none: stays empty
    main = api.slot_versions(t["id"], "main_image")[0]
    # the NKTMXY main image is a composite on white: the baseline is recorded, not blocked
    assert main["status"] == "ok" and main["evaluations"], "baseline evaluated on import"
    assert api.task_state(t["id"])["current"]["main_image"] == main["id"]
    gallery = api.slot_versions(t["id"], "secondary_image")[0]
    assert len(gallery["content"]["urls"]) == 6
    before = dict(state["current"])
    api.say(t["id"], "标题更突出防水")
    after = api.task_state(t["id"])["current"]
    assert after["title"] != before["title"]
    assert {k: v for k, v in after.items() if k != "title"} == {
        k: v for k, v in before.items() if k != "title"
    }
    detail = api.http.get(f"/api/products/{nk['id']}").json()
    assert [x["id"] for x in detail["tasks"]] == [t["id"]]


def test_gallery_slot_is_not_edited_and_the_feedback_says_why(api: Api) -> None:
    nk = _samples(api)["NKTMXY"]
    t = api.task(product_id=nk["id"], import_product=True)
    run = api.say(t["id"], "把副图都换掉")
    assert run["status"] == "succeeded"
    assert len(api.slot_versions(t["id"], "secondary_image")) == 1  # nothing was written
    fb = api.http.get(f"/api/tasks/{t['id']}/feedback").json()[-1]
    assert fb["status"] == "declined" and "副图" in fb["note"]


def test_timeline_rebuilds_the_conversation_from_runs(api: Api) -> None:
    t = api.task()
    api.say(t["id"], "第一版")
    api.say(t["id"], "标题不要超过 20 个字符；标题更突出防水")
    tl = api.http.get(f"/api/tasks/{t['id']}/timeline").json()
    assert [x["user"]["text"] for x in tl] == ["第一版", "标题不要超过 20 个字符；标题更突出防水"]
    first, second = tl
    assert first["status"] == "succeeded" and first["cost"] == 20
    assert [s["slot"] for s in first["steps"]] == [
        "title", "bullets", "description", "search_terms",
    ]
    slot_versions = [v for v in first["versions"] if v["kind"] != "pdp"]
    assert {v["slot"] for v in slot_versions} == {
        "title", "bullets", "description", "search_terms",
    }
    assert any(v["kind"] == "pdp" for v in first["versions"])
    kinds = {i["kind"] for i in second["interpretations"]}
    # One sentence is one Feedback now (decisions/0044). The rule is recorded by a tool, so the
    # turn reads as a rule turn; the edit it also asked for is visible as a new version.
    assert kinds == {"new_constraint"}
    pending = next(i for i in second["interpretations"] if i["kind"] == "new_constraint")
    assert pending["constraint_status"] == "pending" and pending["constraint_id"]
    edited = next(v for v in second["versions"] if v["kind"] != "pdp")
    assert edited["slot"] == "title" and edited["parent_content"] is not None


def test_timeline_marks_a_rejected_version_with_the_failed_rule(api: Api) -> None:
    t = api.task(import_listing={"title": "x" * 300, "bullets": ["b"] * 5})
    api.say(t["id"], "标题改短一点")
    run = api.http.get(f"/api/tasks/{t['id']}/timeline").json()[0]
    v = next(x for x in run["versions"] if x["kind"] != "pdp")
    assert v["status"] == "rejected" and v["is_current"] is False
    assert any(e["problems"] for e in v["evaluations"] if not e["passed"])


def test_tools_skills_and_platform_constraints_are_readable_registry_data(api: Api) -> None:
    tools = {t["name"]: t for t in api.http.get("/api/tools").json()}
    assert {"edit_listing", "generate_product_image", "edit_product_image"} <= set(tools)
    detail = api.http.get("/api/tools/edit_product_image").json()
    assert "base_version_id" in detail["input_schema"]["properties"]
    assert detail["description"] and detail["agents"]
    assert api.http.get("/api/tools/nope").status_code == 404
    skills = api.http.get("/api/skills").json()
    assert {s["id"] for s in skills} >= {"image-local-edit", "listing-first-draft"}
    body = api.http.get("/api/skills/image-local-edit").json()
    assert "edit_product_image" in body["tools"] and body["body"].startswith("---")
    rules = api.http.get("/api/constraints/platform").json()
    assert {i["slot"] for i in rules["items"]} >= {"title", "bullets", "main_image"}
    assert all(i["hard"] for i in rules["items"])


def test_search_terms_are_a_slot_with_a_byte_limit_from_the_constraint_pack(api: Api) -> None:
    from app.evaluators.base import EvalSubject
    from app.evaluators.listing_rules import ListingRulesEvaluator

    t = api.task()
    api.say(t["id"], "第一版")
    versions = api.slot_versions(t["id"], "search_terms")
    assert len(versions) == 1 and versions[0]["status"] == "ok"
    ev = ListingRulesEvaluator()

    def check(text: str) -> bool:
        subject = EvalSubject("search_terms", {"text": text}, {}, [], api.c.store)
        return ev.evaluate(subject).passed

    assert check("a" * 249) and not check("a" * 250)
    assert not check("剃" * 84)  # 84 CJK chars = 252 bytes: the limit is bytes, not characters


def test_creating_a_product_from_user_input(api: Api) -> None:
    up = api.upload_png()
    r = api.http.post("/api/products", json={
        "name": "My lamp", "brand": "Lumo", "attributes": {"Colour": "Black"},
        "main_image_upload_id": up, "gallery_upload_ids": [up],
    })
    assert r.status_code == 201 and r.json()["brand"] == "Lumo"
    bad = api.http.post("/api/products", json={"name": "x", "main_image_upload_id": "nope"})
    assert bad.status_code == 400
    other = api.http.get("/api/products", headers={"X-User-Id": "someone-else"}).json()
    assert other == []  # products belong to their user


def test_importing_a_whole_listing_makes_one_first_pdp_version(api: Api) -> None:
    nk = _samples(api)["NKTMXY"]
    t = api.task(product_id=nk["id"], import_product=True, goal="")
    arts = api.http.get(f"/api/tasks/{t['id']}/artifacts").json()
    pdp = next(a for a in arts if a["kind"] == "pdp")
    assert [v["seq"] for v in pdp["versions"]] == [1]
    assert set(pdp["versions"][0]["manifest"]) >= {"title", "bullets", "main_image"}
