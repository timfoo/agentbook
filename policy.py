"""AgentBook policy validation helpers."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any

from .address_book import get_contact, load_address_book


def _deny(reason: str, contact: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"allowed": False, "reason": reason, "contact": contact}


def _allow(payload: dict[str, Any], contact: dict[str, Any]) -> dict[str, Any]:
    return {"allowed": True, "reason": "allowed", "contact": contact, "agentmail_payload": payload}


def validate_outbound(args: dict[str, Any]) -> dict[str, Any]:
    if args.get("to") and not args.get("contact_id"):
        return _deny("Outbound messages require contact_id; raw to addresses are denied in AgentBook MVP.")
    contact_id = args.get("contact_id")
    if not contact_id:
        return _deny("Outbound messages require contact_id.")
    contact = get_contact(contact_id=contact_id)
    if not contact:
        return _deny(f"Unknown contact_id '{contact_id}'.")
    if contact.get("status") != "trusted":
        return _deny("Contact must be trusted before outbound send is allowed.", contact)
    if "send" not in contact.get("scopes", []):
        return _deny("Contact does not grant send scope.", contact)
    email = contact.get("email", "")
    allowed_globs = contact.get("allow", {}).get("send") or []
    if allowed_globs and not any(fnmatch(email, pat) for pat in allowed_globs):
        return _deny("Contact email is outside allow.send patterns.", contact)
    text = args.get("text") or ""
    subject = args.get("subject") or ""
    max_body = contact.get("allow", {}).get("max_body_chars") or load_address_book().get("defaults", {}).get("max_body_chars", 12000)
    if len(text) > int(max_body):
        return _deny("Message body exceeds max_body_chars policy.", contact)
    if len(subject) > 998:
        return _deny("Subject exceeds safe length.", contact)
    cc = args.get("cc") or []
    allowed_cc = set(contact.get("allow", {}).get("cc") or [])
    if cc and not set(cc).issubset(allowed_cc):
        return _deny("CC contains addresses outside contact allow.cc policy.", contact)
    labels = args.get("labels") or []
    allowed_labels = set(contact.get("allow", {}).get("labels") or [])
    if labels and allowed_labels and not set(labels).issubset(allowed_labels):
        return _deny("Labels contain values outside contact allow.labels policy.", contact)
    payload = {"to": email, "subject": subject, "text": text}
    if cc:
        payload["cc"] = cc
    if labels:
        payload["labels"] = labels
    if args.get("idempotency_key"):
        payload["idempotency_key"] = args["idempotency_key"]
    return _allow(payload, contact)
