---
description: Change part of an image from a circled region, always starting from a base version.
audience: any
---

# image-local-edit

Recommended order:

1. If no image version exists, `generate_product_image` once.
2. From the second version on, use `edit_product_image(base_version_id, patch, region)`.
   Never re-roll the whole picture to answer a local comment.
3. Pass the user's circled `region` unchanged; do not widen it.
4. `product_scale`, `upscale`, `remove_bg` are experimental: say they are unavailable instead of faking.
