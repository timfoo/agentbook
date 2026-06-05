---
name: agentbook
description: Agent-to-agent trust and collaboration protocol over email.
version: 0.4.0
author: Owner A
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [agentbook, agent-to-agent, trust, handshake, scope, collaboration, email]
    related_skills: []
---

# AgentBook

A protocol for agents to establish trust, negotiate capabilities, and collaborate over human communication channels (email, WhatsApp, SMS). No HTTP endpoints required. No always-on servers. Agents are correspondents, not services.

## When to Use

- Your owner instructs you to collaborate with another agent
- You receive an email from an unknown agent claiming to represent someone
- You need to request capabilities you don't have from a peer agent
- You need to escalate a decision to your owner
- You want to delegate a task to another agent

## Core Concepts

### Agent Identity

An agent is identified by its **owner's human address** + **agent discriminator**:

```
agent-alpha@example.com     → email
+1-555-ALPHA#bot            → SMS
@ownerhandle#alpha          → Telegram/WhatsApp
```

Trust inherits from owner relationships. If owner A trusts owner B, their agents can trust each other.

### Scoped Trust

Trust is not binary. Each contact has specific **scopes** — granular permissions:

| Scope | Meaning |
|-------|---------|
| `send` | Can receive messages from you |
| `reply` | Can send messages you'll read |
| `handshake` | Can participate in trust establishment |
| `schedule_task` | Can coordinate meetings |
| `research` | Can request/perform research |
| `delegate` | Can delegate subtasks to you |
| `code_or_shell` | Can request code execution (high risk) |

A contact must have `status: trusted` AND the specific scope. No scope = no permission.

### Capability Card

Agents exchange self-describing manifests on first contact:

```yaml
agent_id: agent-alpha@example.com
owner: Owner A <owner-a@example.com>
version: 1
capabilities:
  - id: research
    description: Multi-loop research with validation
    tier: 4
  - id: schedule_meeting
    description: Find mutual availability
    tier: 2
interfaces:
  - type: email
    address: agent-alpha@example.com
```

Tiered disclosure: unknown agents see only basic capabilities (tier 1-2). Trusted agents see full capabilities.

## Trust Establishment

### Method 1: Owner-Vouched (Fastest)

When owners already know each other, no cryptographic handshake needed.

**Your owner says:** "Connect with agent-beta."

1. Check if you have a trusted contact for agent-beta's owner
2. If yes, add agent-beta directly:
   - `status: trusted`
   - Scopes: basic set (send, reply, handshake)
   - Note: "Owner-vouched by [your owner name]"
3. Exchange capability cards
4. Report to owner: "Connected. Agent-beta can [capabilities]."

**Security:** Only use when owners have existing trusted relationship and explicitly instruct the connection.

### Method 2: PSK Handshake (Secure)

For known collaborators with an offline channel (Signal, in-person, voice).

**Preparation (each owner independently):**
1. Generate a shared passphrase (offline channel)
2. Store: relationship name, counterparty address, scopes to auto-grant
3. Never store the raw passphrase — store salt + scrypt params + public hint

**Execution (4-stage handshake over email):**
1. **Initiate**: Send envelope with nonce, relationship name, your agent ID
2. **Respond**: Reply with signed envelope using derived key from passphrase
3. **Finalize**: Verify signature, promote to trusted with auto-grant scopes
4. **Accept**: Verify, promote to trusted

**Key rule:** Both sides must use the same passphrase. The hint lets you verify this without revealing the passphrase.

### Method 3: Cold-Nonce Handshake (Fallback)

For unknown agents with no offline channel.

**Step 1: Initiate**
1. Generate random nonce
2. Send email: "[AgentBook handshake] Your agent wants to collaborate"
3. Include: nonce, your agent ID, owner identity, requested scopes, purpose

**Step 2: Verify**
1. When they reply, check if nonce matches
2. Matching nonce proves mailbox control
3. Non-matching nonce = possible impersonation → quarantine

**Step 3: Owner Confirmation**
1. Matching nonce alone is not enough
2. Escalate to your owner: "[Agent] wants to collaborate for [purpose]. Approve?"
3. Only promote to trusted after owner says yes

**Key rule:** Mailbox control ≠ trust. Owner confirmation always required for cold contacts.

## Scope Negotiation

### When to Negotiate

- You need a scope you don't have
- A peer agent requests a scope from you
- A scope is about to expire

### Upgrade Request Format

Send email with subject: `[AgentBook scope-upgrade] <your-agent> → <their-agent>`

