"""Profile-safe AgentBook address book helpers."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

try:
    from hermes_constants import get_hermes_home  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover - standalone test/install fallback
    import os

    def get_hermes_home() -> Path:
        return Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_STATUSES = {"pending", "trusted", "blocked", "revoked"}
VALID_SCOPES = {
    "send",
    "reply",
    "read_thread",
    "handshake",
    # Trusted owner-instruction scopes. These authorize low-risk inbound tasks
    # from the owner over email; they do not grant arbitrary code/shell access.
    "owner_instruction",
    "wiki_file",
    "summarize",
    "reply_confirm",
    "schedule_task",
    "code_or_shell",
    # Agent-to-agent collaboration scopes for shadow orgs and multi-agent workflows
    "research",          # Can request/perform research tasks
    "project_update",    # Can send progress updates and status reports
    "delegate",          # Can delegate subtasks to other agents
    "invoke",            # Can invoke tools/skills on behalf of collaborator
    "file_shared",       # Can file content to shared knowledge bases (cross-agent)
    "notify",            # Can send alerts/notifications without full message
}


def agentbook_dir() -> Path:
    path = get_hermes_home() / "agentbook"
    path.mkdir(parents=True, exist_ok=True)
    return path


def address_book_path() -> Path:
    return agentbook_dir() / "address_book.yaml"


def default_address_book() -> dict[str, Any]:
    return {
        "version": 1,
        "self": {"inbox_id": "", "email": "", "display_name": ""},
        "defaults": {
            "unknown_sender_policy": "deny",
            "attachments": "deny",
            "max_body_chars": 12000,
            "require_handshake": True,
        },
        "contacts": {},
    }


def load_address_book() -> dict[str, Any]:
    path = address_book_path()
    if not path.exists():
        book = default_address_book()
        save_address_book(book)
        return book
    data = yaml.safe_load(path.read_text()) or {}
    merged = default_address_book()
    merged.update(data)
    merged.setdefault("defaults", {}).update(data.get("defaults", {}) if isinstance(data.get("defaults"), dict) else {})
    merged.setdefault("contacts", {})
    return merged


def save_address_book(book: dict[str, Any]) -> Path:
    path = address_book_path()
    path.write_text(yaml.safe_dump(book, sort_keys=False), encoding="utf-8")
    return path


def normalize_contact(contact_id: str, data: dict[str, Any]) -> dict[str, Any]:
    contact = deepcopy(data)
    contact.setdefault("email", "")
    contact.setdefault("display_name", "")
    contact.setdefault("agent_type", "agent")
    contact.setdefault("status", "pending")
    contact.setdefault("scopes", ["handshake"])
    contact.setdefault("allow", {})
    contact["allow"].setdefault("send", [contact.get("email", "")])
    contact["allow"].setdefault("cc", [])
    contact["allow"].setdefault("labels", [])
    contact["allow"].setdefault("max_body_chars", None)
    contact.setdefault("handshake", {})
    contact.setdefault("notes", "")
    contact["id"] = contact_id
    return contact


def upsert_contact(contact_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    book = load_address_book()
    contacts = book.setdefault("contacts", {})
    current = contacts.get(contact_id, {}) if isinstance(contacts.get(contact_id), dict) else {}
    updated = {**current, **{k: v for k, v in fields.items() if v is not None}}
    contacts[contact_id] = normalize_contact(contact_id, updated)
    contacts[contact_id].pop("id", None)
    save_address_book(book)
    return normalize_contact(contact_id, contacts[contact_id])


def remove_contact(contact_id: str) -> bool:
    book = load_address_book()
    existed = contact_id in book.get("contacts", {})
    if existed:
        del book["contacts"][contact_id]
        save_address_book(book)
    return existed


def get_contact(contact_id: str | None = None, email: str | None = None) -> dict[str, Any] | None:
    contacts = load_address_book().get("contacts", {})
    if contact_id and contact_id in contacts:
        return normalize_contact(contact_id, contacts[contact_id])
    if email:
        target = email.strip().lower()
        for cid, contact in contacts.items():
            if isinstance(contact, dict):
                # Check primary email
                if str(contact.get("email", "")).lower() == target:
                    return normalize_contact(cid, contact)
                # Check allow.send list for additional emails
                for allowed_email in contact.get("allow", {}).get("send", []):
                    if str(allowed_email).lower() == target:
                        return normalize_contact(cid, contact)
    return None


def list_contacts() -> list[dict[str, Any]]:
    contacts = load_address_book().get("contacts", {})
    return [normalize_contact(cid, c) for cid, c in sorted(contacts.items()) if isinstance(c, dict)]


def validate_address_book(book: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    book = book or load_address_book()
    errors: list[str] = []
    if book.get("version") != 1:
        errors.append("version must be 1")
    defaults = book.get("defaults", {})
    if defaults.get("unknown_sender_policy", "deny") != "deny":
        errors.append("defaults.unknown_sender_policy must be deny for MVP")
    if defaults.get("attachments", "deny") != "deny":
        errors.append("defaults.attachments must be deny for MVP")
    contacts = book.get("contacts", {})
    if not isinstance(contacts, dict):
        errors.append("contacts must be a mapping")
        return False, errors
    for cid, contact in contacts.items():
        if not isinstance(contact, dict):
            errors.append(f"contacts.{cid} must be an object")
            continue
        email = str(contact.get("email", ""))
        if not EMAIL_RE.match(email):
            errors.append(f"contacts.{cid}.email is invalid")
        status = contact.get("status", "pending")
        if status not in VALID_STATUSES:
            errors.append(f"contacts.{cid}.status is invalid")
        scopes = contact.get("scopes", [])
        if not isinstance(scopes, list) or any(scope not in VALID_SCOPES for scope in scopes):
            errors.append(f"contacts.{cid}.scopes contains invalid scope")
    return not errors, errors
