import unittest
import sys
import types

database = types.ModuleType("database")
database.fetchall = None
database.fetchrow = None
database.execute = None
database.fetchval = None
database.json_dumps = lambda value: value
sys.modules["database"] = database

event_logger = types.ModuleType("services.event_logger")
event_logger.log_event = None
sys.modules["services.event_logger"] = event_logger

ticket_links = types.ModuleType("services.ticket_links")
ticket_links.external_ticket_url = lambda ticket: ""
sys.modules["services.ticket_links"] = ticket_links

from api.services.ticket_service import compact_ticket_payload


class TicketPayloadTests(unittest.TestCase):
    def test_compacts_itop_provider_payload(self):
        ticket = {
            "id": 312,
            "provider_class": "Incident",
            "provider_payload": {
                "key": "199",
                "code": 0,
                "class": "Incident",
                "fields": {
                    "friendlyname": "I-000208",
                    "status": "new",
                    "team_name": "Security Team",
                    "description": "x" * 5000,
                },
            },
        }

        compact_ticket_payload(ticket)

        self.assertNotIn("provider_payload", ticket)
        self.assertEqual(ticket["provider_payload_summary"]["key"], "199")
        self.assertEqual(ticket["provider_payload_summary"]["friendlyname"], "I-000208")
        self.assertNotIn("description", ticket["provider_payload_summary"])


if __name__ == "__main__":
    unittest.main()
