import base64
import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet

from database import execute, fetchall, fetchrow, fetchval, json_dumps

PUBLIC_BASE_URL = (
    os.getenv("DASHBOARD_PUBLIC_URL")
    or os.getenv("DASHBOARD_PUBLIC_BASE_URL")
    or os.getenv("DASHBOARD_URL")
    or ""
)
DEFAULT_EXPIRES_HOURS = int(os.getenv("SENSITIVE_INTAKE_EXPIRES_HOURS", "24"))
MAX_TEXT_SCAN_CHARS = int(os.getenv("SENSITIVE_INTAKE_MAX_TEXT_SCAN_CHARS", "20000"))

FIELD_TYPE_ALIASES = {
    "password": "credential",
    "passwd": "credential",
    "passcode": "credential",
    "secret": "secret",
    "token": "token",
    "api_key": "token",
    "apikey": "token",
    "ssn": "ssn",
    "social_security": "ssn",
    "dob": "dob",
    "date_of_birth": "dob",
    "government_id": "government_id",
    "drivers_license": "government_id",
    "credit_card": "financial",
    "bank_account": "financial",
}

SENSITIVE_PATTERNS = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credential", re.compile(
        r"(?i)\b(password|passwd|passcode|temporary password|temp password|initial password)\b\s*[:=]\s*([^\s,;]{6,})"
    )),
    ("token", re.compile(
        r"(?i)\b(api[_ -]?key|token|secret|bearer)\b\s*[:=]\s*([A-Za-z0-9._~+/=$:-]{12,})"
    )),
    ("token", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-or-v1-[A-Za-z0-9]+|ghp_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,})\b")),
    ("token", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("dob", re.compile(
        r"(?i)\b(dob|date of birth|birth date)\b\s*[:=]\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4})"
    )),
    ("financial", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
]


def normalize_field_type(value):
    raw = str(value or "freeform_sensitive").strip().lower().replace("-", "_").replace(" ", "_")
    return FIELD_TYPE_ALIASES.get(raw, raw or "freeform_sensitive")


def _redact_text_only(text):
    value = str(text or "")
    if not value:
        return value
    spans = detect_sensitive_spans(value)
    if not spans:
        return value
    redacted = value
    for span in reversed(spans):
        redacted = redacted[:span["start"]] + f"<redacted:{span['field_type']}>" + redacted[span["end"]:]
    return redacted


def _redact_json_only(value):
    if isinstance(value, str):
        return _redact_text_only(value)
    if isinstance(value, list):
        return [_redact_json_only(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_json_only(item) for key, item in value.items()}
    return value


def _secret_material():
    raw = (
        os.getenv("SENSITIVE_INTAKE_MASTER_KEY", "").strip()
        or os.getenv("DASHBOARD_SESSION_SECRET", "").strip()
        or os.getenv("DASHBOARD_SERVICE_TOKEN", "").strip()
        or os.getenv("DB_PASSWORD", "").strip()
        or "local-sensitive-intake-development-key"
    )
    try:
        Fernet(raw.encode("ascii"))
        return raw.encode("ascii")
    except Exception:
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)


def _fernet():
    return Fernet(_secret_material())


def encrypt_value(value):
    return _fernet().encrypt(str(value or "").encode("utf-8")).decode("ascii")


def decrypt_value(ciphertext):
    return _fernet().decrypt(str(ciphertext or "").encode("ascii")).decode("utf-8")


def hash_token(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def hash_value(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def public_form_url(token):
    path = f"/secure-intake/{token}"
    base = PUBLIC_BASE_URL.rstrip("/")
    return f"{base}{path}" if base else path


def _is_expired(expires_at):
    if not expires_at:
        return False
    now = datetime.now(timezone.utc)
    if getattr(expires_at, "tzinfo", None) is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


def _new_ref(prefix):
    return f"{prefix}_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def _optional_int(value):
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_fields(fields):
    normalized = []
    seen = set()
    for index, item in enumerate(fields or [], start=1):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or item.get("name") or f"field_{index}").strip().lower()
        key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_") or f"field_{index}"
        if key in seen:
            key = f"{key}_{index}"
        seen.add(key)
        label = _redact_text_only(item.get("label") or item.get("name") or key.replace("_", " ").title()).strip()[:240]
        field_type = normalize_field_type(item.get("type") or item.get("field_type"))
        normalized.append({
            "key": key[:120],
            "label": label or key,
            "type": field_type[:80],
            "required": bool(item.get("required", True)),
            "help": _redact_text_only(item.get("help") or "").strip()[:500],
        })
    return normalized


async def _record_event(request_id, actor, action, details=None):
    await execute(
        """
        INSERT INTO sensitive_intake_events (request_id, actor, action, details)
        VALUES ($1, $2, $3, $4::jsonb)
        """,
        request_id,
        actor or "system",
        action,
        json_dumps(details or {}),
    )


async def create_request(
    fields,
    purpose="",
    ticket_id=None,
    session_id=None,
    requested_by="agent",
    requester_name=None,
    requester_email=None,
    channel="dashboard",
    expires_hours=None,
    metadata=None,
):
    normalized_fields = normalize_fields(fields)
    if not normalized_fields:
        return {"error": "at least one field is required"}
    safe_purpose = _redact_text_only(purpose or "")
    safe_metadata = _redact_json_only(metadata or {})
    request_ref = _new_ref("sir")
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(hours=int(expires_hours or DEFAULT_EXPIRES_HOURS))
    ticket_id = _optional_int(ticket_id)
    session_id = _optional_int(session_id)
    request_id = await fetchval(
        """
        INSERT INTO sensitive_intake_requests (
            request_ref, form_token_hash, status, purpose, ticket_id, session_id,
            requested_by, requester_name, requester_email, channel, fields,
            metadata, expires_at
        )
        VALUES ($1, $2, 'pending', $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11::jsonb, $12)
        RETURNING id
        """,
        request_ref,
        hash_token(token),
        safe_purpose,
        ticket_id,
        session_id,
        requested_by or "agent",
        requester_name,
        requester_email,
        channel or "dashboard",
        json_dumps(normalized_fields),
        json_dumps(safe_metadata),
        expires,
    )
    await _record_event(request_id, requested_by, "sensitive_form_requested", {
        "request_ref": request_ref,
        "ticket_id": ticket_id,
        "session_id": session_id,
        "field_count": len(normalized_fields),
        "field_types": sorted({item["type"] for item in normalized_fields}),
        "raw_values_logged": False,
    })
    return {
        "id": request_id,
        "request_ref": request_ref,
        "status": "pending",
        "purpose": safe_purpose,
        "fields": normalized_fields,
        "expires_at": expires.isoformat(),
        "form_url": public_form_url(token),
        "token": token,
        "raw_values_returned": False,
    }


async def get_request_by_token(token):
    row = await fetchrow(
        """
        SELECT id, request_ref, status, purpose, ticket_id, session_id,
               requester_name, requester_email, channel, fields, metadata,
               expires_at, submitted_at, created_at
        FROM sensitive_intake_requests
        WHERE form_token_hash = $1
        """,
        hash_token(token),
    )
    if not row:
        return None
    return _public_request(row)


def _json_value(value, fallback):
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        import json
        return json.loads(value)
    except Exception:
        return fallback


def _public_request(row):
    if not row:
        return None
    fields = _json_value(row.get("fields"), [])
    metadata = _json_value(row.get("metadata"), {})
    expires = row.get("expires_at")
    expired = _is_expired(expires)
    status = row.get("status") or "pending"
    if expired and status == "pending":
        status = "expired"
    return {
        "request_ref": row.get("request_ref"),
        "status": status,
        "purpose": row.get("purpose") or "",
        "ticket_id": row.get("ticket_id"),
        "session_id": row.get("session_id"),
        "requester_name": row.get("requester_name"),
        "requester_email": row.get("requester_email"),
        "channel": row.get("channel"),
        "fields": fields,
        "metadata": metadata,
        "expires_at": row.get("expires_at").isoformat() if row.get("expires_at") else None,
        "submitted_at": row.get("submitted_at").isoformat() if row.get("submitted_at") else None,
        "created_at": row.get("created_at").isoformat() if row.get("created_at") else None,
        "raw_values_returned": False,
    }


async def submit_request(token, values, submitted_by="secure-form"):
    row = await fetchrow("SELECT * FROM sensitive_intake_requests WHERE form_token_hash = $1", hash_token(token))
    if not row:
        return {"error": "invalid_or_expired_form"}
    if row.get("status") != "pending":
        return {"error": "form_not_accepting_submissions", "status": row.get("status")}
    expires = row.get("expires_at")
    if _is_expired(expires):
        await execute("UPDATE sensitive_intake_requests SET status = 'expired', updated_at = NOW() WHERE id = $1", row["id"])
        await _record_event(row["id"], submitted_by, "sensitive_form_expired", {"request_ref": row.get("request_ref")})
        return {"error": "form_expired"}
    fields = _json_value(row.get("fields"), [])
    values = values or {}
    missing = []
    cleaned_values = []
    for field in fields:
        key = field.get("key")
        value = str(values.get(key) or "").strip()
        if field.get("required") and not value:
            missing.append(key)
            continue
        if not value:
            continue
        cleaned_values.append((field, key, value))
    if missing:
        await _record_event(row["id"], submitted_by, "sensitive_form_submit_rejected", {
            "request_ref": row.get("request_ref"),
            "missing_fields": missing,
            "raw_values_logged": False,
        })
        return {"error": "missing_required_fields", "missing": missing}
    stored = []
    for field, key, value in cleaned_values:
        value_ref = _new_ref("siv")
        await fetchval(
            """
            INSERT INTO sensitive_intake_values (
                value_ref, request_id, field_key, field_label, field_type,
                ciphertext, value_sha256, value_len, submitted_by
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (request_id, field_key) DO UPDATE SET
                value_ref = EXCLUDED.value_ref,
                field_label = EXCLUDED.field_label,
                field_type = EXCLUDED.field_type,
                ciphertext = EXCLUDED.ciphertext,
                value_sha256 = EXCLUDED.value_sha256,
                value_len = EXCLUDED.value_len,
                submitted_by = EXCLUDED.submitted_by,
                status = 'submitted',
                created_at = NOW()
            RETURNING id
            """,
            value_ref,
            row["id"],
            key,
            field.get("label") or key,
            normalize_field_type(field.get("type")),
            encrypt_value(value),
            hash_value(value),
            len(value),
            submitted_by,
        )
        stored.append({
            "field_key": key,
            "field_label": field.get("label") or key,
            "field_type": normalize_field_type(field.get("type")),
            "value_ref": value_ref,
            "value_len": len(value),
        })
    await execute(
        """
        UPDATE sensitive_intake_requests
        SET status = 'submitted', submitted_at = NOW(), updated_at = NOW()
        WHERE id = $1
        """,
        row["id"],
    )
    await _record_event(row["id"], submitted_by, "sensitive_form_submitted", {
        "request_ref": row.get("request_ref"),
        "field_count": len(stored),
        "field_types": sorted({item["field_type"] for item in stored}),
        "value_refs": [item["value_ref"] for item in stored],
        "raw_values_logged": False,
    })
    await _write_submission_context(row, stored, submitted_by)
    return {
        "request_ref": row.get("request_ref"),
        "status": "submitted",
        "fields_submitted": stored,
        "raw_values_returned": False,
    }


async def _write_submission_context(request_row, stored, submitted_by):
    summary_lines = [
        "Secure intake form submitted",
        f"- Request: {request_row.get('request_ref')}",
        f"- Submitted by: {submitted_by or 'secure-form'}",
        f"- Fields: {', '.join(item['field_label'] for item in stored) or 'none'}",
        "- Raw values are encrypted in the sensitive intake broker and are not present in this note.",
    ]
    session_id = request_row.get("session_id")
    ticket_id = request_row.get("ticket_id")
    if session_id:
        await execute(
            """
            INSERT INTO ops_chat_messages (session_id, role, body, metadata, ticket_id)
            VALUES ($1, 'system', $2, $3::jsonb, $4)
            """,
            session_id,
            "\n".join(summary_lines),
            json_dumps({
                "sensitive_intake_request_ref": request_row.get("request_ref"),
                "field_refs": [item["value_ref"] for item in stored],
                "raw_values_logged": False,
            }),
            ticket_id,
        )
    if ticket_id:
        await execute(
            """
            INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
            VALUES ($1, 'sensitive-intake', $2, $3, 'internal', $4)
            """,
            ticket_id,
            submitted_by or "secure-form",
            "\n".join(summary_lines),
            f"sensitive-intake:{request_row.get('request_ref')}",
        )


async def list_requests(ticket_id=None, session_id=None, limit=50):
    clauses = []
    args = []
    if ticket_id is not None:
        args.append(int(ticket_id))
        clauses.append(f"r.ticket_id = ${len(args)}")
    if session_id is not None:
        args.append(int(session_id))
        clauses.append(f"r.session_id = ${len(args)}")
    args.append(max(1, min(int(limit or 50), 200)))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = await fetchall(
        f"""
        SELECT r.id, r.request_ref, r.status, r.purpose, r.ticket_id, r.session_id,
               r.requested_by, r.requester_name, r.requester_email, r.channel,
               r.fields, r.metadata, r.expires_at, r.submitted_at, r.created_at,
               COUNT(v.id) AS submitted_field_count
        FROM sensitive_intake_requests r
        LEFT JOIN sensitive_intake_values v ON v.request_id = r.id
        {where}
        GROUP BY r.id
        ORDER BY r.created_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [_public_request(row) | {"submitted_field_count": row.get("submitted_field_count") or 0} for row in rows]


async def get_request_by_ref(request_ref):
    row = await fetchrow(
        """
        SELECT id, request_ref, status, purpose, ticket_id, session_id,
               requested_by, requester_name, requester_email, channel,
               fields, metadata, expires_at, submitted_at, created_at
        FROM sensitive_intake_requests
        WHERE request_ref = $1
        """,
        request_ref,
    )
    if not row:
        return None
    values = await fetchall(
        """
        SELECT value_ref, field_key, field_label, field_type, value_len, status, submitted_by, created_at
        FROM sensitive_intake_values
        WHERE request_id = $1
        ORDER BY id ASC
        """,
        row["id"],
    )
    events = await fetchall(
        """
        SELECT actor, action, details, created_at
        FROM sensitive_intake_events
        WHERE request_id = $1
        ORDER BY created_at ASC
        """,
        row["id"],
    )
    public = _public_request(row)
    public["values"] = [
        {
            "value_ref": item.get("value_ref"),
            "field_key": item.get("field_key"),
            "field_label": item.get("field_label"),
            "field_type": item.get("field_type"),
            "value_len": item.get("value_len"),
            "status": item.get("status"),
            "submitted_by": item.get("submitted_by"),
            "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
            "raw_value_returned": False,
        }
        for item in values
    ]
    public["events"] = [
        {
            "event_type": item.get("action"),
            "action": item.get("action"),
            "actor": item.get("actor"),
            "details": item.get("details") or {},
            "created_at": item.get("created_at").isoformat() if item.get("created_at") else None,
        }
        for item in events
    ]
    return public


def detect_sensitive_spans(text):
    value = str(text or "")
    if not value:
        return []
    spans = []
    scan = value[:MAX_TEXT_SCAN_CHARS]
    for field_type, pattern in SENSITIVE_PATTERNS:
        for match in pattern.finditer(scan):
            start, end = match.span()
            secret_value = match.group(match.lastindex or 0) if match.lastindex else match.group(0)
            if field_type in ("credential", "token", "dob") and match.lastindex and match.lastindex >= 2:
                value_start = match.start(match.lastindex)
                value_end = match.end(match.lastindex)
                secret_value = match.group(match.lastindex)
                start, end = value_start, value_end
            if field_type == "financial":
                digits = re.sub(r"\D", "", match.group(0))
                if len(digits) < 13:
                    continue
            spans.append({
                "start": start,
                "end": end,
                "field_type": normalize_field_type(field_type),
                "value": secret_value,
            })
    spans.sort(key=lambda item: (item["start"], -(item["end"] - item["start"])))
    deduped = []
    last_end = -1
    for item in spans:
        if item["start"] < last_end:
            continue
        deduped.append(item)
        last_end = item["end"]
    return deduped


async def sanitize_and_store_text(
    text,
    source="text",
    actor="system",
    ticket_id=None,
    session_id=None,
    purpose="automatic sensitive-text capture",
):
    value = str(text or "")
    spans = detect_sensitive_spans(value)
    if not spans:
        return {"text": value, "refs": [], "redacted": False}
    fields = []
    for idx, span in enumerate(spans, start=1):
        fields.append({
            "key": f"{span['field_type']}_{idx}",
            "label": f"Auto-captured {span['field_type'].replace('_', ' ')}",
            "type": span["field_type"],
            "required": False,
        })
    request = await create_request(
        fields,
        purpose=purpose,
        ticket_id=ticket_id,
        session_id=session_id,
        requested_by=actor or "system",
        channel=source,
        metadata={"capture_mode": "automatic_redaction", "raw_values_logged": False},
    )
    if request.get("error"):
        redacted = value
        for span in reversed(spans):
            redacted = redacted[:span["start"]] + f"<redacted:{span['field_type']}>" + redacted[span["end"]:]
        return {"text": redacted, "refs": [], "redacted": True, "error": request.get("error")}
    token = request["token"]
    submit_values = {}
    for idx, span in enumerate(spans, start=1):
        submit_values[f"{span['field_type']}_{idx}"] = span["value"]
    submitted = await submit_request(token, submit_values, submitted_by=actor or "system-redactor")
    field_refs = submitted.get("fields_submitted") or []
    replacements = []
    for span, ref in zip(spans, field_refs):
        replacements.append((span["start"], span["end"], f"<sensitive:{span['field_type']}:{ref['value_ref']}>"))
    redacted = value
    for start, end, replacement in reversed(replacements):
        redacted = redacted[:start] + replacement + redacted[end:]
    await _record_event(request["id"], actor, "sensitive_text_auto_redacted", {
        "source": source,
        "ticket_id": ticket_id,
        "session_id": session_id,
        "field_count": len(field_refs),
        "raw_values_logged": False,
    })
    return {
        "text": redacted,
        "refs": field_refs,
        "request_ref": request.get("request_ref"),
        "redacted": True,
    }


async def sanitize_json(value, source="json", actor="system", ticket_id=None, session_id=None):
    if isinstance(value, str):
        return (await sanitize_and_store_text(
            value,
            source=source,
            actor=actor,
            ticket_id=ticket_id,
            session_id=session_id,
        ))["text"]
    if isinstance(value, list):
        return [await sanitize_json(item, source=source, actor=actor, ticket_id=ticket_id, session_id=session_id) for item in value]
    if isinstance(value, dict):
        return {
            key: await sanitize_json(item, source=f"{source}.{key}", actor=actor, ticket_id=ticket_id, session_id=session_id)
            for key, item in value.items()
        }
    return value
