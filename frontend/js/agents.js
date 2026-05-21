// Agentic Operations - Agent Management

const activeStatuses = ['spawned', 'running', 'working'];
const waitingStatuses = ['pending_approval', 'awaiting_access', 'awaiting_user_response', 'blocked'];
const stalledStatuses = ['stalled'];
const finishedStatuses = ['finished', 'failed', 'stopped', 'terminated', 'resolved'];
const AGENT_DEMO_TICKET_IDS = [1393, 695, 690, 531, 83, 82, 580, 578, 525, 539, 422, 558, 575, 530, 118, 363, 430];
const AGENT_DEMO_TICKET_SET = new Set(AGENT_DEMO_TICKET_IDS);

async function loadAgents() {
    loadRunnerHealth();
    loadAgentAuditor();
    const data = await apiGet("/api/agents");
    if (!data) return;

    const grid = document.getElementById("agents-grid");
    if (!grid) return;

    const agents = data.agents || [];
    const queued = agents.filter(a => isQueuedAgent(a));
    const active = agents.filter(a => activeStatuses.includes(a.status) && !isQueuedAgent(a));
    const waiting = agents.filter(a => waitingStatuses.includes(a.status));
    const stalled = agents.filter(a => stalledStatuses.includes(a.status));
    const history = agents.filter(a => finishedStatuses.includes(a.status));
    const archivedHistory = history.filter(a => isArchivedAgentNoise(a));
    const demoHistory = history.filter(a => AGENT_DEMO_TICKET_SET.has(Number(a.ticket_id)));
    const evidenceHistory = demoHistory.length
        ? demoHistory.sort((a, b) => AGENT_DEMO_TICKET_IDS.indexOf(Number(a.ticket_id)) - AGENT_DEMO_TICKET_IDS.indexOf(Number(b.ticket_id)))
        : history.filter(a => !isArchivedAgentNoise(a));

    let html = "";

    // Queued agents section
    if (queued.length > 0) {
        html += `<div class="agent-section-header queued">Queued Agents (${queued.length})</div>`;
        html += queued.map(a => renderAgentCard(a, false)).join("");
    }

    // Active agents section
    if (active.length > 0) {
        html += `<div class="agent-section-header">Active Agents (${active.length})</div>`;
        html += active.map(a => renderAgentCard(a, false)).join("");
    }

    // Waiting agents section
    if (waiting.length > 0) {
        html += `<div class="agent-section-header waiting">Waiting On Gate (${waiting.length})</div>`;
        html += waiting.map(a => renderAgentCard(a, false)).join("");
    }

    // Stalled agents section
    if (stalled.length > 0) {
        html += `<div class="agent-section-header stalled">Stalled Agents (${stalled.length})</div>`;
        html += stalled.map(a => renderAgentCard(a, true)).join("");
    }

    if (evidenceHistory.length > 0) {
        html += `<div class="agent-section-header history">Recent Agent Evidence (${evidenceHistory.length})</div>`;
        html += evidenceHistory.slice(0, 10).map(a => renderAgentCard(a, false)).join("");
        if (evidenceHistory.length > 10) {
            html += `<div class="agent-archive-note">...and ${evidenceHistory.length - 10} more evidence records. Use Tickets -> Demo Proofs for the curated walkthrough.</div>`;
        }
    }

    if (archivedHistory.length > 0) {
        html += `<div class="agent-archive-note">Archived lab history: ${archivedHistory.length} closed synthetic agents are retained in audit but hidden from the primary demo view.</div>`;
    }

    if (agents.length === 0) {
        html = '<div class="agent-empty">No agents. Assign an agent to a ticket to get started.</div>';
    }

    grid.innerHTML = html;

    // Update shared badge/card state using the same lifecycle contract as Overview.
    if (typeof setAgentOpenCount === "function" && typeof computeAgentLifecycleCounts === "function") {
        setAgentOpenCount(computeAgentLifecycleCounts(agents).open);
    } else {
        setText("agent-count", active.length + queued.length + waiting.length);
    }
}