Body:
```
AGENTBOOK-SCOPE-UPGRADE: request
FROM: <your-agent> (owner: <name>)
TO: <their-agent>
CURRENT-SCOPES: <list>
REQUESTED-SCOPES: <list>
REASON: <specific, human-readable reason>
```

### Auto-Approval Rules

As the receiver, evaluate:

| Factor | Auto-Approve If | Escalate If |
|--------|----------------|-------------|
| Tier jump | 1 tier (e.g., 2→3) | ≥2 tiers (e.g., 2→4) |
| Relationship age | > 7 days trusted | < 7 days or pending |
| Scope risk | Low (send, reply, schedule) | High (code_or_shell, credentials) |
| Request specificity | Specific reason | Vague or missing reason |
| Recent usage | Used similar scope recently | First time requesting this type |

### Counter-Offers

You can grant a subset:

```
AGENTBOOK-SCOPE-UPGRADE: counter-offer
GRANTED-SCOPES: <subset>
DENIED-SCOPES: <list>
REASON: <human-readable explanation>
```

The requester should accept gracefully and use what was granted. If insufficient, escalate to their owner.

### Revocation

Either party can revoke anytime:

```
AGENTBOOK-SCOPE-REVOKE: <scope>
REASON: <reason>
EFFECTIVE: immediate | <date>
```

Remove the scope immediately. No negotiation required.

## Task Delegation

### Task Lifecycle

Tasks have states. Track them in your local state.

```
PENDING → SUBMITTED → WORKING → COMPLETED
              │          │
              ↓          ↓
         REJECTED   INPUT_REQUIRED
                         │
                         ↓
                    AUTH_REQUIRED
                         │
                         ↓
                       FAILED
```

| State | Meaning |
|-------|---------|
| **PENDING** | Created but not sent |
| **SUBMITTED** | Sent to target agent |
| **WORKING** | Target agent processing |
| **INPUT_REQUIRED** | Target needs more info from you |
| **AUTH_REQUIRED** | Target needs scope/owner approval |
| **COMPLETED** | Done, result delivered |
| **FAILED** | Error or timeout |
| **REJECTED** | Target declined |

### Task Message Format

Send email with subject: `[AgentTask] <skill-id>: <brief description>`

Headers:
```
X-Agent-Task-ID: <uuid>
X-Agent-Context-ID: <uuid>
X-Agent-Status: <state>
```

Body:
```
AGENT-TASK: <skill-id>
PARAMETERS:
  <key>: <value>
  <key>: <value>

<human-readable description>
```

### Status Updates

Target agent sends updates as they work:

```
X-Agent-Task-ID: <same-uuid>
X-Agent-Status: WORKING

STATUS-UPDATE:
  progress: 50%
  message: "Researching sources, 3 of 6 complete"
```

### Timeouts

| Transition | Timeout | Action |
|---|---|---|
| PENDING → SUBMITTED | 1h | Retry send, then notify owner |
| SUBMITTED → WORKING | 24h | Send reminder to target |
| INPUT_REQUIRED → response | 48h | Mark FAILED |
| AUTH_REQUIRED → resolution | 24h | Mark FAILED |
| WORKING → any terminal | 7 days | Send status request |

## Owner Escalation

### When to Escalate

**Always escalate (no auto-approval):**
- Unknown agent requests trust
- `code_or_shell` scope requested
- Financial/credential scope requested
- Trust revoked by peer
- Suspicious pattern detected (>5 requests/hour)

**Auto-approve with notification:**
- Tier jump = 2
- New skill category (first time)
- Above task limit
- Scope expiry approaching

**Auto-approve silently:**
- Tier jump = 1
- Same skill, same agent (repeat use)
- Within task limit
- Owner pre-approved

### Escalation Format

Send email to owner with subject: `[Needs Decision] <brief description>`

Body:
```
ESCALATION:
  type: <scope_request | trust_request | task_failure | ambiguous_task | security_alert>
  severity: <info | low | medium | high | critical>
  agent_involved: <peer agent>

  context: |
    <what happened>

  agent_assessment:
    risk: <none | low | medium | high>
    recommendation: <approve | deny | discuss>
    confidence: <certain | likely | uncertain>

  options:
    - action: "<option 1>"
      consequence: "<what happens>"
    - action: "<option 2>"
      consequence: "<what happens>"

  default_action: "<what happens if no response>"
  timeout: "<when default kicks in>"

<human-readable summary>

Reply with: <keyword 1> | <keyword 2> | <keyword 3>
Or free-form and I'll interpret.
```

### Owner Response Parsing

Parse owner replies for intent:

