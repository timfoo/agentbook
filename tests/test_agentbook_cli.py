"""Tests for the portable AgentBook CLI and SkillMD distribution path."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    stub = types.ModuleType("hermes_constants")
    stub.get_hermes_home = lambda: Path(os.environ["HERMES_HOME"])
    monkeypatch.setitem(sys.modules, "hermes_constants", stub)
    for name in list(sys.modules):
        if name.startswith("hermes_plugins.agentbook") or name == "agentbook_cli":
            del sys.modules[name]
    return hermes_home


def test_cli_add_lookup_classify_and_validate_outbound(capsys):
    import agentbook_cli

    assert agentbook_cli.main([
        "contacts",
        "add",
        "alice",
        "--email",
        "alice@example.com",
        "--status",
        "trusted",
        "--scopes",
        "send,reply,handshake",
    ]) == 0
    added = json.loads(capsys.readouterr().out)
    assert added["success"] is True
    assert added["contact"]["id"] == "alice"

    assert agentbook_cli.main(["lookup", "--contact-id", "alice"]) == 0
    looked_up = json.loads(capsys.readouterr().out)
    assert looked_up["contact"]["email"] == "alice@example.com"

    assert agentbook_cli.main(["classify", "unknown@example.com"]) == 0
    unknown = json.loads(capsys.readouterr().out)
    assert unknown["classification"] == "unknown"
    assert unknown["decision"] == "quarantine"

    assert agentbook_cli.main([
        "validate-outbound",
        "--contact-id",
        "alice",
        "--subject",
        "Project update",
        "--text",
        "Safe summary only.",
        "--dry-run",
    ]) == 0
    outbound = json.loads(capsys.readouterr().out)
    assert outbound["allowed"] is True
    assert outbound["agentmail_payload"]["to"] == "alice@example.com"


def test_cli_validate_outbound_denial_exits_nonzero(capsys):
    import agentbook_cli

    assert agentbook_cli.main([
        "validate-outbound",
        "--to",
        "raw@example.com",
        "--subject",
        "Nope",
        "--text",
        "Raw address should be denied.",
    ]) == 2
    denied = json.loads(capsys.readouterr().out)
    assert denied["allowed"] is False
    assert "contact_id" in denied["reason"]


def test_claude_and_skillmd_docs_exist_and_deemphasize_mcp():
    root = Path(__file__).resolve().parents[1]
    claude = root / "CLAUDE.md"
    docs = root / "docs" / "claude-code.md"
    collaboration_skill = root / "skills" / "agentmail-collaboration" / "SKILL.md"

    assert claude.exists()
    assert docs.exists()
    assert collaboration_skill.exists()

    content = claude.read_text() + docs.read_text() + collaboration_skill.read_text()
    assert "agentbook validate-outbound" in content
    assert "raw email" in content.lower()
    assert "MCP is optional" in content
