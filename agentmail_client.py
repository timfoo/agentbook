"""Optional AgentMail client shim for AgentBook.

Network send/fetch is intentionally not implemented in the MVP skeleton. Tools
perform validation and dry-run payload construction only, so no credentials or
AgentMail API shape are assumed and no secrets are hardcoded.
"""

from __future__ import annotations


def available() -> bool:
    import os

    return bool(os.getenv("AGENTMAIL_API_KEY"))


def send_message(*_args, **_kwargs):
    raise NotImplementedError("AgentBook MVP validates/dry-runs outbound messages but does not send network requests yet.")
