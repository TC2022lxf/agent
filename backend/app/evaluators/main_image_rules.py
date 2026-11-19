from __future__ import annotations

import io

from PIL import Image, ImageChops

from app.constraints import load_pack
from app.evaluators.base import EvalResult, EvalSubject, Evaluator


class MainImageRulesEvaluator(Evaluator):
    id = "main_image_rules"
    description = (
        "Checks a main image: pure-white border, minimum size and product occupancy, "
        "with numbers from the platform constraint pack."
    )
    can_reject = True

    def applies_to(self, subject: EvalSubject) -> bool:
        return subject.slot == "main_image" or (
            subject.slot == "image" and subject.task_meta.get("profile") == "main_image"
        )

    def evaluate(self, subject: EvalSubject) -> EvalResult:
        cfg = load_pack()["main_image"]
        img = Image.open(io.BytesIO(subject.store.get(subject.content["object_key"]))).convert(
            "RGB"
        )
        problems: list[str] = []
        w, h = img.size
        if max(w, h) < cfg["min_long_side_px"]:
            problems.append(f"long side {max(w, h)} < {cfg['min_long_side_px']}")
        px = img.load()
        assert px is not None
        lo = cfg["background_min_channel"]
        border = (
            [(x, 0) for x in range(w)]
            + [(x, h - 1) for x in range(w)]
            + [(0, y) for y in range(h)]
            + [(w - 1, y) for y in range(h)]
        )
        white = sum(
            1 for p in border if min(px[p[0], p[1]]) >= lo  # type: ignore[arg-type,misc]
        ) / len(border)
        if white < cfg["background_border_fraction"]:
            problems.append(f"border white fraction {white:.2f}")
        # product bbox = pixels that are not near-white
        r, g, b = img.split()
        min_channel = ImageChops.darker(ImageChops.darker(r, g), b)
        bbox = min_channel.point(lambda v: 255 if v < lo else 0).getbbox()
        occupancy = max((bbox[2] - bbox[0]) / w, (bbox[3] - bbox[1]) / h) if bbox else 0.0
        if occupancy < cfg["occupancy_min"]:
            problems.append(f"occupancy {occupancy:.2f} < {cfg['occupancy_min']}")
        return EvalResult(
            passed=not problems,
            details={"problems": problems, "white_fraction": white, "occupancy": occupancy},
        )
