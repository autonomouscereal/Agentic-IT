import json
from database import execute

__all__ = ["log_event"]


async def log_event(category, level, actor, action, target=None, details=None):
    """Write to event_log. Fire-and-forget, never blocks the caller."""
    try:
        details_json = json.dumps(details, default=str) if details else None
        await execute(
            "INSERT INTO event_log (category, level, actor, action, target, details) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            category, level, actor, action, target, details_json,
        )
    except Exception:
        pass
