"""Native routes; opening them requires an installed app and OS scheme handler."""
from uuid import UUID


def conversation_link(source, session_id):
    try:
        identifier = str(UUID(session_id))
    except (ValueError, TypeError, AttributeError):
        return None
    if source == "Codex":
        return "codex://threads/" + identifier
    if source == "Claude":
        # The desktop app resolves a CLI UUID to its native session and resumes it.
        return "claude://resume?session=" + identifier
    return None
