"""Product service: facts and imported listing the Agent may use (docs/09).

Samples are real saved listings from `fixtures/` loaded through the same path as user input.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import Product, Task
from app.ports import ObjectStorePort
from app.services.collab import NotFound

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures"

# slug -> (display name, mode). `generate`: facts only, the Agent writes the first version.
# `optimize`: the saved listing is imported as the first version, then improved.
SAMPLES: dict[str, tuple[str, str]] = {
    "echobyte-razor": ("EchoByte 电动剃须刀 · Gunmetal Grey", "generate"),
    "foil-shaver-com": ("NKTMXY 迷你电动剃须刀", "optimize"),
}


class ProductService:
    def __init__(self, session: Session) -> None:
        self.s = session

    def create(
        self,
        user_id: str,
        *,
        name: str,
        brand: str = "",
        marketplace: str = "",
        mode: str = "generate",
        facts: dict[str, Any] | None = None,
        listing: dict[str, Any] | None = None,
        assets: dict[str, Any] | None = None,
        sample_key: str | None = None,
    ) -> Product:
        p = Product(
            user_id=user_id, name=name, brand=brand, marketplace=marketplace, mode=mode,
            facts=facts or {}, listing=listing or {}, assets=assets or {}, sample_key=sample_key,
        )
        self.s.add(p)
        self.s.flush()
        return p

    def list_for(self, user_id: str) -> list[Product]:
        return list(
            self.s.scalars(
                select(Product).where(Product.user_id == user_id).order_by(Product.created_at)
            )
        )

    def get(self, product_id: str, user_id: str) -> Product:
        p = self.s.get(Product, product_id)
        if p is None or p.user_id != user_id:
            raise NotFound(product_id)
        return p

    def tasks_of(self, product_id: str) -> list[Task]:
        return list(
            self.s.scalars(
                select(Task).where(Task.product_id == product_id).order_by(Task.created_at.desc())
            )
        )

    def seed_samples(self, user_id: str, store: ObjectStorePort) -> list[Product]:
        """Idempotent: a sample already loaded for this user is returned, not duplicated."""
        out: list[Product] = []
        for slug, (name, mode) in SAMPLES.items():
            existing = self.s.scalar(
                select(Product).where(Product.user_id == user_id, Product.sample_key == slug)
            )
            if existing is not None:
                out.append(existing)
                continue
            src = FIXTURES_DIR / slug
            data = json.loads((src / "product.json").read_text(encoding="utf-8"))
            main, gallery = _store_images(store, slug, src, data["images"])
            listing = data["listing"]
            out.append(
                self.create(
                    user_id,
                    name=name,
                    brand=data.get("brand", ""),
                    marketplace=data.get("marketplace", ""),
                    mode=mode,
                    sample_key=slug,
                    facts={
                        "attributes": data.get("attributes", {}),
                        "rating": data.get("rating"),
                        "price_text": data.get("price_text"),
                        "category_path": data.get("category_path", []),
                        "observations": data.get("observations", []),
                    },
                    listing={
                        "title": listing.get("title"),
                        "bullets": [b["text"] for b in listing.get("bullets", [])] or None,
                        "description": listing.get("description"),
                        "search_terms": listing.get("search_terms"),
                    },
                    assets={"main": main, "gallery": gallery},
                )
            )
        return out


def _store_images(
    store: ObjectStorePort, slug: str, src: Path, images: list[dict[str, Any]]
) -> tuple[str | None, list[str]]:
    main: str | None = None
    gallery: list[str] = []
    for im in images:
        buf = io.BytesIO()
        Image.open(src / im["file"]).convert("RGB").save(buf, format="PNG")
        key = f"samples/{slug}/{Path(im['file']).stem}.png"
        store.put(key, buf.getvalue())
        if im["slot"] == "main_image":
            main = key
        else:
            gallery.append(key)
    return main, gallery
