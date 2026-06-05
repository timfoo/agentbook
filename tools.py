"""Tool handlers for the AgentBook plugin.

Handlers return JSON strings and never raise for policy denials. Network send and
fetch are intentionally stubbed; the MVP validates and dry-runs safe payloads.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import address_book
from .audit import append_audit, tail as audit_tail
from .policy import validate_outbound
from .schemas import (
    AUDIT_SCHEMA,
    CLASSIFY_SCHEMA,
    CONTACTS_SCHEMA,
    HANDSHAKE_SCHEMA,
    LOOKUP_SCHEMA,
    VALIDATE_ADDRESS_BOOK_SCHEMA,
    VALIDATE_OUTBOUND_SCHEMA,
)


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True)


def _error(message: str, **extra: Any) -> str:
    payload = {"success": False, "error": message}
    payload.update(extra)
    return _json(payload)


def _contact_fields(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "email": args.get("email"),
        "display_name": args.get("display_name"),
        "agent_type": args.get("agent_type"),
        "status": args.get("status"),
        "scopes": args.get("scopes"),
        "allow": args.get("allow"),
        "notes": args.get("notes"),
    }


def _check_agentbook_available() -> bool:
    return True


def _handle_agentbook_contacts(args: dict[str, Any], **_: Any) -> str:
    action = args.get("action", "list")
    try:
        if action == "list":
            contacts = address_book.list_contacts()
            return _json({"success": True, "contacts": contacts})
        if action == "get":
            contact = address_book.get_contact(args.get("contact_id"), args.get("email"))
            if not contact:
                return _error("contact not found")
            return _json({"success": True, "contact": contact})
        if action in {"add", "update"}:
            contact_id = args.get("contact_id")
            if not contact_id:
                return _error("contact_id is required")
            fields = _contact_fields(args)
            contact = address_book.upsert_contact(contact_id, fields)
            valid, errors = address_book.validate_address_book()
            decision = "allow" if valid else "error"
            append_audit("agentbook_contacts", action, decision, "; ".join(errors), contact_id=contact_id, email=contact.get("email"))
            return _json({"success": valid, "contact": contact, "errors": errors})
        if action == "remove":
            contact_id = args.get("contact_id")
            if not contact_id:
                return _error("contact_id is required")
            removed = address_book.remove_contact(contact_id)
            append_audit("agentbook_contacts", action, "allow" if removed else "deny", "removed" if removed else "not found", contact_id=contact_id)
            return _json({"success": True, "removed": removed})
        return _error(f"unknown action '{action}'")
    except Exception as exc:
        append_audit("agentbook_contacts", action, "error", str(exc), contact_id=args.get("contact_id", ""))
        return _error(str(exc))


def _handle_agentbook_lookup(args: dict[str, Any], **_: Any) -> str:
    contact = address_book.get_contact(args.get("contact_id"), args.get("email"))
    if not contact:
        return _json({"success": False, "contact": None, "classification": "unknown"})
    return _json({"success": True, "contact": contact, "classification": contact.get("status", "pending")})


def _handle_agentbook_classify(args: dict[str, Any], **_: Any) -> str:
    email = args.get("email", "")
    # Strip display name if present (e.g. "Owner A <owner-a@example.com>")
    clean_email = email
    if "<" in email and ">" in email:
        clean_email = email.split("<")[1].split(">")[0]
    contact = address_book.get_contact(email=clean_email)
    if not contact:
        append_audit("agentbook_classify", "classify", "quarantine", "unknown sender", email=clean_email)
        return _json({"success": True, "classification": "unknown", "decision": "quarantine", "contact": None})
    status = contact.get("status", "pending")
    decision = "allow" if status == "trusted" else ("deny" if status in {"blocked", "revoked"} else "quarantine")
    append_audit("agentbook_classify", "classify", decision, status, contact_id=contact.get("id"), email=clean_email)
    return _json({"success": True, "classification": status, "decision": decision, "contact": contact})


def _handle_agentbook_validate_outbound(args: dict[str, Any], **_: Any) -> str:
    result = validate_outbound(args)
    decision = "allow" if result.get("allowed") else "deny"
    payload = result.get("agentmail_payload", {})
    append_audit(
        "agentbook_validate_outbound",
        "validate",
        decision,
        result.get("reason", ""),
        contact_id=args.get("contact_id", ""),
        recipient=payload.get("to") or args.get("to"),
        subject=args.get("subject"),
        idempotency_key=args.get("idempotency_key", ""),
        payload_redacted={"has_text": bool(args.get("text")), "text_chars": len(args.get("text") or "")},
    )
    out = {"success": True, "allowed": result["allowed"], "reason": result["reason"], "dry_run": bool(args.get("dry_run"))}
    if result.get("contact"):
        out["contact"] = result["contact"]
    if result.get("agentmail_payload"):
        out["agentmail_payload"] = result["agentmail_payload"]
    return _json(out)


def _nonce_hash(nonce: str) -> str:
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


def _candidate_id(email: str) -> str:
    local = email.split("@", 1)[0].lower() or "candidate"
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "-" for ch in local).strip("-")
    suffix = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:8]
    return f"{safe}-{suffix}"


def _handle_agentbook_handshake(args: dict[str, Any], **_: Any) -> str:
    action = args.get("action", "status")
    try:
        if action == "initiate":
            email = args.get("email")
            if not email:
                return _error("email is required for initiate")
            contact_id = args.get("contact_id") or _candidate_id(email)
            nonce = secrets.token_urlsafe(18)
            expires_at = args.get("expires_at") or (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
            scopes = args.get("requested_scopes") or ["handshake"]
            contact = address_book.upsert_contact(
                contact_id,
                {
                    "email": email,
                    "display_name": args.get("display_name", ""),
                    "status": "pending",
                    "scopes": ["handshake"],
                    "allow": {"send": [email], "cc": [], "labels": []},
                    "handshake": {"state": "initiated", "nonce_hash": _nonce_hash(nonce), "expires_at": expires_at, "requested_scopes": scopes},
                },
            )
            message = (
                "AgentBook handshake request\n"
                f"Contact ID: {contact_id}\n"
                f"Requested scopes: {', '.join(scopes)}\n"
                f"Expires at: {expires_at}\n"
                f"Reply with this nonce to establish trust: {nonce}"
            )
            append_audit("agentbook_handshake", action, "allow", "initiated", contact_id=contact_id, email=email, payload_redacted={"requested_scopes": scopes})
            return _json({"success": True, "contact": contact, "handshake_message": message, "dry_run": True})
        contact = address_book.get_contact(args.get("contact_id"), args.get("email"))
        if not contact:
            return _error("contact not found")
        contact_id = contact["id"]
        if action == "status":
            return _json({"success": True, "contact": contact, "handshake": contact.get("handshake", {})})
        if action == "accept":
            nonce = args.get("nonce", "")
            expected = contact.get("handshake", {}).get("nonce_hash")
            if expected and _nonce_hash(nonce) != expected:
                append_audit("agentbook_handshake", action, "deny", "nonce mismatch", contact_id=contact_id, email=contact.get("email"))
                return _error("nonce mismatch")
            scopes = args.get("requested_scopes") or contact.get("handshake", {}).get("requested_scopes") or ["send", "reply", "handshake"]
            updated = address_book.upsert_contact(contact_id, {"status": "trusted", "scopes": scopes, "handshake": {"state": "accepted", "established_at": datetime.now(timezone.utc).isoformat()}})
            append_audit("agentbook_handshake", action, "allow", "accepted", contact_id=contact_id, email=contact.get("email"))
            return _json({"success": True, "contact": updated})
        if action == "reject":
            updated = address_book.upsert_contact(contact_id, {"status": "blocked", "handshake": {"state": "rejected"}})
            append_audit("agentbook_handshake", action, "deny", "rejected", contact_id=contact_id, email=contact.get("email"))
            return _json({"success": True, "contact": updated})
        return _error(f"unknown action '{action}'")
    except Exception as exc:
        append_audit("agentbook_handshake", action, "error", str(exc), contact_id=args.get("contact_id", ""), email=args.get("email", ""))
        return _error(str(exc))


def _handle_agentbook_validate_address_book(args: dict[str, Any], **_: Any) -> str:
    valid, errors = address_book.validate_address_book()
    append_audit("agentbook_validate_address_book", "validate", "allow" if valid else "error", "; ".join(errors))
    return _json({"success": True, "valid": valid, "errors": errors, "path": str(address_book.address_book_path())})


def _handle_agentbook_audit(args: dict[str, Any], **_: Any) -> str:
    action = args.get("action", "tail")
    if action not in {"tail", "query"}:
        return _error(f"unknown action '{action}'")
    entries = audit_tail(args.get("limit", 20), args.get("decision"))
    return _json({"success": True, "entries": entries})
