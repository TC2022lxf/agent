"""Measurements of a product picture against the platform main-image rules.

This lives outside the evaluator because three things need the same numbers and they must
agree exactly: the evaluator that rejects a Version, `inspect_image` (what the planner reads
before submitting) and `fix_image` (what a deterministic repair aims at). Two copies of the
formula would drift, and a model told "border white fraction 0.31" would be chasing a number
nobody else computes the same way.

Everything here is pure: bytes in, numbers out. `evaluator` and `fix` are the two callers.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageDraw


@dataclass(frozen=True)
class Metrics:
    width: int
    height: int
    long_side: int
    white_fraction: float
    occupancy: float
    bbox: tuple[int, int, int, int] | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "long_side": self.long_side,
            "border_white_fraction": round(self.white_fraction, 3),
            "occupancy": round(self.occupancy, 3),
            "subject_bbox": list(self.bbox) if self.bbox else None,
            "square": self.width == self.height,
        }


def measure(png: bytes, *, background_min_channel: int) -> Metrics:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = img.size
    px = img.load()
    assert px is not None
    lo = background_min_channel
    border = (
        [(x, 0) for x in range(w)]
        + [(x, h - 1) for x in range(w)]
        + [(0, y) for y in range(h)]
        + [(w - 1, y) for y in range(h)]
    )
    white = sum(1 for p in border if min(px[p[0], p[1]]) >= lo) / len(border)
    # "Product" = pixels that are not near-white. A dark subject on a white sweep is the
    # normal case; a light product on white is measured by its shadows instead, which is
    # why the rule is a floor and not an exact reading.
    r, g, b = img.split()
    min_channel = ImageChops.darker(ImageChops.darker(r, g), b)
    bbox = min_channel.point(lambda v: 255 if v < lo else 0).getbbox()
    occupancy = max((bbox[2] - bbox[0]) / w, (bbox[3] - bbox[1]) / h) if bbox else 0.0
    return Metrics(
        width=w, height=h, long_side=max(w, h),
        white_fraction=white, occupancy=occupancy,
        bbox=tuple(bbox) if bbox else None,
    )


def problems(metrics: Metrics, cfg: dict[str, Any]) -> list[str]:
    """The same wording the evaluator records, so a model can compare its own reading."""
    out: list[str] = []
    if metrics.long_side < cfg["min_long_side_px"]:
        out.append(f"long side {metrics.long_side} < {cfg['min_long_side_px']}")
    if metrics.white_fraction < cfg["background_border_fraction"]:
        out.append(f"border white fraction {metrics.white_fraction:.2f}")
    if metrics.occupancy < cfg["occupancy_min"]:
        out.append(f"occupancy {metrics.occupancy:.2f} < {cfg['occupancy_min']}")
    return out


def repair(
    png: bytes,
    *,
    background_min_channel: int,
    target_occupancy: float,
    target_white_fraction: float,
    square: bool = True,
    min_side: int = 0,
) -> tuple[bytes, dict[str, Any]]:
    """Deterministic repair of the measurable failures, without a vendor call.

    Order matters and is the whole trick:

    1. Whiten the background by flood-filling inward from the border over pixels close to the
       corner colour. Only background-like pixels are touched, so the product is not clipped.
    2. Crop to the subject and lay it on a white canvas sized so BOTH rules hold: the canvas
       is at least `min_side` (or the subject's own size) and small enough that the subject
       covers `target_occupancy` of it. The subject is scaled to exactly that coverage, which
       is why a small product picture stays compliant: without the scale, a 1000px minimum
       and 85% occupancy cannot both hold for a 600px subject.

    The product itself is never repainted — only its scale and the space around it change.
    """
    img = Image.open(io.BytesIO(png)).convert("RGB")
    before = measure(png, background_min_channel=background_min_channel)

    whitened = _whiten_background(img)
    mid = measure(_png(whitened), background_min_channel=background_min_channel)
    out = whitened
    if mid.bbox is not None:
        subject = whitened.crop(mid.bbox)
        longest = max(subject.size)
        # A hair of margin: rounding must not land at 0.849 when the rule needs 0.85.
        want_side = int(longest / max(target_occupancy, 0.05)) + 1
        side = max(want_side, min_side, longest)
        if square:
            side = min(side, 4096)
            cover = min(side, int(side * target_occupancy) + 2)
            scaled = _fit(subject, cover)
            canvas = Image.new("RGB", (side, side), (255, 255, 255))
            canvas.paste(
                scaled, ((side - scaled.width) // 2, (side - scaled.height) // 2),
            )
        else:
            pad = max(2, int(round(longest * max(target_occupancy, 0.05) / target_occupancy * 0.02)))
            canvas = Image.new(
                "RGB",
                (subject.width + 2 * pad, subject.height + 2 * pad),
                (255, 255, 255),
            )
            canvas.paste(subject, (pad, pad))
        out = canvas
    after = measure(_png(out), background_min_channel=background_min_channel)
    notes: dict[str, Any] = {
        "before": before.as_dict(),
        "after": after.as_dict(),
        "improved": (
            after.white_fraction >= target_white_fraction
            and after.occupancy >= target_occupancy
        ),
    }
    return _png(out), notes


def _fit(img: Image.Image, box: int) -> Image.Image:
    """Scale to fit a `box` square and centre it, keeping the aspect ratio."""
    copy = img.copy()
    copy.thumbnail((box, box), Image.LANCZOS)
    # `thumbnail` only shrinks; a subject smaller than the box must grow to reach the target.
    if copy.width < box or copy.height < box:
        scale = min(box / img.width, box / img.height)
        copy = img.resize(
            (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
            Image.LANCZOS,
        )
    return copy


def _whiten_background(img: Image.Image) -> Image.Image:
    """Turn the background into pure white by flooding inward from the border.

    The corner colour is the background's own colour, so no threshold has to be tuned per
    picture. A photo with a gradient sweep only whitens where the gradient is within the
    tolerance of the corner — the rest stays as it was, which is honest: this repair cannot
    fix a busy background, and pretending it did would hide the failure.
    """
    out = img.convert("RGB").copy()
    w, h = out.size
    seeds = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    corner = out.getpixel((0, 0))
    tolerance = 40
    for seed in seeds:
        try:
            ImageDraw.floodfill(out, seed, (255, 255, 255), thresh=tolerance)
        except ValueError:  # a seed outside the image; nothing to fill from there
            continue
    if _distance(out.getpixel((0, 0)), corner) > tolerance:
        return out
    return out


def _distance(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return max(abs(int(x) - int(y)) for x, y in zip(a, b, strict=False))


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
