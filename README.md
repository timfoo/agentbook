# AgentBook

AgentBook is an address-book safety layer for agent-to-agent collaboration over email-like transports such as AgentMail. It provides scoped trust: unknown senders are quarantined by default, known contacts are constrained by explicit policy, and outbound messages are validated before they can be sent.

This repository is intentionally **SkillMD/CLI-first, Hermes-native second, MCP-optional later**. The portable contract is a deterministic `agentbook` CLI plus skills/docs that teach agents when to call it. The Hermes plugin wraps the same policy as native Hermes tools.

Network AgentMail send/fetch is intentionally stubbed in v0.2; the project focuses on profile-safe local storage, policy validation, handshakes, and redacted audit logs.

## What it does

- Stores contacts in `get_hermes_home()/agentbook/address_book.yaml`
- Stores redacted audit decisions in `get_hermes_home()/agentbook/audit.jsonl`
- Classifies unknown senders as `unknown` with a `quarantine` decision
- **Quarantines unknown inbound email silently** — no auto-reply, no inbox validation leak
- Requires trusted contacts and scoped permissions for outbound validation
- Denies raw arbitrary `to` addresses in favor of `contact_id` resolution
- Generates nonce-based handshake messages for human/owner verification flows
- Bundles `plugin:agentbook` and `plugin:agentmail-collaboration` skills with usage and safety guidance
- Supports webhook-based inbound processing via AgentMail `message.received` events with Svix signature verification
- Supports scoped **trusted owner email instructions** for low-risk owner commands such as `wiki_file`, `summarize`, `reply_confirm`, and `schedule_task`; dangerous scopes such as `code_or_shell` should require an out-of-band confirmation step

## Tools registered

- `agentbook_contacts` — list/get/add/update/remove contacts
- `agentbook_lookup` — resolve a known contact by id or email
- `agentbook_classify` — classify a sender as trusted, pending, blocked, revoked, or unknown
- `agentbook_validate_outbound` — validate an outbound AgentMail payload and return a dry-run payload
- `agentbook_handshake` — initiate/accept/reject/status for contact handshakes
- `agentbook_validate_address_book` — validate local policy file
- `agentbook_audit` — tail/query redacted audit entries

## Install

### Hermes plugin

```bash
hermes plugins install owner-a/agentbook --no-enable
hermes plugins enable agentbook
```

Restart Hermes or start a fresh session after enabling the plugin.

### Portable CLI for Claude Code / other agents

```bash
python -m pip install -e .
agentbook --help
```

The CLI is the universal enforcement path for hosts that can run shell commands. Claude Code should follow `CLAUDE.md` / `docs/claude-code.md` and call the CLI before any external send.

Common commands:

```bash
agentbook contacts list
agentbook contacts add alice --email alice@example.com --status trusted --scopes send,reply,handshake
agentbook lookup --contact-id alice
agentbook classify alice@example.com
agentbook validate
agentbook validate-outbound --contact-id alice --subject "Project update" --text "Safe summary" --dry-run
agentbook audit tail --limit 20
```

MCP is optional. Add it later only for hosts that require MCP-native tool discovery.

## Optional AgentMail env

The manifest declares `AGENTMAIL_API_KEY` as optional. v0.2 does not send network messages; future versions can use the same trust/policy layer for real AgentMail send/fetch. Do not commit your API key. Keep secrets in your Hermes `.env` or configured secret store.

## Address book shape

```yaml
version: 1
self:
  inbox_id: ""
  email: ""
  display_name: ""
defaults:
  unknown_sender_policy: deny
  attachments: deny
  max_body_chars: 12000
  require_handshake: true
contacts:
  alice:
    email: alice@example.com
    display_name: Alice Agent
    agent_type: agent
    status: trusted
    scopes: [send, reply, handshake]
    allow:
      send: [alice@example.com]
      cc: []
      labels: []
      max_body_chars: 12000
    handshake:
      state: accepted
    notes: Project-scoped collaborator
  tim-owner:
    email: tim@example.com
    display_name: Owner A Owner
    agent_type: human
    status: trusted
    scopes: [send, reply, owner_instruction, wiki_file, summarize, reply_confirm, schedule_task]
    allow:
      send: [tim@example.com]
      cc: []
      labels: [trusted-owner]
      max_body_chars: 12000
    handshake:
      state: accepted
    notes: Owner email may issue scoped low-risk instructions; require out-of-band confirmation for code_or_shell, destructive changes, third-party sends, credentials, money, or irreversible actions.
```

## Trusted owner email instructions

AgentBook can represent the owner as a trusted human contact whose email may issue scoped instructions to the local agent. This is distinct from ordinary collaborator trust: a known sender gets only the scopes in their contact record.

Recommended owner scopes:

- `owner_instruction` — may include an instruction block at the top of an inbound email.
- `wiki_file` — may ask the agent to file forwarded material into the Wiki/knowledge base.
- `summarize` — may ask for summaries or extraction.
- `reply_confirm` — may receive a confirmation reply after verified completion.
- `schedule_task` — may create low-risk reminders or follow-up jobs.
- `code_or_shell` — high-risk; do not enable by default. If present, still require an out-of-band confirmation step before executing commands, installing software, changing config, or performing destructive actions.

Recommended inbound owner-forward flow:

1. Classify sender with `agentbook classify <sender-email>`.
2. Require `classification=trusted`, `decision=allow`, and `owner_instruction` scope.
3. Split the owner instruction block from forwarded/source content.
4. Execute only scopes present on the owner contact.
5. For low-risk Wiki/summarization tasks, verify the artifact exists before labeling the message `read` + `processed` or sending a confirmation.
6. For unsupported, ambiguous, or dangerous instructions, keep the message `unread`, add `flagged-for-review` / `needs-confirmation`, and ask the owner over the primary channel.
7. Never let trusted email become a remote shell; trust is scoped authorization, not blanket obedience.

## Development

```bash
python -m pip install -e .[dev]
python -m pytest -q
python -m compileall -q .
```

The tests stub `hermes_constants.get_hermes_home()` so they can run outside a full Hermes checkout.

## Security notes

- Unknown senders are never automatically trusted.
- Outbound validation requires `contact_id`; raw recipient strings are denied.
- Audit logs hash recipient and subject values and do not store API keys or full message bodies.
- Attachments and autonomous unknown-sender promotion are out of scope for the MVP.

## License

MIT
