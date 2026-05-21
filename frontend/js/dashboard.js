// Agentic Operations - Main JavaScript
const API = "";
let agentOpenCountState = null;
let skillsCache = [];
let knowledgeCache = [];
let tableSortState = {
    intake: { key: "created_at", dir: "desc" },
    changes: { key: "requested_at", dir: "desc" },
    workflows: { key: "updated_at", dir: "desc" },
    postmortems: { key: "updated_at", dir: "desc" },
    cicd: { key: "created_at", dir: "desc" },
    skills: { key: "name", dir: "asc" },
    tools: { key: "name", dir: "asc" },
    access: { key: "username", dir: "asc" },
};

function computeAgentLifecycleCounts(agents) {
    const rows = agents || [];
    const activeStatuses = new Set(["spawned", "running", "working"]);
    const waitingStatuses = new Set(["pending_approval", "awaiting_access", "awaiting_user_response", "blocked"]);
    const queued = rows.filter(a => a?.task_status === "queued" && (a.status === "spawned" || a.status === "running"));
    const active = rows.filter(a => activeStatuses.has(a.status) && !queued.includes(a));
    const waiting = rows.filter(a => waitingStatuses.has(a.status));
    return {
        queued: queued.length,
        active: active.length,
        waiting: waiting.length,
        open: queued.length + active.length + waiting.length,
    };
}

function agentOpenCountFromStats(agents) {
    if (!agents) return 0;
    if (agents.open !== undefined && agents.open !== null) return Number(agents.open) || 0;
    const openStatuses = new Set([
        "spawned", "running", "working",
        "pending_approval", "awaiting_access", "awaiting_user_response", "blocked",
    ]);
    return (agents.distribution || []).reduce((total, row) => {
        return total + (openStatuses.has(row.status) ? Number(row.count || 0) : 0);
    }, 0);
}

function setAgentOpenCount(count) {
    agentOpenCountState = Number(count || 0);
    setText("agent-count", agentOpenCountState);
    setText("stat-agent-active", agentOpenCountState);
    return agentOpenCountState;
}

// Navigation
document.addEventListener("DOMContentLoaded", () => {
    initNavigation();
    initTicketSorting();
    initGenericTableSorting();
    initTicketInfiniteScroll();
    loadCurrentIdentity();
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

function initTicketInfiniteScroll() {
    const scrollRoot = document.querySelector(".main-content");
    const sentinel = document.getElementById("ticket-pagination");
    if (sentinel && "IntersectionObserver" in window) {
        const observer = new IntersectionObserver(entries => {
            const activePage = document.querySelector(".page.active");
            if (!activePage || activePage.id !== "page-tickets") return;
            if (entries.some(entry => entry.isIntersecting) && !ticketListState.loading && !ticketListState.done) {
                loadMoreTickets();
            }
        }, { root: scrollRoot || null, rootMargin: "500px 0px" });
        observer.observe(sentinel);
    }
    const onScroll = () => {
        const activePage = document.querySelector(".page.active");
        if (!activePage || activePage.id !== "page-tickets") return;
        if (ticketListState.loading || ticketListState.done) return;
        const remaining = scrollRoot
            ? scrollRoot.scrollHeight - (scrollRoot.scrollTop + scrollRoot.clientHeight)
            : document.documentElement.scrollHeight - (window.scrollY + window.innerHeight);
        if (remaining < 480) loadMoreTickets();
    };
    (scrollRoot || window).addEventListener("scroll", onScroll, { passive: true });
}

function navigateTo(page) {
    document.querySelectorAll(".nav-item").forEach(i => i.classList.remove("active"));
    document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));

    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (navItem) navItem.classList.add("active");

    const pageEl = document.getElementById(`page-${page}`);
    if (pageEl) pageEl.classList.add("active");
    if (agentOpenCountState !== null) setAgentOpenCount(agentOpenCountState);

    // Load data for the page
    switch (page) {
        case "overview": loadDashboardStats(); break;
        case "tickets": loadTickets(); break;
        case "intake": loadIntake(); break;
        case "agents": loadAgents(); break;
        case "changes": loadChanges(); break;
        case "workflows": loadWorkflows(); break;
        case "postmortems": loadPostmortemsPage(); break;
        case "cicd": loadCicd(); break;
        case "learning": loadLearning(); break;
        case "skills": loadSkillsPage(); break;
        case "tools": loadTools(); break;
        case "setup": loadSetup(); break;
        case "access": loadAccess(); break;
        case "settings": loadSettings(); break;
        case "audit": loadAudit(); break;
    }
}

function initGenericTableSorting() {
    document.querySelectorAll("[data-sort-table]").forEach(th => {
        th.addEventListener("click", () => {
            const table = th.dataset.sortTable;
            const key = th.dataset.sortKey;
            if (!table || !key) return;
            const current = tableSortState[table] || { key, dir: "asc" };
            tableSortState[table] = {
                key,
                dir: current.key === key && current.dir === "asc" ? "desc" : "asc",
            };
            updateGenericSortIndicators(table);
            reloadSortedTable(table);
        });
    });
    Object.keys(tableSortState).forEach(updateGenericSortIndicators);
}

function updateGenericSortIndicators(table) {
    document.querySelectorAll(`[data-sort-table="${table}"]`).forEach(th => {
        th.classList.remove("sort-asc", "sort-desc");
        if (th.dataset.sortKey === tableSortState[table]?.key) {
            th.classList.add(tableSortState[table].dir === "asc" ? "sort-asc" : "sort-desc");
        }
    });
}

function reloadSortedTable(table) {
    ({
        intake: loadIntake,
        changes: loadChanges,
        workflows: loadWorkflows,
        postmortems: loadPostmortemsPage,
        cicd: loadCicd,
        skills: loadSkillsPage,
        tools: loadTools,
        access: loadAccess,
    }[table] || (() => {}))();
}

function sortableValue(row, key) {
    const value = row?.[key];
    if (key === "requester") return `${row.requester_name || ""} ${row.requester_email || ""}`.toLowerCase();
    if (key === "roles") return normalizeList(row.roles).join(",").toLowerCase();
    if (key.includes("_at") || key === "created" || key === "updated") return Date.parse(value || "") || 0;
    if (typeof value === "number") return value;
    if (typeof value === "boolean") return value ? 1 : 0;
    return String(value ?? "").toLowerCase();
}

function sortRows(rows, table) {
    const sort = tableSortState[table] || { key: "id", dir: "desc" };
    return [...(rows || [])].sort((a, b) => {
        const av = sortableValue(a, sort.key);
        const bv = sortableValue(b, sort.key);
        const cmp = typeof av === "number" && typeof bv === "number"
            ? av - bv
            : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
        return sort.dir === "asc" ? cmp : -cmp;
    });
}

function filterRows(rows, query, fields) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return rows || [];
    return (rows || []).filter(row => fields.some(field => String(row?.[field] ?? "").toLowerCase().includes(q)));
}

function setSelectOptions(id, values, current = "") {
    const el = document.getElementById(id);
    if (!el) return;
    const existing = el.value || current;
    const first = el.querySelector("option[value='']")?.outerHTML || '<option value="">All</option>';
    el.innerHTML = first + [...new Set((values || []).filter(Boolean).map(String))]
        .sort((a, b) => a.localeCompare(b))
        .map(v => `<option value="${escAttr(v)}">${escHtml(v)}</option>`)
        .join("");
    if ([...el.options].some(o => o.value === existing)) el.value = existing;
}

function openOverviewMetric(metric) {
    if (metric === "tickets") {
        setSelectValue("ticket-filter-status", "");
        navigateTo("tickets");
    } else if (metric === "new_tickets") {
        setSelectValue("ticket-filter-status", "new");
        navigateTo("tickets");
    } else if (metric === "agents") {
        navigateTo("agents");
    } else if (metric === "changes") {
        setSelectValue("change-filter-status", "pending");
        navigateTo("changes");
    }
}

function applyAuditUrlFilters() {
    const params = new URLSearchParams(window.location.search);
    const q = params.get("audit_q");
    const source = params.get("audit_source");
    const level = params.get("audit_level");
    let hadAuditParams = false;
    if (q && document.getElementById("audit-filter-text")) document.getElementById("audit-filter-text").value = q;
    if (source && document.getElementById("audit-filter-source")) document.getElementById("audit-filter-source").value = source;
    if (level && document.getElementById("audit-filter-level")) document.getElementById("audit-filter-level").value = level;
    hadAuditParams = !!(q || source || level);
    if (hadAuditParams) clearAuditUrlParams();
}

function clearAuditUrlParams() {
    const url = new URL(window.location.href);
    url.searchParams.delete("audit_q");
    url.searchParams.delete("audit_source");
    url.searchParams.delete("audit_level");
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

function openAuditTrail(query, source = "") {
    navigateTo("audit");
    const text = document.getElementById("audit-filter-text");
    const sourceEl = document.getElementById("audit-filter-source");
    const levelEl = document.getElementById("audit-filter-level");
    if (text) text.value = query || "";
    if (sourceEl) sourceEl.value = source || "";
    if (levelEl) levelEl.value = "";
    clearAuditUrlParams();
    loadAudit();
}

let ticketSort = { by: "updated_at", dir: "desc" };
let ticketListState = { key: "", offset: 0, limit: 200, total: 0, loading: false, done: false, rows: [] };
let agentRuntimeConfig = { models: [], default_model: "", default_harness: "hermes", setups: [], available_harnesses: [] };
const DEMO_TICKET_IDS = [
    1393,
    1384, 1385, 1386, 1309, 1282, 1176,
    695, 690, 83, 580, 525, 539, 531, 422, 575, 530, 118, 363, 430, 578,
];
const DEMO_TICKET_ORDER = new Map(DEMO_TICKET_IDS.map((id, idx) => [id, idx]));

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
                case "postmortems": loadPostmortemsPage(); break;
                case "cicd": loadCicd(); break;
            }
        }
    }, 30000);
}

function isAuthRedirectReason(payload) {
    return payload && payload.error === "access_denied" && payload.authenticated === false && [
        "unauthenticated",
        "missing_authenticated_user",
        "invalid_session",
        "invalid_session_signature",
        "expired_session",
        "unknown_or_disabled_user",
    ].includes(payload.reason);
}

function redirectToLogin() {
    const next = encodeURIComponent(`${window.location.pathname}${window.location.search}${window.location.hash}`);
    window.location.assign(`/login?next=${next}`);
}

async function apiRequest(path, options = {}) {
    try {
        const res = await fetch(`${API}${path}`, options);
        const text = await res.text();
        let payload = {};
        if (text) {
            try {
                payload = JSON.parse(text);
            } catch (e) {
                payload = { raw: text };
            }
        }
        if ((res.status === 401 || res.status === 403) && isAuthRedirectReason(payload)) {
            redirectToLogin();
            return null;
        }
        return payload;
    } catch (e) {
        console.error(`API error ${path}:`, e);
        return null;
    }
}

async function apiGet(path) {
    return apiRequest(path);
}

async function apiPost(path, body) {
    return apiRequest(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
    });
}

async function apiPut(path, body) {
    return apiRequest(path, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
    });
}

async function apiDelete(path) {
    return apiRequest(path, { method: "DELETE" });
}

function handleGlobalSearchKey(event) {
    if (event.key === "Enter") {
        event.preventDefault();
        runGlobalSearch();
    }
}

function searchTypeLabel(type) {
    return ({
        ticket: "Ticket",
        ticket_note: "Ticket Note",
        agent: "Agent",
        change: "Approval Gate",
        postmortem: "Postmortem",
        workflow: "Workflow",
        cicd: "CI/CD",
        tool: "Tool",
        audit: "Audit",
    })[type] || type;
}

let globalSearchState = { query: "", results: [], type: "", status: "", sort: "updated_at:desc" };

function renderSearchResult(item) {
    const meta = item.metadata || {};
    const chips = [
        item.status ? `status: ${item.status}` : "",
        meta.priority ? `priority: ${meta.priority}` : "",
        meta.ticket_id ? `ticket #${meta.ticket_id}` : "",
        meta.provider_ref ? `provider: ${meta.provider_ref}` : "",
        item.updated_at ? formatTime(item.updated_at) : "",
    ].filter(Boolean);
    return `
        <div class="search-result-item" onclick="openGlobalSearchResult(${escAttr(JSON.stringify(item))})">
            <div class="search-result-head">
                <div>
                    <div class="search-result-type">${escHtml(searchTypeLabel(item.type))}</div>
                    <div class="search-result-title">${escHtml(item.title || "Result")}</div>
                </div>
                ${item.status ? `<span class="status-badge ${statusClass(item.status)}">${escHtml(item.status)}</span>` : ""}
            </div>
            ${item.snippet ? `<div class="search-result-snippet">${escHtml(item.snippet)}</div>` : ""}
            ${chips.length ? `<div class="search-result-meta">${chips.map(c => `<span>${escHtml(c)}</span>`).join("")}</div>` : ""}
        </div>
    `;
}

function renderGlobalSearchResults() {
    let results = [...(globalSearchState.results || [])];
    const type = document.getElementById("global-search-type-filter")?.value || globalSearchState.type || "";
    const status = document.getElementById("global-search-status-filter")?.value || globalSearchState.status || "";
    const sort = document.getElementById("global-search-sort")?.value || globalSearchState.sort || "updated_at:desc";
    if (type) results = results.filter(item => item.type === type);
    if (status) results = results.filter(item => String(item.status || "").toLowerCase() === status.toLowerCase());
    const [key, dir] = sort.split(":");
    results.sort((a, b) => {
        const av = key === "type" ? searchTypeLabel(a.type) : key === "title" ? a.title : a.updated_at;
        const bv = key === "type" ? searchTypeLabel(b.type) : key === "title" ? b.title : b.updated_at;
        const cmp = key === "updated_at"
            ? (Date.parse(av || "") || 0) - (Date.parse(bv || "") || 0)
            : String(av || "").localeCompare(String(bv || ""), undefined, { numeric: true, sensitivity: "base" });
        return dir === "asc" ? cmp : -cmp;
    });
    const grid = document.getElementById("global-search-results-grid");
    const count = document.getElementById("global-search-visible-count");
    if (count) count.textContent = `${results.length} shown`;
    if (grid) grid.innerHTML = results.length
        ? results.map(renderSearchResult).join("")
        : '<div class="learning-empty">No matching records found within your filter.</div>';
}

