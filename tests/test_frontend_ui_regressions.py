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
        self.assertIn("function compactChatContextForDisplay(value)", self.dashboard_js)
        self.assertIn("prior chat context retained in ticket metadata and audit trail", self.dashboard_js)
        self.assertIn("compactChatContextForDisplay(decodeHtmlEntities(raw))", self.dashboard_js)
        self.assertIn("compactChatContextForDisplay(String(value || \"\"))", self.dashboard_js)
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

    def test_global_search_is_available_from_dashboard_shell(self):
        index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        self.assertIn("global-search-input", index_html)
        self.assertIn("/api/search/global", self.dashboard_js)
        self.assertIn("function runGlobalSearch()", self.dashboard_js)
        self.assertIn("function openGlobalSearchResult(item)", self.dashboard_js)
        self.assertIn(".search-result-item", css)

    def test_learning_page_keeps_knowledge_and_skills_have_own_plane(self):
        index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        learning_page = index_html.split('id="page-learning"', 1)[1].split("<!-- Skills Page -->", 1)[0]
        skills_page = index_html.split('id="page-skills"', 1)[1].split("<!-- Tools Page -->", 1)[0]
        self.assertIn("knowledge-filter-text", learning_page)
        self.assertIn("knowledge-filter-category", learning_page)
        self.assertIn("knowledge-sort", learning_page)
        self.assertNotIn("learning-tab-skills", learning_page)
        self.assertNotIn("postmortems-tbody", learning_page)
        self.assertIn("skills-filter-text", skills_page)
        self.assertIn("skills-filter-status", skills_page)
        self.assertIn("settings-profile-skills", index_html)
        self.assertIn("function loadSkillsPage()", self.dashboard_js)
        self.assertIn("function renderProfileSkillChecklist(profile)", self.dashboard_js)
        self.assertIn("await loadKnowledge();", self.dashboard_js)
        self.assertIn(".skill-checklist", css)
        self.assertIn(".skill-summary-strip", css)

    def test_ops_chat_is_matrix_element_real_agent_handoff(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        ops_chat = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
        manifest = (ROOT / "platform" / "manifest.json").read_text(encoding="utf-8")
        self.assertIn("ops-chat-synapse", compose)
        self.assertIn("vectorim/element-web", compose)
        self.assertIn("ops-chat-bridge", compose)
        self.assertIn("MATRIX_OIDC_ISSUER", compose)
        self.assertIn("agent_runner.spawn_agent", ops_chat)
        self.assertIn("Matrix/Element", ops_chat)
        self.assertIn("real-agent-harness-handoff", manifest)

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

    def test_ticket_notes_are_rendered_for_demo_readability(self):
        css = (ROOT / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        agent_runner = (ROOT / "api" / "services" / "agent_runner.py").read_text(encoding="utf-8")
        self.assertIn("function renderNoteBody(value)", self.dashboard_js)
        self.assertIn("function renderNoteJson(value)", self.dashboard_js)
        self.assertIn("const text = normalizeNoteBody(value);", self.dashboard_js)
        self.assertIn("${renderNoteBody(n.body)}", self.dashboard_js)
        self.assertIn(".note-marker", css)
        self.assertIn(".note-json-summary", css)
        self.assertIn("## Ticket Note Style", agent_runner)
        self.assertIn("Do not paste raw API responses", agent_runner)

    def test_ticket_modal_renders_chronological_operator_sequence(self):
        css = (ROOT / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        ticket_service = (ROOT / "api" / "services" / "ticket_service.py").read_text(encoding="utf-8")
        agent_runner = (ROOT / "api" / "services" / "agent_runner.py").read_text(encoding="utf-8")
        self.assertIn("function buildTicketTimeline(", self.dashboard_js)
        self.assertIn("function renderTicketTimeline(events)", self.dashboard_js)
        self.assertIn("Sequence of Events", self.dashboard_js)
        self.assertIn("contextData?.model_turn_events", self.dashboard_js)
        self.assertIn("contextData?.steering_events", self.dashboard_js)
        self.assertIn("Model turn ${turnIndex} started", self.dashboard_js)
        self.assertIn(".ticket-sequence", css)
        self.assertIn(".sequence-model", css)
        self.assertIn('"model_turn_events": model_turn_events', ticket_service)
        self.assertIn('"ticket_id" not in event_details', agent_runner)

    def test_ticket_modal_activity_section_renders_before_async_context(self):
        css = (ROOT / "frontend" / "css" / "dashboard.css").read_text(encoding="utf-8")
        index_html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="ticket-activity-section"', self.dashboard_js)
        self.assertIn("ticket-activity-loading", self.dashboard_js)
        self.assertIn("modalBody.dataset.ticketId = String(data.id);", self.dashboard_js)
        self.assertIn('String(modalBody.dataset.ticketId || "") !== String(ticketId)', self.dashboard_js)
        self.assertIn("existingActivity.replaceWith(nextActivity);", self.dashboard_js)
        self.assertIn("function refreshModalScrollLayout", self.dashboard_js)
        self.assertIn("function loadTicketActivityWithRetry(ticketId)", self.dashboard_js)
        self.assertIn("loadTicketActivityWithRetry(id);", self.dashboard_js)
        self.assertIn("activity.innerText.includes(\"Loading evidence trail\")", self.dashboard_js)
        self.assertIn("modalBody.scrollTop = Math.min(maxTop, originalTop + 1);", self.dashboard_js)
        self.assertIn('window.dispatchEvent(new Event("resize"));', self.dashboard_js)
        self.assertIn("flex: 1 1 auto", css)
        self.assertIn("min-height: 0", css)
        self.assertIn("scrollbar-gutter: stable", css)
        self.assertIn("content-visibility: visible", css)
        self.assertIn(".ticket-activity-loading", css)
        self.assertIn("20260521-task-summary-cleanup", index_html)

    def test_ticket_task_output_uses_operator_safe_summary(self):
        self.assertIn("function taskDisplaySummary(task", self.dashboard_js)
        self.assertIn("function isRawHarnessNoise(value)", self.dashboard_js)
        self.assertIn("function extractHarnessResult(value)", self.dashboard_js)
        self.assertIn("function checkpointTaskSummary(task)", self.dashboard_js)
        self.assertIn("taskDisplaySummary(task, 340)", self.dashboard_js)
        self.assertIn("taskDisplaySummary(t, 260)", self.dashboard_js)
        self.assertIn("See ticket notes, checkpoints, and evidence trail", self.dashboard_js)
        self.assertNotIn("shortText(task.error_message || task.output", self.dashboard_js)
        self.assertNotIn("shortText(t.error_message || t.output", self.dashboard_js)
        self.assertIn("AGENT_MEMORY_SKILL_DIR", self.dashboard_js)
        self.assertIn("aggregated_output", self.dashboard_js)


if __name__ == "__main__":
    unittest.main()
