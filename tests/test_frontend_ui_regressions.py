import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FrontendUiRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dashboard_js = (ROOT / "frontend" / "js" / "dashboard.js").read_text(encoding="utf-8")
        cls.agents_js = (ROOT / "frontend" / "js" / "agents.js").read_text(encoding="utf-8")

    def test_audit_deep_link_filters_are_consumed_once(self):
        self.assertIn("function clearAuditUrlParams()", self.dashboard_js)
        self.assertIn("clearAuditUrlParams();", self.dashboard_js)
        self.assertNotIn('history.replaceState(null, "", url);', self.dashboard_js)

    def test_ticket_description_markup_is_cleaned_before_rendering(self):
        self.assertIn("function cleanTicketDescription(value)", self.dashboard_js)
        self.assertIn("const description = cleanTicketDescription(data.description);", self.dashboard_js)
        self.assertIn("${escHtml(description)}", self.dashboard_js)
        self.assertNotIn("${escHtml(data.description)}", self.dashboard_js)

    def test_agent_cards_link_to_tickets_without_idle_timer(self):
        self.assertIn("function renderAgentTicketLink(a)", self.agents_js)
        self.assertIn("onclick=\"viewTicket(${ticketId})\"", self.agents_js)
        self.assertIn("const ticketLink = data.ticket_id", self.agents_js)
        self.assertNotIn("Idle:", self.agents_js)


if __name__ == "__main__":
    unittest.main()
