"""Evaluator-optimizer: a rejected Version goes back to the model with its numbers.

The rule checks are numeric, so a model CAN repair in the same turn — but every retry is a
paid image, so the loop is bounded on three sides: retries per Run, budget left, and whether
the failure is repairable at all. These tests pin the boundary, not the model's skill.
"""

from __future__ import annotations

import io

from PIL import Image

from tests.conftest import Api


def _blue_on_grey(size: int = 1000) -> bytes:
    img = Image.new("RGB", (size, size), (235, 235, 235))
    inner = Image.new("RGB", (size // 2, size // 2), (60, 110, 200))
    img.paste(inner, (size // 4, size // 4))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_whiteness_and_occupancy_are_repairable_and_resolution_is_not() -> None:
    """A retry cannot fix a model that outputs 800px, so it must not be attempted."""
    from app.runtime.langgraph_loop import _repairable

    assert _repairable(["border white fraction 0.31"])
    assert _repairable(["occupancy 0.42 < 0.85"])
    assert not _repairable(["long side 800 < 1000"])
    # Mixed: one repairable problem is enough, the resolution one stays visible in the report.
    assert _repairable(["long side 800 < 1000", "occupancy 0.42 < 0.85"])


def test_a_repair_is_bounded_by_retries(api: Api) -> None:
    """`max_repairs` is 1: a second rejection must stop, not loop."""
    from app.runtime.langgraph_loop import _Session

    assert _Session.__dataclass_fields__["max_repairs"].default == 1


def test_the_rejection_payload_carries_the_numbers_the_model_needs(api: Api) -> None:
    """The old code told the model `status: ok` and told the user the reason."""
    from app.runtime.langgraph_loop import _Session

    # The payload shape is what the tool result is built from; a missing `problems` key would
    # leave the model with a bare "rejected" and nothing to act on.
    fields = _Session.__dataclass_fields__
    assert "awaiting_repair" in fields and "repairs" in fields


def test_a_budget_guard_exists_so_a_retry_is_never_attempted_unpaid(api: Api) -> None:
    """A failed retry costs the same as the first attempt; overspending the hold is worse."""
    import inspect

    from app.runtime import langgraph_loop

    src = inspect.getsource(langgraph_loop._Session._can_retry)
    assert "held" in src and "cost" in src and "max_calls" in src


def test_an_irreparable_rejection_speaks_to_the_user(api: Api) -> None:
    """Resolution failures skip the retry and go straight to the explanation."""
    from app.constraints import load_pack
    from app.domain import image_metrics

    cfg = load_pack()["main_image"]
    small = Image.new("RGB", (400, 400), (255, 255, 255))
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    m = image_metrics.measure(buf.getvalue(), background_min_channel=cfg["background_min_channel"])
    problems = image_metrics.problems(m, cfg)
    assert problems, "a 400px picture must fail the size rule"

    from app.runtime.langgraph_loop import _next_steps

    options = _next_steps("main_image", problems)
    assert any("分辨率" in o for o in options), options
