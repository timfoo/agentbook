#!/usr/bin/env python3
"""
AgentBook PSK (Pre-Shared Key) management.

PSKs encode an *offline* trust relationship between two owners. Both
humans agree to a passphrase out-of-band (Signal, in person, voice call,
etc.) and each registers it with their agent host. Online handshakes
under a registered PSK auto-complete — no per-handshake owner prompts.

Storage model:
  - The raw passphrase is NEVER stored. We store scrypt(passphrase, salt)
    so a stolen psks.yaml can't impersonate the relationship without an
    expensive offline crack.
  - For HMAC operations during a handshake the passphrase must be provided
    again (--passphrase / stdin / $AGENTBOOK_PSK_<label>). The skill
    documents how hosts cache an unwrapped key in memory for a session.
  - A short "psk_hint" (first 4 bytes of HMAC(psk, 'agentbook-psk-hint'))
    is stored alongside so the counterparty can identify which PSK to use
    without revealing it.

Usage:
  python psk_manage.py add LABEL \\
      --counterparty alice-bot@agentmail.to,alice-research@agentmail.to \\
      --scopes reply,project_update \\
      --notes "Owner A/Alice research collab, Signal 2026-05-22" \\
      --passphrase-file /path/to/secret  # or read from stdin

  python psk_manage.py list
  python psk_manage.py show LABEL
  python psk_manage.py rotate LABEL --passphrase-file /path/to/new
  python psk_manage.py revoke LABEL --confirm
  python psk_manage.py hint  LABEL          # print the psk_hint hex
  python psk_manage.py compute-hint --passphrase-file /path/to/secret  # offline

Exit codes:
  0 = success
  2 = bad input / precondition
  3 = label not found
  4 = label already exists (on add)
  5 = missing dependency

Security notes:
  - Passphrases should be >=12 chars or, preferably, generated via
    `python -c "import secrets;print(secrets.token_urlsafe(16))"`.
  - Scrypt params are (n=2**15, r=8, p=1, dklen=32) -- ~32MB RAM,
    ~200ms on a laptop. Tune via AGENTBOOK_SCRYPT_N if needed.
  - High-risk scopes (code_or_shell, money, credentials, third_party_send,
    install, config_change, destructive) are *refused* at the manage layer.
    A PSK can never auto-grant them.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(json.dumps({"error": "pyyaml not installed; pip install pyyaml"}))
    sys.exit(5)

HIGH_RISK_SCOPES = {
    "code_or_shell", "money", "credentials", "third_party_send",
    "install", "config_change", "destructive",
}

SCRYPT_N = int(os.environ.get("AGENTBOOK_SCRYPT_N", 1 << 15))
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 32
HINT_LABEL = b"agentbook-psk-hint"


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z")


def load_psks(path: Path) -> dict:
    if not path.exists():
        return {"psks": []}
    return yaml.safe_load(path.read_text()) or {"psks": []}


def save_psks(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def append_audit(audit_path: Path, entry: dict) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a") as f:
        f.write(json.dumps(entry) + "\n")


def derive_psk(passphrase: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(
        passphrase, salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_DKLEN, maxmem=128 * 1024 * 1024,
    )


def compute_hint(psk: bytes) -> str:
    return hmac.new(psk, HINT_LABEL, hashlib.sha256).hexdigest()[:8]


def read_passphrase(args) -> bytes:
    if args.passphrase_file:
        return Path(args.passphrase_file).read_bytes().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip().encode()
    print(json.dumps({"error": "passphrase required (use --passphrase-file or pipe stdin)"}))
    sys.exit(2)


def cmd_add(args, state_dir: Path) -> dict:
    psks_path = state_dir / "psks.yaml"
    audit_path = state_dir / "audit.jsonl"

    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    bad = [s for s in scopes if s in HIGH_RISK_SCOPES]
    if bad:
        return {"ok": False, "code": 2,
                "reason": "high_risk_scopes_not_allowed_via_psk",
                "high_risk": bad,
                "hint": "PSKs may only auto-grant low/medium-risk scopes. Use handshake_accept with --high-risk-ack for high-risk scopes."}

    counterparty = [c.strip().lower() for c in args.counterparty.split(",") if c.strip()]
    if not counterparty:
        return {"ok": False, "code": 2, "reason": "no_counterparty"}

    data = load_psks(psks_path)
    if any(p["label"] == args.label for p in data["psks"]):
        return {"ok": False, "code": 4, "reason": "label_exists", "label": args.label}

    passphrase = read_passphrase(args)
    if len(passphrase) < 12:
        return {"ok": False, "code": 2,
                "reason": "passphrase_too_short",
                "hint": "Use >=12 chars or `python -c 'import secrets;print(secrets.token_urlsafe(16))'`."}

    salt = secrets.token_bytes(16)
    psk = derive_psk(passphrase, salt)
    hint = compute_hint(psk)

    entry = {
        "label": args.label,
        "counterparty": counterparty,
        "auto_grant_scopes": sorted(scopes),
        "salt": salt.hex(),
        "psk_hint": hint,
        "scrypt": {"n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "dklen": SCRYPT_DKLEN},
        "notes": args.notes or "",
        "created_at": now_iso(),
        "rotated_at": None,
        "status": "active",
    }
    data["psks"].append(entry)
    save_psks(psks_path, data)

    append_audit(audit_path, {
        "ts": now_iso(),
        "action": "psk.add",
        "label": args.label,
        "psk_hint": hint,
        "counterparty_count": len(counterparty),
        "scopes": sorted(scopes),
        "decision": "allow",
        "actor": "owner",
    })

    # Wipe passphrase from memory best-effort
    del passphrase

    return {"ok": True, "code": 0, "label": args.label, "psk_hint": hint,
            "counterparty": counterparty, "scopes": sorted(scopes)}


def cmd_list(args, state_dir: Path) -> dict:
    data = load_psks(state_dir / "psks.yaml")
    redacted = [{
        "label": p["label"],
        "counterparty": p["counterparty"],
        "auto_grant_scopes": p["auto_grant_scopes"],
        "psk_hint": p["psk_hint"],
        "status": p["status"],
        "created_at": p["created_at"],
        "rotated_at": p.get("rotated_at"),
    } for p in data["psks"]]
    return {"ok": True, "code": 0, "psks": redacted}


def cmd_show(args, state_dir: Path) -> dict:
    data = load_psks(state_dir / "psks.yaml")
    entry = next((p for p in data["psks"] if p["label"] == args.label), None)
    if not entry:
        return {"ok": False, "code": 3, "reason": "label_not_found", "label": args.label}
    redacted = dict(entry)
    redacted.pop("salt", None)  # don't print the salt either
    return {"ok": True, "code": 0, "psk": redacted}


def cmd_rotate(args, state_dir: Path) -> dict:
    psks_path = state_dir / "psks.yaml"
    audit_path = state_dir / "audit.jsonl"

    data = load_psks(psks_path)
    entry = next((p for p in data["psks"] if p["label"] == args.label), None)
    if not entry:
        return {"ok": False, "code": 3, "reason": "label_not_found", "label": args.label}

    passphrase = read_passphrase(args)
    if len(passphrase) < 12:
        return {"ok": False, "code": 2, "reason": "passphrase_too_short"}

    salt = secrets.token_bytes(16)
    psk = derive_psk(passphrase, salt)
    hint = compute_hint(psk)

    entry["salt"] = salt.hex()
    entry["psk_hint"] = hint
    entry["rotated_at"] = now_iso()
    save_psks(psks_path, data)

    append_audit(audit_path, {
        "ts": now_iso(), "action": "psk.rotate", "label": args.label,
        "psk_hint": hint, "decision": "allow", "actor": "owner",
    })
    del passphrase
    return {"ok": True, "code": 0, "label": args.label, "psk_hint": hint}


def cmd_revoke(args, state_dir: Path) -> dict:
    psks_path = state_dir / "psks.yaml"
    audit_path = state_dir / "audit.jsonl"

    if not args.confirm:
        return {"ok": False, "code": 2,
                "reason": "confirmation_required",
                "hint": "Pass --confirm to actually revoke."}

    data = load_psks(psks_path)
    entry = next((p for p in data["psks"] if p["label"] == args.label), None)
    if not entry:
        return {"ok": False, "code": 3, "reason": "label_not_found", "label": args.label}

    entry["status"] = "revoked"
    entry["revoked_at"] = now_iso()
    save_psks(psks_path, data)
    append_audit(audit_path, {
        "ts": now_iso(), "action": "psk.revoke", "label": args.label,
        "decision": "allow", "actor": "owner",
    })
    return {"ok": True, "code": 0, "label": args.label, "status": "revoked"}


def cmd_hint(args, state_dir: Path) -> dict:
    data = load_psks(state_dir / "psks.yaml")
    entry = next((p for p in data["psks"] if p["label"] == args.label), None)
    if not entry:
        return {"ok": False, "code": 3, "reason": "label_not_found"}
    return {"ok": True, "code": 0, "label": args.label, "psk_hint": entry["psk_hint"]}


def cmd_compute_hint(args, state_dir: Path) -> dict:
    """Compute the hint a counterparty would see, given a candidate passphrase.
    Useful for verifying both sides registered the same passphrase before
    attempting a real handshake."""
    passphrase = read_passphrase(args)
    if len(passphrase) < 12:
        return {"ok": False, "code": 2, "reason": "passphrase_too_short"}
    # For hint computation we use a fixed salt so both sides can compare.
    # NOTE: the *stored* PSK uses a real per-relationship salt; the hint
    # uses the derived key, so two sides with the same passphrase but
    # different salts WILL produce different hints. This command is for
    # verifying you derived the same key from the same passphrase using
    # the SAME salt -- pass --salt to make it deterministic.
    if not args.salt:
        return {"ok": False, "code": 2,
                "reason": "salt_required",
                "hint": "Pass --salt <hex> matching the counterparty's stored salt to compute a comparable hint."}
    salt = bytes.fromhex(args.salt)
    psk = derive_psk(passphrase, salt)
    hint = compute_hint(psk)
    del passphrase
    return {"ok": True, "code": 0, "psk_hint": hint}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--state-dir", required=True, type=Path)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("label")
    a.add_argument("--counterparty", required=True,
                   help="Comma-separated counterparty email addresses (or domains: *@example.com).")
    a.add_argument("--scopes", required=True,
                   help="Comma-separated scopes to auto-grant under this PSK.")
    a.add_argument("--notes", default="")
    a.add_argument("--passphrase-file", default=None)
    a.set_defaults(fn=cmd_add)

    l = sub.add_parser("list"); l.set_defaults(fn=cmd_list)

    s = sub.add_parser("show"); s.add_argument("label"); s.set_defaults(fn=cmd_show)

    r = sub.add_parser("rotate")
    r.add_argument("label")
    r.add_argument("--passphrase-file", default=None)
    r.set_defaults(fn=cmd_rotate)

    v = sub.add_parser("revoke")
    v.add_argument("label")
    v.add_argument("--confirm", action="store_true")
    v.set_defaults(fn=cmd_revoke)

    h = sub.add_parser("hint"); h.add_argument("label"); h.set_defaults(fn=cmd_hint)

    c = sub.add_parser("compute-hint")
    c.add_argument("--passphrase-file", default=None)
    c.add_argument("--salt", help="Hex-encoded salt to derive the comparable hint with.")
    c.set_defaults(fn=cmd_compute_hint)

    args = p.parse_args()
    result = args.fn(args, args.state_dir)
    print(json.dumps(result, indent=2))
    return result.get("code", 0)


if __name__ == "__main__":
    sys.exit(main())
