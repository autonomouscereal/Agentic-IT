import json
import re


_FAMILY_PATTERNS = (
    ("phishing", ("phish", "credential harvest", "suspicious email", "report phish", "email security")),
    ("edr-sysmon", ("sysmon", "edr", "wazuh alert", "endpoint detection", "windows event")),
    ("cicd-security", ("ci/cd", "cicd", "semgrep", "trivy", "owasp zap", "nuclei", "security gate")),
    ("access-request", ("access request", "permission", "grant access", "account access", "iam")),
    ("service-intake", ("intake", "service desk", "user request", "raci")),
    ("setup-integration", ("setup", "integration", "installer", "deploy")),
    ("false-positive-tuning", ("false positive", "suppression", "training url", "tuning")),
)

_STOPWORDS = {
    "ticket", "incident", "request", "task", "workflow", "postmortem", "smoke",
    "codex", "test", "demo", "simulation", "alert", "reported", "report",
}


def slug(value, fallback="workflow", limit=80):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text or fallback)[:limit].strip("-") or fallback


def normalize_workflow_key(value, fallback="global:general"):
    text = str(value or "").lower().strip()
    if ":" in text:
        left, right = text.split(":", 1)
        return f"{slug(left, 'global', 60)}:{slug(right, 'general', 90)}"[:160]
    return slug(text, fallback.replace(":", "-"), 160)


def load_policy(value):
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def workflow_family(*values):
    text = " ".join(str(value or "") for value in values).lower()
    for family, needles in _FAMILY_PATTERNS:
        if any(needle in text for needle in needles):
            return family
    terms = []
    for term in re.findall(r"[a-z0-9][a-z0-9_.-]{2,}", text):
        term = term.strip("._-")
        if term and term not in _STOPWORDS and term not in terms:
            terms.append(term)
        if len(terms) >= 4:
            break
    return slug("-".join(terms), "general")


def workflow_key_for_fields(
    ticket_class=None,
    trigger_type=None,
    name=None,
    description=None,
    blueprint=None,
    approval_policy=None,
    explicit_key=None,
):
    if explicit_key:
        return normalize_workflow_key(explicit_key)
    policy = load_policy(approval_policy)
    if policy.get("workflow_key"):
        return normalize_workflow_key(policy["workflow_key"])
    class_key = slug(ticket_class or "global", "global", 60)
    family = workflow_family(trigger_type, name, description, blueprint)
    return f"{class_key}:{family}"[:160]


def workflow_key_for_ticket(ticket, *extra_values):
    ticket = ticket or {}
    ticket_class = ticket.get("provider_class") or ticket.get("itop_class") or ticket.get("ticket_class")
    return workflow_key_for_fields(
        ticket_class=ticket_class,
        trigger_type=ticket.get("provider") or "",
        name=ticket.get("title"),
        description=ticket.get("description"),
        blueprint=" ".join(str(value or "") for value in extra_values),
    )


def canonical_workflow_name(workflow_key):
    bits = str(workflow_key or "global:workflow").split(":", 1)
    class_label = bits[0].replace("-", " ").title()
    family_label = (bits[1] if len(bits) > 1 else bits[0]).replace("-", " ")
    return f"{class_label} {family_label} response workflow"[:240]


def canonical_knowledge_ref(workflow_key):
    return f"workflow:{workflow_key}:knowledge"[:200]


def policy_with_key(policy, workflow_key):
    result = load_policy(policy)
    result["workflow_key"] = workflow_key
    return result
