---
description: Explore directions by branching one screen into side-by-side variants, then converge.
audience: canvas
---

# canvas-explore-variants

Use this when the user wants options instead of one answer: 「几个方案」「不同风格」「给我三版」.

Recommended order:

1. `read_canvas` to see the board and pick the screen to branch from.
2. `generate_variants(screen_id, count, base_version_id)`. It places 2–4 copies to the right
   of the original, tagged `variant_of`. The copies start IDENTICAL.
3. Edit each copy with `compose_canvas` so the options genuinely differ. Vary ONE dimension at
   a time and say which in your reply:
   - layout: module order, split ratio between text and picture;
   - colour: pick different theme colours (add a token if the theme has only one accent);
   - copy: a different promise per option, still supported by what the user actually said.
4. Leave all copies on the board. The user converges with 「保留这个」, which drops the others.

Never present identical copies as alternatives. Never delete variants yourself. Never move a
variant on top of another screen: the copies are placed side by side on purpose.
