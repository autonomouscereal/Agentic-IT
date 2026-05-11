// SOC Dashboard - Agent Management

const activeStatuses = ['spawned', 'running', 'working'];
const stalledStatuses = ['stalled'];
const finishedStatuses = ['finished', 'failed', 'stopped', 'terminated', 'resolved'];

async function loadAgents() {
    loadRunnerHealth();
    const data = await apiGet("/api/agents");
    if (!data) return;

    const grid = document.getElementById("agents-grid");
    if (!grid) return;

    const agents = data.agents || [];
    const active = agents.filter(a => activeStatuses.includes(a.status));
    const stalled = agents.filter(a => stalledStatuses.includes(a.status));
    const history = agents.filter(a => finishedStatuses.includes(a.status));

    let html = "";

    // Active agents section
    if (active.length > 0) {
        html += `<div class="agent-section-header">Active Agents (${active.length})</div>`;
        html += active.map(a => renderAgentCard(a, false)).join("");
    }

    // Stalled agents section
    if (stalled.length > 0) {
        html += `<div class="agent-section-header stalled">Stalled Agents (${stalled.length})</div>`;
        html += stalled.map(a => renderAgentCard(a, true)).join("");
    }

    // History section (collapsed by default)
    if (history.length > 0) {
        html += `<div class="agent-section-header history">Agent History (${history.length})</div>`;
        html += history.slice(0, 10).map(a => renderAgentCard(a, false)).join("");
        if (history.length > 10) {
            html += `<div style="grid-column:1/-1;text-align:center;color:var(--text-muted);font-size:12px;padding:8px">...and ${history.length - 10} more</div>`;
        }
    }

    if (agents.length === 0) {
        html = '<div class="agent-empty">No agents. Assign an agent to a ticket to get started.</div>';
    }

    grid.innerHTML = html;

    // Update badge
    setText("agent-count", active.length);
}

function renderAgentCard(a, isStalled) {
    const idle = a.heartbeat ? Math.floor((Date.now() - new Date(a.heartbeat).getTime()) / 1000) : "-";
    const running = a.started_at ? Math.floor((Date.now() - new Date(a.started_at).getTime()) / 1000) : "-";
    const stalledClass = isStalled ? " stalled" : "";

    let actionButtons = `<button class="btn btn-sm" onclick="viewAgentDetail(${a.id})">Detail</button>`;

    if (activeStatuses.includes(a.status)) {
        actionButtons += `<button class="btn btn-sm btn-danger" onclick="stopAgent(${a.id})">Stop</button>`;
    } else if (a.status === "stalled") {
        actionButtons += `
            <button class="btn btn-sm btn-warning" onclick="wakeAgent(${a.id})">Wake</button>
            <button class="btn btn-sm btn-warning" onclick="restartAgent(${a.id})">Restart</button>
            <button class="btn btn-sm btn-danger" onclick="stopAgent(${a.id})">Stop</button>
        `;
    } else {
        actionButtons += `<button class="btn btn-sm btn-warning" onclick="restartAgent(${a.id})">Restart</button>`;
    }

    return `
    <div class="agent-card${stalledClass}" id="agent-card-${a.id}">
        <div class="agent-card-header">
            <span class="agent-id">Agent #${a.id}</span>
            <span class="status-badge ${statusClass(a.status)}">${a.status}</span>
        </div>
        <div class="agent-ticket">${escHtml(a.ticket_title || "No ticket")}</div>
        <div class="agent-meta">
            <span>Model: ${a.model || "-"}</span>
            <span>Idle: ${idle}s</span>
            <span>Running: ${running}s</span>
        </div>
        ${renderTaskSummary(a)}
        <div class="agent-actions">
            ${actionButtons}
        </div>
    </div>
    `;
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
    document.getElementById("modal-body").innerHTML = `
        <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${data.status}</span></div>
        <div class="detail-row"><span class="detail-label">Model:</span><span>${data.model}</span></div>
        <div class="detail-row"><span class="detail-label">Ticket:</span><span>${escHtml(data.ticket_title || "-")} (${data.ticket_itop_ref || "-"})</span></div>
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
    const ok = data.claude_path && data.credentials_exists && modelApi.status === "ok";
    const base = data.effective_anthropic_base_url || data.settings_anthropic_base_url || "default Anthropic endpoint";
    const apiStatus = modelApi.status === "ok" ? "reachable" : `unreachable (${modelApi.error || "unknown"})`;
    const psStatus = processes?.ps_path
        ? `ps: ${processes.processes?.length || 0} visible / ${processes.active_processes?.length || 0} tracked`
        : `ps: ${processes?.error || data.ps_path || "missing"}`;
    el.innerHTML = `
        <span class="status-dot ${ok ? "connected" : ""}"></span>
        <span>Claude: ${escHtml(data.claude_path || "missing")} | Auth: ${data.credentials_exists ? "present" : "missing"} | API: ${escHtml(base)} | Model API: ${escHtml(apiStatus)} | ${escHtml(psStatus)}</span>
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
    const model = document.getElementById("agent-model-select")?.value || "qwen/qwen3.6-27b";
    const result = await apiPost("/api/agents/create-from-prompt", { prompt, model });
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
