"""Model profiles (plan L1). Names and parameters live here, not in Tool code."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.persistence.models import ModelProfile
from app.services.console import MODEL_KEY, ConsoleService

PLANNER_KEY = "gpt-6.1-sol"
IMAGE_KEY = "gemini-3.1-flash-image"
IMAGE_SETTING = "image.profile"
SUMMARY_FRACTION = "summary.fraction"
SUMMARY_KEEP = "summary.keep_messages"
MAX_TOOL_CALLS = "runtime.max_tool_calls"
# Follow-up chips are optional and cost one extra call, so they have their own switch and
# their own model binding: a small model writes them as well as the planner does.
FOLLOWUPS_ENABLED = "followups.enabled"
FOLLOWUPS_MODEL = "followups.model"

_AGENTS = ("general", "amazon_pdp", "image")


class ProfileDisabled(Exception):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"model profile {key} is disabled")


def _planner_seed(key: str = PLANNER_KEY) -> ModelProfile:
    return ModelProfile(
        key=key,
        upstream_model=key,
        kind="planner",
        # The planner bound by default is a 1M-context model. Change this per profile in the
        # console when you bind a different model; the compaction trigger reads it.
        context_window_tokens=1_000_000,
        reasoning={
            "mode": "optional",
            "effort_values": ["low", "medium", "high"],
            "default": "medium",
            "param": "reasoning_effort",
        },
        when_thinking_enabled={"reasoning_effort": "medium"},
        when_thinking_disabled={},
        # `vision`: the planner is sent the task's current picture so it can answer "what
        # colour is it" instead of "I cannot read that". Verified against the bound model,
        # not assumed from its name (decisions/0041).
        capabilities=["plan", "vision"],
        price={"per_million_input": 0, "per_million_output": 0, "per_image": 0},
        param_schema={},
        enabled=True,
    )


def _image_seed(key: str = IMAGE_KEY) -> ModelProfile:
    return ModelProfile(
        key=key,
        upstream_model=key,
        kind="image",
        context_window_tokens=0,
        reasoning={"mode": "unsupported"},
        when_thinking_enabled={},
        when_thinking_disabled={},
        capabilities=["image.generate", "image.edit", "image.chat"],
        price={"per_million_input": 0, "per_million_output": 0, "per_image": 1},
        param_schema={"size": {"type": "integer"}, "aspect_ratio": {"type": "string"}},
        enabled=True,
    )


def thinking_params(profile: ModelProfile, reasoning_on: bool) -> dict[str, Any]:
    """Fields to merge into a planner request. Unsupported profiles contribute nothing."""
    mode = str((profile.reasoning or {}).get("mode", "unsupported"))
    if mode == "unsupported":
        return {}
    if mode == "required" or reasoning_on:
        return dict(profile.when_thinking_enabled or {})
    return dict(profile.when_thinking_disabled or {})


def profile_view(row: ModelProfile) -> dict[str, Any]:
    return {
        "key": row.key,
        "upstream_model": row.upstream_model,
        "kind": row.kind,
        "context_window_tokens": row.context_window_tokens,
        "reasoning": row.reasoning,
        "when_thinking_enabled": row.when_thinking_enabled,
        "when_thinking_disabled": row.when_thinking_disabled,
        "capabilities": list(row.capabilities or []),
        "price": row.price,
        "param_schema": row.param_schema,
        "enabled": row.enabled,
    }


class ProfileService:
    def __init__(self, session: Session) -> None:
        self.s = session
        self.console = ConsoleService(session)

    def ensure_seed(
        self,
        *,
        planner_model: str = "",
        image_model: str = "",
    ) -> None:
        planner_key = planner_model.strip() or PLANNER_KEY
        image_key = image_model.strip() or IMAGE_KEY

        if self.s.get(ModelProfile, planner_key) is None:
            self.s.add(_planner_seed(planner_key))
        elif planner_model.strip():
            row = self.get(planner_key)
            if row is not None:
                row.upstream_model = planner_key
        if planner_key == PLANNER_KEY:
            self._repair_planner_window()
        self._repair_planner_vision(planner_key)

        image = self.s.get(ModelProfile, image_key)
        if image is None:
            self.s.add(_image_seed(image_key))
        else:
            if image_model.strip():
                image.upstream_model = image_key
            if "image.chat" not in (image.capabilities or []):
                # A row created before decision 0022 lacks the shape flag; add it, keep the rest.
                image.capabilities = [*(image.capabilities or []), "image.chat"]
        self.s.flush()
        for agent in _AGENTS:
            key = MODEL_KEY.format(key=agent)
            if planner_model.strip():
                self.console.put(key, planner_key)
            elif self.console.get(key, "") in {"", "fake"}:
                self.console.put(key, PLANNER_KEY)
        if image_model.strip():
            self.console.put(IMAGE_SETTING, image_key)
        elif not self.console.get(IMAGE_SETTING):
            self.console.put(IMAGE_SETTING, IMAGE_KEY)
        if not self.console.get(SUMMARY_FRACTION):
            self.console.put(SUMMARY_FRACTION, "0.7")
        if not self.console.get(SUMMARY_KEEP):
            self.console.put(SUMMARY_KEEP, "20")
        if not self.console.get(MAX_TOOL_CALLS):
            self.console.put(MAX_TOOL_CALLS, "8")

    def get(self, key: str) -> ModelProfile | None:
        return self.s.get(ModelProfile, key)

    def _repair_planner_window(self) -> None:
        """The seed's window used to be 128k, which is wrong for the bound 1M model.

        Only rewrite the value the seed itself shipped; an operator's own number is kept.
        """
        row = self.get(PLANNER_KEY)
        if row is not None and row.context_window_tokens == 128_000:
            row.context_window_tokens = 1_000_000
            self.s.flush()

    def _repair_planner_vision(self, planner_key: str) -> None:
        """Give planners created before `vision` existed the flag, once.

        A planner that can see was answering "I cannot read the picture" purely because its
        profile said `["plan"]`. Guarded by a setting so it happens once: after this, the
        capabilities column is the operator's to control, including removing `vision`.
        """
        marker = "runtime.vision_migrated"
        if self.console.get(marker):
            return
        for key in (planner_key, PLANNER_KEY):
            row = self.get(key)
            if row is None or row.kind != "planner":
                continue
            caps = list(row.capabilities or [])
            if "plan" in caps and "vision" not in caps:
                row.capabilities = [*caps, "vision"]
        self.console.put(marker, "1")
        self.s.flush()

    def list(self) -> list[ModelProfile]:
        return list(self.s.scalars(select(ModelProfile).order_by(ModelProfile.key)))

    def planner_for_agent(self, agent_key: str) -> ModelProfile:
        bound = self.console.get(MODEL_KEY.format(key=agent_key), "") or PLANNER_KEY
        row = self.get(bound)
        if row is None:
            row = self.get(PLANNER_KEY)
        if row is None:
            raise ProfileDisabled(bound)
        if not row.enabled:
            raise ProfileDisabled(row.key)
        if row.kind != "planner":
            raise ProfileDisabled(row.key)
        return row

    def image_profile(self) -> ModelProfile | None:
        bound = self.console.get(IMAGE_SETTING, "") or IMAGE_KEY
        row = self.get(bound)
        if row is None or not row.enabled or row.kind != "image":
            return None
        return row

    def summary_fraction(self) -> float:
        raw = self.console.get(SUMMARY_FRACTION, "0.7") or "0.7"
        try:
            return float(raw)
        except ValueError:
            return 0.7

    def summary_keep(self) -> int:
        raw = self.console.get(SUMMARY_KEEP, "20") or "20"
        try:
            return max(1, int(raw))
        except ValueError:
            return 20

    def max_tool_calls(self) -> int:
        raw = self.console.get(MAX_TOOL_CALLS, "8") or "8"
        try:
            return max(1, int(raw))
        except ValueError:
            return 8

    def followups_enabled(self) -> bool:
        return (self.console.get(FOLLOWUPS_ENABLED, "1") or "1") not in {"0", "false", "off"}

    def followups_model(self) -> str:
        """The profile that writes follow-up questions; empty means "same as the planner".

        A suggestion is one short call with no tools and no artifacts, so a cheap model is
        enough. Binding it separately keeps the planner's cost and quality untouched.
        """
        return self.console.get(FOLLOWUPS_MODEL, "").strip()

    def save(self, key: str, fields: dict[str, Any]) -> ModelProfile:
        row = self.get(key)
        if row is None:
            row = ModelProfile(
                key=key,
                upstream_model=str(fields.get("upstream_model") or key),
                kind=str(fields.get("kind") or "planner"),
            )
            self.s.add(row)
        for name in (
            "upstream_model", "kind", "context_window_tokens", "reasoning",
            "when_thinking_enabled", "when_thinking_disabled", "capabilities",
            "price", "param_schema", "enabled",
        ):
            if name in fields and fields[name] is not None:
                setattr(row, name, fields[name])
        self.s.flush()
        return row

    def bind_image(self, key: str) -> None:
        row = self.get(key)
        if row is None or not row.enabled or row.kind != "image":
            raise ProfileDisabled(key)
        self.console.put(IMAGE_SETTING, key)