async function runGlobalSearch() {
    const input = document.getElementById("global-search-input");
    const query = (input?.value || "").trim();
    if (query.length < 2) {
        alert("Search needs at least 2 characters.");
        return;
    }
    const data = await apiGet(`/api/search/global?q=${encodeURIComponent(query)}&limit=60`);
    if (!data) return;
    globalSearchState = { query, results: data.results || [], type: "", status: "", sort: "updated_at:desc" };
    const groups = Object.entries(data.groups || {}).map(([type, count]) => `${searchTypeLabel(type)} ${count}`).join(" / ");
    const types = [...new Set((data.results || []).map(item => item.type).filter(Boolean))].sort();
    const statuses = [...new Set((data.results || []).map(item => item.status).filter(Boolean))].sort();
    document.getElementById("modal-title").textContent = `Global Search`;
    document.getElementById("modal-body").innerHTML = `
        <div class="search-results-header">
            <div>
                <div class="section-title">Results for "${escHtml(query)}"</div>
                <div class="learning-meta"><span id="global-search-visible-count">${(data.results || []).length} shown</span> of ${data.total || 0} visible results${groups ? ` / ${escHtml(groups)}` : ""}</div>
            </div>
            <div class="search-filter-bar">
                <select id="global-search-type-filter" class="filter-select" onchange="renderGlobalSearchResults()">
                    <option value="">All types</option>
                    ${types.map(type => `<option value="${escAttr(type)}">${escHtml(searchTypeLabel(type))}</option>`).join("")}
                </select>
                <select id="global-search-status-filter" class="filter-select" onchange="renderGlobalSearchResults()">
                    <option value="">All statuses</option>
                    ${statuses.map(status => `<option value="${escAttr(status)}">${escHtml(status)}</option>`).join("")}
                </select>
                <select id="global-search-sort" class="filter-select" onchange="renderGlobalSearchResults()">
                    <option value="updated_at:desc">Newest</option>
                    <option value="updated_at:asc">Oldest</option>
                    <option value="type:asc">Type</option>
                    <option value="title:asc">Title A-Z</option>
                </select>
            </div>
        </div>
        <div class="search-result-grid" id="global-search-results-grid">
            ${(data.results || []).length ? (data.results || []).map(renderSearchResult).join("") : '<div class="learning-empty">No matching records found within your access scope.</div>'}
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

function openGlobalSearchResult(item) {
    closeModal("ticket-modal");
    if (!item || !item.type) return;
    if (item.type === "ticket" || item.type === "ticket_note") {
        const ticketId = item.type === "ticket" ? item.id : item.metadata?.ticket_id;
        if (ticketId) viewTicket(ticketId);
        return;
    }
    if (item.type === "postmortem") {
        navigateTo("postmortems");
        viewPostmortem(item.id);
        return;
    }
    if (item.type === "workflow") {
        navigateTo("workflows");
        viewWorkflow(item.id);
        return;
    }
    if (item.type === "cicd") {
        navigateTo("cicd");
        viewCicdRun(item.id);
        return;
    }
    if (item.type === "audit") {
        navigateTo("audit");
        const text = document.getElementById("audit-filter-text");
        if (text) text.value = item.metadata?.target || item.title || "";
        loadAudit();
        return;
    }
    if (item.type === "change") {
        navigateTo("changes");
        return;
    }
    if (item.type === "agent") {
        navigateTo("agents");
        return;
    }
    if (item.type === "tool") {
        navigateTo("tools");
        return;
    }
}

async function loadCurrentIdentity() {
    const label = document.getElementById("current-user-label");
    if (!label) return;
    const me = await apiGet("/api/access/me");
    if (!me || !me.identity) {
        label.textContent = "Unknown";
        return;
    }
    label.textContent = me.identity.display_name || me.identity.username || "Unknown";
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

function formatDuration(seconds) {
    const value = Math.max(0, Math.floor(Number(seconds) || 0));
    if (value < 60) return `${value}s`;
    const minutes = Math.floor(value / 60);
    if (minutes < 60) return `${minutes}m ${value % 60}s`;
    const hours = Math.floor(minutes / 60);
    if (hours < 48) return `${hours}h ${minutes % 60}m`;
    const days = Math.floor(hours / 24);
    return `${days}d ${hours % 24}h`;
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

async function loadDashboardStats() {
    const [data, metrics, agentData] = await Promise.all([
        apiGet("/api/dashboard/stats"),
        apiGet("/api/dashboard/ops-metrics"),
        apiGet("/api/agents"),
    ]);
    if (!data) return;

    // Update stat cards
    setText("stat-ticket-total", data.tickets?.total || 0);
    setText("stat-ticket-new", (data.tickets?.new || 0) + (data.tickets?.assigned || 0));
    const openAgents = agentData?.agents
        ? computeAgentLifecycleCounts(agentData.agents).open
        : agentOpenCountFromStats(data.agents);
    setAgentOpenCount(openAgents);
    setText("stat-change-pending", data.changes?.pending || 0);

    // Update charts
    updateTicketTrendChart(data.tickets?.trend || []);
    updateAgentDistChart(data.agents || {});

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
    setAgentOpenCount(openAgents);
    setText("change-count", data.changes?.pending || 0);

    // Load pending changes section
    loadPendingChanges();
    renderOpsMetrics(metrics);
}

function renderOpsMetrics(metrics) {
    if (!metrics) return;
    const agent = metrics.agent_summary || {};
    const sla = metrics.sla || {};
    const postmortemSla = metrics.postmortem_sla || {};
    const gates = metrics.approval_gates || {};
    const autoEvents = (metrics.auto_assignment || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
    setText("metric-agent-work", formatDuration(agent.avg_work_seconds || 0));
    setText("metric-agent-work-sub", `${agent.completed || 0}/${agent.tasks || 0} completed, avg gated ${formatDuration(agent.avg_gate_wait_seconds || 0)}`);
    setText("metric-sla", `${sla.compliance_pct ?? 0}%`);
    setText("metric-sla-sub", `${sla.breached_sla || 0} ticket breached, ${postmortemSla.missing_postmortem || 0} PM missing`);
    setText("metric-gates", `${gates.pending || 0} pending`);
    setText("metric-gates-sub", `${gates.completed || 0} completed, avg wait ${formatDuration(gates.avg_wait_seconds || 0)}`);
    setText("metric-automation", String(autoEvents));
    setText("metric-automation-sub", `${metrics.workflows?.active || 0} active workflows, ${metrics.tool_health?.healthy || 0}/${metrics.tool_health?.tools || 0} tools healthy`);

    const taskEl = document.getElementById("agent-task-metrics");
    if (taskEl) {
        const rows = metrics.agent_by_task_type || [];
        taskEl.innerHTML = rows.length ? `
            <div class="agent-task-runtime-grid">
                ${rows.map(row => `
                    <div class="agent-task-runtime-card">
                        <div class="agent-task-name">${escHtml(agentTaskMetricLabel(row.task_type || "task"))}</div>
                        <div class="agent-task-main">
                            <span class="agent-task-value">${formatDuration(row.avg_work_seconds || 0)}</span>
                            <span class="agent-task-label">avg work time</span>
                        </div>
                        <div class="agent-task-stats">
                            <span><strong>${row.completed_tasks || 0}</strong> completed</span>
                            <span><strong>${row.total_tasks || 0}</strong> task runs</span>
                            <span title="95th percentile working time: 95% of completed task runs of this type finished at or below this time."><strong>${formatDuration(row.p95_work_seconds || 0)}</strong> 95% under</span>
                        </div>
                    </div>
                `).join("")}
            </div>
        ` : '<div class="learning-meta">No agent task metrics yet.</div>';
    }
    const slaEl = document.getElementById("sla-tool-metrics");
    if (slaEl) {
        const cicd = metrics.cicd || [];
        slaEl.innerHTML = `
            <div class="metric-row"><span>Open tickets</span><strong>${sla.open_tickets || 0}</strong><span>${sla.within_sla || 0} within SLA</span></div>
            <div class="metric-row"><span>Postmortems</span><strong>${postmortemSla.total_postmortems || 0}</strong><span>${postmortemSla.within_sla || 0}/${postmortemSla.tickets_requiring_postmortem || 0} within ${postmortemSla.target_hours || 24}h</span><span>${postmortemSla.compliance_pct ?? 0}% SLA</span></div>
            <div class="metric-row"><span>Workflow runs</span><strong>${metrics.workflows?.runs?.completed || 0}</strong><span>${metrics.workflows?.runs?.failed || 0} failed</span></div>
            <div class="metric-row"><span>CI/CD runs</span><strong>${cicd.reduce((s, r) => s + Number(r.count || 0), 0)}</strong><span class="metric-status-list">${renderMetricStatusList(cicd)}</span></div>
            <div class="metric-row"><span>Tools</span><strong>${metrics.tool_health?.healthy || 0}/${metrics.tool_health?.tools || 0}</strong><span>${metrics.tool_health?.down || 0} down</span></div>
        `;
    }
}

function agentTaskMetricLabel(taskType) {
    const labels = {
        ticket_resolution: "Ticket resolution",
        ticket_resolution_continuation: "Ticket continuation",
        postmortem: "Postmortem agent task",
        workflow_build: "Workflow build",
        workflow_rerun: "Workflow rerun",
        ad_hoc: "Ad hoc task",
        source_self_repair_smoke: "Source self-repair",
        source_self_repair_smoke_hardened: "Source self-repair hardened",
    };
    return labels[taskType] || String(taskType || "task").replace(/_/g, " ");
}

function renderMetricStatusList(rows) {
    if (!rows || rows.length === 0) return "none";
    return rows.map(row => {
        const status = row.status || "unknown";
        return `<span class="metric-status-chip ${statusClass(status)}">${escHtml(status)} <strong>${Number(row.count || 0)}</strong></span>`;
    }).join("");
}

function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function decodeHtmlEntities(text) {
    return String(text || "")
        .replace(/&nbsp;/gi, " ")
        .replace(/&amp;/gi, "&")
        .replace(/&lt;/gi, "<")
        .replace(/&gt;/gi, ">")
        .replace(/&quot;/gi, '"')
        .replace(/&#39;|&apos;/gi, "'")
        .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
        .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)));
}

function cleanTicketDescription(value) {
    const raw = String(value || "");
    if (!raw) return "";
    return decodeHtmlEntities(raw)
        .replace(/<\s*br\s*\/?>/gi, "\n")
        .replace(/<\/\s*(p|div|li|tr|h[1-6])\s*>/gi, "\n")
        .replace(/<[^>]*>/g, "")
        .replace(/\r/g, "")
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
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

function ticketQueryKey(status) {
    return JSON.stringify({
        status,
        q: document.getElementById("ticket-filter-text")?.value || "",
        provider: document.getElementById("ticket-filter-provider")?.value || "",
        agent_state: document.getElementById("ticket-filter-agent")?.value || "",
        sort_by: ticketSort.by,
        sort_dir: ticketSort.dir,
    });
}

function updateTicketPagination() {
    const statusEl = document.getElementById("ticket-page-status");
    const moreBtn = document.getElementById("ticket-load-more");
    if (!statusEl || !moreBtn) return;
    const loaded = ticketListState.rows.length;
    const total = ticketListState.total || loaded;
    statusEl.textContent = ticketListState.loading
        ? `Loading tickets... ${loaded}${total ? ` of ${total}` : ""}`
        : `Showing ${loaded} of ${total} tickets`;
    moreBtn.style.display = !ticketListState.done && loaded > 0 ? "" : "none";
    moreBtn.disabled = ticketListState.loading;
}

function renderTicketRows(rows) {
    const tbody = document.getElementById("tickets-tbody");
    if (!tbody) return;
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="loading">No tickets found</td></tr>';
        updateTicketPagination();
        return;
    }
    tbody.innerHTML = rows.map(t => {
        const isSynced = !!t.synced_at;
        const sourceBadge = isSynced
            ? `<span class="source-badge itop" title="Synced from iTop">iTop</span>`
            : `<span class="source-badge local" title="Local">Local</span>`;
        return `
        <tr data-itop-ref="${escAttr(t.itop_ref)}" class="${DEMO_TICKET_ORDER.has(Number(t.id)) ? "demo-ticket-row" : ""}">
            <td>${t.id}</td>
            <td class="ticket-title-cell" title="${escAttr(t.title)}">
                ${sourceBadge}
                ${DEMO_TICKET_ORDER.has(Number(t.id)) ? '<span class="source-badge demo">Demo</span>' : ""}
                ${t.external_url ? `<a class="ticket-link" href="${escAttr(t.external_url)}" target="_blank" rel="noopener">${escHtml(t.title)}</a>` : escHtml(t.title)}
            </td>
            <td><span class="class-badge">${escHtml(t.itop_class || "Incident")}</span></td>
            <td><span class="status-badge ${statusClass(t.status)}">${escHtml(t.status)}</span></td>
            <td>${escHtml(t.priority || "-")}</td>
            <td>${escHtml(t.assignee || "-")}</td>
            <td>${t.agent_status ? `<span class="status-badge ${statusClass(t.agent_status)}">${escHtml(t.agent_status)}</span>` : "-"}</td>
            <td>${formatTime(t.updated_at)}</td>
            <td class="row-actions">
                <button class="btn btn-sm" onclick="viewTicket(${t.id})">Detail</button>
                ${!t.agent_status ? `<button class="btn btn-sm btn-success" onclick="assignAgent(${t.id})">Assign Agent</button>` : ""}
            </td>
        </tr>
        `;
    }).join("");
    updateTicketPagination();
}

// Load tickets
async function loadTickets(options = {}) {
    const status = document.getElementById("ticket-filter-status")?.value || "";
    const q = document.getElementById("ticket-filter-text")?.value.trim() || "";
    const provider = document.getElementById("ticket-filter-provider")?.value || "";
    const agentState = document.getElementById("ticket-filter-agent")?.value || "";
    const key = ticketQueryKey(status);
    const append = !!options.append && key === ticketListState.key && !ticketListState.done;
    if (ticketListState.loading) return;
    if (!append) {
        ticketListState = { key, offset: 0, limit: status === "__demo" ? 5000 : 200, total: 0, loading: false, done: false, rows: [] };
    }
    ticketListState.loading = true;
    updateTicketPagination();
    const params = new URLSearchParams();
    if (status && status !== "__demo") params.set("status", status);
    if (q) params.set("q", q);
    if (provider) params.set("provider", provider);
    if (agentState) params.set("agent_state", agentState);
    params.set("sort_by", ticketSort.by);
    params.set("sort_dir", ticketSort.dir);
    params.set("limit", String(ticketListState.limit));
    params.set("offset", String(ticketListState.offset));

    const data = await apiGet(`/api/tickets?${params}`);
    ticketListState.loading = false;
    if (!data) {
        updateTicketPagination();
        return;
    }
    let incoming = data.tickets || [];
    if (status === "__demo") {
        incoming = incoming
            .filter(t => DEMO_TICKET_ORDER.has(Number(t.id)))
            .sort((a, b) => DEMO_TICKET_ORDER.get(Number(a.id)) - DEMO_TICKET_ORDER.get(Number(b.id)));
    }
    ticketListState.total = status === "__demo" ? incoming.length : Number(data.total || incoming.length);
    ticketListState.offset += incoming.length;
    ticketListState.rows = append ? ticketListState.rows.concat(incoming) : incoming;
    ticketListState.done = status === "__demo" || ticketListState.rows.length >= ticketListState.total || incoming.length < ticketListState.limit;
    renderTicketRows(ticketListState.rows);
}

function loadMoreTickets() {
    loadTickets({ append: true });
}

async function loadWorkflows() {
    const status = document.getElementById("workflow-filter-status")?.value || "";
    const text = document.getElementById("workflow-filter-text")?.value || "";
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    params.set("limit", "250");
    const data = await apiGet(`/api/workflows?${params}`);
    if (!data) return;
    const tbody = document.getElementById("workflows-tbody");
    if (!tbody) return;
    const workflows = sortRows(filterRows(data.workflows || [], text, ["name", "workflow_key", "description", "ticket_class", "status", "review_state"]), "workflows");
    updateGenericSortIndicators("workflows");
    if (workflows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No workflows yet</td></tr>';
        return;
    }
    tbody.innerHTML = workflows.map(w => `
        <tr>
            <td>${w.id}</td>
            <td>
                ${escHtml(w.name)}
                ${w.workflow_key ? `<div class="module-meta">key: ${escHtml(w.workflow_key)}</div>` : ""}
                ${w.description ? `<div class="module-meta">${escHtml(w.description).slice(0, 140)}</div>` : ""}
            </td>
            <td>${escHtml(w.ticket_class || "-")}</td>
            <td>
                <span class="status-badge ${statusClass(w.status)}">${escHtml(workflowStatusLabel(w))}</span>
                <div class="module-meta">${workflowReviewHint(w)}</div>
            </td>
            <td>${w.version || 1}</td>
            <td>${formatTime(w.updated_at)}<div class="module-meta">${w.run_count || 0} runs / ${w.completed_run_count || 0} complete${w.latest_run_at ? ` / last ${formatTime(w.latest_run_at)}` : ""}</div></td>
            <td>
                <div class="workflow-actions">
                    <button class="btn btn-sm btn-detail" onclick="viewWorkflow(${w.id})">Detail</button>
                    ${w.status !== "active" ? `<button class="btn btn-sm btn-approve" onclick="reviewWorkflow(${w.id}, true)">Approve</button>` : ""}
                </div>
            </td>
        </tr>
    `).join("");
}

function workflowStatusLabel(w) {
    if (w.review_state === "active_approved") return "Active";
    if (w.review_state === "active_missing_review") return "Active - review missing";
    if (w.review_state === "tested_needs_approval") return "Tested - approval needed";
    if (w.review_state === "ready_for_review") return "Ready for review";
    return w.status || "draft";
}

function workflowReviewHint(w) {
    if (w.review_state === "active_approved") return `approved by ${escHtml(w.reviewed_by || "reviewer")}`;
    if (w.review_state === "active_missing_review") return "inconsistent: active without reviewed_at";
    if (w.review_state === "tested_needs_approval") return "tested but not active until approved";
    if (w.status === "draft") return "draft, not used for automatic work";
    return escHtml(w.review_state || "");
}

async function loadIntake() {
    const [raci, sessions] = await Promise.all([
        apiGet("/api/intake/raci"),
        apiGet("/api/intake/sessions?limit=25"),
    ]);
    const raciList = document.getElementById("intake-raci-list");
    if (raciList && raci) {
        const rules = raci.rules || [];
        const visibleRules = rules.slice(0, 5);
        raciList.innerHTML = visibleRules.map(rule => `
        <div class="learning-item">
            <div><strong>${escHtml(rule.name)}</strong> <span class="source-badge local">${escHtml(rule.ticket_class)}</span></div>
            <div>${escHtml(rule.assignment_group)} &middot; ${rule.approval_required ? "approval required" : "no approval gate"}</div>
            <div class="learning-meta">R: ${escHtml(rule.responsible)} / A: ${escHtml(rule.accountable)} &middot; auto-agent ${rule.auto_assign_agent ? "on" : "off"}</div>
            <div class="modal-actions-bar inline-actions">
                <button class="inline-link" onclick="editRaciRule(${rule.id})">edit</button>
                <button class="inline-link" onclick="disableRaciRule(${rule.id})">disable</button>
                </div>
            </div>
        `).join("");
        if (rules.length > visibleRules.length) {
            raciList.innerHTML += `<div class="learning-meta">Showing ${visibleRules.length} of ${rules.length} routing rules. Use search or edit from the RACI API for the full list.</div>`;
        }
    }
    const tbody = document.getElementById("intake-sessions-tbody");
    if (tbody && sessions) {
        const statusFilter = document.getElementById("intake-filter-status")?.value || "";
        const text = document.getElementById("intake-filter-text")?.value || "";
        let rows = sessions.sessions || [];
        rows = rows.map(row => ({ ...row, intent: row.classification?.intent || "" }));
        if (statusFilter) rows = rows.filter(row => row.status === statusFilter);
        rows = sortRows(filterRows(rows, text, ["requester_name", "requester_email", "intent", "status", "ticket_id"]), "intake");
        updateGenericSortIndicators("intake");
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
    const auto_assign_agent = confirm("Automatically assign an agent when this rule matches?");
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
        auto_assign_agent,
        auto_agent_model: selectedAgentModel(),
        auto_agent_prompt: auto_assign_agent ? `Auto-work ${assignment_group || "assigned group"} tickets that match ${intent || "this route"} using compact ticket evidence, approval gates, notes, and final closure.` : null,
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
    const auto_assign_agent = confirm("Enable automatic agent assignment for this route?");
    const result = await apiPut(`/api/intake/raci/rules/${id}`, {
        assignment_group,
        responsible: assignment_group,
        priority,
        risk_level,
        auto_assign_agent,
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
    const statusFilter = document.getElementById("cicd-filter-status")?.value || "";
    const text = document.getElementById("cicd-filter-text")?.value || "";
    let rows = data.runs || [];
    if (statusFilter) rows = rows.filter(row => row.status === statusFilter);
    rows = sortRows(filterRows(rows, text, ["provider", "repo_ref", "branch", "status", "ticket_id", "change_id"]), "cicd");
    updateGenericSortIndicators("cicd");
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
                ${row.repo_url || repoExternalUrl(row.provider, row.repo_ref) ? `<a class="inline-link" href="${escAttr(row.repo_url || repoExternalUrl(row.provider, row.repo_ref))}" target="_blank" rel="noopener">repo</a>` : ""}
            </td>
            <td><span class="status-badge ${statusClass(row.status)}">${escHtml(row.status)}</span></td>
            <td>${row.ticket_id ? `<button class="artifact-chip ticket-chip" onclick="viewTicket(${row.ticket_id})">Ticket #${row.ticket_id}</button>` : "-"}</td>
            <td>${row.change_id ? `<button class="artifact-chip change-chip" onclick="navigateTo('changes')">Change #${row.change_id}</button>` : "-"}</td>
            <td>${formatTime(row.created_at)} <button class="artifact-chip finding-chip" onclick="viewCicdRun(${row.id})">Findings</button></td>
        </tr>
    `).join("");
}

function repoExternalUrl(provider, repoRef) {
    const ref = String(repoRef || "");
    if (ref.startsWith("http://") || ref.startsWith("https://")) return ref;
    const configuredBase = window.SOC_DASHBOARD_CONFIG?.gitlabBaseUrl || window.GITLAB_BASE_URL || "";
    if (String(provider || "").toLowerCase() === "gitlab" && ref.includes("/") && configuredBase) {
        return `${String(configuredBase).replace(/\/$/, "")}/${ref}`;
    }
    return "";
}

function severitySummary(findings) {
    const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0, unknown: 0 };
    (Array.isArray(findings) ? findings : []).forEach(f => {
        const sev = String(f.severity || "info").toLowerCase();
        counts[counts[sev] === undefined ? "info" : sev] += 1;
    });
    return Object.entries(counts).map(([k, v]) => `${k}:${v}`).join(" ");
}

function scannerDisplayName(tool) {
    return ({ semgrep: "Semgrep", trivy: "Trivy", owasp_zap: "OWASP ZAP", nuclei: "Nuclei" })[tool] || tool;
}

function findingLocation(finding) {
    const path = finding.path || finding.file || finding.url || finding.package || "";
    const line = finding.start_line || finding.line || finding.line_number || "";
    return `${path}${line ? `:${line}` : ""}`;
}

function renderFindingDetail(finding) {
    const title = finding.title || finding.rule_id || finding.message || "finding";
    const rule = finding.rule_id || finding.check_id || finding.cve || "";
    const message = finding.message || finding.description || finding.remediation || "";
    const location = findingLocation(finding);
    return `
        <div class="finding-detail">
            <div class="finding-row">
                <span class="status-badge ${statusClass(finding.severity || "info")}">${escHtml(finding.severity || "info")}</span>
                <strong>${escHtml(title)}</strong>
            </div>
            ${rule ? `<div class="learning-meta">Rule: <code>${escHtml(rule)}</code></div>` : ""}
            ${location ? `<div class="learning-meta">Location: <code>${escHtml(location)}</code></div>` : ""}
            ${message ? `<pre class="task-output compact-output">${escHtml(message)}</pre>` : ""}
        </div>
    `;
}

function renderReportLinks(links, runId) {
    if (!links.length) {
        return '<div class="learning-meta">No report links recorded. Scanner JSON is still stored in the run record below.</div>';
    }
    return links.map(link => {
        const tool = link.tool || "unknown";
        if (link.internal) {
            return `
                <div class="modal-activity-item">
                    <span>${escHtml(scannerDisplayName(tool))}</span>
                    <button class="ticket-link" onclick="viewCicdScannerReport(${Number(runId)}, '${escAttr(tool)}')">${escHtml(link.label || "dashboard report")}</button>
                </div>
            `;
        }
        return `
            <div class="modal-activity-item">
                <span>${escHtml(scannerDisplayName(tool))}</span>
                <span>
                    <a class="ticket-link" href="${escAttr(link.url)}" target="_blank" rel="noopener">${escHtml(link.label || "provider artifact")}</a>
                    ${link.requires_external_auth ? '<span class="learning-meta">provider login may be required</span>' : ""}
                </span>
            </div>
        `;
    }).join("");
}

function renderScannerSummary(scannerSummary, runId = 0) {
    const entries = Object.entries(scannerSummary || {});
    if (!entries.length) return '<div class="learning-meta">No scanner summary recorded.</div>';
    return entries.map(([tool, summary]) => {
        const findings = summary.findings || [];
        const status = summary.status || "not_recorded";
        return `
            <div class="scanner-card">
                <div class="scanner-card-head">
                    <strong>${escHtml(scannerDisplayName(tool))}</strong>
                    <span>
                        <span class="status-badge ${statusClass(status)}">${escHtml(status)}</span>
                        ${runId && status !== "not_recorded" ? `<button class="inline-link" onclick="viewCicdScannerReport(${Number(runId)}, '${escAttr(tool)}')">open report</button>` : ""}
                    </span>
                </div>
                <div class="learning-meta">${severitySummary(findings)} &middot; ${summary.finding_count || 0} findings</div>
                ${findings.length ? findings.slice(0, 8).map(f => `
                    <div class="finding-row">
                        <span class="status-badge ${statusClass(f.severity || "info")}">${escHtml(f.severity || "info")}</span>
                        <span>${escHtml(f.title || f.rule_id || f.message || "finding")}</span>
                        <code>${escHtml(findingLocation(f))}</code>
                    </div>
                `).join("") : '<div class="learning-meta">Scanner completed with no recorded findings.</div>'}
            </div>
        `;
    }).join("");
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
            <div class="section-title">Policy Gate</div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${escHtml(data.status)}</span></div>
            <div class="detail-row"><span class="detail-label">Repo:</span><span>${escHtml(data.repo_ref || "-")} ${data.repo_url ? `<a class="inline-link" href="${escAttr(data.repo_url)}" target="_blank" rel="noopener">open repo</a>` : ""}</span></div>
            <div class="detail-row"><span class="detail-label">Branch:</span><span>${escHtml(data.branch || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Commit:</span><span>${escHtml(data.commit_sha || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Findings:</span><span>${severitySummary(findings)}</span></div>
            ${data.ticket_id ? `<div class="detail-row"><span class="detail-label">Ticket:</span><span><button class="inline-link" onclick="viewTicket(${data.ticket_id})">#${data.ticket_id}</button></span></div>` : ""}
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Summary:</span><pre class="task-output">${escHtml(data.summary || "")}</pre></div>
        </div>
        <div class="modal-section">
            <div class="section-title">Scanner Results</div>
            ${renderScannerSummary(data.scanner_summary || {}, data.id)}
        </div>
        <div class="modal-section">
            <div class="section-title">Reports & Raw Payload</div>
            ${renderReportLinks(links, data.id)}
            <pre class="task-output">${escHtml(JSON.stringify({ findings, tool_results: data.tool_results || {} }, null, 2))}</pre>
        </div>
        <div class="modal-section">
            <div class="section-title">Before / After Runs</div>
            ${related.length ? related.map(r => `<div class="modal-activity-item"><span>#${r.id}</span><span>${formatDate(r.created_at)} <span class="status-badge ${statusClass(r.status)}">${escHtml(r.status)}</span> ${severitySummary(r.findings || [])}</span></div>`).join("") : '<div class="learning-meta">No related before/after runs recorded yet.</div>'}
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function viewCicdScannerReport(runId, tool) {
    const data = await apiGet(`/api/cicd/runs/${runId}/reports/${encodeURIComponent(tool)}`);
    if (!data || data.error) {
        alert(data?.error || "Unable to load scanner report");
        return;
    }
    const findings = Array.isArray(data.findings) ? data.findings : [];
    const externalLinks = data.external_links || [];
    document.getElementById("modal-title").textContent = `${scannerDisplayName(data.tool)} Report for CI/CD Run #${data.run_id}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Dashboard Scanner Report</div>
            <div class="detail-row"><span class="detail-label">Scanner:</span><span>${escHtml(scannerDisplayName(data.tool))}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${escHtml(data.status || "unknown")}</span></div>
            <div class="detail-row"><span class="detail-label">Findings:</span><span>${severitySummary(findings)} &middot; ${data.finding_count || 0} total</span></div>
            <div class="learning-meta">${escHtml(data.note || "")}</div>
        </div>
        <div class="modal-section">
            <div class="section-title">Findings</div>
            ${findings.length ? findings.map(renderFindingDetail).join("") : '<div class="learning-meta">No findings recorded for this scanner.</div>'}
        </div>
        <div class="modal-section">
            <div class="section-title">Provider Artifacts</div>
            ${externalLinks.length ? renderReportLinks(externalLinks, data.run_id) : '<div class="learning-meta">No external provider artifact links recorded for this scanner.</div>'}
        </div>
        <div class="modal-section">
            <div class="section-title">Raw Scanner Result</div>
            <pre class="task-output">${escHtml(JSON.stringify(data.result || {}, null, 2))}</pre>
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
    await loadKnowledge();
}

function setLearningTab(tab) {
    const activeTab = tab === "skills" ? "skills" : "knowledge";
    ["knowledge", "skills"].forEach(name => {
        const button = document.getElementById(`learning-tab-${name}`);
        const panel = document.getElementById(`learning-panel-${name}`);
        const active = name === activeTab;
        if (button) {
            button.classList.toggle("active", active);
            button.setAttribute("aria-selected", active ? "true" : "false");
        }
        if (panel) panel.classList.toggle("active", active);
    });
}

async function loadAccess() {
    const [me, users, policy, rolesData] = await Promise.all([
        apiGet("/api/access/me"),
        apiGet("/api/access/users"),
        apiGet("/api/access/policies"),
        apiGet("/api/access/roles"),
    ]);
    const meEl = document.getElementById("access-me");
    if (meEl && me) {
        meEl.innerHTML = `
                <div class="learning-item">
                    <div><strong>${escHtml(me.identity?.username || "-")}</strong></div>
                    <div>${escHtml(me.identity?.provider || "local")} / ${escHtml(me.identity?.auth_mode || "disabled")}</div>
                <div class="learning-meta">${escHtml(normalizeList(me.roles).join(", ") || "no roles")}</div>
            </div>
        `;
    }
    const policyEl = document.getElementById("access-policy");
    if (policyEl && policy) {
        policyEl.innerHTML = renderAccessPolicy(policy);
    }
    const tbody = document.getElementById("access-users-tbody");
    if (tbody && users) {
        const roleNames = (rolesData?.roles || []).map(r => r.name).filter(Boolean);
        setSelectOptions("access-user-role-filter", roleNames, document.getElementById("access-user-role-filter")?.value || "");
        const roleFilter = document.getElementById("access-user-role-filter")?.value || "";
        const text = document.getElementById("access-user-filter")?.value || "";
        let rows = users.users || [];
        if (roleFilter) rows = rows.filter(u => normalizeList(u.roles).includes(roleFilter));
        rows = sortRows(filterRows(rows, text, ["username", "display_name", "email", "provider", "roles"]), "access");
        updateGenericSortIndicators("access");
        if (rows.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" class="loading">No dashboard users match the current filter</td></tr>';
        } else {
            tbody.innerHTML = rows.map(u => `
                <tr>
                    <td>${u.id}</td>
                    <td>${escHtml(u.display_name || u.username)}<div class="module-meta">${escHtml(u.email || "")}</div></td>
                    <td>${escHtml(u.provider || "local")}</td>
                    <td>${normalizeList(u.roles).map(role => `<span class="profile-chip">${escHtml(role)}</span>`).join("") || '<span class="learning-meta">none</span>'}</td>
                    <td><span class="status-badge ${u.enabled ? "status-enabled" : "status-disabled"}">${u.enabled ? "enabled" : "disabled"}</span></td>
                    <td><button class="btn btn-sm btn-edit" onclick="editUserRoles(${u.id}, '${escJs(normalizeList(u.roles).join(","))}')">Roles</button></td>
                </tr>
            `).join("");
        }
    }
}

function renderAccessPolicy(policy) {
    const view = document.getElementById("access-policy-view")?.value || "summary";
    const query = (document.getElementById("access-policy-filter")?.value || "").trim().toLowerCase();
    const matches = value => !query || String(value || "").toLowerCase().includes(query);
    if (view === "roles") {
        const rows = Object.entries(policy.role_capabilities || {})
            .filter(([role, caps]) => matches(role) || matches((caps || []).join(" ")));
        return rows.length ? rows.map(([role, caps]) => `
            <div class="learning-item policy-row">
                <div><strong>${escHtml(role)}</strong></div>
                <div class="policy-chip-list">${(caps || []).map(cap => `<span class="policy-chip">${escHtml(cap)}</span>`).join("")}</div>
            </div>
        `).join("") : '<div class="learning-empty">No role capabilities match the filter.</div>';
    }
    if (view === "routes") {
        const rows = (policy.route_requirements || [])
            .filter(row => matches(row.method) || matches(row.path) || matches(row.permission));
        return rows.length ? rows.map(row => `
            <div class="learning-item policy-row">
                <div><strong>${escHtml(row.method)}</strong> ${escHtml(row.path)}</div>
                <div class="learning-meta">Requires ${escHtml(row.permission)}</div>
            </div>
        `).join("") : '<div class="learning-empty">No route requirements match the filter.</div>';
    }
    if (view === "vault") {
        const broker = policy.credential_broker || {};
        return `
            <div class="learning-item policy-row">
                <div><strong>Vault broker</strong> <span class="source-badge local">${escHtml(broker.vault_provider || "configured")}</span></div>
                <div>${escHtml(policy.agent_vault_boundary || "")}</div>
                <div class="learning-meta">Resolver: ${escHtml(broker.resolver_mode || "-")} / secret values returned: ${broker.secret_values_returned ? "yes" : "no"}</div>
            </div>
            <div class="learning-item policy-row">
                <div><strong>Workflow preapproval</strong></div>
                <div>${escHtml(policy.workflow_preapproved_leases || "")}</div>
            </div>
        `;
    }
    return `
        <div class="learning-item policy-row">
            <div><strong>${escHtml(policy.auth_mode)}</strong> <span class="source-badge local">${escHtml(policy.enforcement)}</span></div>
            <div>Roles: ${escHtml(Object.keys(policy.role_capabilities || {}).join(", "))}</div>
            <div class="learning-meta">Trusted proxy headers require a shared secret; WebSockets use signed HttpOnly sessions.</div>
        </div>
        <div class="learning-item policy-row">
            <div><strong>Agent permission boundary</strong></div>
            <div>${escHtml(policy.agent_permission_boundary || "")}</div>
        </div>
    `;
}

async function editUserRoles(userId, currentRolesCsv) {
    const rolesData = await apiGet("/api/access/roles");
    const available = (rolesData?.roles || []).map(r => r.name).filter(Boolean);
    const current = currentRolesCsv || "";
    const next = prompt(`Roles for user ${userId}. Available: ${available.join(", ")}`, current);
    if (next === null) return;
    const roles = next.split(",").map(v => v.trim()).filter(Boolean);
    const invalid = roles.filter(role => !available.includes(role));
    if (invalid.length) {
        alert(`Unknown roles: ${invalid.join(", ")}`);
        return;
    }
    const result = await apiPost(`/api/access/users/${userId}/roles`, roles);
    if (result?.error) alert(result.error);
    loadAccess();
}

async function loadPostmortems() {
    const data = await apiGet("/api/postmortems?limit=100");
    const tbody = document.getElementById("postmortems-tbody");
    if (!data || !tbody) return;
    renderPostmortemRows(tbody, data.postmortems || [], true);
}

async function loadPostmortemsPage() {
    const status = document.getElementById("postmortem-filter-status")?.value || "";
    const text = document.getElementById("postmortem-filter-text")?.value || "";
    const params = new URLSearchParams({ limit: "250" });
    if (status) params.set("status", status);
    const data = await apiGet(`/api/postmortems?${params}`);
    const tbody = document.getElementById("postmortems-page-tbody");
    if (!data || !tbody) return;
    const rows = sortRows(filterRows(data.postmortems || [], text, ["summary", "status", "ticket_title", "ticket_id", "root_cause", "improvements"]), "postmortems");
    updateGenericSortIndicators("postmortems");
    renderPostmortemRows(tbody, rows, false);
}

function renderPostmortemRows(tbody, rows, compact) {
    if (rows.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No postmortems yet</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(p => `
        <tr>
            <td>${p.id}</td>
            <td>${p.ticket_id ? `<button class="inline-link" onclick="viewTicket(${p.ticket_id})">#${p.ticket_id}</button>` : "-"} ${escHtml(p.ticket_title || "")}</td>
            <td><span class="status-badge ${statusClass(p.status)}">${learningStatusLabel(p.status)}</span><div class="module-meta">${learningStatusHint(p.status)}</div></td>
            <td class="postmortem-summary-cell" style="max-width:${compact ? "360" : "560"}px">${escHtml(p.summary || "-")}</td>
            <td>${formatTime(p.updated_at || p.created_at)}</td>
            <td>
                <div class="table-actions">
                    <button class="btn btn-sm btn-detail" onclick="viewPostmortem(${p.id})">Full</button>
                    ${p.status === "approved" || p.status === "ready_for_review" ? `<button class="btn btn-sm btn-promote" onclick="promotePostmortem(${p.id})">Promote</button>` : ""}
                    ${p.status !== "approved" && p.status !== "promoted" ? `<button class="btn btn-sm btn-approve" onclick="reviewPostmortem(${p.id}, true)">Approve</button>` : ""}
                    <button class="btn btn-sm btn-audit" onclick="openAuditTrail('postmortem_${p.id}')">Audit</button>
                </div>
            </td>
        </tr>
    `).join("");
}

function learningStatusLabel(status) {
    return ({
        draft: "Draft",
        ready_for_review: "Ready for review",
        approved: "Approved",
        promoted: "Assets created",
        needs_revision: "Needs revision",
    })[status] || escHtml(status || "draft");
}

function learningStatusHint(status) {
    return ({
        draft: "agent draft, not reviewed",
        ready_for_review: "waiting for human approval",
        approved: "approved; assets can be created",
        promoted: "knowledge/workflow/skills already generated",
        needs_revision: "sent back for edits",
    })[status] || "";
}

async function reviewPostmortem(id, approved) {
    const review_notes = prompt(approved ? "Approval notes:" : "Revision notes:", "");
    if (review_notes === null) return;
    const result = await apiPost(`/api/postmortems/${id}/review`, { approved, review_notes, reviewed_by: "dashboard" });
    if (result?.error) alert(result.error);
    loadLearning();
}

async function promotePostmortem(postmortemId) {
    const ok = confirm("Promote or update reusable assets from this postmortem? Existing workflows with the same operational key will be updated, not duplicated.");
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
        alert(`Postmortem promoted. KB ${result.knowledge_article_id || "none"}, workflow ${result.workflow_id || "none"} (${result.workflow_action || "n/a"}), key ${result.workflow_key || "none"}, skills ${(result.skill_ids || []).join(", ") || "none"}.`);
        loadLearning();
        loadPostmortemsPage();
    } else {
        alert(result?.error || "Postmortem promotion failed");
    }
}

async function loadSkillsData() {
    const data = await apiGet("/api/skills?enabled_only=false");
    if (!data) return [];
    skillsCache = data.skills || [];
    return skillsCache;
}

function profileSkillAssignments(skill) {
    const profiles = agentRuntimeConfig.profiles || [];
    return profiles
        .filter(profile => Array.isArray(profile.skills) && profile.skills.includes(skill.name))
        .map(profile => profile.name || profile.id);
}

async function loadSkillsPage() {
    const skills = await loadSkillsData();
    const tbody = document.getElementById("skills-tbody");
    const summary = document.getElementById("skills-summary");
    if (!tbody) return;
    setSelectOptions("skills-filter-category", skills.map(s => s.category || "general"), document.getElementById("skills-filter-category")?.value || "");
    const status = document.getElementById("skills-filter-status")?.value || "";
    const category = document.getElementById("skills-filter-category")?.value || "";
    const text = document.getElementById("skills-filter-text")?.value || "";
    const [sortKey, sortDir] = (document.getElementById("skills-sort")?.value || "name:asc").split(":");
    tableSortState.skills = { key: sortKey, dir: sortDir || "asc" };
    let rows = skills;
    if (category) rows = rows.filter(s => (s.category || "general") === category);
    if (status === "enabled") rows = rows.filter(s => s.enabled);
    if (status === "disabled") rows = rows.filter(s => !s.enabled);
    if (status === "global") rows = rows.filter(s => s.assigned_to_all);
    if (status === "profile") rows = rows.filter(s => profileSkillAssignments(s).length > 0);
    rows = sortRows(filterRows(rows, text, ["name", "description", "category", "prompt_template"]), "skills");
    updateGenericSortIndicators("skills");
    if (summary) {
        const enabled = skills.filter(s => s.enabled).length;
        const global = skills.filter(s => s.assigned_to_all).length;
        summary.innerHTML = `
            <span class="summary-pill success">${enabled} enabled</span>
            <span class="summary-pill neutral">${skills.length} total</span>
            <span class="summary-pill info">${global} default/global</span>
            <span class="summary-pill warn">${skills.length - enabled} disabled</span>
            <span class="learning-meta">Profiles with no selected skill boxes inherit every enabled default skill.</span>
        `;
    }
    if (!skills.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No skills configured</td></tr>';
        return;
    }
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="6" class="loading">No skills match the current filter</td></tr>';
        return;
    }
    tbody.innerHTML = rows.map(s => {
        const assignedProfiles = profileSkillAssignments(s);
        return `
            <tr>
                <td>
                    <strong>${escHtml(s.name)}</strong>
                    <div class="module-meta">${escHtml(shortText(s.description || "", 130))}</div>
                </td>
                <td><span class="source-badge skill-category">${escHtml(s.category || "general")}</span></td>
                <td>
                    <span class="status-badge ${s.enabled ? "status-enabled" : "status-disabled"}">${s.enabled ? "enabled" : "disabled"}</span>
                    ${s.assigned_to_all ? '<span class="source-badge default-skill">default</span>' : ""}
                </td>
                <td>${assignedProfiles.length ? assignedProfiles.map(p => `<span class="profile-chip">${escHtml(p)}</span>`).join("") : '<span class="learning-meta">All profiles by default</span>'}</td>
                <td>${formatTime(s.updated_at || s.created_at)}</td>
                <td>
                    <div class="table-actions">
                        <button class="btn btn-sm btn-detail" onclick="viewSkill(${s.id})">View</button>
                        <button class="btn btn-sm btn-edit" onclick="editSkill(${s.id})">Edit</button>
                        <button class="btn btn-sm ${s.enabled ? "btn-warning" : "btn-approve"}" onclick="toggleSkill(${s.id}, ${s.enabled ? "false" : "true"})">${s.enabled ? "Deactivate" : "Activate"}</button>
                    </div>
                </td>
            </tr>
        `;
    }).join("");
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
    const operational = skills
        .filter(s => s.enabled && !isGeneratedLearningSkill(s))
        .sort((a, b) => `${a.category || ""}${a.name || ""}`.localeCompare(`${b.category || ""}${b.name || ""}`));
    const generated = skills
        .filter(s => s.enabled && isGeneratedLearningSkill(s))
        .sort((a, b) => `${a.category || ""}${a.name || ""}`.localeCompare(`${b.category || ""}${b.name || ""}`));
    const disabled = skills
        .filter(s => !s.enabled)
        .sort((a, b) => `${a.category || ""}${a.name || ""}`.localeCompare(`${b.category || ""}${b.name || ""}`));
    const renderSkill = s => `
        <div class="learning-item">
            <div><strong>${escHtml(s.name)}</strong> <span class="source-badge local">${escHtml(s.category || "general")}</span></div>
            <div>${escHtml(s.description || "")}</div>
            <div class="learning-meta">${s.enabled ? "enabled" : "disabled"} ${s.assigned_to_all ? "&middot; global" : ""}</div>
        </div>
    `;
    list.innerHTML = `
        <div class="learning-meta">Operational skills: ${operational.length} enabled · Generated enabled: ${generated.length} · Disabled legacy/test: ${disabled.length}</div>
        ${operational.map(renderSkill).join("") || '<div class="learning-empty">No operational skills enabled</div>'}
        ${generated.length ? `<details class="learning-details"><summary>Generated skills still enabled (${generated.length})</summary>${generated.map(renderSkill).join("")}</details>` : ""}
        ${disabled.length ? `<details class="learning-details"><summary>Disabled legacy/test skills (${disabled.length})</summary>${disabled.map(renderSkill).join("")}</details>` : ""}
    `;
}

function isGeneratedLearningSkill(skill) {
    const name = String(skill?.name || "").toLowerCase();
    const category = String(skill?.category || "").toLowerCase();
    if (name === "postmortem-builder" || name === "workflow-builder") return false;
    return name.startsWith("postmortem-") || name.startsWith("smoke-skill-") || category === "smoke";
}

async function loadKnowledge() {
    const data = await apiGet("/api/knowledge?limit=50");
    const list = document.getElementById("knowledge-list");
    if (!data || !list) return;
    let articles = data.articles || [];
    knowledgeCache = articles;
    setSelectOptions("knowledge-filter-category", articles.map(a => a.category || "general"), document.getElementById("knowledge-filter-category")?.value || "");
    const category = document.getElementById("knowledge-filter-category")?.value || "";
    const text = document.getElementById("knowledge-filter-text")?.value || "";
    const [sortKey, sortDir] = (document.getElementById("knowledge-sort")?.value || "updated_at:desc").split(":");
    if (category) articles = articles.filter(a => (a.category || "general") === category);
    articles = filterRows(articles, text, ["title", "body", "category"]);
    articles = [...articles].sort((a, b) => {
        const av = sortKey.includes("_at") ? Date.parse(a[sortKey] || a.created_at || "") || 0 : String(a[sortKey] || "").toLowerCase();
        const bv = sortKey.includes("_at") ? Date.parse(b[sortKey] || b.created_at || "") || 0 : String(b[sortKey] || "").toLowerCase();
        const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
        return (sortDir || "desc") === "asc" ? cmp : -cmp;
    });
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
    const text = document.getElementById("change-filter-text")?.value || "";
    const params = status ? `?status=${status}` : "";

    const data = await apiGet(`/api/changes${params}`);
    if (!data) return;

    const tbody = document.getElementById("changes-tbody");
    if (!tbody) return;

    const changes = sortRows(filterRows(data.changes || [], text, ["action", "target", "status", "ticket_title", "ticket_id", "risk_level"]), "changes");
    updateGenericSortIndicators("changes");

    if (changes.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="loading">No change requests</td></tr>';
        return;
    }

    tbody.innerHTML = changes.map(c => `
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
                <div class="table-actions">
                    ${c.status === "pending" ? `
                        <button class="btn btn-sm btn-approve" onclick="approveChange(${c.id})">Approve</button>
                        <button class="btn btn-sm btn-danger" onclick="rejectChange(${c.id})">Reject</button>
                    ` : ""}
                    <button class="btn btn-sm btn-audit" onclick="openAuditTrail('change_${c.id}')">Audit</button>
                </div>
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
    let rows = [
        ...(data.tools || []).map(t => ({
            ...t,
            kind: "active",
            display_status: t.last_check_status || t.status || (t.last_check ? "unknown" : "no_health"),
            has_health: Boolean(t.last_check || t.last_check_status),
            search: [t.name, t.type, t.description, t.host, t.port, t.status, t.last_check_status].join(" "),
        })),
        ...(data.setup_modules || []).map(m => ({
            ...m,
            kind: "module",
            type: m.category || "integration",
            display_status: (m.health_checks || []).length ? (m.status || "blueprint") : "no_health",
            has_health: Boolean((m.health_checks || []).length),
            search: [m.name, m.id, m.category, m.status, m.provider_contract, m.skill, (m.health_checks || []).join(" ")].join(" "),
        })),
    ];
    setSelectOptions("tools-filter-type", rows.map(row => row.type || row.category || row.kind), document.getElementById("tools-filter-type")?.value || "");
    const query = document.getElementById("tools-filter-text")?.value || "";
    const status = document.getElementById("tools-filter-status")?.value || "";
    const type = document.getElementById("tools-filter-type")?.value || "";
    const [sortKey, sortDir] = (document.getElementById("tools-sort")?.value || "name:asc").split(":");
    tableSortState.tools = { key: sortKey, dir: sortDir || "asc" };
    if (status) rows = rows.filter(row => row.display_status === status || row.status === status);
    if (type) rows = rows.filter(row => (row.type || row.category || row.kind) === type);
    rows = sortRows(filterRows(rows, query, ["name", "id", "type", "description", "search", "provider_contract", "skill"]), "tools");
    updateGenericSortIndicators("tools");
    grid.innerHTML = rows.map(renderToolCard).join("") || '<div class="tool-empty">No tools or integrations match the current filters</div>';
}

function renderToolCard(row) {
    const name = row.name || row.id || "Provider module";
    const status = row.display_status || row.status || "unknown";
    const noHealth = status === "no_health" || !row.has_health;
    const isBlueprint = row.kind === "module" && (row.status || "").toLowerCase() === "blueprint";
    const cardClass = [
        "tool-card",
        row.kind === "module" ? "integration-card" : "active-tool-card",
        noHealth ? "no-health-card" : "",
        isBlueprint ? "blueprint-card" : "",
    ].filter(Boolean).join(" ");
    const statusLabel = noHealth ? "No active check" : status;
    const healthMeta = row.kind === "module"
        ? ((row.health_checks || []).slice(0, 3).map(escHtml).join(" / ") || "Blueprint/integration item; no running health probe.")
        : (row.last_check ? `Last check ${formatTime(row.last_check)}${row.response_time_ms ? ` / ${row.response_time_ms}ms` : ""}` : "Inventory item; no health result yet.");
    return `
        <div class="${cardClass}">
            <div class="tool-card-header">
                <span class="tool-name">${escHtml(name)}</span>
                <span class="tool-status-group">
                    ${noHealth ? '<span class="status-badge status-muted">no probe</span>' : `<span class="tool-status-dot ${escAttr(status)}"></span>`}
                    <span class="status-badge ${statusClass(status)}">${escHtml(statusLabel)}</span>
                </span>
            </div>
            <div class="tool-type">${escHtml(row.type || row.category || row.kind || "module")}</div>
            <div class="tool-desc">${escHtml(row.description || row.provider_contract || row.skill || "Provider module")}</div>
            ${row.host ? `<div class="learning-meta">${escHtml(row.host)}:${escHtml(row.port || "N/A")}</div>` : ""}
            <div class="learning-meta">${healthMeta}</div>
        </div>
    `;
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

    let rows = data.audit || [];
    const [sortKey, sortDir] = (document.getElementById("audit-sort")?.value || "created_at:desc").split(":");
    rows = [...rows].sort((a, b) => {
        const av = sortKey === "created_at" ? (Date.parse(a.created_at || "") || 0) : String(a[sortKey] || "").toLowerCase();
        const bv = sortKey === "created_at" ? (Date.parse(b.created_at || "") || 0) : String(b[sortKey] || "").toLowerCase();
        const cmp = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: "base" });
        return (sortDir || "desc") === "asc" ? cmp : -cmp;
    });

    if (rows.length === 0) {
        timeline.innerHTML = '<div class="loading">No audit entries</div>';
        return;
    }

    timeline.innerHTML = rows.map(a => `
        <details class="audit-entry compact-audit-row">
            <summary>
                <span class="audit-time">${formatTime(a.created_at)}</span>
                <span class="source-badge ${a.source === "event" ? "itop" : "local"}">${escHtml(a.source || "audit")}</span>
                ${a.level ? `<span class="status-badge ${statusClass(a.level)}">${escHtml(a.level)}</span>` : ""}
                <span class="audit-action">${escHtml(a.summary || `${a.actor || "system"}: ${a.action || "event"}`)}</span>
                <span class="audit-details">${escHtml(a.category || "")}${a.ticket_id ? ` / ticket ${escHtml(a.ticket_id)}` : ""}${a.agent_id ? ` / agent ${escHtml(a.agent_id)}` : ""}</span>
            </summary>
            <div class="audit-content">
                <div class="audit-links">
                    ${a.ticket_id ? `<button class="inline-link" onclick="viewTicket(${Number(a.ticket_id)})">ticket</button>` : ""}
                    ${a.ticket_id ? `<button class="inline-link" onclick="openAuditTrail('ticket_${escAttr(a.ticket_id)}')">ticket trail</button>` : ""}
                    ${a.agent_id ? `<button class="inline-link" onclick="openAuditTrail('agent_${escAttr(a.agent_id)}')">agent trail</button>` : ""}
                    ${a.target ? `<button class="inline-link" onclick="openAuditTrail('${escJs(a.target)}')">target trail</button>` : ""}
                </div>
                <div class="audit-details">Actor: ${escHtml(a.actor || "-")} / Action: ${escHtml(a.action || "-")} / Target: ${escHtml(a.target || "-")}</div>
                ${a.details ? `<pre class="audit-json">${escHtml(JSON.stringify(a.details, null, 2))}</pre>` : '<div class="learning-meta">No expanded details recorded.</div>'}
            </div>
        </details>
    `).join("");
}

