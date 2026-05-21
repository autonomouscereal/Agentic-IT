from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_ops_chat_create_ticket_has_idempotency_scope():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def message_hash" in source
    assert '"message_hash": original_hash' in source
    assert '"message_preview": original[:220]' in source
    assert "idempotent_replay_existing_ticket" in source


def test_ops_chat_recovery_does_not_attach_harmless_chat_to_latest_ticket():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def _looks_like_operational_ticket_request" in source
    assert "if not _looks_like_operational_ticket_request(message):" in source


def test_ops_chat_tool_rejects_followup_create_ticket_when_room_has_tickets():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def looks_like_existing_ticket_followup" in source
    assert "existing_ticket_followup_requires_continue_ticket" in source
    assert "Use continue-ticket" in source
    assert "The create-ticket tool will reject obvious follow-up" in source


def test_ops_chat_recovery_does_not_claim_update_without_user_response_note():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def _recover_ticket_update_side_effect" in source
    assert "return None\n            return _format_recovered_ticket(row)" in source
    assert "return None\n    return _format_recovered_ticket(row)" in source
    function_body = source.split("def _looks_like_existing_ticket_update_text", 1)[1].split("\ndef _looks_like_operational_ticket_request", 1)[0]
    assert '"change",' not in function_body
    assert '"scope change"' in source
    assert '"instead",' not in function_body


def test_ops_chat_existing_ticket_update_has_bounded_no_tool_fallback():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def _apply_existing_ticket_update_fallback" in source
    assert "fallback_after_harness_no_tool" in source
    assert "len(rows) == 1" in source
    assert "_explicit_ticket_ids_from_text(message)" in source
    assert "chat_agent_existing_ticket_update_fallback" in source


def test_ops_chat_rejects_fake_incident_creation_claims():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert r"\bincident\s*#?\d+" in source
    assert r"\bcreated\s+(an?\s+)?incident\b" in source


def test_ops_chat_assignment_group_aliases_are_normalized():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def normalize_assignment_group" in source
    assert '"delivery gate": "DevSecOps"' in source
    assert "assignment_group = normalize_assignment_group(args.assignment_group)" in source


def test_ops_chat_enterprise_domain_guardrails_cover_matrix_misses():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert '"offboard", "off-boarding", "revoke access"' in source
    assert '"restore a deleted", "restore deleted", "restore file"' in source
    assert '"policy exception", "risk acceptance", "sla report"' in source
    assert '"semgrep", "trivy", "zap", "nuclei"' in source
    assert "Generate an SLA report for executive review -> create a Compliance & Audit ticket." in source


def test_ops_chat_answer_cannot_overwrite_ticket_tool_result():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert "def read_existing_result" in source
    assert "structured_result_already_recorded" in source
    assert "def _last_structured_tool_action" in source
    assert "recovered_overwritten_result" in source


def test_ops_chat_normalizes_placeholder_affected_user_to_requester():
    source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
    assert '"user (user-direct)"' in source
    assert 'affected_user_name = requester_name or "Chat User"' in source


def test_ticket_route_suppresses_duplicate_ops_chat_create():
    source = (ROOT / "api" / "routes" / "tickets.py").read_text(encoding="utf-8")
    assert "def _find_ops_chat_idempotent_ticket" in source
    assert "access_scope->>'message_hash'" in source
    assert "ops_chat_duplicate_create_suppressed" in source
    assert 'existing["_idempotent_replay"] = True' in source
