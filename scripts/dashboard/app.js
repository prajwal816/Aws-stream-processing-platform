/**
 * Cloud-Native Serverless Data Platform — Dashboard Application
 *
 * Fetches data from the local Flask server, renders charts with Chart.js,
 * animates metric counters, and auto-refreshes.
 */

const API_BASE = window.location.origin;
let charts = {};
let refreshInterval = null;
let isSimulating = false;

// ============================================
// Initialization
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    updateClock();
    setInterval(updateClock, 1000);
    initCharts();
    refreshDashboard();
    // Auto-refresh every 10 seconds
    refreshInterval = setInterval(refreshDashboard, 10000);
});

function updateClock() {
    const el = document.getElementById('header-time');
    if (el) {
        el.textContent = new Date().toLocaleTimeString('en-US', { hour12: false });
    }
}

// ============================================
// API Client
// ============================================
async function apiGet(path) {
    try {
        const resp = await fetch(`${API_BASE}${path}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (e) {
        console.warn(`API call failed: ${path}`, e);
        return null;
    }
}

async function apiPost(path, body = {}) {
    try {
        const resp = await fetch(`${API_BASE}${path}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (e) {
        console.warn(`API POST failed: ${path}`, e);
        return null;
    }
}

// ============================================
// Dashboard Refresh
// ============================================
async function refreshDashboard() {
    const data = await apiGet('/analytics/dashboard');
    if (!data || !data.data) return;

    const d = data.data;
    updateOverviewCards(d);
    updateServiceHealth(d);
    updateTables(d);
    updateEventBus(d);
    updateCharts(d);
}

// ============================================
// Simulation
// ============================================
async function runSimulation() {
    if (isSimulating) return;
    isSimulating = true;

    const btn = document.getElementById('btn-simulate');
    const status = document.getElementById('sim-status');
    btn.disabled = true;
    btn.innerHTML = `<svg class="spin" width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="2" fill="none" stroke-dasharray="20 10"/></svg> Simulating...`;

    const totalBatches = 10;
    const batchSize = 500;
    let totalIngested = 0;

    for (let i = 0; i < totalBatches; i++) {
        status.textContent = `Batch ${i + 1}/${totalBatches} — ${totalIngested.toLocaleString()} records ingested...`;
        const result = await apiPost('/api/simulate', { count: batchSize });
        if (result && result.data) {
            totalIngested += result.data.ingested || 0;
        }
        // Small delay between batches
        await new Promise(r => setTimeout(r, 100));
    }

    status.textContent = `✅ Simulation complete — ${totalIngested.toLocaleString()} records ingested`;
    btn.disabled = false;
    btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><path d="M4 2l10 6-10 6V2z"/></svg> Run Simulation`;
    isSimulating = false;

    // Refresh dashboard
    await refreshDashboard();
}

// ============================================
// Overview Cards
// ============================================
function updateOverviewCards(data) {
    const overview = data.overview || {};
    const costData = data.cost_analysis || {};

    animateCounter('val-ingested', overview.total_records_ingested || 0);
    animateCounter('val-processed', overview.total_records_processed || 0);

    const latency = overview.avg_processing_latency_ms || 0;
    const el = document.getElementById('val-latency');
    if (el) el.innerHTML = `${latency.toFixed(1)}<small>ms</small>`;

    const errorRate = overview.total_records_ingested > 0
        ? ((overview.total_errors / overview.total_records_ingested) * 100).toFixed(2)
        : '0.00';
    const errEl = document.getElementById('val-errors');
    if (errEl) errEl.innerHTML = `${errorRate}<small>%</small>`;

    // Cost
    let totalCost = 0;
    for (const svc of Object.values(costData)) {
        totalCost += svc.total_estimated_cost || 0;
    }
    const costEl = document.getElementById('val-cost');
    if (costEl) costEl.textContent = `$${(totalCost * 30).toFixed(2)}`;

    // Trends
    const trendIngested = document.getElementById('trend-ingested');
    if (trendIngested && overview.total_records_ingested > 0) {
        trendIngested.textContent = `${overview.total_records_ingested.toLocaleString()} total`;
        trendIngested.className = 'card-trend trend-up';
    }
    const trendProcessed = document.getElementById('trend-processed');
    if (trendProcessed && overview.total_records_processed > 0) {
        const rate = ((overview.total_records_processed / Math.max(overview.total_records_ingested, 1)) * 100).toFixed(1);
        trendProcessed.textContent = `${rate}% processed`;
        trendProcessed.className = 'card-trend trend-up';
    }
}

function animateCounter(elementId, targetValue) {
    const el = document.getElementById(elementId);
    if (!el) return;

    const current = parseInt(el.textContent.replace(/,/g, '')) || 0;
    if (current === targetValue) return;

    const duration = 800;
    const startTime = performance.now();

    function update(now) {
        const elapsed = now - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
        const value = Math.round(current + (targetValue - current) * eased);
        el.textContent = value.toLocaleString();
        if (progress < 1) requestAnimationFrame(update);
    }
    requestAnimationFrame(update);
}

// ============================================
// Service Health
// ============================================
function updateServiceHealth(data) {
    const metrics = data.service_metrics || {};

    const serviceMap = {
        'ingestion-service': 'svc-ingestion-count',
        'processing-service': 'svc-processing-count',
        'analytics-service': 'svc-analytics-count',
        'notification-service': 'svc-notification-count',
    };

    for (const [svcName, elId] of Object.entries(serviceMap)) {
        const el = document.getElementById(elId);
        if (!el) continue;
        const svcData = metrics[svcName] || {};
        const counters = svcData.counters || {};
        const invocations = counters.lambda_invocations || 0;
        el.textContent = `${invocations.toLocaleString()} invocations`;
    }
}

// ============================================
// Tables
// ============================================
function updateTables(data) {
    // DynamoDB tables
    const infra = data.infrastructure || {};
    const tables = infra.dynamodb_tables || {};
    const tbody = document.getElementById('dynamo-table-body');

    if (tbody && Object.keys(tables).length > 0) {
        tbody.innerHTML = Object.entries(tables).map(([name, info]) => `
            <tr>
                <td>${name}</td>
                <td>${(info.item_count || 0).toLocaleString()}</td>
                <td>${info.partition_key || '—'}</td>
                <td>${info.sort_key || '—'}</td>
                <td>${info.gsi_count || 0}</td>
                <td><span class="status-badge status-active">ACTIVE</span></td>
            </tr>
        `).join('');
    }

    // Recent records
    const records = data.recent_records || [];
    const recTbody = document.getElementById('records-table-body');

    if (recTbody && records.length > 0) {
        recTbody.innerHTML = records.slice(0, 15).map(r => {
            const statusClass = r.status === 'completed' ? 'status-completed'
                : r.status === 'failed' ? 'status-failed' : 'status-skipped';
            return `
            <tr>
                <td>${(r.record_id || '').substring(0, 8)}...</td>
                <td>${r.source_id || '—'}</td>
                <td>${r.category || '—'}</td>
                <td>${typeof r.normalized_value === 'number' ? r.normalized_value.toFixed(2) : '—'}</td>
                <td>${typeof r.quality_score === 'number' ? r.quality_score.toFixed(3) : '—'}</td>
                <td><span class="status-badge ${statusClass}">${(r.status || 'unknown').toUpperCase()}</span></td>
                <td>${r.processed_at ? new Date(r.processed_at).toLocaleTimeString() : '—'}</td>
            </tr>`;
        }).join('');
    }
}

// ============================================
// Event Bus
// ============================================
function updateEventBus(data) {
    const evtData = data.event_bus || {};
    const el = (id, val) => {
        const e = document.getElementById(id);
        if (e) e.textContent = (val || 0).toLocaleString();
    };
    el('evt-total', evtData.total_events);
    el('evt-dlq', evtData.dlq_size);
    el('evt-topics', Object.keys(evtData.topics || {}).length);
}

// ============================================
// Charts
// ============================================
const chartColors = {
    indigo: 'rgba(99, 102, 241, 0.8)',
    violet: 'rgba(139, 92, 246, 0.8)',
    cyan: 'rgba(34, 211, 238, 0.8)',
    emerald: 'rgba(52, 211, 153, 0.8)',
    amber: 'rgba(251, 191, 36, 0.8)',
    rose: 'rgba(244, 63, 94, 0.8)',
    blue: 'rgba(59, 130, 246, 0.8)',
};

const chartDefaults = {
    responsive: true,
    maintainAspectRatio: true,
    aspectRatio: 2,
    plugins: {
        legend: {
            labels: {
                color: '#94a3b8',
                font: { family: 'Inter', size: 11 },
                padding: 16,
                usePointStyle: true,
                pointStyleWidth: 8,
            }
        },
        tooltip: {
            backgroundColor: 'rgba(17, 24, 39, 0.95)',
            titleColor: '#f1f5f9',
            bodyColor: '#94a3b8',
            borderColor: 'rgba(99, 102, 241, 0.3)',
            borderWidth: 1,
            cornerRadius: 8,
            padding: 12,
            titleFont: { family: 'Inter', weight: '600' },
            bodyFont: { family: 'JetBrains Mono', size: 12 },
        },
    },
    scales: {
        x: {
            grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
            ticks: { color: '#64748b', font: { family: 'Inter', size: 10 } },
        },
        y: {
            grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
            ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 10 } },
        },
    },
};

function initCharts() {
    // Throughput chart (line)
    const throughputCtx = document.getElementById('chart-throughput');
    if (throughputCtx) {
        charts.throughput = new Chart(throughputCtx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Ingested',
                        data: [],
                        borderColor: chartColors.indigo,
                        backgroundColor: 'rgba(99, 102, 241, 0.1)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                    },
                    {
                        label: 'Processed',
                        data: [],
                        borderColor: chartColors.emerald,
                        backgroundColor: 'rgba(52, 211, 153, 0.08)',
                        fill: true,
                        tension: 0.4,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                    },
                ],
            },
            options: { ...chartDefaults },
        });
    }

    // Categories chart (doughnut)
    const catCtx = document.getElementById('chart-categories');
    if (catCtx) {
        charts.categories = new Chart(catCtx, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: [{
                    data: [],
                    backgroundColor: Object.values(chartColors),
                    borderWidth: 0,
                    hoverOffset: 8,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: true,
                aspectRatio: 2,
                cutout: '65%',
                plugins: {
                    legend: {
                        position: 'right',
                        labels: {
                            color: '#94a3b8',
                            font: { family: 'Inter', size: 11 },
                            padding: 12,
                            usePointStyle: true,
                        },
                    },
                    tooltip: chartDefaults.plugins.tooltip,
                },
            },
        });
    }

    // Latency distribution (bar)
    const latCtx = document.getElementById('chart-latency-dist');
    if (latCtx) {
        charts.latency = new Chart(latCtx, {
            type: 'bar',
            data: {
                labels: ['Ingestion', 'Processing', 'Analytics', 'Notification'],
                datasets: [{
                    label: 'Avg Latency (ms)',
                    data: [0, 0, 0, 0],
                    backgroundColor: [
                        chartColors.indigo, chartColors.violet,
                        chartColors.cyan, chartColors.amber,
                    ],
                    borderRadius: 6,
                    borderSkipped: false,
                }],
            },
            options: { ...chartDefaults },
        });
    }

    // Cost chart (bar horizontal)
    const costCtx = document.getElementById('chart-cost');
    if (costCtx) {
        charts.cost = new Chart(costCtx, {
            type: 'bar',
            data: {
                labels: ['Lambda', 'DynamoDB', 'API Gateway', 'S3'],
                datasets: [{
                    label: 'Cost ($)',
                    data: [0, 0, 0, 0],
                    backgroundColor: [
                        chartColors.amber, chartColors.blue,
                        chartColors.indigo, chartColors.emerald,
                    ],
                    borderRadius: 6,
                    borderSkipped: false,
                }],
            },
            options: {
                ...chartDefaults,
                indexAxis: 'y',
            },
        });
    }
}

function updateCharts(data) {
    // Throughput chart — use hourly trends
    const hourlyTrends = data.hourly_trends || [];
    if (charts.throughput && hourlyTrends.length > 0) {
        // Group by period and aggregate
        const grouped = {};
        hourlyTrends.forEach(item => {
            const period = item.period || '';
            const key = period.replace('hourly#', '').substring(11, 16); // HH:MM
            if (!grouped[key]) grouped[key] = { ingested: 0, processed: 0 };
            if (item.metric_name === 'records_processed' || item.metric_name === 'throughput') {
                grouped[key].processed += item.count || 0;
            } else {
                grouped[key].ingested += item.count || 0;
            }
        });

        const labels = Object.keys(grouped).sort().slice(-12);
        charts.throughput.data.labels = labels;
        charts.throughput.data.datasets[0].data = labels.map(l => grouped[l]?.ingested || 0);
        charts.throughput.data.datasets[1].data = labels.map(l => grouped[l]?.processed || 0);
        charts.throughput.update('none');
    }

    // Categories chart
    const categories = data.category_breakdown || {};
    if (charts.categories && Object.keys(categories).length > 0) {
        const catLabels = Object.keys(categories).filter(c => c !== 'global' && c !== 'counter' && c !== 'throughput');
        const catData = catLabels.map(c => categories[c]?.total_count || 0);
        charts.categories.data.labels = catLabels.map(l => l.charAt(0).toUpperCase() + l.slice(1));
        charts.categories.data.datasets[0].data = catData;
        charts.categories.update('none');
    }

    // Service latency
    const svcMetrics = data.service_metrics || {};
    if (charts.latency) {
        const getAvgLatency = (svc) => {
            const gauges = svcMetrics[svc]?.gauges || {};
            const dur = gauges['lambda_execution_duration'] || gauges['lambda_execution_duration_duration'] || {};
            return dur.avg || 0;
        };
        charts.latency.data.datasets[0].data = [
            getAvgLatency('ingestion-service'),
            getAvgLatency('processing-service'),
            getAvgLatency('analytics-service'),
            getAvgLatency('notification-service'),
        ].map(v => parseFloat(v.toFixed(2)));
        charts.latency.update('none');
    }

    // Cost chart
    const costData = data.cost_analysis || {};
    if (charts.cost) {
        let lambdaCost = 0, dynamoCost = 0, apiCost = 0;
        for (const svc of Object.values(costData)) {
            lambdaCost += svc.lambda?.total || 0;
            dynamoCost += svc.dynamodb?.total || 0;
            apiCost += svc.api_gateway?.cost || 0;
        }
        charts.cost.data.datasets[0].data = [
            parseFloat((lambdaCost * 1000).toFixed(4)),
            parseFloat((dynamoCost * 1000).toFixed(4)),
            parseFloat((apiCost * 1000).toFixed(4)),
            0.001, // S3 placeholder
        ];
        charts.cost.update('none');
    }
}

// ============================================
// Utility — add spinning animation for loading button
// ============================================
const style = document.createElement('style');
style.textContent = `
    @keyframes spin { to { transform: rotate(360deg); } }
    .spin { animation: spin 1s linear infinite; }
`;
document.head.appendChild(style);
