"""Env-driven ticket provider adapters for external ITSM products.

These adapters are intentionally thin. They keep ServiceNow, Jira, and generic
webhook ticket creation behind the canonical dashboard contract without making
the frontend or agents product-specific. Secrets come only from environment
variables or the deployment's vault injection layer.
"""
import base64
import os
import aiohttp


def _truthy(value):
    return str(value or "").lower() in ("1", "true", "yes", "on")


def _headers(token=None, user=None, password=None, extra=None):
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user and password:
        raw = f"{user}:{password}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    headers.update(extra or {})
    return headers


def _contact_payload(fields):
    return {
        "opened_by_name": fields.get("opened_by_name"),
        "opened_by_email": fields.get("opened_by_email"),
        "requester_name": fields.get("requester_name"),
        "requester_email": fields.get("requester_email"),
        "affected_user_name": fields.get("affected_user_name"),
        "affected_user_email": fields.get("affected_user_email"),
    }


class EnvHttpTicketProvider:
    """Base class for simple outbound ticket create adapters."""

    name = "generic-webhook"
    ticket_classes = ["Incident", "UserRequest", "Change"]

    def __init__(self, name=None):
        if name:
            self.name = name

    @property
    def configured(self):
        return False

    async def connect(self):
        return self.configured

    async def is_connected(self):
        return self.configured

    async def sync_ticket(self, ticket_class, ticket_key):
        return {
            "error": f"{self.name} inbound sync is not configured in this deployment.",
            "provider": self.name,
            "ticket_class": ticket_class,
            "ticket_ref": ticket_key,
        }

    async def full_sync(self):
        return {
            "synced": 0,
            "errors": 0,
            "new": 0,
            "provider": self.name,
            "status": "not_supported",
            "message": "Use provider-native updated-since polling in a site-specific adapter.",
        }

    async def create_ticket(self, ticket_id, fields):
        raise NotImplementedError

    async def update_ticket(self, ticket_id, fields):
        return {"status": "not_supported", "provider": self.name, "ticket_id": ticket_id}

    async def close_ticket(self, ticket_id, notes):
        return {"status": "not_supported", "provider": self.name, "ticket_id": ticket_id}


