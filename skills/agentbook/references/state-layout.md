# AgentBook State Layout

Default state directory: `${AGENTBOOK_STATE_DIR:-./agentbook_state}`

## Files

### `contacts.yaml`
Authoritative contact records. Schema:

```yaml
contacts:
  - id: agent-alpha                       # stable contact_id, slug-style
    email: agent-alpha@agentmail.to       # canonical email
    status: pending                      # pending | trusted | blocked | revoked
    scopes: [handshake]                  # granted scopes; see scopes.md
    handshake:
      state: awaiting_reply              # initiated | awaiting_reply | proof_received | accepted | rejected
      nonce_hash: <sha256-hex>           # SHA-256 of the raw nonce; raw nonce NEVER stored
      initiated_at: 2026-05-22T02:57:00Z
      sent_at: 2026-05-22T02:59:13Z
      thread_id: <agentmail-thread-id>   # to fetch the reply later
      verified_at: 2026-05-22T03:10:00Z  # set by handshake_verify on match
      accepted_at: 2026-05-22T03:12:00Z  # set by handshake_accept on owner confirm
    notes: free-form, no secrets
```

### `audit.jsonl`
Append-only, one JSON object per line. Always redacted: hashes only, no raw
nonces, no full message bodies, no API keys. Entry shape:

```json
{"ts":"2026-05-22T02:57:00Z","action":"handshake.initiate","contact_id":"agent-alpha","email_hash":"a7f4ce342d9caeb7","nonce_hash":"8b315f8b888ab8fd","decision":"allow_initiate","actor":"owner"}
```

Common `action` values:
- `handshake.initiate` — contact created, nonce generated
- `handshake.sent` — outbound message accepted by transport
- `handshake.verify` — verification attempt (decision: allow_proof_received | deny_nonce_mismatch | deny_no_nonce)
- `handshake.accept` — trust upgraded (decision: allow_trust_upgrade)
- `outbound.validate` — pre-send dry-run check
- `outbound.send` — actual send result
- `inbound.classify` — inbound sender classification result

## Lifecycle

```
unknown
  └─ handshake.initiate ──► pending / awaiting_reply
                              └─ handshake.verify ──► pending / proof_received
                                                        └─ handshake.accept ──► trusted
```

Trust upgrades NEVER skip steps. `accept` refuses unless the prior state is
`proof_received`. `verify` refuses unless a `nonce_hash` exists.

## Standard scopes

- `handshake` — minimum scope on pending contacts; permits handshake reply only
- `reply` — agent may receive and have its messages processed
- `project_update` — receive scoped project status updates
- `owner_instruction` — only ever on the owner's own contact; even then scopes
  below must also be present
- `wiki_file`, `summarize`, `reply_confirm`, `schedule_task` — low-risk
  instruction scopes

## High-risk scopes (require `--high-risk-ack`)

`code_or_shell`, `money`, `third_party_send`, `credentials`, `install`,
`config_change`, `destructive`. The CLI/scripts refuse to grant these
silently — explicit acknowledgement flag is required. PSKs may NEVER
auto-grant high-risk scopes; `psk_manage.py add` rejects them at the
manage layer.

## `psks.yaml` (v0.3 — Pre-Shared Key mode)

PSKs encode an **offline** trust agreement between two owners. Both
humans agree on a passphrase out-of-band (Signal, in person, voice call,
etc.) and each registers it with their own agent host using
`scripts/psk_manage.py`. Once registered, the two agents can complete a
4-stage handshake (initiate → respond → finalize → accept) and
auto-promote the counterparty to `status: trusted` with the PSK's
`auto_grant_scopes` — no per-handshake owner prompt.

The **raw passphrase is never stored**. Each side stores a per-relationship
salt and scrypt parameters; at handshake time the passphrase is supplied
again (via `--passphrase-file` or stdin) and the PSK is re-derived in
memory.

```yaml
psks:
  - label: owner-a-partner-research            # stable local label; owner-chosen
    counterparty:                         # who this PSK is shared with
      - alice-bot@agentmail.to            # exact addresses, or
      - "*@alice-research.example.com"    # domain wildcards ("*@domain")
    auto_grant_scopes:                    # scopes auto-granted on handshake
      - reply
      - project_update
    salt: 3f1c…ab                          # 16 random bytes, hex-encoded
    psk_hint: a1b2c3d4                    # first 8 hex of HMAC(psk, "agentbook-psk-hint")
    scrypt:
      n: 32768                            # 2^15
      r: 8
      p: 1
      dklen: 32
    notes: "Owner A/Alice research collab, Signal 2026-05-22"
    created_at: 2026-05-22T03:30:00Z
    rotated_at: null
    revoked_at: null                      # set when status=revoked
    status: active                        # active | revoked
```

### PSK lifecycle

```
(owner exchanges passphrase offline)
  └─ psk_manage add LABEL ──► active PSK
     ├─ initiate ──► pending_psk_<label>.json (stage=initiated)
     ├─ respond  ──► pending_psk_<label>.json (stage=awaiting_finalize)
     ├─ finalize ──► contacts.yaml entry → status=trusted (initiator side)
     └─ accept   ──► contacts.yaml entry → status=trusted (responder side)
  └─ psk_manage rotate LABEL ──► new salt + hint, status remains active
  └─ psk_manage revoke LABEL --confirm ──► status=revoked (handshakes refuse)
```

### `pending_psk_<label>.json`

Transient state file written by `handshake_psk.py` between stages. Holds
the live nonces and addresses for the in-flight handshake. Deleted on
successful finalize/accept. Never contains the raw passphrase or PSK.

```json
{
  "label": "owner-a-partner-research",
  "psk_hint": "a1b2c3d4",
  "from_a": "research-bot@agentmail.to",
  "from_b": "alice-bot@agentmail.to",
  "nonce_a_b64": "…",
  "nonce_b_b64": "…",
  "stage": "awaiting_finalize",
  "created_at": "2026-05-22T03:30:00Z"
}
```

### Wire envelope

Handshake messages embed a single-line JSON envelope between two markers
so they survive mail clients, quoting, and Talon stripping:

```
---AGENTBOOK-PSK-BEGIN---
{"v":"0.3","stage":"initiate","psk_hint":"a1b2c3d4","salt":"…","scrypt":{…},"nonce_a":"<b64>","from":"a@x","to":"b@y","ts":"2026-05-22T03:30:00Z"}
---AGENTBOOK-PSK-END---
```

Each proof is `HMAC-SHA256(PSK, label || stage || psk_hint || from_a ||
from_b || nonce_a || nonce_b)` (NUL-separated). This is channel-bound:
a captured proof cannot be replayed to a different recipient or stage.

### Audit actions (v0.3)

- `psk.add` — owner registered a PSK
- `psk.rotate` — owner rotated PSK salt + hint
- `psk.revoke` — owner revoked a PSK
- `handshake.psk.initiate` — initiator emitted stage=initiate envelope
- `handshake.psk.respond` — responder produced proof_b
- `handshake.psk.finalize` — initiator verified proof_b, produced proof_a,
  promoted contact to trusted (`decision: allow_trust_upgrade`) or failed
  (`decision: deny_proof_b_mismatch`)
- `handshake.psk.accept` — responder verified proof_a, promoted contact
  to trusted (`decision: allow_trust_upgrade`) or failed
  (`decision: deny_proof_a_mismatch`)

All PSK audit entries store only the `label` and `psk_hint`. The raw
passphrase, derived PSK, salt bytes, and full nonces are never logged.
