"""Portable command-line interface for AgentBook.

The Hermes plugin remains the native Hermes adapter. This CLI is the universal
adapter for Claude Code, OpenCode, Codex, shell scripts, and humans: SkillMD can
instruct agents to call these commands before any external collaboration step.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parent
PACKAGE_NAME = "hermes_plugins.agentbook"


def _ensure_plugin_package() -> types.ModuleType:
    """Load this checkout as the Hermes plugin package namespace.

    The public repository is intentionally shaped like a Hermes plugin at its
    root, so relative imports such as ``from . import address_book`` require a
    package namespace. Hermes supplies that namespace at runtime; this helper
    supplies the same namespace for standalone CLI use.
    """

    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []  # type: ignore[attr-defined]
        sys.modules["hermes_plugins"] = ns

    existing = sys.modules.get(PACKAGE_NAME)
    if existing is not None and getattr(existing, "__path__", None):
        return existing  # type: ignore[return-value]

    spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        ROOT / "__init__.py",
        submodule_search_locations=[str(ROOT)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load AgentBook plugin package")
    module = importlib.util.module_from_spec(spec)
    module.__package__ = PACKAGE_NAME
    module.__path__ = [str(ROOT)]  # type: ignore[attr-defined]
    sys.modules[PACKAGE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _tools_module():
    _ensure_plugin_package()
    return __import__(f"{PACKAGE_NAME}.tools", fromlist=["tools"])


def _print_json(payload: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, str):
        data = json.loads(payload)
        print(json.dumps(data, sort_keys=True))
        return data
    print(json.dumps(payload, sort_keys=True))
    return payload


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _json_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentbook", description="Portable AgentBook policy CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    contacts = sub.add_parser("contacts", help="List, add, get, update, or remove contacts")
    contacts_sub = contacts.add_subparsers(dest="action", required=True)
    contacts_sub.add_parser("list", help="List contacts")

    get = contacts_sub.add_parser("get", help="Get a contact")
    get.add_argument("contact_id", nargs="?")
    get.add_argument("--email")

    add = contacts_sub.add_parser("add", help="Add a contact")
    add.add_argument("contact_id")
    add.add_argument("--email", required=True)
    add.add_argument("--display-name", default="")
    add.add_argument("--agent-type", default="agent")
    add.add_argument("--status", default="pending", choices=["pending", "trusted", "blocked", "revoked"])
    add.add_argument("--scopes", default="handshake", help="Comma-separated scopes")
    add.add_argument("--allow-send", default=None, help="Comma-separated send allowlist; defaults to --email")
    add.add_argument("--allow-cc", default="", help="Comma-separated CC allowlist")
    add.add_argument("--labels", default="", help="Comma-separated allowed labels")
    add.add_argument("--max-body-chars", type=int, default=None)
    add.add_argument("--notes", default="")

    update = contacts_sub.add_parser("update", help="Update a contact")
    update.add_argument("contact_id")
    update.add_argument("--email")
    update.add_argument("--display-name")
    update.add_argument("--agent-type")
    update.add_argument("--status", choices=["pending", "trusted", "blocked", "revoked"])
    update.add_argument("--scopes")
    update.add_argument("--allow-send")
    update.add_argument("--allow-cc")
    update.add_argument("--labels")
    update.add_argument("--max-body-chars", type=int)
    update.add_argument("--notes")

    remove = contacts_sub.add_parser("remove", help="Remove a contact")
    remove.add_argument("contact_id")

    lookup = sub.add_parser("lookup", help="Resolve a known contact")
    lookup.add_argument("--contact-id")
    lookup.add_argument("--email")

    classify = sub.add_parser("classify", help="Classify an inbound sender email")
    classify.add_argument("email")

    validate = sub.add_parser("validate", help="Validate the local address book")

    outbound = sub.add_parser("validate-outbound", help="Validate an outbound AgentMail-style payload")
    outbound.add_argument("--file", help="JSON payload file")
    outbound.add_argument("--contact-id")
    outbound.add_argument("--to")
    outbound.add_argument("--subject")
    outbound.add_argument("--text")
    outbound.add_argument("--cc", default="")
    outbound.add_argument("--labels", default="")
    outbound.add_argument("--idempotency-key")
    outbound.add_argument("--dry-run", action="store_true")

    handshake = sub.add_parser("handshake", help="Manage contact handshakes")
    handshake.add_argument("action", choices=["initiate", "accept", "reject", "status"])
    handshake.add_argument("--contact-id")
    handshake.add_argument("--email")
    handshake.add_argument("--display-name", default="")
    handshake.add_argument("--requested-scopes", default="handshake")
    handshake.add_argument("--nonce", default="")

    audit = sub.add_parser("audit", help="Read redacted audit entries")
    audit.add_argument("action", nargs="?", default="tail", choices=["tail", "query"])
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--decision")

    return parser


def _contact_payload(args: argparse.Namespace) -> dict[str, Any]:
    allow_send = _csv(getattr(args, "allow_send", None)) or ([args.email] if getattr(args, "email", None) else [])
    allow: dict[str, Any] = {
        "send": allow_send,
        "cc": _csv(getattr(args, "allow_cc", None)),
        "labels": _csv(getattr(args, "labels", None)),
    }
    if getattr(args, "max_body_chars", None) is not None:
        allow["max_body_chars"] = args.max_body_chars
    return {
        "action": args.action,
        "contact_id": getattr(args, "contact_id", None),
        "email": getattr(args, "email", None),
        "display_name": getattr(args, "display_name", None),
        "agent_type": getattr(args, "agent_type", None),
        "status": getattr(args, "status", None),
        "scopes": _csv(getattr(args, "scopes", None)) if getattr(args, "scopes", None) is not None else None,
        "allow": allow,
        "notes": getattr(args, "notes", None),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tools = _tools_module()

    if args.command == "contacts":
        if args.action in {"add", "update"}:
            data = _print_json(tools._handle_agentbook_contacts(_contact_payload(args)))
            return 0 if data.get("success") else 2
        if args.action == "list":
            data = _print_json(tools._handle_agentbook_contacts({"action": "list"}))
            return 0 if data.get("success") else 2
        if args.action == "get":
            data = _print_json(tools._handle_agentbook_contacts({"action": "get", "contact_id": args.contact_id, "email": args.email}))
            return 0 if data.get("success") else 2
        if args.action == "remove":
            data = _print_json(tools._handle_agentbook_contacts({"action": "remove", "contact_id": args.contact_id}))
            return 0 if data.get("success") else 2

    if args.command == "lookup":
        data = _print_json(tools._handle_agentbook_lookup({"contact_id": args.contact_id, "email": args.email}))
        return 0 if data.get("success") else 2

    if args.command == "classify":
        data = _print_json(tools._handle_agentbook_classify({"email": args.email}))
        return 0 if data.get("success") else 2

    if args.command == "validate":
        data = _print_json(tools._handle_agentbook_validate_address_book({}))
        return 0 if data.get("valid") else 2

    if args.command == "validate-outbound":
        payload = _json_file(args.file)
        payload.update({k: v for k, v in {
            "contact_id": args.contact_id,
            "to": args.to,
            "subject": args.subject,
            "text": args.text,
            "cc": _csv(args.cc),
            "labels": _csv(args.labels),
            "idempotency_key": args.idempotency_key,
            "dry_run": args.dry_run,
        }.items() if v not in (None, [], False)})
        data = _print_json(tools._handle_agentbook_validate_outbound(payload))
        return 0 if data.get("allowed") else 2

    if args.command == "handshake":
        data = _print_json(tools._handle_agentbook_handshake({
            "action": args.action,
            "contact_id": args.contact_id,
            "email": args.email,
            "display_name": args.display_name,
            "requested_scopes": _csv(args.requested_scopes),
            "nonce": args.nonce,
        }))
        return 0 if data.get("success") else 2

    if args.command == "audit":
        data = _print_json(tools._handle_agentbook_audit({"action": args.action, "limit": args.limit, "decision": args.decision}))
        return 0 if data.get("success") else 2

    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
