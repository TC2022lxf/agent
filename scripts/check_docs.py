"""Offline checks for the shared human/agent workspace (Python standard library only).

Scope: root Markdown and docs/ Markdown, plus explanations in owned Python/TS/TSX/CSS.
Supports Markdown inline/image links, reference links, ATX/setext headings, duplicate and
Unicode anchors, percent-encoded relative paths, and source #Lx-Ly fragments. Fenced/inline
code is not interpreted as a link. Raw HTML links and external destinations are not checked.
Unparsed ]( destinations are reported, not silently accepted as verified. JS explanations
use a small string-aware comment lexer, not a complete TypeScript parser; template bodies
are ignored. This is a structural gate, not proof of product requirements or security.
"""
from __future__ import annotations

import argparse
import ast
import html
import io
import re
import tokenize
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

REQUIRED_FILES = (
    "README.md", "AGENTS.md", "CONTRIBUTING.md", "docs/README.md",
    "docs/product/requirements.md", "docs/product/capabilities.md", "docs/product/acceptance.md",
    "docs/architecture/system.md", "docs/architecture/agent-runtime.md",
    "docs/architecture/data-and-contracts.md", "docs/development/local-development.md",
    "docs/development/extension-guide.md", "docs/quality/test-strategy.md",
    "docs/quality/traceability.md", "docs/operations/runbook.md",
    "docs/exploration/current-state.md", "docs/releases/2026-11-19-baseline-verification.md",
    "docs/generated/api.md", "docs/generated/agents.md", "docs/generated/tools.md",
    "docs/generated/skills.md", "docs/generated/slots.md", "docs/generated/evaluators.md",
    ".github/workflows/verify.yml",
)
OLD_FILES = (
    "docs/decisions/0041-review-context-and-vision.md",
    "docs/decisions/0042-suggested-follow-ups.md",
    "docs/decisions/0043-tool-execution-cards.md",
    "docs/decisions/0044-loop-routing-as-tools.md",
    "docs/decisions/0045-evaluator-optimizer.md",
    "docs/decisions/0046-memory-state-and-token-budget.md",
    "docs/decisions/0047-toolbelt-look-before-acting.md",
    "docs/experiments/2026-11-09-review-context-and-vision.md",
    "docs/experiments/tool-card.png",
)
# Keep traversal bounded: no dependency, user data, design, fixture or runtime-skill scans.
SKIP_PARTS = {".git", ".superpowers", ".venv", "venv", "node_modules", "dist", "build",
              "data", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
              "coverage", "fixtures", "design", "skills"}
LEGACY = re.compile(r"\b(?:docs/\d{2}\b|(?:docs/)?decisions?/\d{4}\b|decision[s]? \d{4}\b|docs/(?:STATUS|TECH|TESTING)\.md)")
INLINE_CODE = re.compile(r"(`+)(?!`)(.*?)(?<!`)\1(?!`)")
# Destinations allow angle paths with spaces, escaped characters and one nested () pair.
INLINE_LINK = re.compile(
    r'''!?\[([^\]\n]*)\]\((<[^>\n]+>|(?:\\.|[^\s()\\]|\((?:\\.|[^()])*\))*)(?:\s+(?:"[^"\n]*"|'[^'\n]*'))?\)'''
)
REF_DEF = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)(?:\s+.*)?$")
REF_LINK = re.compile(r"!?\[([^\]\n]+)\]\[([^\]\n]*)\]")
JS_PARTS = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|(?P<comment>//[^\n]*|/\*.*?\*/)''', re.S)


@dataclass(frozen=True)
class Issue:
    path: str
    line: int
    message: str


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group())


def _without_fences(text: str) -> list[str]:
    result = []
    fence = ""
    length = 0
    for line in text.splitlines():
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if not fence and marker:
            fence, length = marker[1][0], len(marker[1])
            result.append("")
        elif fence:
            if re.match(r"^\s{0,3}" + re.escape(fence) + "{" + str(length) + r",}\s*$", line):
                fence = ""
            result.append("")
        else:
            result.append(line)
    return result


def heading_anchors(text: str) -> set[str]:
    """GitHub-style slugs for our ATX/setext subset, with Unicode and collision suffixes."""
    anchors: set[str] = set()
    lines = _without_fences(text)
    for index, line in enumerate(lines):
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", line)
        title = match[1] if match else ""
        if not title and index + 1 < len(lines) and line.strip():
            if re.fullmatch(r"\s{0,3}(?:=+|-+)\s*", lines[index + 1]):
                title = line.strip()
        if not title:
            continue
        title = INLINE_LINK.sub(lambda m: m[1], title)
        title = re.sub(r"<[^>]+>", "", html.unescape(title))
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        unique, suffix = slug, 0
        while unique in anchors:
            suffix += 1
            unique = f"{slug}-{suffix}"
        anchors.add(unique)
    return anchors


def _ref_key(label: str) -> str:
    return " ".join(label.split()).casefold()


def _markdown_links(path: str, text: str) -> tuple[list[tuple[int, str]], list[Issue]]:
    lines = _without_fences(text)
    definitions: dict[str, str] = {}
    links: list[tuple[int, str]] = []
    issues: list[Issue] = []
    for index, line in enumerate(lines):
        match = REF_DEF.match(line)
        if match:
            definitions.setdefault(_ref_key(match[1]), match[2])
            links.append((index + 1, match[2]))
            lines[index] = ""
    for number, raw in enumerate(lines, 1):
        line = INLINE_CODE.sub(_blank, raw)
        for match in INLINE_LINK.finditer(line):
            links.append((number, match[2]))
        line = INLINE_LINK.sub(_blank, line)
        for match in REF_LINK.finditer(line):
            key = _ref_key(match[2] or match[1])
            if key not in definitions:
                issues.append(Issue(path, number, f"missing reference definition: {key}"))
        line = REF_LINK.sub(_blank, line)
        # Shortcut references are links only when a matching definition exists.
        for match in re.finditer(r"!?\[([^\]\n]+)\]", line):
            if _ref_key(match[1]) in definitions:
                pass  # Definition target was already collected above.
        if re.search(r"(?<!\\)\]\(", line):
            issues.append(Issue(path, number, "unsupported link destination syntax"))
    return links, issues


