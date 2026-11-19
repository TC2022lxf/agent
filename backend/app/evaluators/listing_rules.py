from __future__ import annotations

from app.constraints import load_pack
from app.evaluators.base import EvalResult, EvalSubject, Evaluator


class ListingRulesEvaluator(Evaluator):
    id = "listing_rules"
    description = (
        "Checks title, bullets and description against the platform constraint pack and "
        "any confirmed user max_chars rules."
    )
    can_reject = True

    def applies_to(self, subject: EvalSubject) -> bool:
        return subject.slot in {"title", "bullets", "description", "search_terms"}

    def evaluate(self, subject: EvalSubject) -> EvalResult:
        pack = load_pack()
        problems: list[str] = []
        texts = (
            subject.content.get("items", [])
            if subject.slot == "bullets"
            else [subject.content.get("text", "")]
        )
        if subject.slot == "title" and len(texts[0]) > pack["title"]["max_chars"]:
            problems.append(f"title longer than {pack['title']['max_chars']}")
        if subject.slot == "description" and len(texts[0]) > pack["description"]["max_chars"]:
            problems.append("description too long")
        if subject.slot == "search_terms":
            limit = pack["search_terms"]["max_bytes"]
            if len(texts[0].encode("utf-8")) > limit:
                problems.append(f"search terms longer than {limit} bytes")
        if subject.slot == "bullets":
            if len(texts) != pack["bullets"]["count"]:
                problems.append(f"expected {pack['bullets']['count']} bullets, got {len(texts)}")
            if any(len(t) > pack["bullets"]["max_chars_each"] for t in texts):
                problems.append("a bullet is too long")
        for rule in subject.user_rules:
            if rule.get("type") == "max_chars" and rule.get("slot") == subject.slot:
                if any(len(t) > int(rule["value"]) for t in texts):
                    problems.append(f"user rule: {subject.slot} > {rule['value']} chars")
        return EvalResult(passed=not problems, details={"problems": problems})
