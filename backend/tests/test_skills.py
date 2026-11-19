"""Skill audience rules and editing (docs/13). Edits are revisions, not file overwrites."""

from __future__ import annotations

from app.agents.builtin import build_registry
from tests.conftest import Api


def test_general_sees_every_skill_specialists_see_their_own() -> None:
    r = build_registry()
    general = {s.id for s in r.skills_for("general")}
    pdp = {s.id for s in r.skills_for("amazon_pdp")}
    img = {s.id for s in r.skills_for("image")}
    assert {"pdp-search-terms", "pdp-compliance-review"} <= pdp
    assert {"image-first-draft", "image-secondary"} <= img
    assert "pdp-search-terms" not in img
    assert "image-secondary" not in pdp
    assert "image-local-edit" in pdp and "image-local-edit" in img
    assert pdp | img <= general
    assert {"brainstorming", "frontend-design", "writing-plans"} <= general


def test_migrated_deerflow_skills_still_require_a_description() -> None:
    r = build_registry()
    for skill in r.skills():
        assert skill.description.strip(), skill.id
        assert skill.audience in {"general", "pdp", "image", "canvas", "any"}


def test_agent_skill_list_uses_the_audience(api: Api) -> None:
    pdp = {s["id"] for s in api.http.get("/api/agents/amazon_pdp/skills").json()}
    img = {s["id"] for s in api.http.get("/api/agents/image/skills").json()}
    gen = {s["id"] for s in api.http.get("/api/agents/general/skills").json()}
    assert "pdp-search-terms" in pdp and "pdp-search-terms" not in img
    assert "image-first-draft" in img and "image-first-draft" not in pdp
    assert {"brainstorming", "pdp-search-terms", "image-first-draft"} <= gen


def test_edit_is_a_revision_and_the_file_is_untouched(api: Api) -> None:
    before = api.http.get("/api/skills/pdp-search-terms").json()
    assert before["revision"] == 0
    body = before["body"].replace("# 后台关键词", "# 后台关键词（改过）")
    saved = api.http.put(
        "/api/skills/pdp-search-terms", json={"body": body, "base_revision": 0},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 1
    assert saved.json()["source"] == "edited"
    assert "改过" in saved.json()["body"]
    assert (api.c.settings.skill_dir / "pdp-search-terms" / "SKILL.md").read_text(
        encoding="utf-8",
    ).startswith("---")


def test_stale_save_is_rejected_instead_of_overwriting(api: Api) -> None:
    first = api.http.get("/api/skills/pdp-search-terms").json()
    body = first["body"] + "\n"
    ok = api.http.put(
        "/api/skills/pdp-search-terms", json={"body": body, "base_revision": 0},
    )
    assert ok.status_code == 200
    stale = api.http.put(
        "/api/skills/pdp-search-terms",
        json={"body": body + "\n另一处改动\n", "base_revision": 0},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "STALE_SKILL"
    latest = api.http.get("/api/skills/pdp-search-terms").json()
    assert latest["revision"] == 1
    assert "另一处改动" not in latest["body"]


def test_revision_history_and_reset_to_shipped_text(api: Api) -> None:
    original = api.http.get("/api/skills/pdp-search-terms").json()["body"]
    api.http.put(
        "/api/skills/pdp-search-terms",
        json={"body": original + "\n", "base_revision": 0},
    )
    revs = api.http.get("/api/skills/pdp-search-terms/revisions").json()
    assert [r["revision"] for r in revs] == [1]
    assert revs[0]["edited_by"]

    reset = api.http.post("/api/skills/pdp-search-terms/reset")
    assert reset.status_code == 200
    back = reset.json()
    assert back["revision"] == 2 and back["source"] == "restored"
    assert back["body"] == original


def test_edit_without_description_is_rejected(api: Api) -> None:
    bad = "---\naudience: pdp\n---\n\n没有说明\n"
    r = api.http.put("/api/skills/pdp-search-terms", json={"body": bad, "base_revision": 0})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "BAD_SKILL"