def _target_issue(root: Path, source: Path, number: int, destination: str) -> Issue | None:
    rel = source.relative_to(root).as_posix()
    destination = destination.removeprefix("<").removesuffix(">")
    destination = re.sub(r"\\([()\[\] ])", r"\1", destination)
    try:
        url = urlsplit(destination)
    except ValueError:
        return Issue(rel, number, f"unsupported link destination: {destination}")
    if url.scheme in {"http", "https", "mailto", "tel"}:
        return None  # No network checks.
    if url.scheme or url.netloc:
        return Issue(rel, number, f"unsupported local link scheme: {destination}")
    target = (source.parent / unquote(url.path)).resolve() if url.path else source.resolve()
    if not target.is_relative_to(root):
        return Issue(rel, number, f"outside workspace: {destination}")
    if not target.is_file():
        return Issue(rel, number, f"missing target: {destination}")
    fragment = unquote(url.fragment)
    if not fragment:
        return None
    try:
        content = _read(target)
    except (OSError, UnicodeError):
        return Issue(rel, number, f"cannot check fragment in target: {destination}")
    line_match = re.fullmatch(r"L(\d+)(?:-L(\d+))?", fragment)
    if target.suffix.lower() != ".md" and line_match:
        start, end = int(line_match[1]), int(line_match[2] or line_match[1])
        if not 1 <= start <= end <= len(content.splitlines()):
            return Issue(rel, number, f"invalid source line range: {destination}")
    elif target.suffix.lower() != ".md" or fragment not in heading_anchors(content):
        return Issue(rel, number, f"missing anchor: {destination}")
    return None


def _bounded_files(folder: Path, suffixes: set[str]) -> Iterator[Path]:
    if not folder.is_dir() or folder.is_symlink():
        return
    for child in sorted(folder.iterdir()):
        if child.name in SKIP_PARTS or child.is_symlink():
            continue
        if child.is_dir():
            yield from _bounded_files(child, suffixes)
        elif child.suffix.lower() in suffixes:
            yield child


def _python_explanations(text: str) -> Iterator[tuple[int, str]]:
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            yield token.start[0], token.string
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr):
                value = body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    yield body[0].lineno, value.value


def _source_explanations(path: Path, text: str) -> Iterator[tuple[int, str]]:
    if path.suffix == ".py":
        yield from _python_explanations(text)
    else:
        for match in JS_PARTS.finditer(text):
            if match.group("comment"):
                yield text.count("\n", 0, match.start()) + 1, match.group()


def _legacy_issues(path: str, fragments: Iterator[tuple[int, str]]) -> Iterator[Issue]:
    for first, text in fragments:
        for offset, line in enumerate(text.splitlines()):
            for match in LEGACY.finditer(line):
                yield Issue(path, first + offset, f"legacy reference: {match[0]}")


def validate_workspace(root: Path) -> list[Issue]:
    root = root.resolve()
    issues: list[Issue] = []
    for name in REQUIRED_FILES:
        path = root / name
        if not path.is_file() or not path.resolve().is_relative_to(root):
            issues.append(Issue(name, 1, "missing required workspace document"))
    for name in OLD_FILES:
        if (root / name).exists():
            issues.append(Issue(name, 1, "old document still present; remove only the approved file"))
    markdown = sorted(root.glob("*.md")) + list(_bounded_files(root / "docs", {".md"}))
    for path in markdown:
        relative = path.relative_to(root).as_posix()
        if not path.resolve().is_relative_to(root):
            issues.append(Issue(relative, 1, "outside workspace document"))
            continue
        try:
            text = _read(path)
            links, parse_issues = _markdown_links(relative, text)
            issues.extend(parse_issues)
            for number, target in links:
                issue = _target_issue(root, path, number, target)
                if issue:
                    issues.append(issue)
            if not relative.startswith(("docs/superpowers/", "docs/generated/")):
                issues.extend(_legacy_issues(relative, iter(enumerate(_without_fences(text), 1))))
        except (OSError, UnicodeError) as error:
            issues.append(Issue(relative, 1, f"cannot read document: {type(error).__name__}"))
    sources: list[Path] = []
    for name in ("backend/app", "backend/tests", "backend/scripts", "frontend/src", "scripts"):
        sources.extend(_bounded_files(root / name, {".py", ".ts", ".tsx", ".css"}))
    vite = root / "frontend/vite.config.ts"
    if vite.is_file():
        sources.append(vite)
    for path in sources:
        rel = path.relative_to(root).as_posix()
        try:
            issues.extend(_legacy_issues(rel, _source_explanations(path, _read(path))))
        except (OSError, UnicodeError, SyntaxError, tokenize.TokenError) as error:
            issues.append(Issue(rel, 1, f"cannot inspect source explanations: {type(error).__name__}"))
    return sorted(set(issues), key=lambda issue: (issue.path, issue.line, issue.message))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    issues = validate_workspace(args.root)
    for issue in issues:
        print(f"{issue.path}:{issue.line}: {issue.message}")
    if issues:
        print(f"FAIL: {len(issues)} documentation issue(s)")
        return 1
    print("OK: required documents, local Markdown links/anchors and owned legacy references")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
