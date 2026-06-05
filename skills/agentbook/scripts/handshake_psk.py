#!/usr/bin/env python3
"""
AgentBook PSK handshake — HMAC mutual-nonce challenge.

Two roles, four operations:

  initiate   -- A starts the handshake. Emits a JSON envelope to send to B.
  respond    -- B receives the initiate envelope, validates the psk_hint
                matches a known PSK, generates nonce_B and proof_B,
                emits an envelope to send to A.
  finalize   -- A receives B's response, verifies proof_B, generates
                proof_A, emits the final envelope to send to B, and
                auto-promotes the contact to status=trusted with the
                PSK's auto_grant_scopes (no human prompt).
  accept     -- B receives A's finalize envelope, verifies proof_A, and
                auto-promotes the contact to status=trusted with the
                PSK's auto_grant_scopes (no human prompt).

Envelope schema (single-line JSON in the email body, between markers):

  ---AGENTBOOK-PSK-BEGIN---
  {"v":"0.3","stage":"initiate","psk_hint":"a1b2c3d4","nonce_a":"<b64>",
   "from":"a@x","to":"b@y","ts":"2026-05-22T03:30:00Z"}
  ---AGENTBOOK-PSK-END---

Channel binding: every HMAC is computed over a canonical transcript that
includes the message stage, both nonces, both addresses, and the psk_hint.
That prevents a captured proof from being replayed to a different recipient
or repurposed for a different stage.

HMAC inputs (UTF-8, NUL-separated):
  proof_b = HMAC-SHA256(PSK, b"agentbook-psk-v0.3\\0proof_b\\0" +
                              psk_hint || \\0 || from_a || \\0 || from_b || \\0 ||
                              nonce_a || \\0 || nonce_b)
  proof_a = HMAC-SHA256(PSK, b"agentbook-psk-v0.3\\0proof_a\\0" +
                              psk_hint || \\0 || from_a || \\0 || from_b || \\0 ||
                              nonce_a || \\0 || nonce_b)

PSK derivation: each side reads the raw passphrase (from --passphrase-file
or stdin) and scrypt-derives the same key using the salt stored in their
local psks.yaml. Both salts MUST match for handshakes to succeed; the
two parties must use the salt published in the initiator's envelope.

Exit codes:
  0 = success
  2 = envelope/proof verification failure
  3 = no matching PSK for psk_hint
  4 = PSK revoked or expired
  5 = missing dependency / bad input
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "pyyaml not installed"}))
    sys.exit(5)


PROTO_VERSION = "0.3"
PROTO_LABEL = b"agentbook-psk-v0.3"
ENVELOPE_BEGIN = "---AGENTBOOK-PSK-BEGIN---"
ENVELOPE_END = "---AGENTBOOK-PSK-END---"
NONCE_BYTES = 16
HANDSHAKE_TTL_SECONDS = 3600


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def derive_psk(passphrase: bytes, salt: bytes, scrypt_params: dict) -> bytes:
    return hashlib.scrypt(
        passphrase, salt=salt,
        n=scrypt_params["n"], r=scrypt_params["r"], p=scrypt_params["p"],
        dklen=scrypt_params["dklen"], maxmem=128 * 1024 * 1024,
    )


def compute_proof(psk: bytes, stage: str, psk_hint: str,
                  from_a: str, from_b: str,
                  nonce_a: bytes, nonce_b: bytes) -> str:
    msg = (
        PROTO_LABEL + b"\0" + stage.encode() + b"\0" +
        psk_hint.encode() + b"\0" +
        from_a.lower().encode() + b"\0" + from_b.lower().encode() + b"\0" +
        nonce_a + b"\0" + nonce_b
    )
    return b64e(hmac.new(psk, msg, hashlib.sha256).digest())


def load_psks(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return data.get("psks", [])


def find_psk_by_hint(psks: list[dict], hint: str) -> dict | None:
    for p in psks:
        if p.get("psk_hint") == hint and p.get("status") == "active":
            return p
    return None


def find_psk_by_counterparty(psks: list[dict], email: str,
                              include_revoked: bool = False) -> dict | None:
    e = email.lower()
    for p in psks:
        if not include_revoked and p.get("status") != "active":
            continue
        for cp in p.get("counterparty", []):
            if cp.startswith("*@"):
                if e.endswith(cp[1:]):
                    return p
            elif cp.lower() == e:
                return p
    return None


def read_passphrase(args) -> bytes:
    if args.passphrase_file:
        return Path(args.passphrase_file).read_bytes().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip().encode()
    raise SystemExit(json.dumps({"error": "passphrase required"}))


def append_audit(state_dir: Path, entry: dict) -> None:
    audit = state_dir / "audit.jsonl"
    audit.parent.mkdir(parents=True, exist_ok=True)
    with audit.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def upsert_contact(state_dir: Path, contact_id: str, email: str,
                   scopes: list[str], psk_label: str) -> None:
    contacts_path = state_dir / "contacts.yaml"
    data = yaml.safe_load(contacts_path.read_text()) if contacts_path.exists() else {"contacts": []}
    data.setdefault("contacts", [])
    existing = next((c for c in data["contacts"] if c.get("id") == contact_id), None)
    if existing is None:
        existing = {"id": contact_id, "email": email}
        data["contacts"].append(existing)
    existing["status"] = "trusted"
    existing["scopes"] = sorted(set((existing.get("scopes") or []) + scopes) - {"handshake"})
    existing["psk_label"] = psk_label
    existing["accepted_at"] = now_iso()
    existing["handshake"] = {"state": "accepted", "mode": "psk", "psk_label": psk_label,
                              "accepted_at": now_iso()}
    contacts_path.write_text(yaml.safe_dump(data, sort_keys=False))


def make_envelope(payload: dict) -> str:
    return f"{ENVELOPE_BEGIN}\n{json.dumps(payload, separators=(',', ':'))}\n{ENVELOPE_END}"


def parse_envelope(text: str) -> dict:
    if ENVELOPE_BEGIN not in text or ENVELOPE_END not in text:
        raise ValueError("no envelope found")
    body = text.split(ENVELOPE_BEGIN, 1)[1].split(ENVELOPE_END, 1)[0].strip()
    return json.loads(body)


def cmd_initiate(args) -> dict:
    psks = load_psks(args.state_dir / "psks.yaml")
    psk_entry = find_psk_by_counterparty(psks, args.to)
    if not psk_entry:
        return {"ok": False, "code": 3, "reason": "no_psk_for_counterparty", "to": args.to}

    nonce_a = secrets.token_bytes(NONCE_BYTES)
    state = {
        "label": psk_entry["label"],
        "psk_hint": psk_entry["psk_hint"],
        "salt_hex": psk_entry["salt"],
        "scrypt": psk_entry["scrypt"],
        "from_a": args.from_addr.lower(),
        "to_b": args.to.lower(),
        "nonce_a_b64": b64e(nonce_a),
        "stage": "initiated",
        "created_at": now_iso(),
    }
    pending_path = args.state_dir / f"pending_psk_{psk_entry['label']}.json"
    pending_path.write_text(json.dumps(state, indent=2))

    envelope = {
        "v": PROTO_VERSION, "stage": "initiate",
        "psk_hint": psk_entry["psk_hint"],
        "salt": psk_entry["salt"],
        "scrypt": psk_entry["scrypt"],
        "nonce_a": b64e(nonce_a),
        "from": args.from_addr, "to": args.to,
        "ts": now_iso(),
    }
    append_audit(args.state_dir, {
        "ts": now_iso(), "action": "handshake.psk.initiate",
        "label": psk_entry["label"], "psk_hint": psk_entry["psk_hint"],
        "to_hash": hashlib.sha256(args.to.lower().encode()).hexdigest()[:16],
        "decision": "allow",
    })
    return {"ok": True, "code": 0,
            "envelope_text": make_envelope(envelope),
            "envelope": envelope,
            "pending_path": str(pending_path)}


def cmd_respond(args) -> dict:
    envelope = parse_envelope(Path(args.envelope_file).read_text())
    if envelope.get("v") != PROTO_VERSION or envelope.get("stage") != "initiate":
        return {"ok": False, "code": 2, "reason": "bad_envelope"}
    psks = load_psks(args.state_dir / "psks.yaml")

    # Look up PSK by the sender (counterparty), not by the envelope's psk_hint.
    # Each side computes its own hint from its own salt; the envelope's hint
    # belongs to the initiator. We re-derive a comparable hint below.
    from_a = envelope["from"].lower()
    psk_entry = find_psk_by_counterparty(psks, from_a, include_revoked=True)
    if not psk_entry:
        return {"ok": False, "code": 3,
                "reason": "no_psk_for_counterparty",
                "from": from_a}
    if psk_entry.get("status") != "active":
        return {"ok": False, "code": 4, "reason": "psk_revoked",
                "label": psk_entry["label"]}

    passphrase = read_passphrase(args)
    # Re-derive using the INITIATOR's salt (from the envelope) so both
    # sides land on the same key bytes. The local stored salt is only
    # used to compute the local psk_hint for owner display purposes.
    salt = bytes.fromhex(envelope["salt"])
    psk = derive_psk(passphrase, salt, envelope["scrypt"])
    del passphrase

    # Sanity: derived key must produce the SAME psk_hint as the envelope.
    # If it doesn't, the passphrase doesn't match what the initiator used.
    derived_hint = hmac.new(psk, b"agentbook-psk-hint", hashlib.sha256).hexdigest()[:8]
    if derived_hint != envelope["psk_hint"]:
        return {"ok": False, "code": 2, "reason": "passphrase_does_not_match_psk_hint"}

    nonce_a = b64d(envelope["nonce_a"])
    nonce_b = secrets.token_bytes(NONCE_BYTES)

    proof_b = compute_proof(
        psk, "proof_b", envelope["psk_hint"],
        envelope["from"], envelope["to"],
        nonce_a, nonce_b,
    )

    state = {
        "label": psk_entry["label"], "psk_hint": envelope["psk_hint"],
        "salt_hex": envelope["salt"], "scrypt": envelope["scrypt"],
        "from_a": envelope["from"].lower(), "from_b": envelope["to"].lower(),
        "nonce_a_b64": envelope["nonce_a"], "nonce_b_b64": b64e(nonce_b),
        "stage": "awaiting_finalize", "created_at": now_iso(),
    }
    pending_path = args.state_dir / f"pending_psk_{psk_entry['label']}.json"
    pending_path.write_text(json.dumps(state, indent=2))

    response = {
        "v": PROTO_VERSION, "stage": "respond",
        "psk_hint": envelope["psk_hint"],
        "nonce_a": envelope["nonce_a"],
        "nonce_b": b64e(nonce_b),
        "proof_b": proof_b,
        "from": envelope["to"], "to": envelope["from"],
        "ts": now_iso(),
    }
    append_audit(args.state_dir, {
        "ts": now_iso(), "action": "handshake.psk.respond",
        "label": psk_entry["label"], "psk_hint": psk_entry["psk_hint"],
        "decision": "allow",
    })
    return {"ok": True, "code": 0, "envelope_text": make_envelope(response),
            "envelope": response, "pending_path": str(pending_path)}


def cmd_finalize(args) -> dict:
    envelope = parse_envelope(Path(args.envelope_file).read_text())
    if envelope.get("v") != PROTO_VERSION or envelope.get("stage") != "respond":
        return {"ok": False, "code": 2, "reason": "bad_envelope"}

    psks = load_psks(args.state_dir / "psks.yaml")
    # Initiator side: the envelope's psk_hint is OUR hint (we sent it).
    psk_entry = find_psk_by_hint(psks, envelope["psk_hint"])
    if not psk_entry:
        return {"ok": False, "code": 3, "reason": "no_psk_for_hint"}

    pending_path = args.state_dir / f"pending_psk_{psk_entry['label']}.json"
    if not pending_path.exists():
        return {"ok": False, "code": 2, "reason": "no_pending_initiate_state"}
    state = json.loads(pending_path.read_text())

    if envelope["nonce_a"] != state["nonce_a_b64"]:
        return {"ok": False, "code": 2, "reason": "nonce_a_mismatch_possible_replay"}

    passphrase = read_passphrase(args)
    salt = bytes.fromhex(psk_entry["salt"])
    psk = derive_psk(passphrase, salt, psk_entry["scrypt"])
    del passphrase

    nonce_a = b64d(envelope["nonce_a"])
    nonce_b = b64d(envelope["nonce_b"])

    expected_proof_b = compute_proof(
        psk, "proof_b", envelope["psk_hint"],
        state["from_a"], envelope["from"],
        nonce_a, nonce_b,
    )
    if not hmac.compare_digest(expected_proof_b, envelope["proof_b"]):
        append_audit(args.state_dir, {
            "ts": now_iso(), "action": "handshake.psk.finalize",
            "label": psk_entry["label"], "decision": "deny_proof_b_mismatch",
        })
        return {"ok": False, "code": 2, "reason": "proof_b_mismatch"}

    proof_a = compute_proof(
        psk, "proof_a", envelope["psk_hint"],
        state["from_a"], envelope["from"],
        nonce_a, nonce_b,
    )

    # Auto-promote counterparty to trusted
    contact_id = (envelope["from"].split("@")[0]).lower()
    upsert_contact(args.state_dir, contact_id, envelope["from"],
                   psk_entry["auto_grant_scopes"], psk_entry["label"])

    pending_path.unlink()

    final_env = {
        "v": PROTO_VERSION, "stage": "finalize",
        "psk_hint": envelope["psk_hint"],
        "nonce_a": envelope["nonce_a"], "nonce_b": envelope["nonce_b"],
        "proof_a": proof_a,
        "from": state["from_a"], "to": envelope["from"],
        "ts": now_iso(),
    }
    append_audit(args.state_dir, {
        "ts": now_iso(), "action": "handshake.psk.finalize",
        "label": psk_entry["label"], "contact_id": contact_id,
        "granted_scopes": psk_entry["auto_grant_scopes"],
        "decision": "allow_trust_upgrade",
    })
    return {"ok": True, "code": 0, "envelope_text": make_envelope(final_env),
            "envelope": final_env, "contact_id": contact_id,
            "scopes": psk_entry["auto_grant_scopes"], "status": "trusted"}


def cmd_accept(args) -> dict:
    envelope = parse_envelope(Path(args.envelope_file).read_text())
    if envelope.get("v") != PROTO_VERSION or envelope.get("stage") != "finalize":
        return {"ok": False, "code": 2, "reason": "bad_envelope"}

    psks = load_psks(args.state_dir / "psks.yaml")
    # Responder side: the envelope's psk_hint is the INITIATOR's hint.
    # Look up by counterparty (the envelope's `from`), then use the salt
    # we cached in pending state during `respond`.
    from_a = envelope["from"].lower()
    psk_entry = find_psk_by_counterparty(psks, from_a)
    if not psk_entry:
        return {"ok": False, "code": 3, "reason": "no_psk_for_counterparty",
                "from": from_a}

    pending_path = args.state_dir / f"pending_psk_{psk_entry['label']}.json"
    if not pending_path.exists():
        return {"ok": False, "code": 2, "reason": "no_pending_respond_state"}
    state = json.loads(pending_path.read_text())

    if envelope["nonce_a"] != state["nonce_a_b64"] or envelope["nonce_b"] != state["nonce_b_b64"]:
        return {"ok": False, "code": 2, "reason": "nonce_mismatch_possible_replay"}
    if envelope["psk_hint"] != state["psk_hint"]:
        return {"ok": False, "code": 2, "reason": "psk_hint_mismatch_with_pending_state"}

    passphrase = read_passphrase(args)
    # Use the initiator's salt that we cached in pending state during respond.
    salt = bytes.fromhex(state["salt_hex"])
    psk = derive_psk(passphrase, salt, state["scrypt"])
    del passphrase

    nonce_a = b64d(envelope["nonce_a"])
    nonce_b = b64d(envelope["nonce_b"])
    expected_proof_a = compute_proof(
        psk, "proof_a", envelope["psk_hint"],
        envelope["from"], state["from_b"],
        nonce_a, nonce_b,
    )
    if not hmac.compare_digest(expected_proof_a, envelope["proof_a"]):
        append_audit(args.state_dir, {
            "ts": now_iso(), "action": "handshake.psk.accept",
            "label": psk_entry["label"], "decision": "deny_proof_a_mismatch",
        })
        return {"ok": False, "code": 2, "reason": "proof_a_mismatch"}

    contact_id = (envelope["from"].split("@")[0]).lower()
    upsert_contact(args.state_dir, contact_id, envelope["from"],
                   psk_entry["auto_grant_scopes"], psk_entry["label"])
    pending_path.unlink()
    append_audit(args.state_dir, {
        "ts": now_iso(), "action": "handshake.psk.accept",
        "label": psk_entry["label"], "contact_id": contact_id,
        "granted_scopes": psk_entry["auto_grant_scopes"],
        "decision": "allow_trust_upgrade",
    })
    return {"ok": True, "code": 0, "contact_id": contact_id,
            "scopes": psk_entry["auto_grant_scopes"], "status": "trusted"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", required=True, type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("initiate")
    i.add_argument("--from", dest="from_addr", required=True)
    i.add_argument("--to", required=True)
    i.set_defaults(fn=cmd_initiate)

    r = sub.add_parser("respond")
    r.add_argument("--envelope-file", required=True)
    r.add_argument("--passphrase-file", default=None)
    r.set_defaults(fn=cmd_respond)

    f = sub.add_parser("finalize")
    f.add_argument("--envelope-file", required=True)
    f.add_argument("--passphrase-file", default=None)
    f.set_defaults(fn=cmd_finalize)

    a = sub.add_parser("accept")
    a.add_argument("--envelope-file", required=True)
    a.add_argument("--passphrase-file", default=None)
    a.set_defaults(fn=cmd_accept)

    args = p.parse_args()
    result = args.fn(args)
    print(json.dumps(result, indent=2))
    return result.get("code", 0)


if __name__ == "__main__":
    sys.exit(main())
