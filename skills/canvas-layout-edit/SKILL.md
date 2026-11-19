---
description: Change only the module or screen the user pointed at; keep the rest of the board untouched.
audience: canvas
---

# canvas-layout-edit

The user's sentence usually names one thing: a module ("标题再大一点", "这张图往右") or a screen
("第二屏太挤", "删掉最后一屏").

Recommended order:

1. `read_canvas` to get the exact current board — screens, their positions, modules, theme.
2. Change only the named item:
   - a module: its `rect`, its `style`, its `text`, its `prompt`, or the picture it points at;
   - a screen: its `pos`, `name`, `frame.height`, or which screens it links to.
   Keep every other screen's `pos`, every other module's `rect`, and every picture pointer
   exactly as they were.
3. Write with `compose_canvas`, passing the current canvas Version as `base_version_id`.
4. If the sentence could mean two different modules, ask which one. Do not guess and do not
   re-lay out the board to "improve" it.

Never answer a local comment by rebuilding the whole board. Never resize a neighbour to make
room for a change the user did not ask for. Never move a variant on top of another screen.

If the user wants a new picture for a module, that is an image change:
`edit_product_image` for an existing picture (or `generate_product_image` when the module has
none), then `compose_canvas` with `pointers` for that module only. Update the module's `prompt`
to match, so the board still records how the picture was made.

If the user wants a different look for a whole screen rather than a fix, that is exploration —
use `generate_variants` instead of rewriting the board in place.