// View ticket detail
async function viewTicket(id) {
    const data = await apiGet(`/api/tickets/${id}`);
    if (!data) return;
    const description = cleanTicketDescription(data.description);

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
            <div class="detail-row"><span class="detail-label">Opened By:</span><span>${escHtml(contactDisplay(data.opened_by_name, data.opened_by_email))}</span></div>
            <div class="detail-row"><span class="detail-label">Requester:</span><span>${escHtml(contactDisplay(data.requester_name, data.requester_email))}</span></div>
            <div class="detail-row"><span class="detail-label">Affected User:</span><span>${escHtml(contactDisplay(data.affected_user_name, data.affected_user_email))}</span></div>
            <div class="detail-row"><span class="detail-label">iTop Ref:</span><span>${data.itop_ref}</span></div>
            <div class="detail-row"><span class="detail-label">Provider:</span><span>${escHtml(data.provider || "itop")} / ${escHtml(data.provider_ref || data.itop_ref || "-")} <span class="status-badge ${statusClass(data.provider_sync_status || "unknown")}">${escHtml(data.provider_sync_status || "unknown")}</span></span></div>
            ${data.external_url ? `<div class="detail-row"><span class="detail-label">External:</span><span><a class="ticket-link" href="${escAttr(data.external_url)}" target="_blank" rel="noopener">${escHtml(data.external_url)}</a></span></div>` : ""}
            <div class="detail-row"><span class="detail-label">Created:</span><span>${formatDate(data.created_at)}</span></div>
            <div class="detail-row"><span class="detail-label">Updated:</span><span>${formatDate(data.updated_at)}</span></div>
            ${description ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Description:</span><span style="white-space:pre-wrap">${escHtml(description)}</span></div>` : ""}
        </div>
        ${agentSection}
        ${changesSection}
        ${actionsBar}
    `;
    document.getElementById("ticket-modal").classList.add("active");

    // Load activity log for this ticket
    loadTicketActivity(id);
}

function jsonBlock(value) {
    if (value === undefined || value === null || value === "") return "";
    if (typeof value === "string") {
        try {
            return JSON.stringify(JSON.parse(value), null, 2);
        } catch (_) {
            return value;
        }
    }
    return JSON.stringify(value, null, 2);
}

function shortText(value, max = 220) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function contactDisplay(name, email) {
    const n = String(name || "").trim();
    const e = String(email || "").trim();
    if (n && e) return `${n} <${e}>`;
    return n || e || "-";
}

function normalizeNoteBody(value) {
    let text = String(value || "").replace(/\r\n/g, "\n").trim();
    const fence = text.match(/^```(?:json|text|markdown)?\s*\n([\s\S]*?)\n```$/i);
    if (fence) text = fence[1].trim();
    return text.replace(/\n{3,}/g, "\n\n");
}

function renderNoteJson(value) {
    const summaryKeys = ["summary", "status", "action", "target", "reason", "result", "error", "output"];
    const rows = summaryKeys
        .filter(key => value && Object.prototype.hasOwnProperty.call(value, key) && value[key] !== null && value[key] !== "")
        .map(key => `
            <div class="note-json-row">
                <span>${escHtml(key.replace(/_/g, " "))}</span>
                <strong>${escHtml(shortText(value[key], 360))}</strong>
            </div>
        `)
        .join("");
    return `
        <div class="note-json-summary">
            ${rows || '<div class="learning-meta">Structured evidence payload</div>'}
            <details>
                <summary>raw payload</summary>
                <pre class="audit-json">${escHtml(JSON.stringify(value, null, 2))}</pre>
            </details>
        </div>
    `;
}

function renderNoteBody(value) {
    const text = normalizeNoteBody(value);
    if (!text) return "";
    try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === "object") return renderNoteJson(parsed);
    } catch (_) {
        // Not JSON; render as readable note text below.
    }
    const markerPattern = /\b[A-Z][A-Z0-9_]{5,}(?:_[A-Z0-9]+)*\b/g;
    return text.split("\n").map(line => {
        const trimmed = line.trim();
        if (!trimmed) return '<div class="note-gap"></div>';
        const safe = escHtml(trimmed).replace(markerPattern, match => `<span class="note-marker">${match}</span>`);
        if (/^[-*]\s+/.test(trimmed)) {
            return `<div class="note-line note-bullet">${safe.replace(/^[-*]\s+/, "")}</div>`;
        }
        if (/^\d+\.\s+/.test(trimmed)) {
            return `<div class="note-line note-step">${safe}</div>`;
        }
        return `<div class="note-line">${safe}</div>`;
    }).join("");
}

