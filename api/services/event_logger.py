import json
from database import execute

__all__ = ["log_event"]


async def log_event(category, level, actor, action, target=None, details=None):
    """Write to event_log. Fire-and-forget, never blocks the caller."""
    try:
        if details:
            try:
                from services import sensitive_intake
                details = await sensitive_intake.sanitize_json(
                    details,
                    source=f"event_log.{category}.{action}",
                    actor=actor or "event-logger",
                )
            except Exception:
                details = _fallback_redact(details)
        details_json = json.dumps(details, default=str) if details else None
        await execute(
            "INSERT INTO event_log (category, level, actor, action, target, details) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            category, level, actor, action, target, details_json,
        )
    except Exception:
        pass


def _fallback_redact(value):
    if isinstance(value, str):
        import re
        text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "<redacted:ssn>", value)
        text = re.sub(r"(?i)\b(password|token|api[_ -]?key|secret)\b\s*[:=]\s*[^\s,;]{6,}", r"\1=<redacted>", text)
        return text
    if isinstance(value, list):
        return [_fallback_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _fallback_redact(item) for key, item in value.items()}
    return value
