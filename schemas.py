"""Tool schemas for the AgentBook plugin."""

from __future__ import annotations


def _object_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


CONTACTS_SCHEMA = {
    "name": "agentbook_contacts",
    "description": "List, get, add, update, or remove AgentBook contacts in the profile-safe address book.",
    "parameters": _object_schema(
        {
            "action": {"type": "string", "enum": ["list", "get", "add", "update", "remove"]},
            "contact_id": {"type": "string"},
            "email": {"type": "string"},
            "display_name": {"type": "string"},
            "agent_type": {"type": "string"},
            "status": {"type": "string", "enum": ["pending", "trusted", "blocked", "revoked"]},
            "scopes": {"type": "array", "items": {"type": "string"}},
            "allow": {"type": "object"},
            "notes": {"type": "string"},
        },
        ["action"],
    ),
}

LOOKUP_SCHEMA = {
    "name": "agentbook_lookup",
    "description": "Look up a contact by contact_id or email and return its trust/scopes metadata.",
    "parameters": _object_schema({"contact_id": {"type": "string"}, "email": {"type": "string"}}),
}

CLASSIFY_SCHEMA = {
    "name": "agentbook_classify",
    "description": "Classify a sender email as trusted, pending, blocked, revoked, or unknown using the AgentBook address book.",
    "parameters": _object_schema({"email": {"type": "string"}}, ["email"]),
}

VALIDATE_OUTBOUND_SCHEMA = {
    "name": "agentbook_validate_outbound",
    "description": "Validate or dry-run outbound AgentMail payloads against AgentBook policy without sending network requests.",
    "parameters": _object_schema(
        {
            "contact_id": {"type": "string"},
            "to": {"type": "string", "description": "Rejected in MVP; use contact_id."},
            "subject": {"type": "string"},
            "text": {"type": "string"},
            "cc": {"type": "array", "items": {"type": "string"}},
            "labels": {"type": "array", "items": {"type": "string"}},
            "purpose": {"type": "string"},
            "idempotency_key": {"type": "string"},
            "dry_run": {"type": "boolean"},
        }
    ),
}

HANDSHAKE_SCHEMA = {
    "name": "agentbook_handshake",
    "description": "Initiate, accept, reject, or inspect nonce-based AgentBook trust handshakes.",
    "parameters": _object_schema(
        {
            "action": {"type": "string", "enum": ["initiate", "accept", "reject", "status"]},
            "contact_id": {"type": "string"},
            "email": {"type": "string"},
            "display_name": {"type": "string"},
            "requested_scopes": {"type": "array", "items": {"type": "string"}},
            "nonce": {"type": "string"},
            "expires_at": {"type": "string"},
        },
        ["action"],
    ),
}

VALIDATE_ADDRESS_BOOK_SCHEMA = {
    "name": "agentbook_validate_address_book",
    "description": "Validate the profile AgentBook address_book.yaml schema and safety policy constraints.",
    "parameters": _object_schema({}),
}

AUDIT_SCHEMA = {
    "name": "agentbook_audit",
    "description": "Read redacted append-only AgentBook audit log entries.",
    "parameters": _object_schema(
        {"action": {"type": "string", "enum": ["tail", "query"]}, "limit": {"type": "integer"}, "decision": {"type": "string"}}
    ),
}