function normalizeList(value) {
    if (Array.isArray(value)) return value;
    if (!value) return [];
    if (typeof value === "string") {
        try {
            const parsed = JSON.parse(value);
            if (Array.isArray(parsed)) return parsed;
        } catch {
            return value.split(",").map(item => item.trim()).filter(Boolean);
        }
    }
    return [];
}

function renderEvidenceTiles({ notes, relevant, tasks, changes, postmortems, accessRequests }) {
    const completedTasks = tasks.filter(t => t.status === "completed").length;
    const completedChanges = changes.filter(c => c.status === "completed").length;
    const promotedPostmortems = postmortems.filter(p => ["promoted", "approved", "ready_for_review"].includes(p.status)).length;
    const accessCompleted = accessRequests.filter(a => ["approved", "completed", "resolved"].includes(a.status) || ["approved", "completed"].includes(a.change_status)).length;
    const tiles = [
        ["Notes", notes.length, "human-readable updates"],
        ["Audit", relevant.length, "events linked to ticket"],
        ["Agent Work", `${completedTasks}/${tasks.length}`, "tasks completed"],
        ["Approval Gates", `${completedChanges}/${changes.length}`, "gates completed"],
        ["Access", `${accessCompleted}/${accessRequests.length}`, "requests approved"],
        ["Learning", `${promotedPostmortems}/${postmortems.length}`, "postmortems ready+"],
    ];
    return `
        <div class="evidence-grid">
            ${tiles.map(([label, value, hint]) => `
                <div class="evidence-tile">
                    <span>${escHtml(label)}</span>
                    <strong>${escHtml(value)}</strong>
                    <small>${escHtml(hint)}</small>
                </div>
            `).join("")}
        </div>
    `;
}

