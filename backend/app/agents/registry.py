"""Agent, Tool and Skill registration (docs/architecture/agent-runtime.md). Registration fails without descriptions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.agents.skills import Skill, agent_audience, parse_skill
from app.tools.base import Tool


@dataclass(frozen=True)
class AgentSpec:
    key: str
    title: str
    description: str
    system_prompt_ref: str
    tool_names: tuple[str, ...]
    skill_ids: tuple[str, ...]
    artifact_kinds: tuple[str, ...]  # what its workbenches can open
    workbench: str  # pdp | image | general
    task_kind: str | None  # kind of Task created from this Agent's entry (None = chosen by user)


class Registry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._agents: dict[str, AgentSpec] = {}
        self._skills: dict[str, Skill] = {}
        self._shipped: dict[str, str] = {}  # id -> body as shipped in the repo file

    # tools
    def register_tool(self, tool: Tool) -> None:
        m = tool.meta
        if not m.description.strip():
            raise ValueError(f"tool {m.name}: description is required")
        if m.cost_credits < 0 or m.timeout_s <= 0:
            raise ValueError(f"tool {m.name}: invalid cost/timeout metadata")
        self._tools[m.name] = tool

    def tool(self, name: str) -> Tool:
        return self._tools[name]

    def tools(self) -> list[Tool]:
        return list(self._tools.values())

    # skills
    def load_skills(self, root: Path) -> None:
        for md in sorted(root.glob("*/SKILL.md")):
            text = md.read_text(encoding="utf-8")
            skill = parse_skill(md.parent.name, text)
            if not skill.description.strip():
                raise ValueError(f"skill {skill.id}: description is required")
            self._skills[skill.id] = skill
            self._shipped[skill.id] = text

    def load_skill_text(
        self, skill_id: str, text: str, *, revision: int = 0, source: str = "edited",
    ) -> Skill:
        """An edited copy replaces the file text in the registry. The file is left as shipped."""
        skill = parse_skill(skill_id, text)
        if not skill.description.strip():
            raise ValueError(f"skill {skill_id}: description is required")
        replaced = Skill(
            id=skill.id, description=skill.description, body=skill.body,
            content_hash=skill.content_hash, audience=skill.audience,
            revision=revision, source=source,
        )
        self._skills[skill_id] = replaced
        return replaced

    def shipped_text(self, skill_id: str) -> str:
        return self._shipped.get(skill_id, "")

    def skill(self, skill_id: str) -> Skill:
        return self._skills[skill_id]

    def has_skill(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    def skills_for(self, agent_key: str) -> list[Skill]:
        """A specialist sees only its own audience. The general entry sees every Skill."""
        audience = agent_audience(agent_key)
        if agent_key == "general":
            return self.skills()
        return [s for s in self.skills() if s.audience in {audience, "any"}]

    # agents
    def register_agent(self, spec: AgentSpec) -> None:
        allowed = {s.id for s in self.skills_for(spec.key)}
        for t in spec.tool_names:
            if t not in self._tools:
                raise ValueError(f"agent {spec.key}: unknown tool {t}")
        for s in spec.skill_ids:
            if s not in self._skills:
                raise ValueError(f"agent {spec.key}: unknown skill {s}")
            if s not in allowed:
                raise ValueError(f"agent {spec.key}: skill {s} is for another audience")
        self._agents[spec.key] = spec

    def register_aggregate(
        self, key: str, title: str, description: str, members: tuple[str, ...]
    ) -> AgentSpec:
        """`general`: union of the members' Tools and kinds; every Skill, not only theirs."""
        specs = [self._agents[m] for m in members]
        spec = AgentSpec(
            key=key,
            title=title,
            description=description,
            system_prompt_ref="general",
            tool_names=_union(s.tool_names for s in specs),
            skill_ids=tuple(s.id for s in self.skills()),
            artifact_kinds=_union(s.artifact_kinds for s in specs),
            workbench="general",
            task_kind=None,
        )
        self._agents[key] = spec
        return spec

    def grant(
        self, key: str, *, tools: tuple[str, ...] = (), skills: tuple[str, ...] = (),
        kinds: tuple[str, ...] = (),
    ) -> AgentSpec:
        """Add tools this agent owns itself. Members' tools stay a union, not a copy."""
        spec = self._agents[key]
        for t in tools:
            if t not in self._tools:
                raise ValueError(f"agent {key}: unknown tool {t}")
        for s in skills:
            if s not in self._skills:
                raise ValueError(f"agent {key}: unknown skill {s}")
        granted = AgentSpec(
            key=spec.key,
            title=spec.title,
            description=spec.description,
            system_prompt_ref=spec.system_prompt_ref,
            tool_names=_union([spec.tool_names, tools]),
            skill_ids=_union([spec.skill_ids, skills]),
            artifact_kinds=_union([spec.artifact_kinds, kinds]),
            workbench=spec.workbench,
            task_kind=spec.task_kind,
        )
        self._agents[key] = granted
        return granted

    def agent(self, key: str) -> AgentSpec:
        return self._agents[key]

    def agents(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def has_agent(self, key: str) -> bool:
        return key in self._agents


def _union(groups: object) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for g in groups:  # type: ignore[attr-defined]
        for item in g:
            seen.setdefault(item, None)
    return tuple(seen)
