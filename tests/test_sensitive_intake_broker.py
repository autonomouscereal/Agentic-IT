import asyncio
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "api" / "services" / "sensitive_intake.py"
sys.path.insert(0, str(ROOT / "api"))


def load_module():
    spec = importlib.util.spec_from_file_location("sensitive_intake_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_detects_common_sensitive_values():
    module = load_module()
    text = "Bob SSN 123-45-6789 password: SuperSecret123 token: sk-or-v1-abc123456789abc123"
    spans = module.detect_sensitive_spans(text)
    assert {item["field_type"] for item in spans} >= {"ssn", "credential", "token"}


def test_detects_recovery_codes_and_government_ids():
    module = load_module()
    text = "MFA recovery code: AB12-CD34-EF56 passport number: X1234567 dob: 01/02/1990"
    spans = module.detect_sensitive_spans(text)
    detected = {item["field_type"] for item in spans}
    assert detected >= {"recovery_code", "government_id", "dob"}
    assert any(item["value"] == "AB12-CD34-EF56" for item in spans)
    assert any(item["value"] == "X1234567" for item in spans)


def test_metadata_redaction_handles_nested_attachment_like_json():
    module = load_module()
    raw = {
        "filename": "alice_ssn_123-45-6789_password_SecretValue123.txt",
        "storage_ref": "ops-chat-upload://session-1/passport number: X1234567.pdf",
        "labels": ["token: sk-or-v1-abc123456789abc123"],
    }
    safe = module.redact_json_for_metadata(raw)
    combined = str(safe)
    assert "123-45-6789" not in combined
    assert "SecretValue123" not in combined
    assert "X1234567" not in combined
    assert "sk-or-v1-abc123456789abc123" not in combined
    assert "<redacted:ssn>" in combined
    assert "<redacted:credential>" in combined
    assert "<redacted:government_id>" in combined
    assert "<redacted:token>" in combined


def test_secure_request_submit_returns_references_not_values(monkeypatch):
    module = load_module()
    state = {"requests": {}, "values": [], "events": [], "next_id": 1}

    async def fake_fetchval(query, *args):
        if "INSERT INTO sensitive_intake_requests" in query:
            request_id = state["next_id"]
            state["next_id"] += 1
            state["requests"][request_id] = {
                "id": request_id,
                "request_ref": args[0],
                "form_token_hash": args[1],
                "status": "pending",
                "purpose": args[2],
                "ticket_id": args[3],
                "session_id": args[4],
                "requested_by": args[5],
                "requester_name": args[6],
                "requester_email": args[7],
                "channel": args[8],
                "fields": args[9],
                "metadata": args[10],
                "expires_at": args[11],
            }
            return request_id
        if "INSERT INTO sensitive_intake_values" in query:
            state["values"].append(args)
            return len(state["values"])
        return None

    async def fake_fetchrow(query, *args):
        if "WHERE form_token_hash" in query:
            token_hash = args[0]
            for row in state["requests"].values():
                if row["form_token_hash"] == token_hash:
                    return dict(row)
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO sensitive_intake_events" in query:
            state["events"].append(args)
        if "UPDATE sensitive_intake_requests" in query:
            state["requests"][args[-1]]["status"] = "submitted"
        return "OK"

    monkeypatch.setattr(module, "fetchval", fake_fetchval)
    monkeypatch.setattr(module, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(module, "execute", fake_execute)

    created = asyncio.run(module.create_request(
        [{"key": "ssn", "type": "ssn", "label": "SSN", "required": True}],
        purpose="unit secure intake",
        session_id=44,
        requested_by="unit-test",
    ))
    submitted = asyncio.run(module.submit_request(
        created["token"],
        {"ssn": "123-45-6789"},
        submitted_by="demo-user",
    ))

    assert submitted["status"] == "submitted"
    assert submitted["raw_values_returned"] is False
    assert "123-45-6789" not in str(submitted)
    assert state["values"]
    assert "123-45-6789" not in str(state["events"])


def test_missing_required_submission_does_not_store_partial_values(monkeypatch):
    module = load_module()
    state = {"requests": {}, "values": [], "events": [], "next_id": 1}

    async def fake_fetchval(query, *args):
        if "INSERT INTO sensitive_intake_requests" in query:
            request_id = state["next_id"]
            state["next_id"] += 1
            state["requests"][request_id] = {
                "id": request_id,
                "request_ref": args[0],
                "form_token_hash": args[1],
                "status": "pending",
                "purpose": args[2],
                "ticket_id": args[3],
                "session_id": args[4],
                "requested_by": args[5],
                "requester_name": args[6],
                "requester_email": args[7],
                "channel": args[8],
                "fields": args[9],
                "metadata": args[10],
                "expires_at": args[11],
            }
            return request_id
        if "INSERT INTO sensitive_intake_values" in query:
            state["values"].append(args)
            return len(state["values"])
        return None

    async def fake_fetchrow(query, *args):
        if "WHERE form_token_hash" in query:
            for row in state["requests"].values():
                if row["form_token_hash"] == args[0]:
                    return dict(row)
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO sensitive_intake_events" in query:
            state["events"].append(args)
        return "OK"

    monkeypatch.setattr(module, "fetchval", fake_fetchval)
    monkeypatch.setattr(module, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(module, "execute", fake_execute)

    created = asyncio.run(module.create_request(
        [
            {"key": "legal_name", "type": "freeform_sensitive", "label": "Full legal name", "required": True},
            {"key": "ssn", "type": "ssn", "label": "SSN", "required": True},
        ],
        purpose="unit missing required",
        requested_by="unit-test",
    ))
    submitted = asyncio.run(module.submit_request(
        created["token"],
        {"legal_name": "Alice Example"},
        submitted_by="demo-user",
    ))

    assert submitted["error"] == "missing_required_fields"
    assert submitted["missing"] == ["ssn"]
    assert state["values"] == []


def test_submitted_form_cannot_be_submitted_again(monkeypatch):
    module = load_module()
    state = {"requests": {}, "values": [], "events": [], "next_id": 1}

    async def fake_fetchval(query, *args):
        if "INSERT INTO sensitive_intake_requests" in query:
            request_id = state["next_id"]
            state["next_id"] += 1
            state["requests"][request_id] = {
                "id": request_id,
                "request_ref": args[0],
                "form_token_hash": args[1],
                "status": "pending",
                "purpose": args[2],
                "ticket_id": args[3],
                "session_id": args[4],
                "requested_by": args[5],
                "requester_name": args[6],
                "requester_email": args[7],
                "channel": args[8],
                "fields": args[9],
                "metadata": args[10],
                "expires_at": args[11],
            }
            return request_id
        if "INSERT INTO sensitive_intake_values" in query:
            state["values"].append(args)
            return len(state["values"])
        return None

    async def fake_fetchrow(query, *args):
        if "WHERE form_token_hash" in query:
            for row in state["requests"].values():
                if row["form_token_hash"] == args[0]:
                    return dict(row)
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO sensitive_intake_events" in query:
            state["events"].append(args)
        if "UPDATE sensitive_intake_requests" in query:
            state["requests"][args[-1]]["status"] = "submitted"
        return "OK"

    monkeypatch.setattr(module, "fetchval", fake_fetchval)
    monkeypatch.setattr(module, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(module, "execute", fake_execute)

    created = asyncio.run(module.create_request(
        [{"key": "ssn", "type": "ssn", "label": "SSN", "required": True}],
        purpose="unit one submit",
        requested_by="unit-test",
    ))
    first = asyncio.run(module.submit_request(created["token"], {"ssn": "123-45-6789"}, submitted_by="demo-user"))
    second = asyncio.run(module.submit_request(created["token"], {"ssn": "987-65-4321"}, submitted_by="demo-user"))

    assert first["status"] == "submitted"
    assert second["error"] == "form_not_accepting_submissions"
    assert second["status"] == "submitted"
    assert len(state["values"]) == 1


def test_form_request_metadata_is_redacted_without_storing_plaintext(monkeypatch):
    module = load_module()
    state = {"request": None, "events": []}

    async def fake_fetchval(query, *args):
        if "INSERT INTO sensitive_intake_requests" in query:
            state["request"] = args
            return 7
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO sensitive_intake_events" in query:
            state["events"].append(args)
        return "OK"

    monkeypatch.setattr(module, "fetchval", fake_fetchval)
    monkeypatch.setattr(module, "execute", fake_execute)

    created = asyncio.run(module.create_request(
        [{"key": "notes", "type": "freeform_sensitive", "label": "Password: SecretValue123", "required": True}],
        purpose="collect SSN 123-45-6789",
        requested_by="unit-test",
        metadata={"bad": "token: sk-or-v1-abc123456789abc123"},
    ))

    assert "123-45-6789" not in str(created)
    assert "SecretValue123" not in str(created)
    assert "sk-or-v1-abc123456789abc123" not in str(state["request"])
    assert "<redacted:ssn>" in created["purpose"]
    assert "<redacted:credential>" in str(created["fields"])


def test_auto_sanitize_replaces_pasted_secret_with_reference(monkeypatch):
    module = load_module()
    captured = {"requests": {}, "values": [], "events": [], "next_id": 1}

    async def fake_fetchval(query, *args):
        if "INSERT INTO sensitive_intake_requests" in query:
            request_id = captured["next_id"]
            captured["next_id"] += 1
            captured["requests"][request_id] = {
                "id": request_id,
                "request_ref": args[0],
                "form_token_hash": args[1],
                "status": "pending",
                "purpose": args[2],
                "ticket_id": args[3],
                "session_id": args[4],
                "requested_by": args[5],
                "requester_name": args[6],
                "requester_email": args[7],
                "channel": args[8],
                "fields": args[9],
                "metadata": args[10],
                "expires_at": args[11],
            }
            return request_id
        if "INSERT INTO sensitive_intake_values" in query:
            captured["values"].append(args)
            return len(captured["values"])
        return None

    async def fake_fetchrow(query, *args):
        if "WHERE form_token_hash" in query:
            for row in captured["requests"].values():
                if row["form_token_hash"] == args[0]:
                    return dict(row)
        return None

    async def fake_execute(query, *args):
        if "INSERT INTO sensitive_intake_events" in query:
            captured["events"].append(args)
        return "OK"

    monkeypatch.setattr(module, "fetchval", fake_fetchval)
    monkeypatch.setattr(module, "fetchrow", fake_fetchrow)
    monkeypatch.setattr(module, "execute", fake_execute)

    result = asyncio.run(module.sanitize_and_store_text(
        "Please set Bob's SSN to 123-45-6789 and password: SuperSecret123",
        source="unit",
        actor="demo-user",
        session_id=99,
    ))

    assert result["redacted"] is True
    assert "123-45-6789" not in result["text"]
    assert "SuperSecret123" not in result["text"]
    assert "<sensitive:ssn:" in result["text"]
    assert "<sensitive:credential:" in result["text"]
