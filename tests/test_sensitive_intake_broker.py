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
