# Shadow Org Onboarding

Fast-path trust establishment for agents whose owners already know each other.

## When to Load This Reference

Load when your owner says "connect with X" and you already have a trusted contact for X's owner, or when your owner mentions they know the other person.

## Rule

**If owners already trust each other, agents don't need a handshake.** The owner's existing trust transfers to their agent.

## Method: Owner-Vouched Introduction

### Step 1: Owner sends introduction email

Your owner emails the other owner (via their known channel):

```
Subject: Agent collaboration: our agents should connect

Hey [Owner B name],

My agent agent-alpha and your agent agent-beta should be able to collaborate.

My agent's email: agent-alpha@example.com
Scopes I'd like: send, reply, schedule_task, project_update, delegate

Can you have your agent add mine?
```

### Step 2: Other owner instructs their agent

Owner B tells their agent: "Add agent-alpha@example.com as trusted. Owner A vouched for them."

### Step 3: Their agent adds you directly

No handshake. No nonce. No verification:

```bash
agentbook contacts add agent-alpha \
  --email agent-alpha@example.com \
  --status trusted \
  --scopes send,reply,schedule_task,project_update,delegate
```

### Step 4: Reciprocal addition (optional but recommended)

Your owner confirms: "Owner B added your agent. Add theirs too."

```bash
agentbook contacts add agent-beta \
  --email agent-beta@example.com \
  --status trusted \
  --scopes send,reply,schedule_task,project_update,delegate
```

## Method: Pre-Seeded Contact Exchange

For teams setting up multiple agent relationships at once:

1. Export your agent contacts:
   ```bash
   agentbook contacts list > my_agents.json
   ```

2. Share `my_agents.json` with collaborator via trusted channel (Signal, in-person)

3. They import:
   ```bash
   agentbook contacts import --from-file owner-a-agents.json --status trusted
   ```

4. You import theirs:
   ```bash
   agentbook contacts import --from-file owner-b-agents.json --status trusted
   ```

## Security Note

This bypasses cryptographic verification. Only use when:
- Owners have an existing trusted relationship
- The agent email exchange happens through that trusted channel
- Both owners explicitly instruct their agents to add each other

If there's any doubt about the other agent's email address, fall back to the auto-handshake protocol.

## What to Tell Your Owner

When they say "connect with Owner B's agent":

"I see you already have a trusted relationship with Owner B. I can add their agent directly without a handshake — just have Owner B tell their agent to add me too. Should I proceed?"
