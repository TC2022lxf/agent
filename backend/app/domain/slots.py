"""Slot registry (docs/09). Slots are read from here, never hard-coded elsewhere.

File tasks have no fixed slots. `write_file` creates one artifact per file name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SlotDef:
    key: str
    # text | bullets | image | gallery (several images; imported and shown, edits come later)
    # | canvas (a laid-out page of modules; the module list lives in the Version body)
    value_type: str
    artifact_kind: str  # text | image | canvas
    max_items: int
    description: str
    aspect_ratio: str = ""  # Gemini ratios like 1:1; empty means the vendor default
    enabled: bool = True  # registered but not yet open: cannot create an Artifact


_SLOTS: dict[str, SlotDef] = {
    s.key: s
    for s in [
        SlotDef("title", "text", "text", 1, "PDP title"),
        SlotDef("bullets", "bullets", "text", 5, "PDP five bullet points"),
        SlotDef("description", "text", "text", 1, "PDP description"),
        SlotDef("search_terms", "text", "text", 1, "PDP backend search terms (not on the page)"),
        # Amazon requires a square main image; the ratio is a slot fact, not a model choice.
        SlotDef("main_image", "image", "image", 1, "PDP main image", aspect_ratio="1:1"),
        SlotDef("secondary_image", "gallery", "image", 9, "PDP secondary images (imported)"),
        SlotDef("image", "image", "image", 1, "Standalone image task artifact"),
        # The board lives in the Version body, so one slot holds the whole canvas (0029).
        SlotDef(
            "canvas", "canvas", "canvas", 1,
            "Design canvas: a board of screens, each laying out text and image modules",
        ),
    ]
}

# Image modules of a canvas are separate image artifacts, named canvas_image_1, canvas_image_2…
# The numbered key is created on first write, like a file name (decisions/0029).
CANVAS_SLOT = "canvas"
CANVAS_MODULE_PREFIX = "canvas_image_"
_CANVAS_MODULE = re.compile(r"^canvas_image_([1-9][0-9]?)$")

# Which slots a Task kind owns. First-draft text slots are those of kind "text".
# `general` owns no fixed slot: the Agent creates a file or image artifact when it needs one.
_TASK_KIND_SLOTS: dict[str, tuple[str, ...]] = {
    "pdp": (
        "title", "bullets", "description", "search_terms", "main_image", "secondary_image",
    ),
    "image": ("image",),
    "file": (),
    "general": (),
    "canvas": (CANVAS_SLOT,),
}

# A general Task is the one place several artifact kinds live together: the same
# conversation can hold written PDP slots, a picture, and a file (decisions/0019, 0020).
# A canvas Task holds its canvas, the canvas' image modules, and the exported file (0025).
_MULTI_ARTIFACT_KINDS = frozenset({"general", "canvas"})

# Slots that belong to the PDP manifest. Writing one of these from a general Task
# creates the `pdp` artifact on first use. Ordered: the planner sees this order.
PDP_SLOT_ORDER: tuple[str, ...] = (
    "title", "bullets", "description", "search_terms", "main_image", "secondary_image",
)
PDP_SLOT_KEYS = frozenset(PDP_SLOT_ORDER)

# Text the model may write. PDF, images and media are previewed from a blob URL, not from this tool.
_TEXT_EXT: dict[str, tuple[str, str]] = {
    "html": ("text/html", "html"),
    "htm": ("text/html", "html"),
    "md": ("text/markdown", "markdown"),
    "markdown": ("text/markdown", "markdown"),
    "csv": ("text/csv", "table"),
    "tsv": ("text/tab-separated-values", "table"),
}
_BINARY_EXT = frozenset({
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "svg",
    "mp3", "wav", "mp4", "webm", "ogg", "mov",
})
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
MAX_FILE_CHARS = 200_000

IMAGE_SLOT_KEYS = frozenset(k for k, s in _SLOTS.items() if s.value_type == "image")
GALLERY_SLOT_KEYS = frozenset(k for k, s in _SLOTS.items() if s.value_type == "gallery")


def canvas_module_index(key: str) -> int | None:
    """`canvas_image_3` -> 3. Module keys are created on first write, like file names."""
    m = _CANVAS_MODULE.match(key)
    return int(m.group(1)) if m else None


def canvas_module_slot(index: int) -> str:
    return f"{CANVAS_MODULE_PREFIX}{index}"


def is_canvas_slot(key: str) -> bool:
    return key == CANVAS_SLOT


def is_image_slot(key: str) -> bool:
    """Anything whose Version content is `object_key` + width + height (docs/09)."""
    return key in IMAGE_SLOT_KEYS or canvas_module_index(key) is not None


def get_slot(key: str) -> SlotDef:
    return _SLOTS[key]


def has_slot(key: str) -> bool:
    return key in _SLOTS


def all_slots() -> list[SlotDef]:
    return list(_SLOTS.values())


def slots_for_task_kind(kind: str) -> tuple[str, ...]:
    return _TASK_KIND_SLOTS[kind]


def open_slots_for_task_kind(kind: str) -> tuple[str, ...]:
    """The slots of this kind a Task starts with: a closed type gets no Artifact (docs/09)."""
    return tuple(s for s in _TASK_KIND_SLOTS[kind] if is_open(s))


def is_open(slot: str) -> bool:
    """A registered slot may be closed: `docs/09` says a closed type cannot get an Artifact."""
    d = _SLOTS.get(slot)
    if d is None:
        return True  # a canvas module instance or a file name: not a registered slot
    return d.enabled


def task_kinds() -> list[str]:
    return list(_TASK_KIND_SLOTS)


def text_slots_for_task_kind(kind: str) -> tuple[str, ...]:
    return tuple(s for s in _TASK_KIND_SLOTS[kind] if _SLOTS[s].artifact_kind == "text")


def is_multi_artifact(kind: str) -> bool:
    return kind in _MULTI_ARTIFACT_KINDS


def aspect_ratio_for(slot: str) -> str | None:
    """The ratio a slot expects, or None to let the vendor decide."""
    s = _SLOTS.get(slot)
    return s.aspect_ratio or None if s is not None else None


def is_pdp_slot(key: str) -> bool:
    """Writing one of these updates (and on a general Task, creates) the PDP manifest."""
    return key in PDP_SLOT_KEYS



def allows_slot(kind: str, slot: str) -> bool:
    """`target_slot` and Tool output must pass this.

    A general Task is the flexible one: it may write any PDP slot, the standalone image, the
    canvas, a canvas module's picture, or a file name. the `pdp` and `canvas` artifacts appear
    the first time one of their slots is written (decisions/0020, 0025). A canvas Task may
    write its canvas, the canvas' image modules, the standalone image and a file name (the
    exported HTML).
    """
    if slot in _TASK_KIND_SLOTS.get(kind, ()):
        return is_open(slot)
    if kind == "canvas":
        return is_image_slot(slot) or is_file_slot(slot)
    if not is_multi_artifact(kind):
        return False
    if is_canvas_slot(slot) or canvas_module_index(slot) is not None:
        return is_open(slot)
    if slot in PDP_SLOT_KEYS or slot == "image":
        return is_open(slot)
    return is_file_slot(slot)


def may_write(kind: str, slot: str) -> bool:
    """Whether a Version for `slot` may exist at all in a Task of this kind.

    `allows_slot` answers "may `target_slot` be this?" and is what the API validates. This is
    the runtime-side check and differs in one place: a `file` Task owns no fixed slots, so its
    only legal slots are file names, which `allows_slot` cannot say.
    """
    if kind == "file":
        return is_file_slot(slot)
    return allows_slot(kind, slot)


def normalize_file_name(raw: str) -> str:
    """A single file name. Directories, `..` and extension-less names are rejected."""
    name = raw.strip()
    if "/" in name or "\\" in name or name.startswith("."):
        raise ValueError(name)
    if not _FILE_NAME.match(name) or "." not in name:
        raise ValueError(name)
    return name


def is_file_slot(key: str) -> bool:
    try:
        return normalize_file_name(key) == key
    except ValueError:
        return False


def file_extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower()


def is_binary_file(name: str) -> bool:
    return file_extension(name) in _BINARY_EXT


def file_type(name: str) -> tuple[str, str]:
    """`(mime, media)` where media is html, markdown, table, or download."""
    ext = file_extension(name)
    return _TEXT_EXT.get(ext, ("text/plain", "download"))
