"""The workspace checker validates docs without reading user data or contacting networks."""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("workspace_documentation", ROOT / "scripts/check_docs.py")
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = checker
SPEC.loader.exec_module(checker)


def write(root: Path, name: str, text: str = "# Heading\n") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    for name in checker.REQUIRED_FILES:
        write(tmp_path, name)
    return tmp_path


def messages(root: Path) -> str:
    return "\n".join(i.message for i in checker.validate_workspace(root))


def test_healthy_workspace(workspace: Path) -> None:
    assert checker.validate_workspace(workspace) == []


@pytest.mark.parametrize("name", ["README.md", "AGENTS.md", "docs/product/acceptance.md"])
def test_missing_required_document(workspace: Path, name: str) -> None:
    (workspace / name).unlink()
    assert "missing required" in messages(workspace)


def test_old_document_is_rejected(workspace: Path) -> None:
    write(workspace, checker.OLD_FILES[0])
    assert "old document" in messages(workspace)


def test_missing_target_has_path_and_line(workspace: Path) -> None:
    write(workspace, "README.md", "# Home\n\n[broken](docs/missing.md)\n")
    issues = checker.validate_workspace(workspace)
    assert any(i.path == "README.md" and i.line == 3 and "missing target" in i.message
               for i in issues)


@pytest.mark.parametrize("link", [
    "[inline](docs/topic.md#标题)",
    "![image](docs/topic.md)",
    "[explicit][guide]\n\n[guide]: docs/topic.md#标题",
    "[collapsed][]\n\n[collapsed]: docs/topic.md",
    "[shortcut]\n\n[shortcut]: docs/topic.md",
])
def test_markdown_link_forms(workspace: Path, link: str) -> None:
    write(workspace, "docs/topic.md", "# 标题\n")
    write(workspace, "README.md", link)
    assert checker.validate_workspace(workspace) == []


def test_missing_reference_definition(workspace: Path) -> None:
    write(workspace, "README.md", "[label][undefined]\n")
    assert "missing reference definition" in messages(workspace)


def test_unicode_and_duplicate_heading_anchors(workspace: Path) -> None:
    write(workspace, "docs/topic.md", "# 中文 标题\n# 中文 标题\n")
    write(workspace, "README.md", "[one](docs/topic.md#中文-标题)\n[two](docs/topic.md#中文-标题-1)")
    assert checker.validate_workspace(workspace) == []
    write(workspace, "README.md", "[bad](docs/topic.md#中文-标题-2)")
    assert "missing anchor" in messages(workspace)


def test_same_file_and_setext_heading(workspace: Path) -> None:
    write(workspace, "README.md", "Overview\n========\n\n[here](#overview)\n")
    assert checker.validate_workspace(workspace) == []


def test_heading_inline_markup_uses_visible_text(workspace: Path) -> None:
    write(workspace, "docs/topic.md", "# **Hello** `World`\n")
    write(workspace, "README.md", "[go](docs/topic.md#hello-world)")
    assert checker.validate_workspace(workspace) == []


def test_percent_encoded_path_and_fragment(workspace: Path) -> None:
    write(workspace, "docs/hello world.md", "# 中文\n")
    write(workspace, "README.md", "[go](docs/hello%20world.md#%E4%B8%AD%E6%96%87)")
    assert checker.validate_workspace(workspace) == []


def test_parentheses_and_angle_destination(workspace: Path) -> None:
    write(workspace, "docs/name (one).md")
    write(workspace, "README.md", '[go](<docs/name (one).md> "title")')
    assert checker.validate_workspace(workspace) == []


def test_fenced_and_inline_code_are_not_links(workspace: Path) -> None:
    write(workspace, "README.md", "```md\n[bad](missing.md)\n```\n`[bad](absent.md)`\n")
    assert checker.validate_workspace(workspace) == []


def test_external_links_do_not_use_network(workspace: Path, monkeypatch) -> None:
    import socket
    def denied(*args, **kwargs):
        raise AssertionError("checker must not contact external services")
    monkeypatch.setattr(socket, "create_connection", denied)
    write(workspace, "README.md", "[web](https://example.invalid/path#missing)\n[email](mailto:a@example.invalid)")
    assert checker.validate_workspace(workspace) == []