function parseDetails(value) {
    if (!value) return {};
    if (typeof value === "object") return value;
    try {
        const parsed = JSON.parse(value);
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
        return {};
    }
}

function eventMs(value) {
    const ms = Date.parse(value || "");
    return Number.isFinite(ms) ? ms : 0;
}

function eventKey(parts) {
    return parts.filter(v => v !== undefined && v !== null && v !== "").join(":");
}

function pushTimelineEvent(events, seen, event) {
    if (!event?.at) return;
    const key = event.key || eventKey([event.kind, event.id, event.at, event.title]);
    if (seen.has(key)) return;
    seen.add(key);
    events.push({ ...event, key });
}

function firstNoteLine(body) {
    return normalizeNoteBody(body).split("\n").map(line => line.trim()).filter(Boolean)[0] || "Ticket note";
}

function noteTitleBody(body) {
    const lines = normalizeNoteBody(body).split("\n").map(line => line.trim()).filter(Boolean);
    if (!lines.length) return { title: "Ticket note", body: "" };
    let title = lines[0];
    const bodyLines = lines.slice(1);
    const colonIndex = title.indexOf(": ");
    if (colonIndex > 0 && title.length > 110) {
        bodyLines.unshift(title.slice(colonIndex + 2).trim());
        title = title.slice(0, colonIndex).trim();
    }
    return {
        title: shortText(title, 150),
        body: bodyLines.join("\n"),
    };
}

function includeNoteInSequence(note) {
    const title = noteTitleBody(note.body).title.toLowerCase();
    if (!title) return false;
    const repetitive = [
        "agent started",
        "agent assigned",
        "agent waiting",
        "agent provider retry scheduled",
        "agent completed with recovered finalization",
        "approval gate opened",
        "approval gate completed",
        "access request opened",
        "provider close failed",
    ];
    if (repetitive.some(prefix => title.startsWith(prefix))) return false;
    if (/^change \d+ completed/.test(title)) return false;
    return true;
}

function includeAuditInSequence(audit) {
    return false;
}

function modelTurnSummary(turn) {
    const details = parseDetails(turn.details);
    const turnIndex = details.turn_index || details.model_turn_index || "?";
    if (turn.action === "agent_model_turn_started") {
        return {
            title: `Model turn ${turnIndex} started`,
            body: "The model began generating from the context it had at this moment. Approvals or notes that land after this point may not be reflected until the next tool result, steering event, or continuation.",
            badge: "model-start",
        };
    }
    const duration = details.duration_seconds ? `${details.duration_seconds}s` : "duration not recorded";
    const toolUse = details.has_tool_use ? "tool call emitted" : "no tool call";
    return {
        title: `Model turn ${turnIndex} finished`,
        body: `${duration}; ${toolUse}; stop reason ${details.stop_reason || "unknown"}.`,
        badge: "model-finish",
    };
}

