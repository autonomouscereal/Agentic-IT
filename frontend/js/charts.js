// Agentic Operations - Chart.js Integration

let ticketTrendChart = null;
let agentDistChart = null;
let toolUptimeChart = null;

const chartColors = {
    cyan: "#00d4ff",
    green: "#00ff88",
    yellow: "#ffd700",
    red: "#ff4757",
    orange: "#ff6b35",
    purple: "#a855f7",
    gray: "#64748b",
};

// Initialize charts on load
document.addEventListener("DOMContentLoaded", () => {
    initTicketTrendChart();
    initAgentDistChart();
    loadToolUptimeChart();
});

function initTicketTrendChart() {
    const canvas = document.getElementById("ticket-trend-chart");
    if (!canvas) return;

    ticketTrendChart = new Chart(canvas, {
        type: "line",
        data: {
            labels: [],
            datasets: [{
                label: "Tickets Created",
                data: [],
                borderColor: chartColors.cyan,
                backgroundColor: "rgba(0, 212, 255, 0.1)",
                fill: true,
                tension: 0.4,
                pointRadius: 4,
                pointHoverRadius: 6,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
            },
            scales: {
                x: {
                    grid: { color: "rgba(45, 58, 79, 0.5)" },
                    ticks: { color: "#94a3b8" },
                },
                y: {
                    grid: { color: "rgba(45, 58, 79, 0.5)" },
                    ticks: { color: "#94a3b8", stepSize: 1 },
                    beginAtZero: true,
                },
            },
        },
    });
}

function initAgentDistChart() {
    const canvas = document.getElementById("agent-dist-chart");
    if (!canvas) return;

    agentDistChart = new Chart(canvas, {
        type: "doughnut",
        data: {
            labels: [],
            datasets: [{
                data: [],
                backgroundColor: [
                    chartColors.cyan, chartColors.green, chartColors.yellow,
                    chartColors.red, chartColors.purple, chartColors.gray,
                ],
                borderWidth: 0,
                spacing: 2,
            }],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: "65%",
            plugins: {
                legend: {
                    position: "right",
                    labels: {
                        color: "#94a3b8",
                        padding: 12,
                        usePointStyle: true,
                        pointStyleWidth: 10,
                        font: { size: 11 },
                    },
                },
            },
        },
    });
}

function updateTicketTrendChart(trend) {
    if (!ticketTrendChart || !trend) return;

    const labels = trend.map(t => {
        const d = new Date(t.date);
        return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    });
    const data = trend.map(t => t.count);

    ticketTrendChart.data.labels = labels;
    ticketTrendChart.data.datasets[0].data = data;
    ticketTrendChart.update("none");
}

function updateAgentDistChart(distribution) {
    if (!agentDistChart || !distribution) return;

    const labels = distribution.map(d => d.status);
    const data = distribution.map(d => d.count);

    agentDistChart.data.labels = labels;
    agentDistChart.data.datasets[0].data = data;
    agentDistChart.update("none");
}

async function loadToolUptimeChart() {
    const canvas = document.getElementById("tool-uptime-chart");
    if (!canvas) return;

    try {
        const res = await fetch(`${API || ""}/api/dashboard/tool-uptime`);
        const data = await res.json();

        if (!data.tools || data.tools.length === 0) {
            canvas.parentElement.innerHTML = '<div style="color:var(--text-muted);font-size:12px">No uptime data yet</div>';
            return;
        }

        toolUptimeChart = new Chart(canvas, {
            type: "bar",
            data: {
                labels: data.tools.map(t => t.name),
                datasets: [{
                    label: "Uptime %",
                    data: data.tools.map(t => t.uptime_pct || 0),
                    backgroundColor: data.tools.map(t => {
                        const pct = parseFloat(t.uptime_pct || 0);
                        if (pct >= 95) return chartColors.green;
                        if (pct >= 80) return chartColors.yellow;
                        return chartColors.red;
                    }),
                    borderRadius: 4,
                    borderSkipped: false,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: "y",
                plugins: {
                    legend: { display: false },
                },
                scales: {
                    x: {
                        max: 100,
                        grid: { color: "rgba(45, 58, 79, 0.5)" },
                        ticks: { color: "#94a3b8", callback: v => v + "%" },
                    },
                    y: {
                        grid: { display: false },
                        ticks: { color: "#94a3b8", font: { size: 10 } },
                    },
                },
            },
        });
    } catch (e) {
        console.error("Tool uptime chart error:", e);
    }
}