@pytest.mark.parametrize("fragment", ["L1", "L2-L3"])
def test_source_line_ranges(workspace: Path, fragment: str) -> None:
    write(workspace, "backend/app/example.py", "# one\n# two\n# three\n")
    write(workspace, "README.md", f"[code](backend/app/example.py#{fragment})")
    assert checker.validate_workspace(workspace) == []


@pytest.mark.parametrize("fragment", ["L0", "L9", "L3-L2"])
def test_invalid_source_line_ranges(workspace: Path, fragment: str) -> None:
    write(workspace, "backend/app/example.py", "# one\n# two\n# three\n")
    write(workspace, "README.md", f"[code](backend/app/example.py#{fragment})")
    assert "line range" in messages(workspace)


def test_cannot_read_outside_workspace(workspace: Path) -> None:
    outside = workspace.parent / "outside.md"
    outside.write_text("# Secret\n", encoding="utf-8")
    write(workspace, "README.md", "[no](../outside.md#secret)")
    assert "outside workspace" in messages(workspace)


def test_unsupported_destination_reports_instead_of_silent_pass(workspace: Path) -> None:
    write(workspace, "README.md", "[label](docs/foo bar.md)")
    assert "unsupported" in messages(workspace)


@pytest.mark.parametrize("name,text", [
    ("backend/app/example.py", "# see docs/11\n"),
    ("backend/app/example.py", '"""See decisions/0003."""\n'),
    ("frontend/src/example.ts", "// see docs/08\n"),
    ("frontend/src/example.tsx", "/* see decisions/0030 */\n"),
    ("frontend/src/example.css", "/* see docs/06 */\n"),
    ("docs/product/capabilities.md", "See `docs/11` for details.\n"),
])
def test_legacy_reference_in_owned_explanation(workspace: Path, name: str, text: str) -> None:
    write(workspace, name, text)
    assert "legacy reference" in messages(workspace)


@pytest.mark.parametrize("name,text", [
    ("backend/app/example.py", 'PROMPT = "docs/11"\n'),
    ("frontend/src/example.ts", 'const prompt = "docs/08";\n'),
    ("frontend/src/example.ts", 'const url = "https://host/docs/11"; // a real comment\n'),
])
def test_executable_strings_are_not_documentation(workspace: Path, name: str, text: str) -> None:
    write(workspace, name, text)
    assert checker.validate_workspace(workspace) == []


@pytest.mark.parametrize("name", [
    "frontend/node_modules/library/README.md", "backend/.venv/README.md",
    "backend/data/private.md", "fixtures/source.html", "design/source.html",
    ".git/private.md", ".superpowers/scratch.md", "skills/third-party/SKILL.md",
])
def test_excluded_inputs_are_not_scanned(workspace: Path, name: str) -> None:
    write(workspace, name, "[bad](missing.md)\nSee docs/11\n")
    assert checker.validate_workspace(workspace) == []


def test_process_documents_keep_historical_mentions_but_links_are_checked(workspace: Path) -> None:
    write(workspace, "docs/superpowers/specs/change.md", "Delete `docs/decisions/0041-old.md`.\n")
    assert checker.validate_workspace(workspace) == []
    write(workspace, "docs/superpowers/specs/change.md", "[bad](../../absent.md)")
    assert "missing target" in messages(workspace)


def test_cli_root_independent_of_cwd(workspace: Path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(workspace.parent)
    monkeypatch.setattr(checker, "__file__", str(workspace / "scripts/check_docs.py"))
    assert checker.main([]) == 0
    assert "OK" in capsys.readouterr().out
    write(workspace, "README.md", "[bad](missing.md)")
    assert checker.main(["--root", str(workspace)]) == 1
    assert "README.md:1" in capsys.readouterr().out


def test_cli_real_process_uses_explicit_root(workspace: Path) -> None:
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_docs.py"),
                             "--root", str(workspace)], cwd=workspace.parent,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
