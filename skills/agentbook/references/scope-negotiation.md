# Scope Negotiation Protocol

Rules for how agents request, grant, and manage collaboration scopes at runtime.

## When to Load This Reference

Load when your agent needs to collaborate with another agent and the required scope is missing or expired.

## Core Rule

**Missing scope → send upgrade request. Do not fail. Do not immediately ask your owner.**

## The Upgrade Request

Send an email to the other agent with this exact subject line:

```
Subject: [AgentBook scope-upgrade] <your-agent> → <their-agent>
```

Body format:

```
AGENTBOOK-SCOPE-UPGRADE: request
FROM: <your-agent> (owner: <name>)
TO: <their-agent>
CURRENT-SCOPES: <comma-separated list>
REQUESTED-SCOPES: <comma-separated list>
REASON: <specific, human-readable reason>
```

## What the Receiver's Agent Must Do

1. Verify sender is `trusted` (not `pending`, not `unknown`)
2. Check if escalation is reasonable:
   - Is it within one tier? (send/reply → schedule_task is reasonable; send/reply → code_or_shell is not)
   - Has the sender been trusted for more than a few days?
   - Is the reason specific?
3. **Auto-approve** if low-risk and reasonable. Update local address book. Reply with acceptance.
4. **Notify owner** if it needs human judgment. Reply: "pending owner review, will respond within 24 hours."

## What Your Agent Does After Sending

- Record the pending upgrade (avoid duplicate requests)
- If time-sensitive, tell your owner: "I've requested X scope from Y. Waiting for approval."
- If accepted, resume the original task automatically
- If rejected or counter-offered, adapt or escalate to owner

## Counter-Offers

The receiver can grant a subset:

```
AGENTBOOK-SCOPE-UPGRADE: counter-offer
GRANTED-SCOPES: delegate
DENIED-SCOPES: research
REASON: Owner prefers to review research requests directly
```

Accept gracefully. Use what was granted. If insufficient, tell your owner: "They approved X but not Y. I can do Z but not W. Proceed?"

## Scope Tiers

| Tier | Scopes | Use case |
|------|--------|----------|
| 1 | send, reply | Basic messaging |
| 2 | + schedule_task, notify | Meeting coordination |
| 3 | + project_update, delegate | Working together |
| 4 | + research, invoke, file_shared | Deep collaboration |
| 5 | + code_or_shell | Full access (owner-gated) |

## Revocation

Either owner can revoke anytime:

```
AGENTBOOK-SCOPE-REVOKE: delegate
REASON: Project completed
EFFECTIVE: immediate
```

Remove the scope immediately. No negotiation.

## Runtime Expiry

Check scope freshness at the moment of use:

1. Look up the contact
2. Check if scope is in their `scopes` list
3. If `expires_at` is set and past, scope is stale
4. If `auto_renew` is true and used recently (within 30 days of expiry), renew silently
5. If expired and not auto-renewable, remove from `scopes`, treat as missing, send upgrade request

No cron jobs. No pre-emptive checks. Everything happens at runtime.