async function loadAgentAuditor() {
    const el = document.getElementById("agent-auditor-health");
    if (!el) return;
    const data = await apiGet("/api/agents/audits?limit=5");
    if (!data) return;
    const audits = data.audits || [];
    const latest = audits[0];
    const warningCount = audits.filter(a => a.severity === "warning" || a.severity === "error").length;
    el.innerHTML = `
        <span class="status-dot ${warningCount ? "" : "connected"}"></span>
        <span>Auditor: ${audits.length} recent reviews${latest ? ` / latest ${escHtml(latest.finding)} on agent ${latest.agent_id || "-"}` : ""}</span>
        <button class="btn btn-sm" onclick="runAgentAuditOnce()">Run Audit</button>
    `;
}

async function runAgentAuditOnce() {
    const result = await apiPost("/api/agents/audits/run", {});
    if (result?.error) alert(result.error);
    await loadAgentAuditor();
    await loadAgents();
}

function renderAgentCard(a, isStalled) {
    const workSeconds = a.status === "stalled" ? 0 : a.task_working_seconds;
    const workTime = Number.isFinite(Number(workSeconds)) ? formatDuration(workSeconds) : "-";
    const stalledClass = isStalled ? " stalled" : "";
    const displayStatus = agentDisplayStatus(a);

    let actionButtons = `<button class="btn btn-sm" onclick="viewAgentDetail(${a.id})">Detail</button>`;

    if (activeStatuses.includes(a.status)) {
        actionButtons += `<button class="btn btn-sm btn-danger" onclick="stopAgent(${a.id})">Stop</button>`;
    } else if (a.status === "stalled") {
        actionButtons += `
            <button class="btn btn-sm btn-warning" onclick="wakeAgent(${a.id})">Wake</button>
            <button class="btn btn-sm btn-warning" onclick="restartAgent(${a.id})">Restart</button>
            <button class="btn btn-sm btn-danger" onclick="stopAgent(${a.id})">Stop</button>
        `;
    } else if (!isTerminalTicket(a)) {
        actionButtons += `<button class="btn btn-sm btn-warning" onclick="restartAgent(${a.id})">Restart</button>`;
    }

    return `
    <div class="agent-card${stalledClass}" id="agent-card-${a.id}">
        <div class="agent-card-header">
            <span class="agent-id">Agent #${a.id}</span>
            <span class="status-badge ${statusClass(displayStatus)}">${escHtml(displayStatus)}</span>
        </div>
        <div class="agent-ticket">${renderAgentTicketLink(a)}</div>
        <div class="agent-meta">
            <span>Harness: ${escHtml(a.harness || "-")}</span>
            <span>Model: ${a.model || "-"}</span>
            <span>Ticket: ${a.ticket_status || "-"}</span>
            <span>Total work time: ${workTime}</span>
        </div>
        ${renderTaskSummary(a)}
        <div class="agent-actions">
            ${actionButtons}
        </div>
    </div>
    `;
}

function isTerminalTicket(a) {
    return ["resolved", "closed", "implemented", "cancelled"].includes(a?.ticket_status);
}

function isArchivedAgentNoise(a) {
    const title = String(a?.ticket_title || "").toLowerCase();
    const error = String(a?.task_error_message || a?.error_message || "").toLowerCase();
    return isTerminalTicket(a)
        && ["failed", "stopped", "terminated"].includes(a?.status)
        && (error.includes("archived stale synthetic/demo artifact")
            || title.includes("smoke test")
            || title.includes("runner smoke")
            || title.includes("deploy agentic it/soc platform profile"));
}

function isQueuedAgent(a) {
    return a?.task_status === "queued" && (a.status === "spawned" || a.status === "running");
}

function agentDisplayStatus(a) {
    if (isQueuedAgent(a)) return "queued";
    return a?.status || "unknown";
}