function buildTicketTimeline({ ticket, notes, relevant, tasks, changes, postmortems, accessRequests, steeringEvents, modelTurns }) {
    const events = [];
    const seen = new Set();
    if (ticket?.created_at) {
        pushTimelineEvent(events, seen, {
            kind: "ticket",
            at: ticket.created_at,
            title: `Ticket created`,
            body: ticket.title || "",
            badge: ticket.status || "ticket",
            key: eventKey(["ticket-created", ticket.id]),
        });
    }
    tasks.forEach(task => {
        pushTimelineEvent(events, seen, {
            kind: "agent",
            at: task.started_at || task.created_at,
            title: `Agent ${task.agent_id || "-"} started ${task.task_type || "task"}`,
            body: `Task #${task.id}; model work begins from this task context.`,
            badge: "agent-start",
            key: eventKey(["task-start", task.id]),
        });
        if (task.completed_at) {
            pushTimelineEvent(events, seen, {
                kind: "agent",
                at: task.completed_at,
                title: `Agent task ${task.id} ${task.status || "completed"}`,
                body: shortText(task.error_message || task.output || "Task completed.", 340),
                badge: task.status || "task",
                key: eventKey(["task-end", task.id, task.status]),
            });
        }
    });
    modelTurns.forEach(turn => {
        const summary = modelTurnSummary(turn);
        const details = parseDetails(turn.details);
        pushTimelineEvent(events, seen, {
            kind: "model",
            at: turn.created_at,
            title: summary.title,
            body: summary.body,
            badge: summary.badge,
            agentId: details.agent_id,
            key: eventKey(["model-turn", turn.source, turn.id, turn.action]),
        });
    });
    changes.forEach(change => {
        pushTimelineEvent(events, seen, {
            kind: "gate",
            at: change.requested_at,
            title: `Approval gate ${change.id} requested`,
            body: `${change.action || "Change"} on ${change.target || "target"}. ${shortText(change.reason || "", 240)}`,
            badge: change.risk_level || "gate",
            key: eventKey(["gate-request", change.id]),
        });
        if (change.approved_at) {
            pushTimelineEvent(events, seen, {
                kind: "gate",
                at: change.approved_at,
                title: `Approval gate ${change.id} ${change.status || "approved"}`,
                body: `Approved by ${change.approved_by || "unknown"}. ${shortText(change.result || "", 260)}`,
                badge: change.status || "approved",
                key: eventKey(["gate-approved", change.id, change.status]),
            });
        }
    });
    accessRequests.forEach(access => {
        pushTimelineEvent(events, seen, {
            kind: "access",
            at: access.created_at,
            title: `Access request ${access.id || access.access_ticket_id || ""}`.trim(),
            body: `${access.permission || "access"} for ${access.resource || access.resource_id || "resource"}. ${shortText(access.reason || "", 240)}`,
            badge: access.status || access.change_status || "access",
            key: eventKey(["access", access.id, access.access_ticket_id]),
        });
    });
    steeringEvents.forEach(steer => {
        pushTimelineEvent(events, seen, {
            kind: "steering",
            at: steer.created_at,
            title: `Agent steering delivered`,
            body: shortText(steer.message || steer.body || steer.summary || "Updated context was delivered without interrupting the original objective.", 320),
            badge: steer.source || "steering",
            key: eventKey(["steering", steer.id]),
        });
    });
    notes.filter(includeNoteInSequence).forEach(note => {
        const noteParts = noteTitleBody(note.body);
        pushTimelineEvent(events, seen, {
            kind: "note",
            at: note.created_at,
            title: noteParts.title,
            body: noteParts.body,
            badge: note.source || "note",
            author: note.author,
            key: eventKey(["note", note.id]),
        });
    });
    postmortems.forEach(postmortem => {
        pushTimelineEvent(events, seen, {
            kind: "learning",
            at: postmortem.created_at,
            title: `Postmortem ${postmortem.id} created`,
            body: shortText(postmortem.summary || postmortem.improvements || "Learning artifact recorded.", 320),
            badge: postmortem.status || "postmortem",
            key: eventKey(["postmortem", postmortem.id]),
        });
    });
    relevant
        .filter(a => a.source !== "note")
        .filter(includeAuditInSequence)
        .forEach(audit => {
            const action = audit.action || "";
            if (action === "agent_model_turn_started" || action === "agent_model_turn_finished") return;
            pushTimelineEvent(events, seen, {
                kind: audit.source || "audit",
                at: audit.created_at,
                title: audit.summary || `${audit.actor || "system"} ${action.replace(/_/g, " ")}`,
                body: "",
                badge: audit.source || "audit",
                agentId: audit.agent_id,
                key: eventKey(["audit", audit.source, audit.id, action]),
            });
        });
    return events.sort((a, b) => eventMs(a.at) - eventMs(b.at) || String(a.key).localeCompare(String(b.key)));
}

function renderTicketTimeline(events) {
    if (!events.length) return '<div class="learning-meta">No sequence evidence recorded yet.</div>';
    return `
        <div class="ticket-sequence">
            ${events.map((event, index) => `
                <div class="sequence-row sequence-${escAttr(event.kind || "event")}">
                    <div class="sequence-index">${index + 1}</div>
                    <div class="sequence-content">
                        <div class="sequence-head">
                            <span>${formatTime(event.at)}</span>
                            <strong>${escHtml(event.title || "Event")}</strong>
                            <span class="source-badge local">${escHtml(event.badge || event.kind || "event")}</span>
                            ${event.agentId ? `<button class="inline-link" onclick="openAuditTrail('agent_${escAttr(event.agentId)}')">agent trail</button>` : ""}
                        </div>
                        ${event.author ? `<div class="sequence-meta">${escHtml(event.author)}</div>` : ""}
                        ${event.body ? `<div class="sequence-body">${renderNoteBody(event.body)}</div>` : ""}
                    </div>
                </div>
            `).join("")}
        </div>
    `;
}

function renderTaskTrace(tasks) {
    if (!tasks.length) return '<div class="learning-meta">No agent task records linked yet.</div>';
    return tasks.slice(0, 8).map(t => `
        <div class="trace-card">
            <div class="trace-card-head">
                <span>Task #${escHtml(t.id)} &middot; ${escHtml(t.task_type || "agent")}</span>
                <span class="status-badge ${statusClass(t.status)}">${escHtml(t.status || "-")}</span>
            </div>
            <div class="trace-card-meta">
                Agent ${escHtml(t.agent_id || "-")} &middot; ${escHtml(t.progress_pct ?? 0)}% &middot; ${formatTime(t.completed_at || t.started_at || t.created_at)}
            </div>
            ${(t.error_message || t.output) ? `<div class="trace-card-body">${escHtml(shortText(t.error_message || t.output, 260))}</div>` : ""}
        </div>
    `).join("");
}

function renderPostmortemTrace(postmortems) {
    if (!postmortems.length) return '<div class="learning-meta">No postmortem artifact linked yet.</div>';
    return postmortems.slice(0, 5).map(p => `
        <div class="trace-card">
            <div class="trace-card-head">
                <button class="inline-link" onclick="viewPostmortem(${Number(p.id)})">Postmortem #${escHtml(p.id)}</button>
                <span class="status-badge ${statusClass(p.status)}">${escHtml(learningStatusLabel(p.status))}</span>
            </div>
            <div class="trace-card-meta">${escHtml(p.created_by || "system")} &middot; ${formatTime(p.updated_at || p.created_at)}</div>
            <div class="trace-card-body">${escHtml(shortText(p.summary || p.improvements || "Postmortem recorded.", 280))}</div>
        </div>
    `).join("");
}

function renderAccessTrace(accessRequests) {
    if (!accessRequests.length) return "";
    return `
        <div class="trace-subsection">Access Requests</div>
        ${accessRequests.slice(0, 6).map(a => `
            <div class="trace-card">
                <div class="trace-card-head">
                    <span>${escHtml(a.permission || "access")} for ${escHtml(a.resource || a.resource_id || "resource")}</span>
                    <span class="status-badge ${statusClass(a.status || a.change_status)}">${escHtml(a.status || a.change_status || "-")}</span>
                </div>
                <div class="trace-card-meta">
                    ${a.access_ticket_id ? `ticket #${escHtml(a.access_ticket_id)} &middot; ` : ""}${escHtml(a.assignment_group || "approval group")}
                </div>
                ${a.reason ? `<div class="trace-card-body">${escHtml(shortText(a.reason, 240))}</div>` : ""}
            </div>
        `).join("")}
    `;
}

