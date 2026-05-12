// SOC Dashboard - Main JavaScript
const API = "";

// Navigation
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTicketSorting();
    loadAgentModels();
    applyAuditUrlFilters();
    loadDashboardStats();
    startAutoRefresh();
});

function initNavigation() {
    document.querySelectorAll(".nav-item").forEach(item => {
        item.addEventListener("click", () => {
            const page = item.dataset.page;
            navigateTo(page);
        });
    });
}

function navigateTo(page) {
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));

    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navItem) navItem.classList.add("active");

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add("active");

    // Load data for the page
    switch (page) {
        case "overview": loadDashboardStats(); break;
        case "tickets": loadTickets(); break;
        case "intake": loadIntake(); break;
        case "agents": loadAgents(); break;
        case "changes": loadChanges(); break;
        case "workflows": loadWorkflows(); break;
        case "cicd": loadCicd(); break;
        case "learning": loadLearning(); break;
        case "tools": loadTools(); break;
        case "setup": loadSetup(); break;
        case "access": loadAccess(); break;
        case "audit": loadAudit(); break;
    }
}

function applyAuditUrlFilters() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("audit_q");
    const source = params.get("audit_source");
    const level = params.get("audit_level");
    if (q && document.getElementById("audit-filter-text")) document.getElementById("audit-filter-text").value = q;
    if (source && document.getElementById("audit-filter-source")) document.getElementById("audit-filter-source").value = source;
    if (level && document.getElementById("audit-filter-level")) document.getElementById("audit-filter-level").value = level;
}

function openAuditTrail(query, source = "") {
    navigateTo("audit");
    const text = document.getElementById("audit-filter-text");
    const sourceEl = document.getElementById("audit-filter-source");
    const levelEl = document.getElementById("audit-filter-level");
    if (text) text.value = query || "";
    if (sourceEl) sourceEl.value = source || "";
    if (levelEl) levelEl.value = "";
    const url = new URL(window.location.href);
    url.searchParams.set("audit_q", query || "");
    if (source) url.searchParams.set("audit_source", source);
    else url.searchParams.delete("audit_source");
    history.replaceState(null, "", url);
    loadAudit();
}

let ticketSort = { by: "updated_at", dir: "desc" };

function initTicketSorting() {
    document.querySelectorAll("[data-ticket-sort]").forEach(th => {
        th.addEventListener("click", () => {
            const by = th.dataset.ticketSort;
            if (ticketSort.by === by) {
                ticketSort.dir = ticketSort.dir === "asc" ? "desc" : "asc";
            } else {
                ticketSort.by = by;
                ticketSort.dir = "asc";
            }
            updateTicketSortIndicators();
            loadTickets();
        });
    });
    updateTicketSortIndicators();
}

function updateTicketSortIndicators() {
    document.querySelectorAll("[data-ticket-sort]").forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.ticketSort === ticketSort.by) {
            th.classList.add(ticketSort.dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });
}

// Auto-refresh every 30 seconds
function startAutoRefresh() {
    setInterval(() => {
        const activePage = document.querySelector(".page.active");
        if (activePage) {
            const pageId = activePage.id.replace("page-", "");
            switch (pageId) {
                case "overview": loadDashboardStats(); break;
                case "tickets": loadTickets(); break;
                case "intake": loadIntake(); break;
                case "agents": loadAgents(); break;
                case "changes": loadChanges(); break;
                case "workflows": loadWorkflows(); break;
                case "cicd": loadCicd(); break;
            }
        }
    }, 30000);
}

async function apiGet(path) {
    try {
        const res = await fetch(`${API}${path}`);
        return await res.json();
    } catch (e) {
        console.error(`API error ${path}:`, e);
        return null;
    }
}

async function apiPost(path, body) {
    try {
        const res = await fetch(`${API}${path}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
        });
        return await res.json();
    } catch (e) {
        console.error(`API POST ${path}:`, e);
        return null;
    }
}

async function apiPut(path, body) {
    try {
        const res = await fetch(`${API}${path}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: body ? JSON.stringify(body) : undefined,
        });
        return await res.json();
    } catch (e) {
        console.error(`API PUT ${path}:`, e);
        return null;
    }
}

async function apiDelete(path) {
    try {
        const res = await fetch(`${API}${path}`, { method: "DELETE" });
        return await res.json();
    } catch (e) {
        console.error(`API DELETE ${path}:`, e);
        return null;
    }
}

function formatTime(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDate(iso) {
    if (!iso) return "-";
    const d = new Date(iso);
    return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function statusClass(status) {
    if (!status) return "";
    return "status-" + status.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z-]/g, "");
}

function isAutoApproval(actor) {
    const value = String(actor || "").toLowerCase();
    return value.includes("auto") || value.includes("demo") || value.includes("smoke");
}

function approvalModeBadge(change) {
    if (change.status === "pending") {
        return `<span class="status-badge status-pending">Gate pending</span>`;
    }
    if (change.status === "approved" || change.status === "completed") {
        return isAutoApproval(change.approved_by)
            ? `<span class="status-badge status-approved">Auto-approved demo gate</span>`
            : `<span class="status-badge status-approved">Manually approved gate</span>`;
    }
    if (change.status === "rejected") {
        return `<span class="status-badge status-rejected">Gate rejected</span>`;
    }
    return `<span class="status-badge ${statusClass(change.status)}">Gate ${escHtml(change.status || "unknown")}</span>`;
}

function renderGateSummary(change) {
    const requested = formatTime(change.requested_at);
    const approved = change.approved_at ? formatTime(change.approved_at) : "-";
    const approver = change.approved_by || "-";
    return `
        <div class="gate-card">
            <div class="gate-card-header">
                <strong>Approval Gate #${change.id}</strong>
                ${approvalModeBadge(change)}
            </div>
            <div class="gate-card-body">
                <div>${escHtml(change.action || "Change")} on <code>${escHtml(change.target || "-")}</code></div>
                <div class="gate-meta">Risk ${escHtml(change.risk_level || "unknown")} &middot; requested ${requested} &middot; approved ${approved} by ${escHtml(approver)}</div>
                ${change.reason ? `<div class="gate-reason">${escHtml(change.reason)}</div>` : ""}
                ${change.result ? `<div class="gate-result">${escHtml(String(change.result).slice(0, 260))}</div>` : ""}
                <button class="inline-link" onclick="openAuditTrail('change_${change.id}')">full gate audit</button>
                ${change.agent_id ? `<button class="inline-link" onclick="openAuditTrail('agent_${change.agent_id}')">agent trail</button>` : ""}
            </div>
        </div>
    `;
}

