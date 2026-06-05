"""Smoke tests for the bundled AgentBook plugin MVP."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT


def _load_agentbook_module(module_name: str):
    """Load a module from plugins/agentbook using the plugin namespace."""
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    package_name = "hermes_plugins.agentbook"
    if package_name not in sys.modules:
        pkg = types.ModuleType(package_name)
        pkg.__path__ = [str(PLUGIN_DIR)]
        sys.modules[package_name] = pkg
    path = PLUGIN_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"{package_name}.{module_name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"{package_name}.{module_name}"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_plugin_init():
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    spec = importlib.util.spec_from_file_location(
        "hermes_plugins.agentbook",
        PLUGIN_DIR / "__init__.py",
        submodule_search_locations=[str(PLUGIN_DIR)],
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = "hermes_plugins.agentbook"
    mod.__path__ = [str(PLUGIN_DIR)]
    sys.modules["hermes_plugins.agentbook"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

    stub = types.ModuleType("hermes_constants")
    stub.get_hermes_home = lambda: Path(os.environ["HERMES_HOME"])
    monkeypatch.setitem(sys.modules, "hermes_constants", stub)
    for name in list(sys.modules):
        if name.startswith("hermes_plugins.agentbook"):
            del sys.modules[name]
    return hermes_home


def test_manifest_and_plugin_skill_exist():
    assert (PLUGIN_DIR / "plugin.yaml").read_text().startswith("name: agentbook")
    skill = PLUGIN_DIR / "skills" / "agentbook" / "SKILL.md"
    assert skill.exists()
    assert "AgentBook" in skill.read_text()


def test_register_exposes_minimum_tool_set_and_skill():
    plugin = _load_plugin_init()

    class FakeContext:
        def __init__(self):
            self.tools = []
            self.skills = []

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def register_skill(self, name, path, description=""):
            self.skills.append((name, Path(path), description))

    ctx = FakeContext()
    plugin.register(ctx)

    names = {tool["name"] for tool in ctx.tools}
    assert names == {
        "agentbook_contacts",
        "agentbook_lookup",
        "agentbook_classify",
        "agentbook_validate_outbound",
        "agentbook_handshake",
        "agentbook_validate_address_book",
        "agentbook_audit",
    }
    assert all(tool["toolset"] == "agentbook" for tool in ctx.tools)
    assert ctx.skills and ctx.skills[0][0] == "agentbook"


def test_contacts_add_get_and_classify_write_profile_safe_address_book(_isolated_home):
    tools = _load_agentbook_module("tools")

    added = json.loads(
        tools._handle_agentbook_contacts(
            {
                "action": "add",
                "contact_id": "alice",
                "email": "alice@example.com",
                "display_name": "Alice",
                "status": "trusted",
                "scopes": ["send", "reply", "handshake"],
                "allow": {"send": ["alice@example.com"], "max_body_chars": 2000},
            }
        )
    )
    assert added["success"] is True
    assert added["contact"]["id"] == "alice"

    book_path = _isolated_home / "agentbook" / "address_book.yaml"
    assert book_path.exists()

    got = json.loads(tools._handle_agentbook_lookup({"contact_id": "alice"}))
    assert got["success"] is True
    assert got["contact"]["email"] == "alice@example.com"

    known = json.loads(tools._handle_agentbook_classify({"email": "alice@example.com"}))
    assert known["classification"] == "trusted"
    unknown = json.loads(tools._handle_agentbook_classify({"email": "bob@example.com"}))
    assert unknown["classification"] == "unknown"
    assert unknown["decision"] == "quarantine"


def test_outbound_validation_denies_raw_or_untrusted_recipients_and_supports_dry_run():
    tools = _load_agentbook_module("tools")
    tools._handle_agentbook_contacts(
        {
            "action": "add",
            "contact_id": "trusted",
            "email": "trusted@example.com",
            "status": "trusted",
            "scopes": ["send"],
            "allow": {"send": ["trusted@example.com"], "max_body_chars": 100},
        }
    )
    tools._handle_agentbook_contacts(
        {
            "action": "add",
            "contact_id": "pending",
            "email": "pending@example.com",
            "status": "pending",
            "scopes": ["send"],
        }
    )

    raw = json.loads(
        tools._handle_agentbook_validate_outbound(
            {"to": "raw@example.com", "subject": "hi", "text": "hello"}
        )
    )
    assert raw["allowed"] is False
    assert "contact_id" in raw["reason"]

    pending = json.loads(
        tools._handle_agentbook_validate_outbound(
            {"contact_id": "pending", "subject": "hi", "text": "hello"}
        )
    )
    assert pending["allowed"] is False
    assert "trusted" in pending["reason"]

    dry_run = json.loads(
        tools._handle_agentbook_validate_outbound(
            {
                "contact_id": "trusted",
                "subject": "hi",
                "text": "hello",
                "dry_run": True,
                "idempotency_key": "k1",
            }
        )
    )
    assert dry_run["allowed"] is True
    assert dry_run["dry_run"] is True
    assert dry_run["agentmail_payload"]["to"] == "trusted@example.com"


def test_handshake_generates_nonce_and_audit_tail_redacts_message_body():
    tools = _load_agentbook_module("tools")

    result = json.loads(
        tools._handle_agentbook_handshake(
            {"action": "initiate", "email": "candidate@example.com", "requested_scopes": ["send"]}
        )
    )
    assert result["success"] is True
    assert result["contact"]["status"] == "pending"
    assert "nonce" in result["handshake_message"]

    audit = json.loads(tools._handle_agentbook_audit({"action": "tail", "limit": 10}))
    assert audit["success"] is True
    assert audit["entries"]
    rendered = json.dumps(audit["entries"])
    assert "candidate@example.com" not in rendered
    assert "nonce_hash" not in result["handshake_message"]


def test_address_book_validation_reports_invalid_contact_email():
    tools = _load_agentbook_module("tools")
    address_book = _load_agentbook_module("address_book")
    book = address_book.default_address_book()
    book["contacts"] = {"bad": {"email": "not-an-email", "status": "trusted"}}
    address_book.save_address_book(book)

    result = json.loads(tools._handle_agentbook_validate_address_book({}))
    assert result["valid"] is False
    assert any("bad.email" in err for err in result["errors"])
