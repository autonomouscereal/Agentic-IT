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
        self.assertNotIn("Runtime:", self.agents_js)
        self.assertNotIn("Gated:", self.agents_js)
        self.assertIn("Total work time:", self.agents_js)

    def test_agent_status_groups_expose_queue_and_wait_gates(self):
        self.assertIn("const waitingStatuses = ['pending_approval', 'awaiting_access', 'awaiting_user_response', 'blocked'];", self.agents_js)
        self.assertIn("function isQueuedAgent(a)", self.agents_js)
        self.assertIn("Queued Agents", self.agents_js)
        self.assertIn("Waiting On Gate", self.agents_js)

    def test_agent_history_prioritizes_demo_evidence(self):
        self.assertIn("const AGENT_DEMO_TICKET_IDS", self.agents_js)
        self.assertIn("Recent Agent Evidence", self.agents_js)
        self.assertIn("function isArchivedAgentNoise(a)", self.agents_js)
        self.assertIn("Archived lab history:", self.agents_js)
        self.assertIn("Use Tickets -> Demo Proofs", self.agents_js)

    def test_ops_metrics_labels_postmortem_tasks_and_renders_status_chips(self):
        self.assertIn("function agentTaskMetricLabel(taskType)", self.dashboard_js)
        self.assertIn('postmortem: "Postmortem agent task"', self.dashboard_js)
        self.assertIn("agent-task-runtime-card", self.dashboard_js)
        self.assertIn("avg work time", self.dashboard_js)
        self.assertIn("task runs", self.dashboard_js)
        self.assertIn("95% under", self.dashboard_js)
        self.assertIn("postmortemSla.total_postmortems", self.dashboard_js)
        self.assertIn("function renderMetricStatusList(rows)", self.dashboard_js)
        self.assertIn("metric-status-chip", self.dashboard_js)

    def test_overview_agent_count_uses_open_lifecycle_total(self):
        index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Open Agents", index_html)
        self.assertRegex(index_html, r"/static/js/dashboard\.js\?v=[0-9a-z-]+")
        self.assertRegex(index_html, r"/static/js/agents\.js\?v=[0-9a-z-]+")
        self.assertIn("function computeAgentLifecycleCounts(agents)", self.dashboard_js)
        self.assertIn("function setAgentOpenCount(count)", self.dashboard_js)
        self.assertIn("function agentOpenCountFromStats(agents)", self.dashboard_js)
        self.assertIn('"pending_approval", "awaiting_access", "awaiting_user_response", "blocked"', self.dashboard_js)
        self.assertIn('apiGet("/api/agents")', self.dashboard_js)
        self.assertIn("computeAgentLifecycleCounts(agentData.agents).open", self.dashboard_js)
        self.assertIn("if (agentOpenCountState !== null) setAgentOpenCount(agentOpenCountState);", self.dashboard_js)
        self.assertIn("setAgentOpenCount(computeAgentLifecycleCounts(agents).open);", self.agents_js)
        self.assertIn('setText("stat-agent-active", agentOpenCountState);', self.dashboard_js)
        self.assertIn('setText("agent-count", agentOpenCountState);', self.dashboard_js)

    def test_setup_modules_use_explicit_scope_actions(self):
        index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn("Choose scope per module", index_html)
        self.assertIn("data-setup-action", self.dashboard_js)
        self.assertIn("Deploy reference", self.dashboard_js)
        self.assertIn("Integrate existing", self.dashboard_js)
        self.assertIn("Off / not in scope", self.dashboard_js)
        self.assertIn("Keep active", self.dashboard_js)
        self.assertIn("data-setup-notes", self.dashboard_js)
        self.assertIn("createModuleSetupTicket", self.dashboard_js)
        self.assertIn("/api/setup/module-ticket", self.dashboard_js)
        self.assertIn("/api/setup/status", self.dashboard_js)
        self.assertIn("Undeploy", self.dashboard_js)
        self.assertIn("Reinstall", self.dashboard_js)
        self.assertIn("module_actions: moduleActions", self.dashboard_js)
        self.assertIn("module_notes: moduleNotes", self.dashboard_js)
        self.assertIn("scoped module tickets", self.dashboard_js)


if __name__ == "__main__":
    unittest.main()