async function viewPostmortem(id) {
    const data = await apiGet(`/api/postmortems/${id}`);
    if (!data) return;
    const assets = data.promotion_assets || {};
    const workflow = assets.workflow;
    document.getElementById("modal-title").textContent = `Postmortem #${data.id}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Postmortem</div>
            <div class="detail-row"><span class="detail-label">Ticket:</span><span>${data.ticket_id ? `<button class="inline-link" onclick="viewTicket(${data.ticket_id})">#${data.ticket_id}</button>` : "-"} ${escHtml(data.ticket_title || "")}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${learningStatusLabel(data.status)}</span></div>
            <div class="detail-row"><span class="detail-label">Reviewed:</span><span>${escHtml(data.reviewed_by || "-")} ${data.reviewed_at ? `at ${formatDate(data.reviewed_at)}` : ""}</span></div>
            <div class="detail-row"><span class="detail-label">Created:</span><span>${formatDate(data.created_at)}</span></div>
            <div class="detail-row"><span class="detail-label">Updated:</span><span>${formatDate(data.updated_at)}</span></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Summary:</span><pre class="task-output">${escHtml(data.summary || "")}</pre></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Went Well:</span><pre class="task-output">${escHtml(data.went_well || "")}</pre></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Improvements:</span><pre class="task-output">${escHtml(data.improvements || "")}</pre></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Workflow Proposal:</span><pre class="task-output">${escHtml(data.workflow_proposal || "")}</pre></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Test Cases:</span><pre class="task-output">${escHtml(jsonBlock(data.test_cases))}</pre></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Guardrails:</span><pre class="task-output">${escHtml(jsonBlock(data.guardrails))}</pre></div>
            ${data.documentation ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Documentation:</span><pre class="task-output">${escHtml(data.documentation)}</pre></div>` : ""}
        </div>
        <div class="modal-section">
            <div class="section-title">Promotion Assets</div>
            <div class="detail-row"><span class="detail-label">Workflow key:</span><span>${escHtml(assets.workflow_key || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Workflow:</span><span>${workflow ? `<button class="inline-link" onclick="viewWorkflow(${workflow.id})">#${workflow.id} ${escHtml(workflow.name || "")}</button> <span class="status-badge ${statusClass(workflow.status)}">${escHtml(workflow.status || "")}</span> v${workflow.version || 1}` : "not promoted"}</span></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Knowledge Articles:</span><div>${(assets.knowledge_articles || []).length ? assets.knowledge_articles.map(a => `<div class="modal-activity-item"><span>#${a.id}</span><span>${escHtml(a.title || "")}</span></div>`).join("") : '<div class="learning-meta">No promoted article found.</div>'}</div></div>
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Skills:</span><div>${(assets.skills || []).length ? assets.skills.map(s => `<div class="modal-activity-item"><span>#${s.id}</span><span>${escHtml(s.name || "")} <span class="source-badge local">${escHtml(s.category || "")}</span></span></div>`).join("") : '<div class="learning-meta">No promoted skills found.</div>'}</div></div>
        </div>
        <div class="modal-actions-bar">
            ${data.status === "approved" || data.status === "ready_for_review" ? `<button class="btn btn-sm" onclick="promotePostmortem(${data.id})">Promote / Update Assets</button>` : ""}
            ${data.status !== "approved" && data.status !== "promoted" ? `<button class="btn btn-sm btn-success" onclick="reviewPostmortem(${data.id}, true)">Approve</button>` : ""}
            <button class="btn btn-sm" onclick="openAuditTrail('postmortem_${data.id}')">Audit Trail</button>
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function viewWorkflow(id) {
    const data = await apiGet(`/api/workflows/${id}`);
    if (!data) return;
    const workflowDescription = data.description || "";
    document.getElementById("modal-title").textContent = `Workflow #${data.id}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="section-title">Workflow</div>
            <div class="detail-row"><span class="detail-label">Name:</span><span>${escHtml(data.name)}</span></div>
            <div class="detail-row"><span class="detail-label">Workflow key:</span><span>${escHtml(data.workflow_key || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${statusClass(data.status)}">${escHtml(workflowStatusLabel(data))}</span></div>
            <div class="detail-row"><span class="detail-label">Review:</span><span>${workflowReviewHint(data)}</span></div>
            <div class="detail-row"><span class="detail-label">Class:</span><span>${escHtml(data.ticket_class || "-")}</span></div>
            <div class="detail-row"><span class="detail-label">Version:</span><span>${data.version || 1}</span></div>
            <div class="detail-row"><span class="detail-label">Trigger:</span><span>${escHtml(data.trigger_type || "-")}</span></div>
            ${workflowDescription ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Description:</span><pre class="task-output">${escHtml(workflowDescription)}</pre></div>` : ""}
            <div class="detail-row" style="flex-direction:column"><span class="detail-label">Blueprint:</span><pre class="task-output">${escHtml(data.blueprint || "")}</pre></div>
            ${data.test_plan ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Test Plan:</span><pre class="task-output">${escHtml(data.test_plan)}</pre></div>` : ""}
            ${data.test_results ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Test Results:</span><pre class="task-output">${escHtml(data.test_results)}</pre></div>` : ""}
            ${data.approval_policy ? `<div class="detail-row" style="flex-direction:column"><span class="detail-label">Approval Policy:</span><pre class="task-output">${escHtml(jsonBlock(data.approval_policy))}</pre></div>` : ""}
        </div>
        <div class="modal-section">
            <div class="section-title">Tickets / Test Runs</div>
            ${(data.runs || []).length ? data.runs.map(r => `
                <div class="modal-activity-item">
                    <span>#${r.id}</span>
                    <span>
                        <span class="status-badge ${statusClass(r.status)}">${escHtml(r.status)}</span>
                        ${r.ticket_id ? `<button class="inline-link" onclick="viewTicket(${r.ticket_id})">ticket ${r.ticket_id}</button>` : "no ticket"}
                        ${escHtml(r.ticket_title || "")}
                    </span>
                </div>
            `).join("") : '<div class="learning-meta">No tickets or test runs linked yet.</div>'}
        </div>
        <div class="modal-actions-bar workflow-modal-actions">
            <button class="btn btn-sm btn-success" onclick="reviewWorkflow(${data.id}, true)">Approve</button>
            <button class="btn btn-sm btn-danger" onclick="reviewWorkflow(${data.id}, false)">Request Revision</button>
            <button class="btn btn-sm btn-warning" onclick="rerunWorkflow(${data.id})">Rerun on Ticket</button>
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function rerunWorkflow(id) {
    const ticketId = prompt("Ticket id to rerun this workflow on:");
    if (!ticketId) return;
    const model = selectedAgentModel();
    const result = await apiPost(`/api/workflows/${id}/rerun`, { ticket_id: Number(ticketId), model, created_by: "dashboard" });
    if (result?.error) alert(result.error);
    else {
        alert(`Workflow rerun started as run ${result.run_id}, agent ${result.agent_id || "-"}.`);
        closeModal("ticket-modal");
        navigateTo("agents");
    }
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
        const postmortems = contextData?.postmortems || [];
        const accessRequests = contextData?.access_requests || [];
        const steeringEvents = contextData?.steering_events || [];
        const modelTurns = contextData?.model_turn_events || [];
        const sequence = buildTicketTimeline({
            ticket: contextData?.ticket || {},
            notes,
            relevant,
            tasks,
            changes,
            postmortems,
            accessRequests,
            steeringEvents,
            modelTurns,
        });

        const modalBody = document.getElementById("modal-body");
        if (!modalBody) return;

        // Insert before the actions bar
        const actionsBar = modalBody.querySelector(".modal-actions-bar");
        if (!actionsBar) return;

        const activityHtml = `
            <div class="modal-section">
                <div class="section-title">
                    Evidence Trail
                    <button class="inline-link" onclick="openAuditTrail('ticket_${ticketId}')">open full trail</button>
                </div>
                <div class="timeline-summary">
                    Chronological operator sequence across ticket notes, agent tasks, model turns, approvals, steering, postmortems, and audit.
                </div>
                ${renderEvidenceTiles({ notes, relevant, tasks, changes, postmortems, accessRequests })}
                <div class="trace-subsection">Sequence of Events</div>
                ${renderTicketTimeline(sequence)}
                <div class="trace-subsection">Agent Work</div>
                ${renderTaskTrace(tasks)}
                <div class="trace-subsection">Approval Gates</div>
                ${changes.length ? changes.slice(0, 8).map(c => renderGateSummary(c)).join("") : '<div class="learning-meta">No approval gates recorded.</div>'}
                ${renderAccessTrace(accessRequests)}
                <div class="trace-subsection">Postmortems & Learning</div>
                ${renderPostmortemTrace(postmortems)}
                <div class="trace-subsection">Recent Notes & Audit Detail</div>
                ${notes.length === 0 ? '<div style="color:var(--text-muted);font-size:12px">No notes recorded yet</div>' : ""}
                ${notes.slice(-8).reverse().map(n => `
                    <div class="modal-activity-item note-item">
                        <span style="min-width:60px">${formatTime(n.created_at)}</span>
                        <span>
                            <strong>${escHtml(n.author || "note")}</strong>
                            <span class="source-badge local">${escHtml(n.source || "note")}</span>
                            <div class="activity-note-body">${renderNoteBody(n.body)}</div>
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
    const model = selectedAgentModel();
    const harness = selectedAgentHarness();
    const result = await apiPost(`/api/tickets/${ticketId}/assign-agent`, { model, harness });
    if (result?.error) {
        alert(result.error);
    } else if (result) {
        alert(`Agent ${result.agent_id} assigned to ticket ${ticketId}`);
        loadTickets();
    }
}

async function startTicketPostmortem(ticketId) {
    const model = selectedAgentModel();
    const harness = selectedAgentHarness();
    const context = prompt("Optional postmortem context or review focus:", "");
    if (context === null) return;
    const result = await apiPost(`/api/tickets/${ticketId}/postmortem`, { model, harness, context });
    if (result && !result.error) {
        closeModal("ticket-modal");
        navigateTo("agents");
    } else if (result?.error) {
        alert(result.error);
    }
}

async function startTicketWorkflow(ticketId) {
    const model = selectedAgentModel();
    const harness = selectedAgentHarness();
    const context = prompt("Describe the workflow/automation to build or improve:", "");
    if (context === null) return;
    const result = await apiPost(`/api/tickets/${ticketId}/workflow`, { model, harness, context });
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
    loadSkillsPage();
}

async function viewSkill(skillId) {
    const skill = await apiGet(`/api/skills/${skillId}`);
    if (!skill || skill.error) {
        alert(skill?.error || "Skill not found");
        return;
    }
    document.getElementById("modal-title").textContent = `Skill #${skill.id}: ${skill.name}`;
    document.getElementById("modal-body").innerHTML = `
        <div class="modal-section">
            <div class="detail-row"><span class="detail-label">Category:</span><span>${escHtml(skill.category || "general")}</span></div>
            <div class="detail-row"><span class="detail-label">Status:</span><span class="status-badge ${skill.enabled ? "status-enabled" : "status-disabled"}">${skill.enabled ? "enabled" : "disabled"}</span></div>
            <div class="detail-row"><span class="detail-label">Default:</span><span>${skill.assigned_to_all ? "available to all agents" : "profile/agent assigned"}</span></div>
            <div class="detail-row"><span class="detail-label">Updated:</span><span>${formatDate(skill.updated_at || skill.created_at)}</span></div>
            <div class="section-title">Description</div>
            <div class="learning-item">${escHtml(skill.description || "No description")}</div>
            <div class="section-title">Instructions</div>
            <pre class="audit-json skill-preview">${escHtml(skill.prompt_template || "")}</pre>
        </div>
    `;
    document.getElementById("ticket-modal").classList.add("active");
}

async function editSkill(skillId) {
    const skill = await apiGet(`/api/skills/${skillId}`);
    if (!skill || skill.error) {
        alert(skill?.error || "Skill not found");
        return;
    }
    const name = prompt("Skill name:", skill.name || "");
    if (name === null || !name.trim()) return;
    const category = prompt("Category:", skill.category || "general");
    if (category === null) return;
    const description = prompt("Description:", skill.description || "");
    if (description === null) return;
    const promptTemplate = prompt("Skill instructions:", skill.prompt_template || "");
    if (promptTemplate === null || !promptTemplate.trim()) return;
    const assignedToAll = confirm("Make this skill available to all agent profiles by default? Cancel keeps it profile-assigned only.");
    const result = await apiPut(`/api/skills/${skillId}`, {
        name: name.trim(),
        category: category.trim() || "general",
        description,
        prompt_template: promptTemplate,
        assigned_to_all: assignedToAll,
    });
    if (result?.error) alert(result.error);
    await loadSkillsPage();
    renderSettings();
}

async function toggleSkill(skillId, enabled) {
    const verb = enabled ? "activate" : "deactivate";
    if (!confirm(`Really ${verb} this skill? This changes future agent context; currently running agents are not interrupted.`)) return;
    const result = await apiPut(`/api/skills/${skillId}`, { enabled });
    if (result?.error) alert(result.error);
    await loadSkillsPage();
    renderSettings();
}

async function loadAgentModels() {
    const data = await apiGet("/api/agents/models");
    agentRuntimeConfig = normalizeRuntimeConfig(data || {});
    renderAgentModelSelectors();
    renderAgentHarnessSelectors();
    renderSettings();
}

function normalizeRuntimeConfig(data) {
    const models = data?.models || ["gpt-5.5", "local/agent-default", "qwen/qwen3.6-27b"];
    const profiles = data?.profiles || [];
    return {
        models,
        default_model: data?.default_model || data?.default || profiles[0]?.model || "gpt-5.5",
        default_harness: data?.default_harness || profiles[0]?.harness || "codex",
        active_profile: data?.active_profile || profiles[0]?.id || "codex-primary",
        profiles,
        route_assignments: data?.route_assignments || [],
        setups: data?.setups || [],
        available_harnesses: data?.available_harnesses || [{ name: "codex" }, { name: "hermes" }, { name: "claude-code" }],
        max_concurrent_agents: Number(data?.max_concurrent_agents || 1),
        default_timeout_minutes: Number(data?.default_timeout_minutes || 10),
        reasoning_efforts: data?.reasoning_efforts || ["low", "medium", "high", "extra-high"],
    };
}

function renderAgentModelSelectors() {
    const models = agentRuntimeConfig.models || [];
    document.querySelectorAll("[data-agent-model-select]").forEach(select => {
        const current = select.value || agentRuntimeConfig.default_model;
        select.innerHTML = models.map(m => `<option value="${escAttr(m)}">${escHtml(m)}</option>`).join("");
        select.value = models.includes(current) ? current : (agentRuntimeConfig.default_model || models[0] || "");
    });
}

function renderAgentHarnessSelectors() {
    const harnesses = (agentRuntimeConfig.available_harnesses || [{ name: "hermes" }, { name: "claude-code" }])
        .map(h => h.name || h)
        .filter(Boolean);
    document.querySelectorAll("[data-agent-harness-select]").forEach(select => {
        const current = select.value || agentRuntimeConfig.default_harness || "hermes";
        select.innerHTML = harnesses.map(h => `<option value="${escAttr(h)}">${h === "claude-code" ? "Claude Code" : escHtml(h)}</option>`).join("");
        select.value = harnesses.includes(current) ? current : (agentRuntimeConfig.default_harness || harnesses[0] || "hermes");
    });
    const setupHarness = document.getElementById("setup-harness");
    if (setupHarness && agentRuntimeConfig.default_harness) setupHarness.value = agentRuntimeConfig.default_harness;
}

function setAgentConfigStatus(message, kind = "") {
    const el = document.getElementById("agent-config-status");
    if (!el) return;
    el.textContent = message || "";
    el.className = `setup-help agent-config-status ${kind}`.trim();
}

function selectedAgentHarness() {
    const active = activeRuntimeProfile();
    return document.getElementById("setup-harness")?.value
        || active?.harness
        || agentRuntimeConfig.default_harness
        || "codex";
}

function selectedAgentModel() {
    const active = activeRuntimeProfile();
    return active?.model
        || agentRuntimeConfig.default_model
        || "gpt-5.5";
}

function activeRuntimeProfile() {
    return (agentRuntimeConfig.profiles || []).find(p => p.id === agentRuntimeConfig.active_profile)
        || (agentRuntimeConfig.profiles || [])[0]
        || null;
}

function renderSettings() {
    const page = document.getElementById("page-settings");
    if (!page) return;
    const profiles = agentRuntimeConfig.profiles || [];
    const active = activeRuntimeProfile();
    setText("settings-active-profile-label", active?.name || "-");
    setText("settings-active-profile-sub", active ? `${active.harness} / ${active.model}` : "Harness routing");
    setText("settings-concurrency-label", String(agentRuntimeConfig.max_concurrent_agents || 1));
    setText("settings-timeout-label", `${agentRuntimeConfig.default_timeout_minutes || 10}m`);
    setText("settings-harness-label", (agentRuntimeConfig.available_harnesses || []).map(h => h.name || h).join(", ") || "-");
    const activeSelect = document.getElementById("settings-active-profile");
    const profileSelect = document.getElementById("settings-profile-select");
    const assignmentProfile = document.getElementById("settings-assignment-profile");
    const profileOptions = profiles.map(p => `<option value="${escAttr(p.id)}">${escHtml(p.name || p.id)} (${escHtml(p.harness)} / ${escHtml(p.model)})</option>`).join("");
    [activeSelect, profileSelect, assignmentProfile].forEach(select => {
        if (!select) return;
        const current = select.value || agentRuntimeConfig.active_profile;
        select.innerHTML = profileOptions;
        select.value = profiles.some(p => p.id === current) ? current : (agentRuntimeConfig.active_profile || profiles[0]?.id || "");
    });
    const maxInput = document.getElementById("settings-max-concurrent");
    if (maxInput) maxInput.value = agentRuntimeConfig.max_concurrent_agents || 1;
    const timeoutInput = document.getElementById("settings-default-timeout");
    if (timeoutInput) timeoutInput.value = agentRuntimeConfig.default_timeout_minutes || 10;
    applySettingsProfileSelection();
    renderRuntimeAssignments();
}

async function loadSettings() {
    await Promise.all([loadAgentModels(), loadSkillsData()]);
    renderSettings();
    loadRunnerHealth();
}

function activateRuntimePreset(profileId) {
    const select = document.getElementById("settings-active-profile");
    if (select) select.value = profileId;
    agentRuntimeConfig.active_profile = profileId;
    renderSettings();
}

function applySettingsProfileSelection() {
    const profileId = document.getElementById("settings-profile-select")?.value || agentRuntimeConfig.active_profile;
    const profile = (agentRuntimeConfig.profiles || []).find(p => p.id === profileId);
    if (!profile) return;
    setInputValue("settings-profile-name", profile.name || "");
    setSelectValue("settings-profile-harness", profile.harness || agentRuntimeConfig.default_harness);
    setSelectValue("settings-profile-model", profile.model || agentRuntimeConfig.default_model);
    setSelectValue("settings-profile-reasoning", profile.reasoning_effort || "medium");
    const fast = document.getElementById("settings-profile-fast");
    if (fast) fast.checked = Boolean(profile.fast_mode);
    setInputValue("settings-profile-timeout", profile.timeout_minutes || 10);
    setInputValue("settings-profile-concurrent", profile.max_concurrent_agents || 1);
    setInputValue("settings-profile-fallbacks", (profile.fallbacks || []).map(f => `${f.harness},${f.model},${f.route || ""}`).join("\n"));
    setInputValue("settings-profile-notes", profile.notes || "");
    renderProfileSkillChecklist(profile);
}

function renderProfileSkillChecklist(profile) {
    const wrap = document.getElementById("settings-profile-skills");
    if (!wrap) return;
    const selected = new Set(profile?.skills || []);
    const skills = (skillsCache || []).filter(skill => skill.enabled !== false)
        .sort((a, b) => `${a.category || ""}:${a.name || ""}`.localeCompare(`${b.category || ""}:${b.name || ""}`, undefined, { sensitivity: "base" }));
    if (!skills.length) {
        wrap.innerHTML = '<div class="learning-meta">No enabled skills are available yet.</div>';
        return;
    }
    wrap.innerHTML = skills.map(skill => `
        <label class="skill-check-row ${selected.has(skill.name) ? "selected" : ""}">
            <input type="checkbox" value="${escAttr(skill.name)}" ${selected.has(skill.name) ? "checked" : ""}>
            <span>
                <strong>${escHtml(skill.name)}</strong>
                <small>${escHtml(skill.category || "general")}${skill.assigned_to_all ? " / default" : " / profile-selected"}</small>
            </span>
        </label>
    `).join("");
}

function setInputValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value ?? "";
}

function setSelectValue(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = value;
}

function profileFromEditor(existingId) {
    const name = document.getElementById("settings-profile-name")?.value.trim() || "Custom profile";
    const id = existingId || name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 80) || `profile-${Date.now()}`;
    const fallbackLines = (document.getElementById("settings-profile-fallbacks")?.value || "").split(/\r?\n/);
    const fallbacks = fallbackLines.map(line => {
        const [harness, model, route] = line.split(",").map(v => (v || "").trim());
        return harness && model ? { harness, model, route: route || "" } : null;
    }).filter(Boolean);
    const selectedSkills = Array.from(document.querySelectorAll("#settings-profile-skills input:checked"))
        .map(input => input.value)
        .filter(Boolean);
    return {
        id,
        name,
        description: "",
        harness: document.getElementById("settings-profile-harness")?.value || selectedAgentHarness(),
        model: document.getElementById("settings-profile-model")?.value || selectedAgentModel(),
        reasoning_effort: document.getElementById("settings-profile-reasoning")?.value || "medium",
        fast_mode: Boolean(document.getElementById("settings-profile-fast")?.checked),
        timeout_minutes: Number(document.getElementById("settings-profile-timeout")?.value || 10),
        max_concurrent_agents: Number(document.getElementById("settings-profile-concurrent")?.value || 1),
        fallbacks,
        skills: selectedSkills,
        notes: document.getElementById("settings-profile-notes")?.value || "",
    };
}

function saveProfileFromEditor() {
    const profileId = document.getElementById("settings-profile-select")?.value || agentRuntimeConfig.active_profile;
    const profile = profileFromEditor(profileId);
    const profiles = (agentRuntimeConfig.profiles || []).map(p => p.id === profileId ? profile : p);
    agentRuntimeConfig.profiles = profiles;
    renderSettings();
}

function createProfileFromEditor() {
    const profile = profileFromEditor("");
    const profiles = (agentRuntimeConfig.profiles || []).filter(p => p.id !== profile.id);
    profiles.push(profile);
    agentRuntimeConfig.profiles = profiles;
    agentRuntimeConfig.active_profile = profile.id;
    renderSettings();
}

