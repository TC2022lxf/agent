---
description: Build a canvas board from the user's sentence, with screens, modules and a theme.
audience: canvas
---

# canvas-first-draft

A canvas is a BOARD: screens laid out side by side on a surface, each screen holding modules
(text and pictures) with a position and a size. One board = one Version.

The board is a **blank surface**. What goes on it comes from the user's sentence — a poster, a
landing page, a product page, a social image, a diagram. Do not assume e-commerce, and do not
assume Amazon: unless the user says "Amazon" or "A+", it is just a design.

Recommended order:

1. `read_canvas` first. If it returns a blank board, this is the first draft.
2. Decide the screens before any copy: usually one screen is enough; add a second only when
   the content genuinely needs its own frame. Do not pad the board to look busy.
3. For each screen decide its modules: what text blocks, what pictures, and roughly where.
   Leave a screen empty if you do not yet know what belongs on it.
4. Set the theme once: `colors` (`bg`, `fg`, `accent`, `muted`) and `fonts` (`display`,
   `body`). Every text module then names a token (`"color": "fg"`, `"font": "display"`).
   Never put a raw hex on a module.
5. Call `compose_canvas` with the whole board: `theme`, `screens`, `edges`. Every module needs
   `id` (unique across the whole board), `kind`, `rect` (fractions of ITS screen) and `style`.
   Image modules need `slot` (`canvas_image_1`, `canvas_image_2`, …).
6. Pictures: if a module has no picture yet, call `generate_product_image` with that
   `canvas_image_N` slot and the prompt the user described, then `compose_canvas` with
   `pointers` mapping the module id to the new image Version, and put the same prompt on the
   module so it stays readable. Never invent a picture inside `compose_canvas`.
7. Add `edges` (`{from, to, label}`) when the user talks about what happens on click. Do not
   invent a flow nobody asked for.

Screens are placed in world pixels: put the second screen to the right of the first, not on
top of it. Width is 1280 by default; change it only if the user names a size or ratio.

Copy: write what the user's sentence supports. If they gave facts (specs, price, claims), stay
inside them; if they gave none, write plain descriptive copy rather than inventing numbers. Do
not treat this as a whiteboard: no free drawing, no arbitrary fonts, no layers.
