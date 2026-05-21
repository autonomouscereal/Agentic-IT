from api.services.task_prompts import (
    STATIC_DEPLOYMENT_BOUNDARY_RULE,
    build_ticket_resolution_prompt,
)


def test_ticket_prompt_distinguishes_preview_from_real_deployment():
    prompt = build_ticket_resolution_prompt({"id": 1409, "title": "Deploy webpage called hello"})
    assert STATIC_DEPLOYMENT_BOUNDARY_RULE in prompt
    assert "safe local artifact preview, not a real deployment" in prompt
    assert "/api/agents/<agent_id>/deploy/static-site" in prompt
    assert "127.0.0.1" in prompt
    assert "container-local behavior" in prompt
