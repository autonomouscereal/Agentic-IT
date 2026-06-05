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
    "passport": "government_id",
    "passport_number": "government_id",
    "drivers_license": "government_id",
    "driver_license": "government_id",
    "recovery_code": "recovery_code",
    "mfa_recovery_code": "recovery_code",
    "credit_card": "financial",
    "bank_account": "financial",
}

SENSITIVE_PATTERNS = [
    ("ssn", re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("credential", re.compile(
        r"(?i)(?<![A-Za-z0-9])(password|passwd|passcode|temporary password|temp password|initial password)\b\s*[:=]\s*([^\s,;]{6,})"
    )),
    ("credential", re.compile(
        r"(?i)(?<![A-Za-z0-9])(password|passwd|passcode|temporary password|temp password|initial password)[ _-]+([^\s,;._]{6,})"
    )),
    ("token", re.compile(
        r"(?i)\b(api[_ -]?key|token|secret|bearer)\b\s*[:=]\s*([A-Za-z0-9._~+/=$:-]{12,})"
    )),
    ("token", re.compile(r"\b(sk-[A-Za-z0-9_-]{16,}|sk-or-v1-[A-Za-z0-9]+|ghp_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,})\b")),
    ("token", re.compile(r"\b(AKIA[0-9A-Z]{16})\b")),
    ("recovery_code", re.compile(
        r"(?i)\b(recovery code|mfa recovery code|backup code)\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9-]{5,})"
    )),
    ("government_id", re.compile(
        r"(?i)\b(passport|passport number|driver'?s license|driver license|government id|national id)\b\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9-]{5,})"
    )),
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


def _passes_luhn(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    double = False
    for char in reversed(digits):
        n = ord(char) - 48
        if n < 0 or n > 9:
            return False
        if double:
            n *= 2
            if n > 9:
                n -= 9
        total += n
        double = not double
    return total % 10 == 0


def redact_text_for_metadata(text):
    return _redact_text_only(text)


def redact_json_for_metadata(value):
    return _redact_json_only(value)


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


def _field_key_from_label(label, index=1):
    key = str(label or f"field_{index}").strip().lower()
    key = re.sub(r"[^a-z0-9_]+", "_", key).strip("_")
    return (key or f"field_{index}")[:120]


def _field_type_from_label(label):
    value = str(label or "").strip().lower()
    if "ssn" in value or "social security" in value:
        return "ssn"
    if "date of birth" in value or value == "dob" or "birth date" in value:
        return "dob"
    if "password" in value or "credential" in value or "passcode" in value:
        return "credential"
    if "api key" in value or "token" in value or "secret" in value:
        return "token"
    if "recovery code" in value or "backup code" in value:
        return "recovery_code"
    if "passport" in value or "driver" in value or "government id" in value or "national id" in value:
        return "government_id"
    if "email" in value or "mailbox" in value:
        return "email"
    if "start date" in value or "end date" in value or "hire date" in value:
        return "date"
    if "username" in value or "user name" in value or "login" in value:
        return "username"
    return "freeform_sensitive"


def _split_requested_field_labels(text):
    value = str(text or "")
    if ":" in value:
        value = value.split(":", 1)[1]
    value = re.sub(r"(?i)\bplease\b|\bconfirm\b|\bprovide\b|\binclude\b|\bneeded\b", " ", value)
    value = re.sub(r"(?i)\bdo not paste.*$", " ", value)
    value = re.sub(r"(?i)\bthen\b.*$", " ", value)
    value = re.sub(r"(?i)\bmarker\b.*$", " ", value)
    parts = re.split(r",|;|\n|\band\b", value)
    labels = []
    for part in parts:
        label = re.sub(r"(?i)\b(required|optional|if known|when known)\b", " ", part)
        label = re.sub(r"\s+", " ", label).strip(" .:-")
        if not label:
            continue
        if len(label.split()) > 8:
            continue
        labels.append(label[:160])
    return labels[:12]


def infer_request_info_fields(question, context="", ticket=None):
    """Infer dynamic secure-intake fields from a requester-info ask.

    This is a platform safety fallback. Agents still decide what they need, but
    if they ask for account/onboarding/credential/person-sensitive details
    through a normal requester-info note, the platform converts the ask into a
    brokered secure form instead of sending a plain Matrix/ticket question.
    """
    ticket = ticket or {}
    combined = " ".join([
        str(ticket.get("title") or ""),
        str(ticket.get("description") or ""),
        str(question or ""),
        str(context or ""),
    ])
    lower = combined.lower()
    protected_terms = (
        "ssn", "social security", "date of birth", "dob", "birth date",
        "password", "passcode", "credential", "api key", "token", "secret",
        "recovery code", "backup code", "government id", "passport",
        "driver license", "driver's license", "national id", "bank account",
        "credit card",
    )
    account_terms = (
        "create account", "new account", "setup account", "set up account",
        "account setup", "account details", "new user", "user onboarding",
        "onboarding", "hire", "identity", "access request",
    )
    if not any(term in lower for term in protected_terms + account_terms):
        return []

    labels = _split_requested_field_labels(question)
    fields = []
    if labels and any(term in lower for term in account_terms):
        for index, label in enumerate(labels, start=1):
            fields.append({
                "key": _field_key_from_label(label, index),
                "label": label,
                "type": _field_type_from_label(label),
                "required": True,
            })

    explicit_labels = [
        ("Full legal name", "freeform_sensitive", ("legal name", "full name")),
        ("Date of birth", "dob", ("date of birth", "dob", "birth date")),
        ("SSN", "ssn", ("ssn", "social security")),
        ("Initial password or credential", "credential", ("password", "passcode", "credential")),
        ("API key or token", "token", ("api key", "token", "secret")),
        ("Recovery code", "recovery_code", ("recovery code", "backup code")),
        ("Government ID", "government_id", ("government id", "passport", "driver license", "driver's license", "national id")),
        ("Financial information", "financial", ("bank account", "credit card")),
    ]
    for label, field_type, terms in explicit_labels:
        if any(term in lower for term in terms):
            if field_type in {"ssn", "dob", "credential", "token", "recovery_code", "government_id", "financial"} and any(
                item.get("type") == field_type for item in fields
            ):
                continue
            fields.append({
                "key": _field_key_from_label(label, len(fields) + 1),
                "label": label,
                "type": field_type,
                "required": True,
            })

    if not fields and any(term in lower for term in account_terms):
        default_labels = [
            ("Target system(s)", "freeform_sensitive"),
            ("Desired username", "username"),
            ("Work email address", "email"),
            ("Display name or full legal name", "freeform_sensitive"),
            ("Required roles or access level", "freeform_sensitive"),
            ("Manager or sponsor", "freeform_sensitive"),
            ("Start date", "date"),
            ("Additional account notes", "freeform_sensitive"),
        ]
        fields = [
            {
                "key": _field_key_from_label(label, index),
                "label": label,
                "type": field_type,
                "required": index <= 6,
            }
            for index, (label, field_type) in enumerate(default_labels, start=1)
        ]

    deduped = []
    seen = set()
    for field in fields:
        key = field.get("key") or _field_key_from_label(field.get("label"), len(deduped) + 1)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(field)
    return normalize_fields(deduped)


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
    resume = await _resume_ticket_after_submission(row, stored, submitted_by)
    return {
        "request_ref": row.get("request_ref"),
        "status": "submitted",
        "ticket_id": row.get("ticket_id"),
        "session_id": row.get("session_id"),
        "fields_submitted": stored,
        "resume": resume,
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


async def _resume_ticket_after_submission(request_row, stored, submitted_by):
    ticket_id = request_row.get("ticket_id")
    if not ticket_id:
        return {"status": "not_applicable", "reason": "no_ticket_id"}
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"status": "skipped", "reason": "ticket_not_found"}
    if ticket.get("status") != "awaiting_user_response":
        return {"status": "skipped", "reason": "ticket_not_waiting", "ticket_status": ticket.get("status")}

    payload = _json_value(ticket.get("provider_payload"), {})
    previous_status = ((payload or {}).get("awaiting_user_response") or {}).get("previous_status") or "in_progress"
    await execute("""
        UPDATE tickets
        SET status = $1,
            provider_payload = COALESCE(provider_payload, '{}'::jsonb) - 'awaiting_user_response',
            updated_at = NOW()
        WHERE id = $2
    """, previous_status, ticket_id)

    await execute(
        """
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
        VALUES ($1, 'user-response', $2, $3, 'internal', $4)
        """,
        ticket_id,
        submitted_by or "secure-form",
        "\n".join([
            "Secure intake response received",
            f"Responder: {submitted_by or 'secure-form'}",
            f"Request: {request_row.get('request_ref')}",
            f"Fields submitted: {', '.join(item['field_label'] for item in stored) or 'none'}",
            "Raw values remain encrypted in the sensitive intake broker and are not present in this note.",
        ]),
        f"user_response:{ticket_id}:sensitive-intake:{request_row.get('request_ref')}",
    )

    resume = {"status": "not_requested"}
    if ticket.get("agent_id"):
        active_task = await fetchrow("""
            SELECT id FROM agent_tasks
            WHERE agent_id = $1 AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
        """, ticket["agent_id"])
        if active_task:
            resume = {"status": "already_active", "task_id": active_task["id"]}
        else:
            from services import access_control, agent_runner
            from services.task_prompts import build_ticket_resolution_prompt

            agent = await fetchrow("SELECT model, selected_model FROM agents WHERE id = $1", ticket["agent_id"])
            resume_prompt = "\n".join([
                build_ticket_resolution_prompt(ticket),
                "",
                (
                    "Secure intake form submitted. Re-read "
                    f"/api/tickets/{ticket_id}/context, use the latest "
                    "sensitive-intake and user-response notes, resolve only "
                    "through broker references or approved provider adapters, "
                    "and continue the ticket."
                ),
            ])
            resume = await agent_runner.spawn_agent(
                ticket_id,
                (agent or {}).get("selected_model") or (agent or {}).get("model") or os.getenv("AGENT_DEFAULT_MODEL") or "gpt-5.5",
                resume_prompt,
                "ticket_resolution",
                actor_context=await access_control.load_agent_subject(ticket["agent_id"]),
            )

    await _record_event(request_row["id"], submitted_by, "ticket_resumed_after_secure_intake", {
        "request_ref": request_row.get("request_ref"),
        "ticket_id": ticket_id,
        "previous_status": previous_status,
        "resume": resume,
        "raw_values_logged": False,
    })
    return resume


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


async def get_submitted_values_for_adapter(request_ref):
    """Return decrypted values for trusted server-side provider adapters only.

    This is intentionally not exposed as a public/raw-value API. Adapters should
    consume the values in-process and return only refs, status, and evidence.
    """
    row = await fetchrow(
        """
        SELECT id, request_ref, status, purpose, ticket_id, session_id,
               requested_by, requester_name, requester_email, channel,
               fields, metadata, submitted_at, created_at
        FROM sensitive_intake_requests
        WHERE request_ref = $1
        """,
        request_ref,
    )
    if not row:
        return {"error": "request_not_found", "request_ref": request_ref}
    if row.get("status") != "submitted":
        return {
            "error": "request_not_submitted",
            "request_ref": row.get("request_ref"),
            "status": row.get("status"),
        }
    value_rows = await fetchall(
        """
        SELECT value_ref, field_key, field_label, field_type, encrypted_value,
               value_len, status, submitted_by, created_at
        FROM sensitive_intake_values
        WHERE request_id = $1
        ORDER BY id ASC
        """,
        row["id"],
    )
    values = []
    for item in value_rows or []:
        values.append({
            "value_ref": item.get("value_ref"),
            "field_key": item.get("field_key"),
            "field_label": item.get("field_label"),
            "field_type": item.get("field_type"),
            "value": decrypt_value(item.get("encrypted_value")),
            "value_len": item.get("value_len"),
            "status": item.get("status"),
            "submitted_by": item.get("submitted_by"),
        })
    return {
        "request_ref": row.get("request_ref"),
        "status": row.get("status"),
        "purpose": row.get("purpose"),
        "ticket_id": row.get("ticket_id"),
        "session_id": row.get("session_id"),
        "values": values,
        "raw_values_for_adapter_only": True,
    }


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
            if field_type in ("credential", "token", "dob", "recovery_code", "government_id") and match.lastindex and match.lastindex >= 2:
                value_start = match.start(match.lastindex)
                value_end = match.end(match.lastindex)
                secret_value = match.group(match.lastindex)
                start, end = value_start, value_end
            if field_type == "financial":
                digits = re.sub(r"\D", "", match.group(0))
                if not _passes_luhn(digits):
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
