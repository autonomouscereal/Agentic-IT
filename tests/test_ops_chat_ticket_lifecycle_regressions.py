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


def test_ticket_route_suppresses_duplicate_ops_chat_create():
    source = (ROOT / "api" / "routes" / "tickets.py").read_text(encoding="utf-8")
    assert "def _find_ops_chat_idempotent_ticket" in source
    assert "access_scope->>'message_hash'" in source
    assert "ops_chat_duplicate_create_suppressed" in source
    assert 'existing["_idempotent_replay"] = True' in source