// Load dashboard stats
async function loadDashboardStats() {
    const data = await apiGet("/api/dashboard/stats");
    if (!data) return;

    // Update stat cards
    setText("stat-ticket-total", data.tickets?.total || 0);
    setText("stat-ticket-new", (data.tickets?.new || 0) + (data.tickets?.assigned || 0));
    setText("stat-agent-active", data.agents?.active || 0);
    setText("stat-change-pending", data.changes?.pending || 0);

    // Update charts
    updateTicketTrendChart(data.tickets?.trend || []);
    updateAgentDistChart(data.agents?.distribution || []);

    // Update activity feed
    const feed = document.getElementById("activity-feed");
    if (feed && data.recent_activity) {
        feed.innerHTML = data.recent_activity.slice(0, 15).map(a => `
            <div class="activity-item">
                <span class="activity-time">${formatTime(a.created_at)}</span>
                <span class="activity-dot"></span>
                <span class="activity-text">
                    <strong>${escHtml(a.actor || "system")}</strong>
                    ${escHtml(a.summary || `${a.action || ""} ${a.target || ""}`)}
                    ${a.ticket_id ? `<button class="inline-link" onclick="openAuditTrail('ticket_${escAttr(a.ticket_id)}')">trail</button>` : ""}
                </span>
            </div>
        `).join("");
    }

    // Update badge counts
    setText("agent-count", data.agents?.active || 0);
    setText("change-count", data.changes?.pending || 0);

    // Load pending changes section
    loadPendingChanges();
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// Load pending changes for overview page
async function loadPendingChanges() {
    const data = await apiGet("/api/changes/pending");
    if (!data) return;

    const section = document.getElementById("pending-changes-section");
    const list = document.getElementById("pending-changes-list");
    if (!section || !list) return;

    if (data.changes.length === 0) {
        section.style.display = "none";
        return;
    }

    section.style.display = "";
    list.innerHTML = data.changes.map(c => {
        const waiting = c.waiting_seconds ? Math.floor(c.waiting_seconds) : "-";
        return `
        <div class="pending-change-card">
            <div class="pending-change-info">
                <div class="pending-change-action">${escHtml(c.action)} on ${escHtml(c.target)}</div>
                <div class="pending-change-meta">
                    Ticket: ${escHtml(c.ticket_title || "-")} &middot; Waiting: ${waiting}s
                </div>
            </div>
            <div class="pending-change-actions">
                <button class="btn btn-sm btn-success" onclick="approveChange(${c.id})">Approve</button>
                <button class="btn btn-sm btn-danger" onclick="rejectChange(${c.id})">Reject</button>
            </div>
        </div>
        `;
    }).join("");
}

// Load tickets
async function loadTickets() {
    const status = document.getElementById("ticket-filter-status")?.value || "";
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    params.set("sort_by", ticketSort.by);
    params.set("sort_dir", ticketSort.dir);
    params.set("limit", "200");

    const data = await apiGet(`/api/tickets?${params}`);
    if (!data) return;

    const tbody = document.getElementById("tickets-tbody");
    if (!tbody) return;

    if (data.tickets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="loading">No tickets found</td></tr>';
        return;
    }

    tbody.innerHTML = data.tickets.map(t => {
        const isSynced = !!t.synced_at;
        const sourceBadge = isSynced
            ? `<span class="source-badge itop" title="Synced from iTop">iTop</span>`
            : `<span class="source-badge local" title="Local">Local</span>`;
        return `
        <tr data-itop-ref="${t.itop_ref}">
            <td>${t.id}</td>
            <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(t.title)}">
                ${sourceBadge}
                ${t.external_url ? `<a class="ticket-link" href="${escAttr(t.external_url)}" target="_blank" rel="noopener">${escHtml(t.title)}</a>` : escHtml(t.title)}
            </td>
            <td><span class="class-badge">${escHtml(t.itop_class || "Incident")}</span></td>
            <td><span class="status-badge ${statusClass(t.status)}">${t.status}</span></td>
            <td>${t.priority || "-"}</td>
            <td>${escHtml(t.assignee || "-")}</td>
            <td>${t.agent_status ? `<span class="status-badge ${statusClass(t.agent_status)}">${t.agent_status}</span>` : "-"}</td>
            <td>${formatTime(t.updated_at)}</td>
            <td>
                <button class="btn btn-sm" onclick="viewTicket(${t.id})">Detail</button>
                ${!t.agent_status ? `<button class="btn btn-sm btn-success" onclick="assignAgent(${t.id})">Assign Agent</button>` : ""}
            </td>
        </tr>
        `;
    }).join("");
}

async function loadWorkflows() {
    const status = document.getElementById("workflow-filter-status")?.value || "";
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    const data = await apiGet(`/api/workflows?${params}`);
    if (!data) return;
    const tbody = document.getElementById("workflows-tbody");
    if (!tbody) return;
    const workflows = data.workflows || [];
    if (workflows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No workflows yet</td></tr>';
        return;
    }
    tbody.innerHTML = workflows.map(w => `
        <tr>
            <td>${w.id}</td>
            <td>${escHtml(w.name)}</td>
            <td>${escHtml(w.ticket_class || "-")}</td>
            <td><span class="status-badge ${statusClass(w.status)}">${escHtml(w.status)}</span></td>
            <td>${w.version || 1}</td>
            <td>${formatTime(w.updated_at)}</td>
            <td>
                <button class="btn btn-sm" onclick="viewWorkflow(${w.id})">Detail</button>
                ${w.status !== "approved" ? `<button class="btn btn-sm btn-success" onclick="reviewWorkflow(${w.id}, true)">Approve</button>` : ""}
            </td>
        </tr>
    `).join("");
}

async function loadIntake() {
    const [raci, sessions] = await Promise.all([
        apiGet("/api/intake/raci"),
        apiGet("/api/intake/sessions?limit=25"),
    ]);
    const raciList = document.getElementById("intake-raci-list");
    if (raciList && raci) {
        const rules = raci.rules || [];
        raciList.innerHTML = rules.slice(0, 20).map(rule => `
            <div class="learning-item">
                <div><strong>${escHtml(rule.name)}</strong> <span class="source-badge local">${escHtml(rule.ticket_class)}</span></div>
                <div>${escHtml(rule.assignment_group)} &middot; ${rule.approval_required ? "approval required" : "no approval gate"}</div>
                <div class="learning-meta">R: ${escHtml(rule.responsible)} / A: ${escHtml(rule.accountable)}</div>
                <div class="modal-actions-bar inline-actions">
                    <button class="inline-link" onclick="editRaciRule(${rule.id})">edit</button>
                    <button class="inline-link" onclick="disableRaciRule(${rule.id})">disable</button>
                </div>
            </div>
        `).join("");
    }
    const tbody = document.getElementById("intake-sessions-tbody");
    if (tbody && sessions) {
        const rows = sessions.sessions || [];
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="loading">No intake sessions yet</td></tr>';
        } else {
            tbody.innerHTML = rows.map(row => {
                const classification = row.classification || {};
                return `
                    <tr>
                        <td>${row.id}</td>
                        <td>${escHtml(row.requester_name || "-")}<div class="module-meta">${escHtml(row.requester_email || "")}</div></td>
                        <td>${escHtml(classification.intent || "-")}</td>
                        <td>${row.ticket_id ? `<button class="btn btn-sm" onclick="viewTicket(${row.ticket_id})">#${row.ticket_id}</button>` : "-"}</td>
                        <td><span class="status-badge ${statusClass(row.status)}">${escHtml(row.status)}</span></td>
                        <td>${formatTime(row.created_at)}</td>
                    </tr>
                `;
            }).join("");
        }
    }
}

function collectIntakeBody() {
    const attachment = document.getElementById("intake-attachment")?.value.trim() || "";
    return {
        requester_name: document.getElementById("intake-requester-name")?.value || "Demo User",
        requester_email: document.getElementById("intake-requester-email")?.value || "",
        title: document.getElementById("intake-title")?.value || "",
        message: document.getElementById("intake-message")?.value || "",
        channel: "dashboard",
        attachments: attachment ? [{ filename: attachment, storage_ref: "dashboard-metadata" }] : [],
    };
}

function renderIntakeClassification(classification) {
    const el = document.getElementById("intake-classification");
    if (!el || !classification) return;
    const raci = classification.raci || {};
    el.innerHTML = `
        <div class="intake-summary">
            <div><strong>${escHtml(classification.rule_name || classification.intent)}</strong> <span class="status-badge ${statusClass(classification.risk_level)}">${escHtml(classification.risk_level || "low")}</span></div>
            <div>${escHtml(classification.ticket_class)} &middot; ${escHtml(classification.priority)} &middot; ${escHtml(classification.assignment_group)}</div>
            <div class="learning-meta">Confidence ${Math.round((classification.confidence || 0) * 100)}% / approval ${classification.approval_required ? "required" : "not required"}</div>
        </div>
        <div class="intake-raci-grid">
            <div><span>Responsible</span><strong>${escHtml(raci.responsible || "-")}</strong></div>
            <div><span>Accountable</span><strong>${escHtml(raci.accountable || "-")}</strong></div>
            <div><span>Consulted</span><strong>${escHtml((raci.consulted || []).join(", ") || "-")}</strong></div>
            <div><span>Informed</span><strong>${escHtml((raci.informed || []).join(", ") || "-")}</strong></div>
        </div>
        ${classification.approval_action ? `<div class="setup-help">${escHtml(classification.approval_action)}</div>` : ""}
        <div class="setup-help">${classification.related_tickets?.length || 0} related tickets, ${classification.knowledge_articles?.length || 0} knowledge articles</div>
    `;
}

async function classifyIntake() {
    const result = await apiPost("/api/intake/clarify", collectIntakeBody());
    if (result?.error) {
        alert(result.error);
        return;
    }
    renderIntakeClassification(result?.classification);
    if (result?.needs_clarification && result.questions?.length) {
        const el = document.getElementById("intake-classification");
        if (el) el.innerHTML += `<div class="setup-help"><strong>Clarifying questions:</strong><br>${result.questions.map(escHtml).join("<br>")}</div>`;
    }
}

async function submitIntake() {
    const body = collectIntakeBody();
    const result = await apiPost("/api/intake/submit", body);
    if (result?.error) {
        alert(result.error);
        return;
    }
    renderIntakeClassification(result?.classification);
    alert(`Created ticket ${result?.ticket?.id}${result?.change_id ? ` and approval ${result.change_id}` : ""}. Provider sync: ${result?.ticket?.provider_sync_status || "local_only"}.`);
    await loadIntake();
    loadDashboardStats();
}

async function createRaciGroup() {
    const name = prompt("Group name:");
    if (!name) return;
    const description = prompt("Description:", "");
    if (description === null) return;
    const default_assignee = prompt("Default assignee:", "");
    if (default_assignee === null) return;
    const risk_level = prompt("Risk level:", "low");
    if (risk_level === null) return;
    const result = await apiPost("/api/intake/raci/groups", { name, description, default_assignee, risk_level, enabled: true });
    if (result?.error) alert(result.error);
    loadIntake();
}

async function createRaciRule() {
    const name = prompt("Rule name:");
    if (!name) return;
    const intent = prompt("Intent:", "general");
    if (intent === null) return;
    const keywords = prompt("Keywords, comma-separated:", "");
    if (keywords === null) return;
    const assignment_group = prompt("Assignment group:", "Business Applications");
    if (assignment_group === null) return;
    const ticket_class = prompt("Ticket class:", "UserRequest");
    if (ticket_class === null) return;
    const responsible = prompt("Responsible:", assignment_group);
    if (responsible === null) return;
    const accountable = prompt("Accountable:", "Service Desk Manager");
    if (accountable === null) return;
    const approval_required = confirm("Require approval gate for this route?");
    const result = await apiPost("/api/intake/raci/rules", {
        name,
        intent: intent || "general",
        keywords: keywords.split(",").map(v => v.trim()).filter(Boolean),
        ticket_class: ticket_class || "UserRequest",
        priority: "P3",
        assignment_group: assignment_group || "Business Applications",
        responsible: responsible || assignment_group || "Business Applications",
        accountable: accountable || "Service Desk Manager",
        consulted: [],
        informed: [],
        approval_required,
        risk_level: approval_required ? "medium" : "low",
        knowledge_tags: [intent || "general"],
        enabled: true,
    });
    if (result?.error) alert(result.error);
    loadIntake();
}

async function editRaciRule(id) {
    const assignment_group = prompt("Assignment group:");
    if (assignment_group === null) return;
    const priority = prompt("Priority:", "P3");
    if (priority === null) return;
    const risk_level = prompt("Risk level:", "low");
    if (risk_level === null) return;
    const result = await apiPut(`/api/intake/raci/rules/${id}`, {
        assignment_group,
        responsible: assignment_group,
        priority,
        risk_level,
    });
    if (result?.error) alert(result.error);
    loadIntake();
}

async function disableRaciRule(id) {
    if (!confirm("Disable this RACI rule?")) return;
    const result = await apiDelete(`/api/intake/raci/rules/${id}`);
    if (result?.error) alert(result.error);
    loadIntake();
}

async function loadCicd() {
    const data = await apiGet("/api/cicd/runs?limit=50");
    const tbody = document.getElementById("cicd-runs-tbody");
    if (!tbody || !data) return;
    const rows = data.runs || [];
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No CI/CD security runs yet</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(row => `
        <tr>
            <td>${row.id}</td>
            <td>${escHtml(row.provider || "gitlab")}</td>
            <td style="max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escAttr(row.repo_ref)}">
                ${escHtml(row.repo_ref)}
                ${repoExternalUrl(row.provider, row.repo_ref) ? `<a class="inline-link" href="${escAttr(repoExternalUrl(row.provider, row.repo_ref))}" target="_blank" rel="noopener">repo</a>` : ""}
            </td>
            <td><span class="status-badge ${statusClass(row.status)}">${escHtml(row.status)}</span></td>
            <td>${row.ticket_id ? `<button class="btn btn-sm" onclick="viewTicket(${row.ticket_id})">#${row.ticket_id}</button>` : "-"}</td>
            <td>${row.change_id ? `<button class="btn btn-sm" onclick="navigateTo('changes')">#${row.change_id}</button>` : "-"}</td>
            <td>${formatTime(row.created_at)} <button class="inline-link" onclick="viewCicdRun(${row.id})">findings</button></td>
        </tr>
    `).join("");
}

function repoExternalUrl(provider, repoRef) {
    const ref = String(repoRef || "");
    if (ref.startsWith("http://") || ref.startsWith("https://")) return ref;
    if (String(provider || "").toLowerCase() === "gitlab" && ref.includes("/")) return `http://192.168.50.222/${ref}`;
    return "";
}

function severitySummary(findings) {
    const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    (Array.isArray(findings) ? findings : []).forEach(f => {
        const sev = String(f.severity || "info").toLowerCase();
        counts[counts[sev] === undefined ? "info" : sev] += 1;
    });
    return Object.entries(counts).map(([k, v]) => `${k}:${v}`).join(" ");
}

async function viewCicdRun(id) {
    const data = await apiGet(`/api/cicd/runs/${id}`);
    if (!data) return;
    const findings = Array.isArray(data.findings) ? data.findings : [];
    const related = data.related_runs || [];
    const links = data.report_links || [];
    document.getElementById("modal-title").textContent = `CI/CD Run #${data.id}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Security Gate</div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${escHtml(data.status)}</span></div>
            <div class="detail-row"><span class="detail-label">Repo:</span><span>${escHtml(data.repo_ref || "-")} ${data.repo_url ? `<a class="inline-link" href="${escAttr(data.repo_url)}" target="_blank" rel="noopener">open repo</a>` : ""}</span></div>
            <div class="detail-row"><span class="detail-label">Branch:</span><span>${escHtml(data.branch || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Commit:</span><span>${escHtml(data.commit_sha || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Findings:</span><span>${severitySummary(findings)}</span></div>
            ${data.ticket_id ? `<div class="detail-row"><span class="detail-label">Ticket:</span><span><button class="inline-link" onclick="viewTicket(${data.ticket_id})">#${data.ticket_id}</button></span></div>` : ""}
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Summary:</span><pre class="task-output">${escHtml(data.summary || "")}</pre></div>
        </div>
        <div class="modal-section">
            <div class="section-title">Reports</div>
            ${links.length ? links.map(l => `<div class="modal-activity-item"><span>${escHtml(l.tool)}</span><a class="ticket-link" href="${escAttr(l.url)}" target="_blank" rel="noopener">${escHtml(l.label)}</a></div>`).join("") : '<div class="learning-meta">No report links recorded. Scanner JSON is still stored in the run record below.</div>'}
            <pre class="task-output">${escHtml(JSON.stringify({ findings, tool_results: data.tool_results || {} }, null, 2))}</pre>
        </div>
        <div class="modal-section">
            <div class="section-title">Before / After Runs</div>
            ${related.length ? related.map(r => `<div class="modal-activity-item"><span>#${r.id}</span><span>${formatDate(r.created_at)} <span class="status-badge ${statusClass(r.status)}">${escHtml(r.status)}</span> ${severitySummary(r.findings || [])}</span></div>`).join("") : '<div class="learning-meta">No related before/after runs recorded yet.</div>'}
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function showGitlabTemplate() {
    const data = await apiGet("/api/cicd/gitlab/template");
    const el = document.getElementById("cicd-template");
    if (el && data) el.textContent = data.template || "";
}

async function recordDemoCicdRun() {
    const repoRef = document.getElementById("cicd-repo-ref")?.value || "gitlab/demo/security-pipeline";
    const branch = document.getElementById("cicd-branch")?.value || "main";
    const targetUrl = document.getElementById("cicd-target-url")?.value || "";
    const createTicket = !!document.getElementById("cicd-create-ticket")?.checked;
    const requireChange = !!document.getElementById("cicd-require-change")?.checked;
    const result = await apiPost("/api/cicd/runs", {
        provider: "gitlab",
        repo_ref: repoRef,
        branch,
        target_url: targetUrl || null,
        deployment_target: "production",
        create_ticket: createTicket,
        require_change: requireChange,
        status: "passed",
        summary: "Demo GitLab CI/CD security gate recorded from dashboard. Replace this with scripts/run_cicd_security_pipeline.py output in real pipelines.",
        findings: [],
        tool_results: {
            semgrep: { status: "completed" },
            trivy: { status: "completed" },
            owasp_zap: targetUrl ? { status: "completed" } : { status: "skipped", reason: "target URL not provided" },
            nuclei: targetUrl ? { status: "completed" } : { status: "skipped", reason: "target URL not provided" },
        },
    });
    if (result?.error) alert(result.error);
    await loadCicd();
    loadDashboardStats();
}

async function loadLearning() {
    await Promise.all([loadPostmortems(), loadSkills(), loadKnowledge()]);
}

async function loadAccess() {
    const [me, users, policy] = await Promise.all([
        apiGet("/api/access/me"),
        apiGet("/api/access/users"),
        apiGet("/api/access/policies"),
    ]);
    const meEl = document.getElementById("access-me");
    if (meEl && me) {
        meEl.innerHTML = `
            <div class="learning-item">
                <div><strong>${escHtml(me.identity?.username || "-")}</strong></div>
                <div>${escHtml(me.identity?.provider || "local")} / ${escHtml(me.identity?.auth_mode || "disabled")}</div>
                <div class="learning-meta">${escHtml((me.roles || []).join(", ") || "no roles")}</div>
            </div>
        `;
    }
    const policyEl = document.getElementById("access-policy");
    if (policyEl && policy) {
        policyEl.innerHTML = `
            <div class="learning-item">
                <div><strong>${escHtml(policy.auth_mode)}</strong> <span class="source-badge local">${escHtml(policy.enforcement)}</span></div>
                <div>${escHtml(Object.keys(policy.role_capabilities || {}).join(", "))}</div>
                <div class="learning-meta">Header-based provider adapter ready for Keycloak, Entra, Okta, or reverse proxy auth.</div>
            </div>
        `;
    }
    const tbody = document.getElementById("access-users-tbody");
    if (tbody && users) {
        const rows = users.users || [];
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" class="loading">No dashboard users configured</td></tr>';
        } else {
            tbody.innerHTML = rows.map(u => `
                <tr>
                    <td>${u.id}</td>
                    <td>${escHtml(u.display_name || u.username)}<div class="module-meta">${escHtml(u.email || "")}</div></td>
                    <td>${escHtml(u.provider || "local")}</td>
                    <td>${escHtml((u.roles || []).join(", "))}</td>
                    <td>${u.enabled ? "yes" : "no"}</td>
                </tr>
            `).join("");
        }
    }
}

async function loadPostmortems() {
    const data = await apiGet("/api/postmortems?limit=100");
    const tbody = document.getElementById("postmortems-tbody");
    if (!data || !tbody) return;
    const rows = data.postmortems || [];
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No postmortems yet</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(p => `
        <tr>
            <td>${p.id}</td>
            <td>${escHtml(p.ticket_title || p.ticket_id || "-")}</td>
            <td><span class="status-badge ${statusClass(p.status)}">${escHtml(p.status)}</span></td>
            <td style="max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(p.summary || "-")}</td>
            <td>${formatTime(p.updated_at || p.created_at)}</td>
            <td>
                <button class="btn btn-sm" onclick="promotePostmortem(${p.id})">Promote</button>
                <button class="inline-link" onclick="openAuditTrail('postmortem_${p.id}')">audit</button>
            </td>
        </tr>
    `).join("");
}

async function promotePostmortem(postmortemId) {
    const ok = confirm("Promote this postmortem into a knowledge article, draft workflow, and reusable skills?");
    if (!ok) return;
    const result = await apiPost(`/api/postmortems/${postmortemId}/promote`, {
        create_knowledge: true,
        create_workflow: true,
        create_skills: true,
        workflow_status: "draft",
        created_by: "dashboard",
        mark_promoted: true,
    });
    if (result && !result.error) {
        alert(`Postmortem promoted. KB ${result.knowledge_article_id || "none"}, workflow ${result.workflow_id || "none"}, skills ${(result.skill_ids || []).join(", ") || "none"}.`);
        loadLearning();
    } else {
        alert(result?.error || "Postmortem promotion failed");
    }
}

async function loadSkills() {
    const data = await apiGet("/api/skills?enabled_only=false");
    const list = document.getElementById("skills-list");
    if (!data || !list) return;
    const skills = data.skills || [];
    if (skills.length === 0) {
        list.innerHTML = '<div class="learning-empty">No skills configured</div>';
        return;
    }
    list.innerHTML = skills.map(s => `
        <div class="learning-item">
            <div><strong>${escHtml(s.name)}</strong> <span class="source-badge local">${escHtml(s.category || "general")}</span></div>
            <div>${escHtml(s.description || "")}</div>
            <div class="learning-meta">${s.enabled ? "enabled" : "disabled"} ${s.assigned_to_all ? "&middot; global" : ""}</div>
        </div>
    `).join("");
}

async function loadKnowledge() {
    const data = await apiGet("/api/knowledge?limit=50");
    const list = document.getElementById("knowledge-list");
    if (!data || !list) return;
    const articles = data.articles || [];
    if (articles.length === 0) {
        list.innerHTML = '<div class="learning-empty">No knowledge articles yet</div>';
        return;
    }
    list.innerHTML = articles.map(a => `
        <div class="learning-item">
            <div><strong>${escHtml(a.title)}</strong> <span class="source-badge itop">${escHtml(a.category || "general")}</span></div>
            <div>${escHtml((a.body || "").slice(0, 220))}</div>
            <div class="learning-meta">${formatDate(a.updated_at || a.created_at)}</div>
        </div>
    `).join("");
}

// Load changes
async function loadChanges() {
    const status = document.getElementById("change-filter-status")?.value || "";
    const params = status ? `?status=${status}` : "";

    const data = await apiGet(`/api/changes${params}`);
    if (!data) return;

    const tbody = document.getElementById("changes-tbody");
    if (!tbody) return;

    if (data.changes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No change requests</td></tr>';
        return;
    }

    tbody.innerHTML = data.changes.map(c => `
        <tr>
            <td>${c.id}</td>
            <td>
                ${escHtml(c.action)}
                <div class="module-meta">${approvalModeBadge(c)}</div>
            </td>
            <td>${escHtml(c.target)}</td>
            <td>${c.ticket_id ? `<button class="inline-link" onclick="viewTicket(${c.ticket_id})">#${c.ticket_id}</button> ${escHtml(c.ticket_title || "")}` : escHtml(c.ticket_title || "-")}</td>
            <td><span class="status-badge ${statusClass(c.status)}">${c.status}</span></td>
            <td>${formatTime(c.requested_at)}</td>
            <td>
                ${c.status === "pending" ? `
                    <button class="btn btn-sm btn-success" onclick="approveChange(${c.id})">Approve</button>
                    <button class="btn btn-sm btn-danger" onclick="rejectChange(${c.id})">Reject</button>
                ` : ""}
                <button class="inline-link" onclick="openAuditTrail('change_${c.id}')">audit</button>
            </td>
        </tr>
    `).join("");
}

// Load tools
async function loadTools() {
    const data = await apiGet("/api/tools");
    if (!data) return;

    const grid = document.getElementById("tools-grid");
    if (!grid) return;

    grid.innerHTML = data.tools.map(t => `
        <div class="tool-card">
            <div class="tool-card-header">
                <span class="tool-name">${escHtml(t.name)}</span>
                <span class="tool-status-dot ${t.last_check_status || t.status || 'unknown'}"></span>
            </div>
            <div class="tool-type">${t.type}</div>
            <div class="tool-desc">${escHtml(t.description || "")}</div>
            ${t.host ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">${t.host}:${t.port || 'N/A'}</div>` : ""}
            ${t.last_check ? `<div style="font-size:11px;color:var(--text-muted)">Last check: ${formatTime(t.last_check)}</div>` : ""}
        </div>
    `).join("");
}

// Load audit log
async function loadAudit() {
    const params = new URLSearchParams();
    params.set("limit", "100");
    const source = document.getElementById("audit-filter-source")?.value || "";
    const level = document.getElementById("audit-filter-level")?.value || "";
    const text = document.getElementById("audit-filter-text")?.value.trim() || "";
    if (source) params.set("source", source);
    if (level) params.set("level", level);
    if (text) params.set("q", text);
    const data = await apiGet(`/api/dashboard/audit?${params}`);
    if (!data) return;

    const timeline = document.getElementById("audit-timeline");
    if (!timeline) return;

    if (data.audit.length === 0) {
        timeline.innerHTML = '<div class="loading">No audit entries</div>';
        return;
    }

    timeline.innerHTML = data.audit.map(a => `
        <div class="audit-entry">
            <span class="audit-time">${formatTime(a.created_at)}</span>
            <div class="audit-icon">&#9650;</div>
            <div class="audit-content">
                <div class="audit-action">
                    <span class="source-badge ${a.source === "event" ? "itop" : "local"}">${escHtml(a.source || "audit")}</span>
                    ${a.level ? `<span class="status-badge ${statusClass(a.level)}">${escHtml(a.level)}</span>` : ""}
                    ${escHtml(a.summary || `${a.actor}: ${a.action}`)}
                </div>
                <div class="audit-details">${escHtml(a.category || "")}${a.ticket_id ? ` &middot; ticket ${escHtml(a.ticket_id)}` : ""}${a.agent_id ? ` &middot; agent ${escHtml(a.agent_id)}` : ""}</div>
                <div class="audit-links">
                    ${a.ticket_id ? `<button class="inline-link" onclick="viewTicket(${Number(a.ticket_id)})">ticket</button>` : ""}
                    ${a.ticket_id ? `<button class="inline-link" onclick="openAuditTrail('ticket_${escAttr(a.ticket_id)}')">ticket trail</button>` : ""}
                    ${a.agent_id ? `<button class="inline-link" onclick="openAuditTrail('agent_${escAttr(a.agent_id)}')">agent trail</button>` : ""}
                    ${a.target ? `<button class="inline-link" onclick="openAuditTrail('${escJs(a.target)}')">target trail</button>` : ""}
                </div>
                ${a.details ? `<pre class="audit-json">${escHtml(JSON.stringify(a.details, null, 2))}</pre>` : ""}
            </div>
        </div>
    `).join("");
}

// View ticket detail
async function viewTicket(id) {
    const data = await apiGet(`/api/tickets/${id}`);
    if (!data) return;

    document.getElementById("modal-title").textContent = `Ticket #${data.id} - ${data.itop_class || "Incident"}::${data.itop_ref}`;

    // Build agent section
    const agentSection = data.agent_status ? `
        <div class="modal-section">
            <div class="section-title">Agent Status</div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.agent_status)}">${data.agent_status}</span></div>
            <div class="detail-row"><span class="detail-label">Model:</span><span>${data.agent_model || "-"}</span></div>
            <div class="detail-row"><span class="detail-label">Started:</span><span>${formatDate(data.agent_started)}</span></div>
            <div class="detail-row"><span class="detail-label">Heartbeat:</span><span>${formatTime(data.agent_heartbeat)}</span></div>
            ${data.agent_error ? `<div class="detail-row"><span class="detail-label">Error:</span><span style="color:var(--accent-danger)">${escHtml(data.agent_error)}</span></div>` : ""}
        </div>
    ` : `
        <div class="modal-section">
            <div class="section-title">Agent Status</div>
            <div style="color:var(--text-muted);font-size:13px">No agent assigned</div>
        </div>
    `;

    // Build change requests section
    const changesSection = data.change_requests && data.change_requests.length > 0 ? `
        <div class="modal-section">
            <div class="section-title">Approval Gates</div>
            ${data.change_requests.map(c => renderGateSummary(c)).join("")}
        </div>
    ` : "";

    // Build actions bar
    const actionsBar = `
        <div class="modal-actions-bar">
            ${!data.agent_status ? `<button class="btn btn-sm btn-success" onclick="assignAgent(${data.id});closeModal('ticket-modal')">Assign Agent</button>` : ""}
            ${data.agent_status ? `<button class="btn btn-sm" onclick="apiPost('/api/tickets/${data.id}/unassign-agent');setTimeout(()=>{closeModal('ticket-modal');loadTickets()}, 500)">Unassign Agent</button>` : ""}
            <button class="btn btn-sm" onclick="apiPost('/api/tickets/${data.id}/sync');setTimeout(()=>viewTicket(${data.id}), 1000)">Sync from iTop</button>
            <button class="btn btn-sm btn-warning" onclick="startTicketPostmortem(${data.id})">Postmortem</button>
            <button class="btn btn-sm btn-warning" onclick="startTicketWorkflow(${data.id})">Build Workflow</button>
            <button class="btn btn-sm" onclick="openAuditTrail('ticket_${data.id}')">Full Audit Trail</button>
            ${data.external_url ? `<a class="btn btn-sm" href="${escAttr(data.external_url)}" target="_blank" rel="noopener">Open Ticket</a>` : ""}
        </div>
    `;

    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Ticket Information</div>
            <div class="detail-row"><span class="detail-label">Title:</span><span>${escHtml(data.title)}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${data.status}</span></div>
            <div class="detail-row"><span class="detail-label">Priority:</span><span>${data.priority || "-"}</span></div>
            <div class="detail-row"><span class="detail-label">Impact:</span><span>${data.impact || "-"}</span></div>
            <div class="detail-row"><span class="detail-label">Urgency:</span><span>${data.urgency || "-"}</span></div>
            <div class="detail-row"><span class="detail-label">Assignee:</span><span>${escHtml(data.assignee || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Team:</span><span>${escHtml(data.assignee_team || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">iTop Ref:</span><span>${data.itop_ref}</span></div>
            <div class="detail-row"><span class="detail-label">Provider:</span><span>${escHtml(data.provider || "itop")} / ${escHtml(data.provider_ref || data.itop_ref || "-")} <span class="status-badge ${statusClass(data.provider_sync_status || "unknown")}">${escHtml(data.provider_sync_status || "unknown")}</span></span></div>
            ${data.external_url ? `<div class="detail-row"><span class="detail-label">External:</span><span><a class="ticket-link" href="${escAttr(data.external_url)}" target="_blank" rel="noopener">${escHtml(data.external_url)}</a></span></div>` : ""}
            <div class="detail-row"><span class="detail-label">Created:</span><span>${formatDate(data.created_at)}</span></div>
            <div class="detail-row"><span class="detail-label">Updated:</span><span>${formatDate(data.updated_at)}</span></div>
            ${data.description ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Description:</span><span style="white-space:pre-wrap">${escHtml(data.description)}</span></div>` : ""}
        </div>
        ${agentSection}
        ${changesSection}
        ${actionsBar}
    `;
    document.getElementById("ticket-modal").classList.add("active");

    // Load activity log for this ticket
    loadTicketActivity(id);
}

async function viewWorkflow(id) {
    const data = await apiGet(`/api/workflows/${id}`);
    if (!data) return;
    document.getElementById("modal-title").textContent = `Workflow #${data.id}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Workflow</div>
            <div class="detail-row"><span class="detail-label">Name:</span><span>${escHtml(data.name)}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${escHtml(data.status)}</span></div>
            <div class="detail-row"><span class="detail-label">Class:</span><span>${escHtml(data.ticket_class || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Version:</span><span>${data.version || 1}</span></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Blueprint:</span><pre class="task-output">${escHtml(data.blueprint || "")}</pre></div>
            ${data.test_plan ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Test Plan:</span><pre class="task-output">${escHtml(data.test_plan)}</pre></div>` : ""}
            ${data.test_results ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Test Results:</span><pre class="task-output">${escHtml(data.test_results)}</pre></div>` : ""}
        </div>
        <div class="modal-actions-bar">
            <button class="btn btn-sm btn-success" onclick="reviewWorkflow(${data.id}, true)">Approve</button>
            <button class="btn btn-sm btn-danger" onclick="reviewWorkflow(${data.id}, false)">Request Revision</button>
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

// Load activity log for a ticket (appends to modal)
async function loadTicketActivity(ticketId) {
    try {
        const [auditData, contextData] = await Promise.all([
            apiGet(`/api/dashboard/audit?limit=80&ticket_id=${ticketId}`),
            apiGet(`/api/tickets/${ticketId}/context`),
        ]);
        const relevant = auditData?.audit || [];
        const notes = contextData?.notes || [];
        const tasks = contextData?.tasks || [];
        const changes = contextData?.change_requests || [];

        const modalBody = document.getElementById("modal-body");
        if (!modalBody) return;

        // Insert before the actions bar
        const actionsBar = modalBody.querySelector(".modal-actions-bar");
        if (!actionsBar) return;

        const activityHtml = `
            <div class="modal-section">
                <div class="section-title">
                    Ticket Timeline
                    <button class="inline-link" onclick="openAuditTrail('ticket_${ticketId}')">open full trail</button>
                </div>
                <div class="timeline-summary">
                    ${notes.length} notes &middot; ${relevant.length} audit/events &middot; ${tasks.length} tasks &middot; ${changes.length} changes
                </div>
                ${notes.length === 0 ? '<div style="color:var(--text-muted);font-size:12px">No notes recorded yet</div>' : ""}
                ${notes.slice(-8).reverse().map(n => `
                    <div class="modal-activity-item note-item">
                        <span style="min-width:60px">${formatTime(n.created_at)}</span>
                        <span>
                            <strong>${escHtml(n.author || "note")}</strong>
                            <span class="source-badge local">${escHtml(n.source || "note")}</span>
                            <div class="activity-note-body">${escHtml(n.body || "")}</div>
                        </span>
                    </div>
                `).join("")}
                ${relevant.length === 0 ? '<div style="color:var(--text-muted);font-size:12px;margin-top:8px">No audit entries recorded</div>' : ""}
                ${relevant.slice(0, 20).map(a => `
                    <div class="modal-activity-item">
                        <span style="min-width:60px">${formatTime(a.created_at)}</span>
                        <span>
                            <strong>${escHtml(a.actor)}</strong> ${escHtml(a.summary || `${a.action} ${a.target || ""}`)}
                            ${a.agent_id ? `<button class="inline-link" onclick="openAuditTrail('agent_${escAttr(a.agent_id)}')">agent trail</button>` : ""}
                            ${a.target ? `<button class="inline-link" onclick="openAuditTrail('${escJs(a.target)}')">target trail</button>` : ""}
                        </span>
                    </div>
                `).join("")}
            </div>
        `;

        const activityEl = document.createElement("div");
        activityEl.innerHTML = activityHtml;
        modalBody.insertBefore(activityEl, actionsBar);
    } catch (e) {
        console.error("Failed to load ticket activity:", e);
    }
}

// Assign agent to ticket
async function assignAgent(ticketId) {
    const model = document.getElementById("agent-model-select")?.value || "qwen/qwen3.6-27b";
    const result = await apiPost(`/api/tickets/${ticketId}/assign-agent`, { model });
    if (result?.error) {
        alert(result.error);
    } else if (result) {
        alert(`Agent ${result.agent_id} assigned to ticket ${ticketId}`);
        loadTickets();
    }
}

async function startTicketPostmortem(ticketId) {
    const model = document.getElementById("agent-model-select")?.value || "qwen/qwen3.6-27b";
    const context = prompt("Optional postmortem context or review focus:", "");
    if (context === null) return;
    const result = await apiPost(`/api/tickets/${ticketId}/postmortem`, { model, context });
    if (result && !result.error) {
        closeModal("ticket-modal");
        navigateTo("agents");
    } else if (result?.error) {
        alert(result.error);
    }
}

async function startTicketWorkflow(ticketId) {
    const model = document.getElementById("agent-model-select")?.value || "qwen/qwen3.6-27b";
    const context = prompt("Describe the workflow/automation to build or improve:", "");
    if (context === null) return;
    const result = await apiPost(`/api/tickets/${ticketId}/workflow`, { model, context });
    if (result && !result.error) {
        closeModal("ticket-modal");
        navigateTo("agents");
    } else if (result?.error) {
        alert(result.error);
    }
}

async function createWorkflowFromPrompt() {
    const name = prompt("Workflow name:");
    if (!name) return;
    const blueprint = prompt("Workflow blueprint:");
    if (!blueprint) return;
    const result = await apiPost("/api/workflows", {
        name,
        blueprint,
        description: "",
        status: "draft",
        trigger_type: "manual",
        approval_policy: { destructive_actions_require_approval: true },
    });
    if (result?.error) alert(result.error);
    loadWorkflows();
}

async function reviewWorkflow(id, approved) {
    const review_notes = prompt(approved ? "Approval notes:" : "Revision notes:", "");
    if (review_notes === null) return;
    const result = await apiPost(`/api/workflows/${id}/review`, { approved, review_notes, reviewed_by: "dashboard" });
    if (result?.error) alert(result.error);
    loadWorkflows();
}

async function createKnowledgeArticle() {
    const title = prompt("Article title:");
    if (!title) return;
    const body = prompt("Article body:");
    if (!body) return;
    await apiPost("/api/knowledge", { title, body, category: "general", source: "dashboard", tags: [] });
    loadLearning();
}

async function importKnowledgeUrl() {
    const url = prompt("Knowledge source URL:");
    if (!url) return;
    const title = prompt("Article title (blank uses URL):", "");
    if (title === null) return;
    const category = prompt("Category:", "imported");
    if (category === null) return;
    const result = await apiPost("/api/knowledge/import-url", {
        url,
        title: title || null,
        category: category || "imported",
        source: "dashboard-url-import",
        tags: [],
    });
    if (result?.error) alert(result.error);
    loadLearning();
}

async function createDashboardUser() {
    const username = prompt("Username:");
    if (!username) return;
    const display_name = prompt("Display name:", username);
    if (display_name === null) return;
    const email = prompt("Email:", "");
    if (email === null) return;
    const provider = prompt("Provider:", "local");
    if (provider === null) return;
    const result = await apiPost("/api/access/users", {
        username,
        display_name: display_name || username,
        email: email || null,
        provider: provider || "local",
        enabled: true,
    });
    if (result?.error) alert(result.error);
    loadAccess();
}

async function createSkill() {
    const name = prompt("Skill name:");
    if (!name) return;
    const prompt_template = prompt("Skill instructions:");
    if (!prompt_template) return;
    await apiPost("/api/skills", {
        name,
        prompt_template,
        description: "",
        category: "custom",
    });
    loadLearning();
}

async function loadAgentModels() {
    const data = await apiGet("/api/agents/models");
    const selects = document.querySelectorAll("[data-agent-model-select]");
    const models = data?.models || ["qwen/qwen3.6-27b"];
    selects.forEach(select => {
        select.innerHTML = models.map(m => `<option value="${escHtml(m)}">${escHtml(m)}</option>`).join("");
    });
}

// Approve change
async function approveChange(id) {
    await apiPost(`/api/changes/${id}/approve`, {});
    loadChanges();
}

// Reject change
async function rejectChange(id) {
    const reason = prompt("Rejection reason:");
    if (reason !== null) {
        await apiPost(`/api/changes/${id}/reject`, { reason });
        loadChanges();
    }
}

// Check all tools
async function checkAllTools() {
    await apiPost("/api/tools/check-all", {});
    setTimeout(loadTools, 2000);
}

// Refresh all
function refreshAll() {
    loadDashboardStats();
    loadTickets();
    loadAgents();
    loadChanges();
    loadTools();
}

// Modal
function closeModal(id) {
    document.getElementById(id).classList.remove("active");
}

// Utility
function escHtml(str) {
    if (!str) return "";
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function escAttr(str) {
    return escHtml(String(str || "")).replace(/"/g, "&quot;");
}

function escJs(str) {
    return String(str || "")
        .replace(/\\/g, "\\\\")
        .replace(/'/g, "\\'")
        .replace(/\n/g, "\\n")
        .replace(/\r/g, "");
}

let setupManifest = null;
let setupPlan = null;

async function loadSetup() {
    setupManifest = await apiGet("/api/setup/manifest");
    if (!setupManifest) return;
    renderSetupModules();
    await generateSetupPlan();
}

function setupSelectedProfileModules() {
    const profile = document.getElementById("setup-profile")?.value || "soc";
    return new Set(setupManifest?.profiles?.[profile]?.modules || []);
}

function renderSetupModules() {
    const grid = document.getElementById("setup-modules");
    if (!grid || !setupManifest) return;
    const selected = setupSelectedProfileModules();
    const modules = setupManifest.modules || [];
    grid.innerHTML = modules.map(m => {
        const inProfile = selected.has(m.id);
        const disabled = m.status === "optional" || !m.deployable;
        const statusLabel = m.status || "unknown";
        return `
            <div class="module-card ${inProfile ? "selected" : ""}">
                <div class="module-card-head">
                    <div>
                        <strong>${escHtml(m.name)}</strong>
                        <div class="module-meta">${escHtml(m.category)} / ${escHtml(statusLabel)}</div>
                    </div>
                    <span class="status-badge ${statusClass(statusLabel)}">${escHtml(statusLabel)}</span>
                </div>
                <div class="module-desc">${escHtml(m.notes || "")}</div>
                <div class="module-controls">
                    <label class="setup-check small">
                        <input type="checkbox" data-setup-include="${escAttr(m.id)}" ${inProfile ? "checked" : ""} ${disabled ? "disabled" : ""} onchange="generateSetupPlan()">
                        <span>Use</span>
                    </label>
                    <label class="setup-check small">
                        <input type="checkbox" data-setup-existing="${escAttr(m.id)}" onchange="generateSetupPlan()">
                        <span>Existing product</span>
                    </label>
                </div>
                ${m.skill ? `<div class="module-meta">Skill: ${escHtml(m.skill)} ${m.skill_available ? "" : "(missing in container)"}</div>` : ""}
            </div>
        `;
    }).join("");
}

function collectSetupChoices() {
    const profile = document.getElementById("setup-profile")?.value || "soc";
    const profileModules = setupSelectedProfileModules();
    const include = [];
    const exclude = [];
    const existingTools = [];
    document.querySelectorAll("[data-setup-include]").forEach(input => {
        const id = input.dataset.setupInclude;
        if (input.checked && !profileModules.has(id)) include.push(id);
        if (!input.checked && profileModules.has(id)) exclude.push(id);
    });
    document.querySelectorAll("[data-setup-existing]").forEach(input => {
        if (input.checked) existingTools.push(input.dataset.setupExisting);
    });
    return {
        profile,
        include,
        exclude,
        existing_tools: existingTools,
        deploy_missing: !!document.getElementById("setup-deploy-missing")?.checked,
    };
}

async function generateSetupPlan() {
    if (!document.getElementById("setup-plan-tbody")) return;
    if (!setupManifest) {
        setupManifest = await apiGet("/api/setup/manifest");
        if (!setupManifest) return;
        renderSetupModules();
    }
    const choices = collectSetupChoices();
    setupPlan = await apiPost("/api/setup/plan", choices);
    renderSetupPlan();
}

function renderSetupPlan() {
    const summary = document.getElementById("setup-summary");
    const tbody = document.getElementById("setup-plan-tbody");
    if (!setupPlan || !summary || !tbody) return;
    const s = setupPlan.summary || {};
    summary.innerHTML = `
        <span class="source-badge itop">${escHtml(setupPlan.profile)}</span>
        ${s.total || 0} modules &middot;
        ${s.deploy || 0} deploy &middot;
        ${s.integrate_existing || 0} integrate existing &middot;
        ${s.blueprint || 0} blueprint
        ${s.missing_skills?.length ? `<span class="status-badge status-warning">${s.missing_skills.length} missing skills in runtime</span>` : ""}
    `;
    const steps = setupPlan.steps || [];
    if (steps.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No setup steps selected</td></tr>';
        return;
    }
    tbody.innerHTML = steps.map((step, idx) => `
        <tr>
            <td>${idx + 1}</td>
            <td>${escHtml(step.name)}<div class="module-meta">${escHtml(step.module_id)}</div></td>
            <td>${escHtml(step.category || "-")}</td>
            <td><span class="status-badge ${statusClass(step.status)}">${escHtml(step.status)}</span></td>
            <td>${step.skill ? `${escHtml(step.skill)} ${step.skill_available ? "" : '<span class="status-badge status-error">missing</span>'}` : "-"}</td>
            <td>${escHtml((step.health_checks || []).slice(0, 2).join(", "))}</td>
        </tr>
    `).join("");
}

async function createSetupTicket(spawnAgent) {
    if (!setupManifest) await loadSetup();
    const choices = collectSetupChoices();
    const result = await apiPost("/api/setup/ticket", {
        ...choices,
        ai_base_url: document.getElementById("setup-ai-base-url")?.value || null,
        model: document.getElementById("setup-model")?.value || document.getElementById("agent-model-select")?.value || "qwen/qwen3.6-27b",
        notes: document.getElementById("setup-notes")?.value || "",
        spawn_agent: spawnAgent,
        sync_provider: false,
    });
    if (result?.ticket?.id) {
        alert(`Setup ticket ${result.ticket.id} created${result.agent?.agent_id ? ` with agent ${result.agent.agent_id}` : ""}.`);
        navigateTo(spawnAgent ? "agents" : "tickets");
    } else if (result?.error) {
        alert(result.error);
    }
}
