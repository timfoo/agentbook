#!/usr/bin/env python3
"""
AgentBook handshake acceptance (owner-gated trust upgrade).

This script is the SECOND step of a successful handshake. It is run ONLY
after:
  1. handshake_verify.py reported {"ok": true, "state": "proof_received"}, AND
  2. The owner has out-of-band confirmed the requested scopes.

It promotes a contact from status='pending' -> status='trusted' and grants
the listed scopes. Per skill rule §5, this NEVER happens automatically -
the script requires --owner-confirmed to be set explicitly, simulating
the out-of-band gate.

The script refuses to grant high-risk scopes (code_or_shell, money,
third_party_send, credentials, install) without --high-risk-ack also set,
so a stray invocation can never silently grant a remote-shell-equivalent
scope.

Usage:
  python handshake_accept.py \
    --state-dir /home/user/workspace/agentbook_state \
    --contact-id agent-alpha \
    --grant-scopes reply,project_update \
    --owner-confirmed

Exit codes:
  0 - trust upgraded
  2 - precondition failed (no proof_received, missing flag, etc.)
  3 - contact not found
  4 - high-risk scope requested without --high-risk-ack
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "pyyaml not installed; pip install pyyaml"}))
    sys.exit(5)


HIGH_RISK_SCOPES = {
    "code_or_shell",
    "money",
    "third_party_send",
    "credentials",
    "install",
    "config_change",
    "destructive",
}


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def append_audit(audit_path: Path, entry: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def accept(state_dir: Path, contact_id: str, scopes: list[str],
           owner_confirmed: bool, high_risk_ack: bool) -> dict:
    contacts_path = state_dir / "contacts.yaml"
    audit_path = state_dir / "audit.jsonl"

    if not owner_confirmed:
        return {"ok": False, "code": 2,
                "reason": "owner_confirmation_required",
                "hint": "Re-run with --owner-confirmed after out-of-band verification."}

    if not contacts_path.exists():
        return {"ok": False, "code": 3, "reason": "no_state_file"}

    data = yaml.safe_load(contacts_path.read_text()) or {"contacts": []}
    contact = next((c for c in data["contacts"] if c.get("id") == contact_id), None)
    if contact is None:
        return {"ok": False, "code": 3, "reason": "contact_not_found",
                "contact_id": contact_id}

    hs = contact.get("handshake") or {}
    if hs.get("state") != "proof_received":
        return {"ok": False, "code": 2,
                "reason": "handshake_not_in_proof_received_state",
                "current_state": hs.get("state"),
                "hint": "Run handshake_verify.py first."}

    requested_high_risk = [s for s in scopes if s in HIGH_RISK_SCOPES]
    if requested_high_risk and not high_risk_ack:
        return {"ok": False, "code": 4,
                "reason": "high_risk_scope_requires_ack",
                "high_risk_scopes": requested_high_risk,
                "hint": "Re-run with --high-risk-ack to grant these explicitly."}

    # Promote
    contact["status"] = "trusted"
    # Replace handshake-only scopes with granted scopes (keep handshake for audit)
    existing = set(contact.get("scopes", []))
    existing.discard("handshake")
    existing.update(scopes)
    contact["scopes"] = sorted(existing)
    hs["state"] = "accepted"
    hs["accepted_at"] = now_iso()
    contact["handshake"] = hs

    contacts_path.write_text(yaml.safe_dump(data, sort_keys=False))

    append_audit(audit_path, {
        "ts": now_iso(),
        "action": "handshake.accept",
        "contact_id": contact_id,
        "granted_scopes": sorted(scopes),
        "high_risk_granted": requested_high_risk,
        "decision": "allow_trust_upgrade",
    })

    return {
        "ok": True,
        "code": 0,
        "contact_id": contact_id,
        "status": "trusted",
        "scopes": contact["scopes"],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", required=True, type=Path)
    p.add_argument("--contact-id", required=True)
    p.add_argument("--grant-scopes", required=True,
                   help="Comma-separated scopes to grant (e.g. reply,project_update)")
    p.add_argument("--owner-confirmed", action="store_true",
                   help="Required: confirms owner has done out-of-band verification.")
    p.add_argument("--high-risk-ack", action="store_true",
                   help="Required if any granted scope is high-risk.")
    args = p.parse_args()

    scopes = [s.strip() for s in args.grant_scopes.split(",") if s.strip()]
    result = accept(args.state_dir, args.contact_id, scopes,
                    args.owner_confirmed, args.high_risk_ack)
    print(json.dumps(result, indent=2))
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
