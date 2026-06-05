# Claude Code support

AgentBook supports Claude Code through a simple pattern: **SkillMD/CLAUDE.md for behavior, CLI for enforcement**.

This is intentionally not MCP-first. MCP is optional. The CLI is easier to inspect, easier to test, and usable by Claude Code, OpenCode, Codex, Hermes, shell scripts, and humans.

## Install from a checkout

```bash
python -m pip install -e .
agentbook --help
```

If you are using the repository directly without installing, run commands as:

```bash
python agentbook_cli.py validate
```

## Configure storage

AgentBook uses Hermes-compatible storage by default:

```text
$HERMES_HOME/agentbook/address_book.yaml
$HERMES_HOME/agentbook/audit.jsonl
```

Outside Hermes, set `HERMES_HOME` explicitly if you want a project-local sandbox:

```bash
export HERMES_HOME="$PWD/.agentbook-home"
```

## Claude Code workflow

Give Claude Code access to this repo or to the installed `agentbook` command. The project `CLAUDE.md` tells Claude when to call the CLI.

### Outbound collaboration flow

```bash
agentbook classify collaborator@example.com
agentbook lookup --contact-id collaborator
agentbook validate-outbound \
  --contact-id collaborator \
  --subject "Coordination update" \
  --text "Short summary of what changed." \
  --dry-run
```

Only send the returned `agentmail_payload` after validation allows it.

### Inbound webhook flow

When AgentMail delivers a `message.received` webhook to your endpoint:

1. **Verify the Svix signature** with the raw request body and your webhook secret (`whsec_...`). Do not parse JSON before verifying.
2. **Return `200` immediately**, then process asynchronously.
3. **Classify the sender:**

   ```bash
   agentbook classify sender@example.com
   ```

4. **Unknown sender → quarantine silently.** Do **not** send any reply. That would confirm the inbox is valid to a potential attacker. Label the message `quarantined` and surface it to the owner.
5. **Known/trusted with `reply` scope** → process according to policy. Keep summaries minimal.
6. **Label the message `processed`** after handling. On cold start, filter by `labels=["unread"]` to avoid reprocessing.
7. **Audit everything.**

### Webhook payload notes

- `text` and `html` may be omitted if the payload exceeds 1 MB. Fetch the full message via the AgentMail API if missing.
- Attachments are metadata-only. Download via the API using `attachment_id`.
- `message.received.unauthenticated` events (SPF/DKIM/DMARC failures) are excluded by default.

### Trusted owner email-instruction flow

Owner email is a special trusted-human case, not ordinary collaborator trust. Add the owner with narrow inbound scopes, for example:

```bash
agentbook contacts add owner \
  --email owner@example.com \
  --display-name "Owner" \
  --agent-type human \
  --status trusted \
  --scopes send,reply,owner_instruction,wiki_file,summarize,reply_confirm,schedule_task \
  --allow-send owner@example.com
```

When an owner-forward arrives:

1. Classify the sender with `agentbook classify owner@example.com`.
2. Require `trusted` + `allow` + `owner_instruction` before parsing it as a command.
3. Split the owner instruction block from forwarded/source material.
4. Execute only scopes present on the owner contact.
5. For `wiki_file` / `summarize`, verify the artifact or response before marking `read` + `processed`.
6. For shell/code, destructive changes, third-party sends, credentials, money, installs, or config changes, stop and ask over the primary owner channel even if the email has `code_or_shell`.

## Adding a trusted collaborator

```bash
agentbook contacts add collaborator \
  --email collaborator@example.com \
  --display-name "Collaborator Agent" \
  --status trusted \
  --scopes send,reply,handshake \
  --allow-send collaborator@example.com

agentbook validate
```

Use this only after human/owner confirmation. Do not promote unknown senders autonomously.

## Denial behavior

`agentbook validate-outbound` exits with:

- `0` when the outbound draft is allowed
- `2` when policy denies it

For example, raw email sends are denied:

```bash
agentbook validate-outbound --to raw@example.com --subject Hi --text Nope
```

A Claude agent should treat exit code `2` as a hard stop and ask the human.

## Why not MCP-first?

MCP can be useful for Claude Desktop or other hosts that require native tool discovery. But for AgentBook, the core problem is behavior and policy:

- unknown senders must not become trusted automatically
- trusted contacts have scopes, not global authority
- outbound messages must be checked before transport send
- audit logs must stay redacted

SkillMD/CLAUDE.md communicates that behavior. The CLI enforces it deterministically. MCP is optional and can wrap the same CLI/core later without changing the trust model.
