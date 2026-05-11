// SOC Dashboard - WebSocket for Real-time Updates

let ws = null;
let reconnectTimer = null;

function connectWebSocket() {
    const wsUrl = window.location.origin.replace("http", "ws") + "/api/agents/ws";

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log("WebSocket connected");
            updateConnectionStatus(true);
        };

        ws.onmessage = (event) => {
            if (event.data === "pong") return;
            try {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            } catch (e) {
                console.error("WS parse error:", e);
            }
        };

        ws.onclose = () => {
            console.log("WebSocket disconnected, reconnecting...");
            updateConnectionStatus(false);
            reconnectTimer = setTimeout(connectWebSocket, 5000);
        };

        ws.onerror = (err) => {
            console.error("WebSocket error:", err);
        };
    } catch (e) {
        console.error("WebSocket connect error:", e);
        reconnectTimer = setTimeout(connectWebSocket, 5000);
    }
}

function handleWebSocketMessage(data) {
    switch (data.type) {
        case "agent_spawned":
            console.log(`Agent ${data.agent_id} spawned for ticket ${data.ticket_id}`);
            showNotification(`Agent #${data.agent_id} spawned`, "info");
            refreshCurrentPage();
            break;

        case "agent_stalled":
            console.warn(`Agent ${data.agent_id} stalled (idle ${data.idle_seconds}s)`);
            showNotification(`Agent #${data.agent_id} stalled`, "warning");
            refreshCurrentPage();
            break;

        case "agent_finished":
            console.log(`Agent ${data.agent_id} finished`);
            showNotification(`Agent #${data.agent_id} finished`, "success");
            refreshCurrentPage();
            break;

        case "agent_stopped":
            console.log(`Agent ${data.agent_id} stopped`);
            refreshCurrentPage();
            break;

        case "change_pending":
            console.log(`New change request #${data.change_id}`);
            showNotification(`Change request #${data.change_id} pending`, "info");
            updateChangeBadge();
            break;

        case "ticket_synced":
            console.log(`Ticket synced: ${data.itop_class}::${data.itop_ref}`);
            showNotification(`Synced ${data.itop_class} #${data.itop_ref}`, "sync");
            flashRow(`[data-itop-ref="${data.itop_ref}"]`);
            // Refresh tickets page if visible
            const ticketPage = document.querySelector(".page.active");
            if (ticketPage && (ticketPage.id === "page-tickets" || ticketPage.id === "page-overview")) {
                refreshCurrentPage();
            }
            break;

        case "ticket_updated":
            console.log(`Ticket ${data.ticket_id} updated`);
            refreshCurrentPage();
            break;

        case "sync_complete":
            console.log(`Sync complete: ${data.synced} synced, ${data.new} new`);
            showNotification(`Sync: ${data.synced} tickets (${data.new} new)`, "sync");
            refreshCurrentPage();
            break;

        case "tool_status_changed":
            console.log(`Tool ${data.tool_name}: ${data.status}`);
            const toolsPage = document.querySelector(".page.active");
            if (toolsPage && toolsPage.id === "page-tools") {
                refreshCurrentPage();
            }
            break;

        default:
            console.log("WS event:", data.type, data);
    }
}

function refreshCurrentPage() {
    const activePage = document.querySelector(".page.active");
    if (!activePage) return;

    const pageId = activePage.id.replace("page-", "");
    switch (pageId) {
        case "overview": loadDashboardStats(); break;
        case "tickets": loadTickets(); break;
        case "agents": loadAgents(); break;
        case "changes": loadChanges(); break;
        case "workflows": loadWorkflows(); break;
        case "intake": loadIntake(); break;
        case "cicd": loadCicd(); break;
        case "tools": loadTools(); break;
        case "audit": loadAudit(); break;
    }
}

function updateConnectionStatus(connected) {
    const dot = document.querySelector(".status-dot");
    const label = document.querySelector(".connection-status span:last-child");
    if (dot) {
        dot.className = connected ? "status-dot connected" : "status-dot";
    }
    if (label) {
        label.textContent = connected ? "Live" : "Offline";
    }
}

function updateChangeBadge() {
    apiGet("/api/changes/stats").then(data => {
        if (data) {
            setText("change-count", data.pending || 0);
        }
    });
}

function showNotification(message, type = "info") {
    const notification = document.createElement("div");
    const colors = {
        "info": "var(--accent-primary)",
        "warning": "var(--accent-warning)",
        "success": "var(--accent-success)",
        "sync": "var(--accent-primary)",
    };
    notification.style.cssText = `
        position: fixed; bottom: 20px; right: 20px; z-index: 2000;
        background: var(--bg-card); border: 1px solid var(--border-color);
        border-left: 4px solid ${colors[type] || colors["info"]};
        padding: 12px 20px; border-radius: 8px; font-size: 13px;
        color: var(--text-primary); box-shadow: 0 4px 24px rgba(0,0,0,0.4);
        animation: slide-in 0.2s ease;
    `;
    notification.textContent = message;
    document.body.appendChild(notification);
    setTimeout(() => {
        notification.style.opacity = "0";
        notification.style.transition = "opacity 0.3s";
        setTimeout(() => notification.remove(), 300);
    }, 3500);
}

function flashRow(selector) {
    const row = document.querySelector(selector);
    if (!row) return;
    row.style.transition = "background 0.2s";
    row.style.background = "rgba(0, 212, 255, 0.15)";
    setTimeout(() => { row.style.background = ""; }, 2000);
}

// Heartbeat ping to keep connection alive
setInterval(() => {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send("ping");
    }
}, 30000);

// Connect on load
document.addEventListener("DOMContentLoaded", () => {
    connectWebSocket();
});