class ServiceNowProvider(EnvHttpTicketProvider):
    name = "servicenow"
    ticket_classes = ["incident", "sc_request", "change_request"]

    @property
    def base_url(self):
        return (os.getenv("SERVICENOW_INSTANCE_URL") or "").rstrip("/")

    @property
    def configured(self):
        has_auth = bool(os.getenv("SERVICENOW_TOKEN")) or bool(os.getenv("SERVICENOW_USER") and os.getenv("SERVICENOW_PASSWORD"))
        return bool(self.base_url and has_auth)

    def _table(self, fields):
        ticket_class = (fields.get("provider_class") or fields.get("ticket_class") or "incident").lower()
        mapping = {
            "incident": "incident",
            "userrequest": os.getenv("SERVICENOW_REQUEST_TABLE", "sc_request"),
            "user_request": os.getenv("SERVICENOW_REQUEST_TABLE", "sc_request"),
            "request": os.getenv("SERVICENOW_REQUEST_TABLE", "sc_request"),
            "change": "change_request",
            "normalchange": "change_request",
            "routinechange": "change_request",
            "emergencychange": "change_request",
        }
        return mapping.get(ticket_class, ticket_class)

    async def create_ticket(self, ticket_id, fields):
        if not self.configured:
            return {"error": "ServiceNow provider is not configured.", "provider": self.name, "ticket_id": ticket_id}
        table = self._table(fields)
        payload = {
            "short_description": fields.get("title") or f"Agentic Operations ticket {ticket_id}",
            "description": fields.get("description") or "",
        }
        if fields.get("priority"):
            payload["priority"] = fields["priority"]
        assignment_group = os.getenv("SERVICENOW_ASSIGNMENT_GROUP")
        if assignment_group:
            payload["assignment_group"] = assignment_group

        url = f"{self.base_url}/api/now/table/{table}"
        headers = _headers(
            token=os.getenv("SERVICENOW_TOKEN"),
            user=os.getenv("SERVICENOW_USER"),
            password=os.getenv("SERVICENOW_PASSWORD"),
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    return {"error": f"ServiceNow create failed with HTTP {resp.status}", "provider": self.name, "raw": data}
        result = data.get("result", data)
        ref = str(result.get("number") or result.get("sys_id") or ticket_id)
        sys_id = result.get("sys_id")
        provider_url = f"{self.base_url}/nav_to.do?uri={table}.do?sys_id={sys_id}" if sys_id else None
        return {
            "status": "created",
            "provider": self.name,
            "ticket_id": ticket_id,
            "provider_ref": ref,
            "provider_class": table,
            "provider_url": provider_url,
            "raw": data,
        }


class JiraProvider(EnvHttpTicketProvider):
    name = "jira"
    ticket_classes = ["Bug", "Task", "Story", "Incident", "Service Request", "Change"]

    @property
    def base_url(self):
        return (os.getenv("JIRA_BASE_URL") or "").rstrip("/")

    @property
    def configured(self):
        return bool(self.base_url and os.getenv("JIRA_PROJECT_KEY") and os.getenv("JIRA_EMAIL") and os.getenv("JIRA_API_TOKEN"))

    async def create_ticket(self, ticket_id, fields):
        if not self.configured:
            return {"error": "Jira provider is not configured.", "provider": self.name, "ticket_id": ticket_id}
        issue_type = fields.get("provider_class") or os.getenv("JIRA_ISSUE_TYPE", "Task")
        payload = {
            "fields": {
                "project": {"key": os.getenv("JIRA_PROJECT_KEY")},
                "summary": fields.get("title") or f"Agentic Operations ticket {ticket_id}",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": fields.get("description") or ""}],
                    }],
                },
                "issuetype": {"name": issue_type},
            }
        }
        contact = _contact_payload(fields)
        labels = payload["fields"].setdefault("labels", [])
        if contact.get("affected_user_name") or contact.get("affected_user_email"):
            labels.append("affected-user-recorded")
        url = f"{self.base_url}/rest/api/3/issue"
        headers = _headers(user=os.getenv("JIRA_EMAIL"), password=os.getenv("JIRA_API_TOKEN"))
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    return {"error": f"Jira create failed with HTTP {resp.status}", "provider": self.name, "raw": data}
        ref = str(data.get("key") or data.get("id") or ticket_id)
        return {
            "status": "created",
            "provider": self.name,
            "ticket_id": ticket_id,
            "provider_ref": ref,
            "provider_class": issue_type,
            "provider_url": f"{self.base_url}/browse/{ref}" if ref else None,
            "raw": data,
        }


class GenericWebhookProvider(EnvHttpTicketProvider):
    name = "generic-webhook"
    ticket_classes = ["Incident", "UserRequest", "Change"]

    @property
    def url(self):
        return os.getenv("GENERIC_TICKETING_WEBHOOK_URL", "")

    @property
    def configured(self):
        return bool(self.url)

    async def create_ticket(self, ticket_id, fields):
        if not self.configured:
            return {"error": "Generic ticketing webhook is not configured.", "provider": self.name, "ticket_id": ticket_id}
        payload = {
            "ticket_id": ticket_id,
            "title": fields.get("title"),
            "description": fields.get("description"),
            "ticket_class": fields.get("provider_class") or fields.get("ticket_class"),
            "priority": fields.get("priority"),
            "created_by": fields.get("created_by"),
            "contacts": _contact_payload(fields),
            "dry_run": _truthy(os.getenv("GENERIC_TICKETING_DRY_RUN", "false")),
        }
        extra_headers = {}
        token = os.getenv("GENERIC_TICKETING_WEBHOOK_TOKEN")
        if token:
            extra_headers["X-Webhook-Token"] = token
        async with aiohttp.ClientSession() as session:
            async with session.post(self.url, json=payload, headers=_headers(extra=extra_headers), timeout=30) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    return {"error": f"Generic webhook create failed with HTTP {resp.status}", "provider": self.name, "raw": data}
        ref = str(data.get("provider_ref") or data.get("id") or data.get("key") or ticket_id)
        return {
            "status": "created",
            "provider": self.name,
            "ticket_id": ticket_id,
            "provider_ref": ref,
            "provider_class": payload["ticket_class"],
            "provider_url": data.get("provider_url"),
            "raw": data,
        }
