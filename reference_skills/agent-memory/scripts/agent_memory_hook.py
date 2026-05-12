#!/usr/bin/env python3
"""
Async hook adapter for the PostgreSQL-only agent memory backend.

Reads hook JSON from stdin first, then argv fallback. Errors are logged and the
hook exits zero so memory failures never break the agent harness.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from typing import Any

from agent_memory import LOG_DIR, add_event_async, json_default, normalize_space, parse_json_arg


SECRET_KEY_RE = re.compile(
    r"(token|secret|password|credential|authorization|api[_-]?key|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
SECRET_TEXT_RE = re.compile(
    r"(?i)(token|secret|password|credential|authorization|api[_-]?key|access[_-]?token|refresh[_-]?token)"
    r"([\"'=:\s]{0,8})([^,\s\"'}]{8,})"
)


def audit_safe_text(text: str, limit: int | None = 4000) -> str:
    """Keep hook payload text UTF-8 safe without dropping audit content."""
    if not text:
        return ""
    value = text if limit is None else text[:limit]
    value = value.replace("\x00", "\\x00")
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


def redact_text(text: str, limit: int = 4000) -> str:
    if not text:
        return ""
    return SECRET_TEXT_RE.sub(r"\1\2<redacted>", audit_safe_text(text, limit))


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if SECRET_KEY_RE.search(str(key)):
                clean[key] = "<redacted>"
            else:
                clean[key] = sanitize_value(item)
        return clean
    if isinstance(value, list):
        return [sanitize_value(item) for item in value[:100]]
    if isinstance(value, str):
        return redact_text(value, limit=None)
    return value


def safe_log(filename: str, record: dict[str, Any]) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / filename).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=json_default, sort_keys=True) + "\n")
    except Exception:
        pass


def parse_payload(raw: str) -> tuple[Any, str]:
    raw = raw.strip()
    if not raw:
        return {}, ""
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError:
        try:
            return json.loads(raw.replace('\\"', '"')), raw
        except json.JSONDecodeError:
            lax = parse_json_arg(raw, None)
            if isinstance(lax, dict):
                return lax, raw
            return {"raw": raw}, raw


def extract_text(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("prompt", "message", "content", "last_assistant_message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        if "payload" in payload:
            nested = extract_text(payload["payload"])
            if nested:
                return nested
    return json.dumps(payload, ensure_ascii=False, indent=2, default=json_default)


def normalize_event(event: str) -> tuple[str, str]:
    mapping = {
        "UserPromptSubmit": ("user_prompt", "user"),
        "PostToolUse": ("tool_call", "tool"),
        "PostToolUseFailure": ("tool_call_failure", "tool"),
        "Stop": ("session_stop", "assistant"),
        "SessionEnd": ("session_end", "system"),
        "PreCompact": ("pre_compact", "system"),
    }
    return mapping.get(event, (event.lower(), "system"))


def build_metadata(args: argparse.Namespace, payload: Any, raw_payload: str) -> dict[str, Any]:
    metadata = {
        "hook_event": args.event,
        "raw_payload": sanitize_value(payload) if isinstance(payload, dict) else redact_text(raw_payload),
        "cwd": os.getcwd(),
        "recorded_at": datetime.now(UTC).isoformat(),
    }
    if isinstance(payload, dict):
        for key in ("tool_name", "tool_input", "duration_ms", "status", "transcript_path", "cwd"):
            if key in payload:
                metadata[key] = sanitize_value(payload[key])
    return metadata


def derive_space(args: argparse.Namespace, payload: Any) -> str:
    if args.space:
        return normalize_space(args.space)
    env_space = os.getenv("AGENT_MEMORY_SPACE", "").strip()
    if env_space:
        return normalize_space(env_space)
    cwd = ""
    if isinstance(payload, dict):
        cwd = str(payload.get("cwd") or "")
        if not cwd:
            cwd = str((payload.get("raw_payload") or {}).get("cwd") or "") if isinstance(payload.get("raw_payload"), dict) else ""
    cwd = cwd or os.getcwd()
    normalized = cwd.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    lowered = [part.lower() for part in parts]
    if "codex" in lowered:
        idx = lowered.index("codex")
        tail = parts[idx + 1 : idx + 4]
        if tail:
            return normalize_space("codex/" + "/".join(tail))
    if "soc-dashboard" in lowered:
        return normalize_space("soc-dashboard")
    if "memory_backend" in lowered:
        return normalize_space("agent-memory/backend")
    if parts:
        return normalize_space("workspace/" + parts[-1])
    return "global"


async def run_hook(args: argparse.Namespace, raw: str, started: float) -> int:
    payload, raw_payload = parse_payload(raw)
    event_type, role = normalize_event(args.event)
    session_id = args.session_id
    if isinstance(payload, dict):
        session_id = str(payload.get("session_id") or payload.get("conversation_id") or session_id or "")

    clean_payload = sanitize_value(payload)
    content = extract_text(clean_payload)
    metadata = build_metadata(args, clean_payload, raw_payload)
    space = derive_space(args, clean_payload)
    metadata["memory_space"] = space

    try:
        result = await add_event_async(
            agent=args.agent,
            event_type=event_type,
            space=space,
            memory_kind="hook",
            role=role,
            source=args.source,
            session_id=session_id,
            content=content,
            tags=[args.agent, event_type, args.source, "asyncpg", space],
            metadata=metadata,
        )
        safe_log(
            "agent_memory_hook_events.jsonl",
            {
                "ok": True,
                "created_at": datetime.now(UTC).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "event": args.event,
                "event_type": event_type,
                "agent": args.agent,
                "source": args.source,
                "space": space,
                "session_id": session_id,
                "memory_id": result["id"],
                "inserted": result.get("inserted"),
                "content_sha256": hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest(),
                "payload_chars": len(raw or ""),
                "driver": "asyncpg",
                "pid": os.getpid(),
            },
        )
        if args.emit_json:
            print(json.dumps({"continue": True, "suppressOutput": True}, ensure_ascii=False))
        return 0
    except Exception as exc:
        safe_log(
            "agent_memory_hook_errors.jsonl",
            {
                "ok": False,
                "created_at": datetime.now(UTC).isoformat(),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "event": args.event,
                "agent": args.agent,
                "source": args.source,
                "space": space,
                "session_id": session_id,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "payload_excerpt": redact_text(raw or "", 1200),
                "payload_sha256": hashlib.sha256((raw or "").encode("utf-8", errors="replace")).hexdigest(),
                "driver": "asyncpg",
                "pid": os.getpid(),
            },
        )
        if args.emit_json:
            print(json.dumps({"continue": True, "suppressOutput": True}, ensure_ascii=False))
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Record harness hook payload in async agent memory")
    parser.add_argument("--event", required=True)
    parser.add_argument("--agent", default=os.getenv("AGENT_MEMORY_AGENT", "agent"))
    parser.add_argument("--source", default="hook")
    parser.add_argument("--space", default=os.getenv("AGENT_MEMORY_SPACE", ""))
    parser.add_argument("--session-id", default=os.getenv("CLAUDE_CODE_SESSION_ID", os.getenv("AGENT_MEMORY_SESSION_ID", "")))
    parser.add_argument("--emit-json", action="store_true", help="Emit Codex/Claude hook-control JSON for explicit tests only")
    parser.add_argument("payload", nargs="*")
    return parser


def main() -> int:
    started = time.monotonic()
    args = build_parser().parse_args()
    stdin_raw = ""
    if not sys.stdin.isatty():
        stdin_raw = sys.stdin.read()
    argv_raw = " ".join(args.payload).strip()
    raw = stdin_raw.strip() or argv_raw
    return asyncio.run(run_hook(args, raw, started))


if __name__ == "__main__":
    raise SystemExit(main())
