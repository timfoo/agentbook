"""AgentBook plugin — address-book safety layer for agent-to-agent email.

Registers profile-safe local tools. Network AgentMail send/fetch operations are
intentionally optional/stubbed in the MVP; tools validate and dry-run payloads.
"""

from __future__ import annotations

from pathlib import Path

from .schemas import (
    AUDIT_SCHEMA,
    CLASSIFY_SCHEMA,
    CONTACTS_SCHEMA,
    HANDSHAKE_SCHEMA,
    LOOKUP_SCHEMA,
    VALIDATE_ADDRESS_BOOK_SCHEMA,
    VALIDATE_OUTBOUND_SCHEMA,
)
from .tools import (
    _check_agentbook_available,
    _handle_agentbook_audit,
    _handle_agentbook_classify,
    _handle_agentbook_contacts,
    _handle_agentbook_handshake,
    _handle_agentbook_lookup,
    _handle_agentbook_validate_address_book,
    _handle_agentbook_validate_outbound,
)

_TOOLS = (
    ("agentbook_contacts", CONTACTS_SCHEMA, _handle_agentbook_contacts, "📒"),
    ("agentbook_lookup", LOOKUP_SCHEMA, _handle_agentbook_lookup, "🔎"),
    ("agentbook_classify", CLASSIFY_SCHEMA, _handle_agentbook_classify, "🧭"),
    ("agentbook_validate_outbound", VALIDATE_OUTBOUND_SCHEMA, _handle_agentbook_validate_outbound, "🛡️"),
    ("agentbook_handshake", HANDSHAKE_SCHEMA, _handle_agentbook_handshake, "🤝"),
    ("agentbook_validate_address_book", VALIDATE_ADDRESS_BOOK_SCHEMA, _handle_agentbook_validate_address_book, "✅"),
    ("agentbook_audit", AUDIT_SCHEMA, _handle_agentbook_audit, "🧾"),
)


def register(ctx) -> None:
    """Register AgentBook tools and bundled skill."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="agentbook",
            schema=schema,
            handler=handler,
            check_fn=_check_agentbook_available,
            emoji=emoji,
        )
    skills_dir = Path(__file__).resolve().parent / "skills"
    if hasattr(ctx, "register_skill"):
        ctx.register_skill("agentbook", skills_dir / "agentbook" / "SKILL.md", "Use AgentBook contacts, handshakes, outbound validation, and audit logs safely.")
        collaboration_skill = skills_dir / "agentmail-collaboration" / "SKILL.md"
        if collaboration_skill.exists():
            ctx.register_skill("agentmail-collaboration", collaboration_skill, "Use AgentBook before collaborating with another agent over AgentMail/email-like transports.")