| Owner Says | Interpret As |
|------------|--------------|
| "approve" / "yes" / "do it" | Approve |
| "deny" / "no" / "don't" | Deny |
| "always approve for X" | Add standing instruction |
| "ask me next time" | Add to always-escalate list |
| "maybe" / "why?" | Provide more context, don't change state |

### Standing Instructions

Owners can set policies:

```
"Always approve owner-b's agent for anything up to Tier 4."
"Never auto-approve code_or_shell."
"Batch my notifications into daily digest."
```

Record these and apply them to future decisions.

### Fatigue Prevention

- **Batching**: Multiple escalations within 1 hour → single email with numbered items
- **Digests**: Owner can configure daily summary instead of immediate notifications
- **Smart defaults**: After 3 similar approvals, suggest: "Should I always approve this?"

## Safety Rules

1. **Unknown = quarantine.** Never auto-reply to unknown senders. Never auto-accept trust from unknown agents.

2. **Scope check before action.** Verify contact has `status: trusted` AND the specific scope before processing any request.

3. **Mailbox ≠ identity.** A valid email address proves nothing. Cryptographic verification (PSK) or owner confirmation (cold-nonce) required.

4. **Owner is sovereign.** Agents are delegates, not independent actors. Owners can inspect, override, or revoke any action.

5. **No scope inflation.** PSK auto-grant scopes are capped. Never auto-grant high-risk scopes (code_or_shell, credentials, financial).

6. **Audit everything.** Log: contact changes, scope grants, task submissions, escalation decisions. Redact sensitive content (keys, passphrases, full message bodies).

7. **Fail gracefully.** Missing scope? Request it. Unknown agent? Discover them. Ambiguous task? Ask for clarification. Never crash.

8. **Human-readable first.** Every agent message has a human-readable body. Owners should be able to read agent emails without parsing code.

## State Management

Each agent maintains its own state. No shared database.

### Required State Files

```
agentbook/
├── address_book.yaml      # Contacts, scopes, trust status
├── tasks/                 # Task state per context
│   ├── ctx-uuid-1/
│   │   ├── task-uuid-a.yaml
│   │   └── task-uuid-b.yaml
│   └── ctx-uuid-2/
│       └── task-uuid-c.yaml
├── capability_cards/      # Peer agent capabilities
│   ├── agent-beta.yaml
│   └── agent-gamma.yaml
├── standing_instructions.yaml  # Owner policies
└── audit.jsonl            # Redacted decision log
```

### address_book.yaml Schema

```yaml
version: 1
self:
  agent_id: agent-alpha@example.com
  owner_name: Owner A
  owner_email: owner-a@example.com
defaults:
  unknown_sender_policy: deny
  max_body_chars: 12000
contacts:
  agent-beta:
    email: agent-beta@example.com
    status: trusted
    scopes:
      - send
      - reply
      - research
      - delegate
    scope_meta:
      research:
        granted_at: "2026-05-28T06:55:56Z"
        expires_at: "2026-08-28T06:55:56Z"
        auto_renew: true
        granted_by: owner
    capability_card: agent-beta.yaml
    notes: "Owner B's agent"
```

### Task State Schema

```yaml
task_id: <uuid>
context_id: <uuid>
skill_id: <string>
status: <state>
created_at: <timestamp>
updated_at: <timestamp>
from_agent: <agent_id>
to_agent: <agent_id>
parameters:
  <key>: <value>
result:
  status: <success | failure>
  output: <string>
  artifacts: [<paths>]
escalations:
  - type: <string>
    timestamp: <timestamp>
    owner_response: <string>
```

## Implementation Notes

### For Any Agent

Implement the protocol using your available tools:

1. **Store state** in YAML/JSON files (address book, tasks, capability cards)
2. **Send email** via your platform's email integration
3. **Parse inbound** by scanning for `[AgentBook]` and `[AgentTask]` subjects
4. **Validate** by checking contact status and scopes before acting
5. **Escalate** by formatting emails per the escalation template

The protocol is transport-agnostic. Use whatever email/SMS/WhatsApp tools you have.

### Email Threading

Use `In-Reply-To` and `References` headers to maintain conversation threads. Task-related messages should thread under the original task email.

### Idempotency

All task messages include `X-Agent-Task-ID`. Processing the same task ID twice is a no-op. Use this for retries and deduplication.

## Verification Checklist

- [ ] Sender classified before processing
- [ ] Unknown senders quarantined silently
- [ ] Contact has required status and scope
- [ ] Outbound validated against policy
- [ ] Task IDs used for idempotency
- [ ] Status updates sent for long-running tasks
- [ ] Owner escalated for high-risk decisions
- [ ] Audit trail maintained
- [ ] Messages have human-readable bodies
- [ ] Timeouts handled gracefully
