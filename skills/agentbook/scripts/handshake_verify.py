#!/usr/bin/env python3
"""
AgentBook handshake verification.

Given a candidate reply body (plain text) and a contact_id, this script:
  1. Loads the contact record from contacts.yaml.
  2. Extracts the AGENTBOOK-NONCE token from the reply body.
  3. Hashes it (SHA-256) and compares against the stored nonce_hash.
  4. On match: advances contact state to 'proof_received' (still NOT trusted).
  5. Writes a redacted audit entry (no raw nonce ever stored or printed).
  6. Exits 0 on match, 2 on mismatch / missing, 3 on missing contact.

The script never upgrades status -> trusted. Upgrading trust requires an
explicit, separate owner action (handshake_accept.py) after out-of-band
confirmation per skill rule §3.

Usage:
  python handshake_verify.py \
    --state-dir /home/user/workspace/agentbook_state \
    --contact-id agent-alpha \
    --reply-file /tmp/reply.txt

  # Or pipe the reply body via stdin:
  cat reply.txt | python handshake_verify.py \
    --state-dir ./agentbook_state --contact-id agent-alpha
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "pyyaml not installed; pip install pyyaml"}))
    sys.exit(4)


NONCE_RE = re.compile(r"AGENTBOOK-NONCE:\s*([A-Za-z0-9_\-]+)")


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def load_contacts(path: Path) -> dict:
    if not path.exists():
        return {"contacts": []}
    return yaml.safe_load(path.read_text()) or {"contacts": []}


def save_contacts(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def find_contact(data: dict, contact_id: str) -> dict | None:
    for c in data.get("contacts", []):
        if c.get("id") == contact_id:
            return c
    return None


def append_audit(audit_path: Path, entry: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def extract_nonce(body: str) -> str | None:
    m = NONCE_RE.search(body)
    return m.group(1) if m else None


def verify(state_dir: Path, contact_id: str, reply_body: str) -> dict:
    contacts_path = state_dir / "contacts.yaml"
    audit_path = state_dir / "audit.jsonl"

    data = load_contacts(contacts_path)
    contact = find_contact(data, contact_id)
    if contact is None:
        return {
            "ok": False,
            "code": 3,
            "reason": "contact_not_found",
            "contact_id": contact_id,
        }

    hs = contact.get("handshake") or {}
    expected_hash = hs.get("nonce_hash")
    if not expected_hash:
        return {
            "ok": False,
            "code": 2,
            "reason": "no_pending_handshake",
            "contact_id": contact_id,
        }

    candidate = extract_nonce(reply_body)
    if candidate is None:
        append_audit(audit_path, {
            "ts": now_iso(),
            "action": "handshake.verify",
            "contact_id": contact_id,
            "decision": "deny_no_nonce",
        })
        return {
            "ok": False,
            "code": 2,
            "reason": "no_nonce_in_reply",
            "contact_id": contact_id,
        }

    candidate_hash = hashlib.sha256(candidate.encode()).hexdigest()
    if candidate_hash != expected_hash:
        append_audit(audit_path, {
            "ts": now_iso(),
            "action": "handshake.verify",
            "contact_id": contact_id,
            "decision": "deny_nonce_mismatch",
            "expected_prefix": expected_hash[:16],
            "received_prefix": candidate_hash[:16],
        })
        return {
            "ok": False,
            "code": 2,
            "reason": "nonce_mismatch",
            "contact_id": contact_id,
        }

    # Match — advance state. Still NOT trusted.
    hs["state"] = "proof_received"
    hs["verified_at"] = now_iso()
    contact["handshake"] = hs
    contact.setdefault("notes", "")
    save_contacts(contacts_path, data)

    append_audit(audit_path, {
        "ts": now_iso(),
        "action": "handshake.verify",
        "contact_id": contact_id,
        "decision": "allow_proof_received",
        "nonce_hash_prefix": expected_hash[:16],
    })

    return {
        "ok": True,
        "code": 0,
        "contact_id": contact_id,
        "state": "proof_received",
        "status": contact.get("status", "pending"),
        "next_step": "Owner must run handshake_accept with requested scopes (out-of-band confirmation required).",
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", required=True, type=Path)
    p.add_argument("--contact-id", required=True)
    p.add_argument("--reply-file", type=Path, default=None,
                   help="Path to reply body file; if omitted, read from stdin.")
    args = p.parse_args()

    if args.reply_file:
        reply_body = args.reply_file.read_text()
    else:
        reply_body = sys.stdin.read()

    result = verify(args.state_dir, args.contact_id, reply_body)
    print(json.dumps(result, indent=2))
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
