"""Append-only redacted audit logging for AgentBook."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .address_book import agentbook_dir


def audit_path() -> Path:
    return agentbook_dir() / "audit.jsonl"


def _hash(value: str | None) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def append_audit(tool: str, action: str, decision: str, reason: str = "", **fields: Any) -> dict[str, Any]:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "actor_profile": os.getenv("HERMES_PROFILE", "default"),
        "tool": tool,
        "action": action,
        "decision": decision,
        "reason": reason,
        "contact_id": fields.get("contact_id", ""),
        "inbox_id": fields.get("inbox_id", ""),
        "thread_id": fields.get("thread_id", ""),
        "message_id": fields.get("message_id", ""),
        "recipient_hash": _hash(fields.get("recipient") or fields.get("email")),
        "subject_hash": _hash(fields.get("subject")),
        "idempotency_key": fields.get("idempotency_key", ""),
        "payload_redacted": fields.get("payload_redacted", {}),
        "agentmail_status": fields.get("agentmail_status", "not_sent"),
    }
    path = audit_path()
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry


def tail(limit: int = 20, decision: str | None = None) -> list[dict[str, Any]]:
    path = audit_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if decision and entry.get("decision") != decision:
            continue
        entries.append(entry)
    return entries[-max(1, min(int(limit or 20), 200)):]