function renderRuntimeAssignments() {
    const list = document.getElementById("settings-assignments-list");
    if (!list) return;
    const profilesById = Object.fromEntries((agentRuntimeConfig.profiles || []).map(p => [p.id, p]));
    const rows = agentRuntimeConfig.route_assignments || [];
    if (!rows.length) {
        list.innerHTML = '<div class="learning-meta">No scoped routing assignments yet.</div>';
        return;
    }
    list.innerHTML = rows.map((row, idx) => {
        const profile = profilesById[row.profile_id];
        return `
            <div class="learning-item settings-route-row">
                <div>
                    <strong>${escHtml(row.scope_type)}: ${escHtml(row.scope_value)}</strong>
                    <div class="learning-meta">${escHtml(row.notes || "No notes")}</div>
                </div>
                <div>
                    <span class="status-badge status-info">${escHtml(profile?.name || row.profile_id)}</span>
                    <button class="btn btn-sm btn-danger" onclick="removeRuntimeAssignment(${idx})">Remove</button>
                </div>
            </div>
        `;
    }).join("");
}

function addRuntimeAssignment() {
    const row = {
        scope_type: document.getElementById("settings-assignment-scope-type")?.value || "platform_area",
        scope_value: document.getElementById("settings-assignment-scope-value")?.value.trim() || "",
        profile_id: document.getElementById("settings-assignment-profile")?.value || agentRuntimeConfig.active_profile,
        enabled: true,
        notes: document.getElementById("settings-assignment-notes")?.value.trim() || "",
    };
    if (!row.scope_value) {
        alert("Add a scope value first.");
        return;
    }
    agentRuntimeConfig.route_assignments = [...(agentRuntimeConfig.route_assignments || []), row];
    setInputValue("settings-assignment-scope-value", "");
    setInputValue("settings-assignment-notes", "");
    renderRuntimeAssignments();
}

function removeRuntimeAssignment(idx) {
    agentRuntimeConfig.route_assignments = (agentRuntimeConfig.route_assignments || []).filter((_, rowIdx) => rowIdx !== idx);
    renderRuntimeAssignments();
}

async function saveRuntimeSettings() {
    const activeProfile = document.getElementById("settings-active-profile")?.value || agentRuntimeConfig.active_profile;
    const payload = {
        active_profile: activeProfile,
        default_harness: (agentRuntimeConfig.profiles || []).find(p => p.id === activeProfile)?.harness || agentRuntimeConfig.default_harness,
        default_model: (agentRuntimeConfig.profiles || []).find(p => p.id === activeProfile)?.model || agentRuntimeConfig.default_model,
        models: agentRuntimeConfig.models || [],
        profiles: agentRuntimeConfig.profiles || [],
        route_assignments: agentRuntimeConfig.route_assignments || [],
        max_concurrent_agents: Number(document.getElementById("settings-max-concurrent")?.value || agentRuntimeConfig.max_concurrent_agents || 1),
        default_timeout_minutes: Number(document.getElementById("settings-default-timeout")?.value || agentRuntimeConfig.default_timeout_minutes || 10),
        setups: agentRuntimeConfig.setups || [],
    };
    const updated = await apiPut("/api/agents/config", payload);
    if (updated && !updated.error) {
        agentRuntimeConfig = normalizeRuntimeConfig(updated);
        renderAgentModelSelectors();
        renderAgentHarnessSelectors();
        renderSettings();
        loadRunnerHealth();
        setAgentConfigStatus("Saved runtime settings.");
    } else {
        setAgentConfigStatus(updated?.error || "Settings save failed.", "warning");
    }
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
let setupRuntime = null;
let setupModuleStatuses = {};
let setupModuleActions = {};
let setupModuleNotes = {};

async function loadSetup() {
    setupManifest = await apiGet("/api/setup/manifest");
    setupRuntime = await apiGet("/api/agents/runner-health");
    const setupStatus = await apiGet("/api/setup/status");
    setupModuleStatuses = setupStatus?.module_statuses || {};
    if (!setupManifest) return;
    renderSetupRuntime();
    renderSetupModules();
    await generateSetupPlan();
}

function renderSetupRuntime() {
    const panel = document.getElementById("setup-runtime-status");
    if (!panel) return;
    const health = setupRuntime || {};
    const proxy = health.effective_anthropic_base_url || "";
    const harness = health.harness || "unknown";
    const available = (health.available_harnesses || []).map(h => h.name).join(", ") || "none";
    const modelStatus = health.model_api?.status || "unknown";
    const model = health.default_model || document.getElementById("setup-model")?.value || "deepseek/deepseek-v4-flash";
    const aiInput = document.getElementById("setup-ai-base-url");
    if (aiInput && !aiInput.value && proxy) aiInput.value = proxy;
    const harnessSelect = document.getElementById("setup-harness");
    if (harnessSelect) harnessSelect.value = agentRuntimeConfig.default_harness || harness || "hermes";
    panel.innerHTML = `
        <div><strong>Proxy URL:</strong> ${escHtml(proxy || "not configured")}</div>
        <div><strong>Proxy health:</strong> <span class="status-badge ${statusClass(modelStatus)}">${escHtml(modelStatus)}</span></div>
        <div><strong>Harness:</strong> ${escHtml(harness)}</div>
        <div><strong>Available harnesses:</strong> ${escHtml(available)}</div>
        <div><strong>Selected model:</strong> ${escHtml(model)}</div>
        <div><strong>Setup agent:</strong> created when installer or operator chooses Create + Assign Agent</div>
    `;
}

function setupSelectedProfileModules() {
    const profile = document.getElementById("setup-profile")?.value || "soc";
    return new Set(setupManifest?.profiles?.[profile]?.modules || []);
}

function defaultSetupActionFor(module, profileModules = setupSelectedProfileModules()) {
    const moduleStatus = setupModuleStatuses[module.id] || {};
    const deployStatus = moduleStatus.deployment_status || "not_configured";
    const isReady = ["ready", "built_in", "configured"].includes(deployStatus);
    return isReady ? "keep" : (profileModules.has(module.id) ? "deploy" : "disabled");
}

function syncSetupModuleInputs() {
    document.querySelectorAll("[data-setup-action]").forEach(input => {
        setupModuleActions[input.dataset.setupAction] = input.value || "disabled";
    });
    document.querySelectorAll("[data-setup-notes]").forEach(input => {
        setupModuleNotes[input.dataset.setupNotes] = input.value || "";
    });
}

function renderSetupModules() {
    const grid = document.getElementById("setup-modules");
    if (!grid || !setupManifest) return;
    syncSetupModuleInputs();
    const selected = setupSelectedProfileModules();
    const modules = setupManifest.modules || [];
    const categorySelect = document.getElementById("setup-module-category");
    if (categorySelect && categorySelect.options.length <= 1) {
        const categories = [...new Set(modules.map(m => m.category).filter(Boolean))].sort();
        categorySelect.innerHTML = '<option value="">All categories</option>' + categories.map(c => `<option value="${escAttr(c)}">${escHtml(c)}</option>`).join("");
    }
    const search = (document.getElementById("setup-module-search")?.value || "").trim().toLowerCase();
    const category = document.getElementById("setup-module-category")?.value || "";
    const actionFilter = document.getElementById("setup-module-action-filter")?.value || "";
    const visibleModules = modules.filter(m => {
        const inProfile = selected.has(m.id);
        const defaultAction = setupModuleActions[m.id] || defaultSetupActionFor(m, selected);
        const haystack = [m.id, m.name, m.category, m.status, m.skill, m.provider_contract, m.notes].join(" ").toLowerCase();
        return (!search || haystack.includes(search))
            && (!category || m.category === category)
            && (!actionFilter || defaultAction === actionFilter);
    });
    const countEl = document.getElementById("setup-module-count");
    if (countEl) countEl.textContent = `${visibleModules.length} of ${modules.length} modules`;
    grid.innerHTML = visibleModules.map(m => {
        const inProfile = selected.has(m.id);
        const statusLabel = m.status || "unknown";
        const moduleStatus = setupModuleStatuses[m.id] || {};
        const deployStatus = moduleStatus.deployment_status || "not_configured";
        const defaultAction = setupModuleActions[m.id] || defaultSetupActionFor(m, selected);
        return `
            <div class="module-card ${inProfile ? "selected" : ""}" data-module-card="${escAttr(m.id)}">
                <div class="module-card-head">
                    <div>
                        <strong>${escHtml(m.name)}</strong>
                        <div class="module-meta">${escHtml(m.category)} / ${escHtml(statusLabel)}</div>
                    </div>
                    <span class="status-badge ${statusClass(statusLabel)}">${escHtml(statusLabel)}</span>
                </div>
                <div class="module-status-line">
                    <span class="status-badge ${statusClass(deployStatus)}">${escHtml(deployStatus)}</span>
                    ${moduleStatus.tool?.name ? `<span class="module-meta">via ${escHtml(moduleStatus.tool.name)} ${moduleStatus.tool.port ? `:${escHtml(moduleStatus.tool.port)}` : ""}</span>` : `<span class="module-meta">${escHtml(moduleStatus.source || "manifest")}</span>`}
                </div>
                <div class="module-desc">${escHtml(m.notes || "")}</div>
                <div class="module-controls">
                    <select class="filter-select" data-setup-action="${escAttr(m.id)}" onchange="setupModuleActions['${escJs(m.id)}']=this.value;generateSetupPlan()">
                        <option value="keep" ${defaultAction === "keep" ? "selected" : ""}>Keep active</option>
                        <option value="deploy" ${defaultAction === "deploy" ? "selected" : ""}>Deploy reference</option>
                        <option value="integrate">Integrate existing</option>
                        <option value="disabled" ${defaultAction === "disabled" ? "selected" : ""}>Off / not in scope</option>
                    </select>
                </div>
                <textarea class="setup-textarea module-note-input" rows="2" data-setup-notes="${escAttr(m.id)}" oninput="setupModuleNotes['${escJs(m.id)}']=this.value" placeholder="Module notes: port, endpoint, credential vault key, tenant, migration detail...">${escHtml(setupModuleNotes[m.id] || "")}</textarea>
                <div class="module-actions-row">
                    <button class="btn btn-sm" onclick="createModuleSetupTicket('${escJs(m.id)}', null, false)">Ticket</button>
                    <button class="btn btn-sm btn-warning" onclick="createModuleSetupTicket('${escJs(m.id)}', null, true)">Ticket + Agent</button>
                    <button class="btn btn-sm btn-danger" onclick="createModuleSetupTicket('${escJs(m.id)}', 'undeploy', false)">Undeploy</button>
                    <button class="btn btn-sm" onclick="createModuleSetupTicket('${escJs(m.id)}', 'reinstall', false)">Reinstall</button>
                </div>
                ${m.skill ? `<div class="module-meta">Skill: ${escHtml(m.skill)} ${m.skill_available ? "" : "(missing in container)"}</div>` : ""}
            </div>
        `;
    }).join("") || '<div class="tool-empty">No modules match the current filters</div>';
}

function bulkSetSetupModules(action) {
    syncSetupModuleInputs();
    const selected = setupSelectedProfileModules();
    document.querySelectorAll("[data-setup-action]").forEach(input => {
        const id = input.dataset.setupAction;
        if (action === "profile") {
            const module = (setupManifest.modules || []).find(m => m.id === id) || { id };
            input.value = defaultSetupActionFor(module, selected);
        } else {
            input.value = action;
        }
        setupModuleActions[id] = input.value;
    });
    generateSetupPlan();
}

function collectSetupChoices() {
    syncSetupModuleInputs();
    const profile = document.getElementById("setup-profile")?.value || "soc";
    const profileModules = setupSelectedProfileModules();
    const include = [];
    const exclude = [];
    const existingTools = [];
    const moduleActions = {};
    const moduleNotes = {};
    (setupManifest?.modules || []).forEach(module => {
        const id = module.id;
        const action = setupModuleActions[id] || defaultSetupActionFor(module, profileModules);
        moduleActions[id] = action;
        if (action !== "disabled" && !profileModules.has(id)) include.push(id);
        if (action === "disabled" && profileModules.has(id)) exclude.push(id);
        if (action === "integrate") existingTools.push(id);
    });
    Object.entries(setupModuleNotes).forEach(([id, value]) => {
        if (String(value || "").trim()) moduleNotes[id] = String(value).trim();
    });
    return {
        profile,
        include,
        exclude,
        existing_tools: existingTools,
        module_actions: moduleActions,
        module_notes: moduleNotes,
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
        ${s.already_active || 0} keep active &middot;
        ${s.blueprint || 0} blueprint &middot;
        ${(s.undeploy || 0) + (s.redeploy || 0) ? `${(s.undeploy || 0) + (s.redeploy || 0)} teardown/reinstall &middot;` : ""}
        ${s.disabled || 0} off
        ${s.blocked ? `<span class="status-badge status-warning">${s.blocked} blocked by disabled dependencies</span>` : ""}
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
            <td>${escHtml((step.disabled_dependencies?.length ? [`blocked by ${step.disabled_dependencies.join(", ")}`] : (step.health_checks || []).slice(0, 2)).join(", "))}</td>
        </tr>
    `).join("");
}

async function createSetupTicket(spawnAgent) {
    if (!setupManifest) await loadSetup();
    const choices = collectSetupChoices();
    const result = await apiPost("/api/setup/ticket", {
        ...choices,
        ai_base_url: document.getElementById("setup-ai-base-url")?.value || null,
        model: document.getElementById("setup-model")?.value || selectedAgentModel(),
        proxy_mode: document.getElementById("setup-proxy-mode")?.value || "deploy",
        proxy_url: document.getElementById("setup-ai-base-url")?.value || null,
        harness: document.getElementById("setup-harness")?.value || setupRuntime?.harness || "auto",
        provider: (document.getElementById("setup-model")?.value || "").startsWith("qwen/") ? "lmstudio" : "nous",
        notes: document.getElementById("setup-notes")?.value || "",
        spawn_agent: spawnAgent,
        sync_provider: false,
    });
    if (result?.ticket?.id) {
        const childCount = result.module_tickets?.length || 0;
        alert(`Setup parent ticket ${result.ticket.id} created with ${childCount} scoped module tickets${result.agent?.agent_id ? ` and agent ${result.agent.agent_id}` : ""}.`);
        navigateTo(spawnAgent ? "agents" : "tickets");
    } else if (result?.error) {
        alert(result.error);
    }
}

async function createModuleSetupTicket(moduleId, operation, spawnAgent) {
    if (!setupManifest) await loadSetup();
    const actionInput = document.querySelector(`[data-setup-action="${CSS.escape(moduleId)}"]`);
    const notesInput = document.querySelector(`[data-setup-notes="${CSS.escape(moduleId)}"]`);
    const action = operation || actionInput?.value || "deploy";
    if (["undeploy", "reinstall"].includes(action)) {
        const label = action === "undeploy" ? "tear down" : "reinstall";
        if (!confirm(`Create a ${label} ticket for ${moduleId}? This will require approval before any infrastructure changes.`)) {
            return;
        }
    }
    const result = await apiPost("/api/setup/module-ticket", {
        module_id: moduleId,
        action,
        ai_base_url: document.getElementById("setup-ai-base-url")?.value || null,
        model: document.getElementById("setup-model")?.value || selectedAgentModel(),
        proxy_mode: document.getElementById("setup-proxy-mode")?.value || "deploy",
        proxy_url: document.getElementById("setup-ai-base-url")?.value || null,
        harness: document.getElementById("setup-harness")?.value || setupRuntime?.harness || "auto",
        provider: (document.getElementById("setup-model")?.value || "").startsWith("qwen/") ? "lmstudio" : "nous",
        notes: notesInput?.value || "",
        spawn_agent: spawnAgent,
        sync_provider: false,
    });
    if (result?.ticket?.id) {
        alert(`Module ticket ${result.ticket.id} created for ${moduleId}${result.agent?.agent_id ? ` with agent ${result.agent.agent_id}` : ""}.`);
        navigateTo(spawnAgent ? "agents" : "tickets");
    } else {
        alert(result?.error || "Could not create module ticket.");
    }
}