function renderAgentTicketLink(a) {
    if (!a.ticket_id) return escHtml(a.ticket_title || "No ticket");
    const ticketId = Number(a.ticket_id);
    const title = escHtml(a.ticket_title || "Untitled ticket");
    const ref = a.ticket_itop_ref ? ` <span class="agent-ticket-ref">${escHtml(a.ticket_itop_ref)}</span>` : "";
    return `<button class="inline-link" onclick="viewTicket(${ticketId})">Ticket #${ticketId}</button><span>${ref} ${title}</span>`;
}

function renderTaskSummary(a) {
    if (!a.current_task_id && !a.task_status) return "";
    const progress = Number(a.task_progress_pct || 0);
    return `
        <div class="task-summary">
            <div class="task-summary-row">
                <span>Task #${a.current_task_id || "-"}</span>
                <span class="status-badge ${statusClass(a.task_status || "queued")}">${a.task_status || "queued"}</span>
            </div>
            <div class="task-progress"><div style="width:${Math.max(0, Math.min(100, progress))}%"></div></div>
            ${a.task_error_message ? `<div class="task-error">${escHtml(a.task_error_message)}</div>` : ""}
        </div>
    `;
}

async function viewAgentDetail(id) {
    const data = await apiGet(`/api/agents/${id}`);
    if (!data) return;
    const latestLogs = await apiGet(`/api/agents/${id}/logs?lines=160`);

    document.getElementById("modal-title").textContent = `Agent #${data.id}`;
    const task = data.current_task || null;
    const checkpoints = normalizeCheckpoints(task?.checkpoints);
    const ticketLink = data.ticket_id
        ? `<button class="inline-link" onclick="viewTicket(${Number(data.ticket_id)})">#${Number(data.ticket_id)}</button> ${escHtml(data.ticket_title || "-")} (${escHtml(data.ticket_itop_ref || "-")})`
        : `${escHtml(data.ticket_title || "-")} (${escHtml(data.ticket_itop_ref || "-")})`;
    document.getElementById("modal-body").innerHTML = `
        <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${data.status}</span></div>
        <div class="detail-row"><span class="detail-label">Model:</span><span>${data.model}</span></div>
        <div class="detail-row"><span class="detail-label">Ticket:</span><span>${ticketLink}</span></div>
        <div class="detail-row"><span class="detail-label">Started:</span><span>${formatDate(data.started_at)}</span></div>
        <div class="detail-row"><span class="detail-label">Heartbeat:</span><span>${formatTime(data.heartbeat)}</span></div>
        ${data.error_message ? `<div class="detail-row"><span class="detail-label">Error:</span><span style="color:var(--accent-danger)">${escHtml(data.error_message)}</span></div>` : ""}
        ${task ? `
            <div class="modal-section">
                <div class="section-title">Current Task</div>
                <div class="detail-row"><span class="detail-label">Task:</span><span>#${task.id} ${escHtml(task.task_type || "")}</span></div>
                <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(task.status)}">${task.status}</span></div>
                <div class="detail-row"><span class="detail-label">Progress:</span><span>${task.progress_pct || 0}%</span></div>
                <div class="detail-row"><span class="detail-label">Work dir:</span><span>${escHtml(task.work_dir || "-")}</span></div>
                ${task.error_message ? `<div class="detail-row"><span class="detail-label">Task Error:</span><span class="task-error">${escHtml(task.error_message)}</span></div>` : ""}
                ${task.output ? `<pre class="task-output">${escHtml(task.output)}</pre>` : ""}
                ${latestLogs && !latestLogs.error ? `
                    <div class="section-title">Output Log</div>
                    <pre class="task-output">${escHtml(latestLogs.content || "No log output yet")}</pre>
                ` : ""}
            </div>
            <div class="modal-section">
                <div class="section-title">Checkpoints</div>
                ${checkpoints.length === 0 ? '<div style="color:var(--text-muted);font-size:12px">No checkpoints recorded</div>' : ""}
                ${checkpoints.map(c => `
                    <div class="checkpoint-item">
                        <span class="status-badge ${statusClass(c.status || "running")}">${escHtml(c.status || "running")}</span>
                        <strong>${escHtml(c.step || "step")}</strong>
                        <span>${escHtml(c.output || "")}</span>
                    </div>
                `).join("")}
            </div>
        ` : ""}
        ${data.change_requests && data.change_requests.length > 0 ? `
            <div style="margin-top:16px"><strong>Change Requests:</strong>
            ${data.change_requests.map(c => `<div style="margin-top:4px;font-size:12px">${c.action} on ${c.target} - <span class="status-badge ${statusClass(c.status)}">${c.status}</span></div>`).join("")}
            </div>
        ` : ""}
        ${data.audit && data.audit.length > 0 ? `
            <div style="margin-top:16px"><strong>Activity Log:</strong>
            ${data.audit.slice(0, 10).map(a => `<div style="margin-top:4px;font-size:12px;color:var(--text-muted)">${formatTime(a.created_at)} - ${a.action}</div>`).join("")}
            </div>
        ` : ""}
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function loadRunnerHealth() {
    const el = document.getElementById("runner-health");
    if (!el) return;
    const [data, processes] = await Promise.all([
        apiGet("/api/agents/runner-health"),
        apiGet("/api/agents/processes"),
    ]);
    if (!data) return;
    const modelApi = data.model_api || {};
    const harness = data.harness || "claude-code";
    const harnessPath = harness === "hermes" ? data.hermes_path : data.claude_path;
    const authPresent = harness === "hermes" ? data.hermes_nous_auth_exists : data.credentials_exists;
    const ok = harnessPath && authPresent && modelApi.status === "ok";
    const base = data.effective_anthropic_base_url || data.settings_anthropic_base_url || "default Anthropic endpoint";
    const apiStatus = modelApi.status === "ok" ? "reachable" : `unreachable (${modelApi.error || "unknown"})`;
    const psStatus = processes?.ps_path
        ? `ps: ${processes.processes?.length || 0} visible / ${processes.active_processes?.length || 0} tracked`
        : `ps: ${processes?.error || data.ps_path || "missing"}`;
    el.innerHTML = `
        <span class="status-dot ${ok ? "connected" : ""}"></span>
        <span>Harness: ${escHtml(harness)} | Binary: ${escHtml(harnessPath || "missing")} | Auth: ${authPresent ? "present" : "missing"} | API: ${escHtml(base)} | Model API: ${escHtml(apiStatus)} | ${escHtml(psStatus)}</span>
    `;
}

function normalizeCheckpoints(raw) {
    if (!raw) return [];
    if (Array.isArray(raw)) return raw;
    if (typeof raw === "string") {
        try {
            const parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch {
            return [];
        }
    }
    return [];
}

async function createAgentFromPrompt() {
    const input = document.getElementById("agent-prompt-input");
    const prompt = input?.value.trim();
    if (!prompt) return;
    const model = typeof selectedAgentModel === "function"
        ? selectedAgentModel()
        : "gpt-5.5";
    const harness = typeof selectedAgentHarness === "function"
        ? selectedAgentHarness()
        : "codex";
    const result = await apiPost("/api/agents/create-from-prompt", { prompt, model, harness });
    if (result && !result.error) {
        input.value = "";
        loadAgents();
    } else if (result?.error) {
        alert(result.error);
    }
}

async function stopAgent(id) {
    if (!confirm(`Stop Agent #${id}?`)) return;
    const result = await apiPost(`/api/agents/${id}/stop`, { reason: "stopped_via_dashboard" });
    if (result) {
        loadAgents();
    }
}

async function wakeAgent(id) {
    const result = await apiPost(`/api/agents/${id}/wake`, {});
    if (result) {
        loadAgents();
    }
}

async function restartAgent(id) {
    if (!confirm(`Restart Agent #${id}? This will terminate the current agent and spawn a new one.`)) return;
    const result = await apiPost(`/api/agents/${id}/restart`, {});
    if (result) {
        loadAgents();
    }
}

// Auto-refresh agents every 10 seconds
setInterval(() => {
    const activePage = document.querySelector(".page.active");
    if (activePage && activePage.id === "page-agents") {
        loadAgents();
    }
}, 10000);
