"""Reserved AgentBook state helpers.

The MVP uses static YAML policy plus append-only JSONL audit. A future phase may
place idempotency/thread state under get_hermes_home()/agentbook/state.sqlite.
"""

from __future__ import annotations

from pathlib import Path

from .address_book import agentbook_dir


def state_path() -> Path:
    return agentbook_dir() / "state.sqlite"
