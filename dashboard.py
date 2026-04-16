"""Dashboard HTML for the API statistics page."""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TwAPI Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --text2: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --blue: #58a6ff; --purple: #bc8cff;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; }
  .header { background: var(--card); border-bottom: 1px solid var(--border); padding: 16px 24px; display: flex; align-items: center; justify-content: space-between; }
  .header h1 { font-size: 20px; font-weight: 600; }
  .header h1 span { color: var(--accent); }
  .header-right { display: flex; align-items: center; gap: 12px; }
  .header-right select, .header-right button {
    background: var(--bg); border: 1px solid var(--border); color: var(--text);
    padding: 6px 12px; border-radius: 6px; font-size: 13px; cursor: pointer;
  }
  .header-right button:hover { border-color: var(--accent); }
  .live-dot { width: 8px; height: 8px; background: var(--green); border-radius: 50%; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
  .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .card .label { font-size: 12px; color: var(--text2); text-transform: uppercase; letter-spacing: .5px; margin-bottom: 4px; }
  .card .value { font-size: 28px; font-weight: 700; }
  .card .sub { font-size: 12px; color: var(--text2); margin-top: 2px; }
  .card .value.green { color: var(--green); }
  .card .value.red { color: var(--red); }
  .card .value.blue { color: var(--blue); }
  .card .value.yellow { color: var(--yellow); }
  .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 20px; }
  @media (max-width: 768px) { .grid2 { grid-template-columns: 1fr; } }
  .panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
  .panel h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text2); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--text2); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
  td { padding: 6px 8px; border-bottom: 1px solid var(--border); }
  tr:last-child td { border: none; }
  .status-ok { color: var(--green); }
  .status-err { color: var(--red); }
  .bar-wrap { background: var(--bg); border-radius: 4px; height: 8px; overflow: hidden; }
  .bar-fill { height: 100%; border-radius: 4px; transition: width .5s; }
  .chart-area { position: relative; height: 200px; margin-top: 8px; }
  canvas { width: 100% !important; height: 100% !important; }
  .log-panel { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-top: 12px; }
  .log-panel h3 { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: var(--text2); }
  .log-row { display: grid; grid-template-columns: 150px 50px 200px 80px 80px 1fr; gap: 4px; padding: 4px 0; border-bottom: 1px solid var(--border); font-size: 12px; font-family: monospace; }
  .log-row:last-child { border: none; }
  .log-header { color: var(--text2); font-weight: 600; font-family: sans-serif; }
  .empty { text-align: center; padding: 40px; color: var(--text2); }
</style>
</head>
<body>
<div class="header">
  <h1>📊 <span>TwAPI</span> Dashboard</h1>
  <div class="header-right">
    <div class="live-dot" id="liveDot"></div>
    <select id="period" onchange="refresh()">
      <option value="1">Last 1 hour</option>
      <option value="6">Last 6 hours</option>
      <option value="24" selected>Last 24 hours</option>
      <option value="72">Last 3 days</option>
      <option value="168">Last 7 days</option>
    </select>
    <button onclick="refresh()">⟳ Refresh</button>
  </div>
</div>

<div class="container">
  <!-- Summary cards -->
  <div class="cards" id="cards"></div>

  <div class="grid2">
    <!-- Chart -->
    <div class="panel">
      <h3>📈 Requests Over Time</h3>
      <div class="chart-area"><canvas id="chart"></canvas></div>
    </div>
    <!-- Endpoint breakdown -->
    <div class="panel">
      <h3>🎯 Endpoint Breakdown</h3>
      <table id="epTable"><thead><tr><th>Endpoint</th><th>Calls</th><th>Success</th><th>Avg ms</th><th></th></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div class="grid2">
    <!-- Status codes -->
    <div class="panel">
      <h3>📋 Status Codes</h3>
      <table id="statusTable"><thead><tr><th>Code</th><th>Count</th><th></th></tr></thead><tbody></tbody></table>
    </div>
    <!-- Top paths -->
    <div class="panel">
      <h3>🔗 Top Paths</h3>
      <table id="pathTable"><thead><tr><th>Path</th><th>Calls</th></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <!-- Recent calls -->
  <div class="log-panel">
    <h3>📜 Recent API Calls</h3>
    <div class="log-row log-header"><span>Timestamp</span><span>Code</span><span>Path</span><span>Latency</span><span>Method</span><span>Query</span></div>
    <div id="logRows"></div>
  </div>
</div>

<script>
let chartCanvas, chartCtx;

async function refresh() {
  const hours = document.getElementById('period').value;
  try {
    const [statsRes, recentRes] = await Promise.all([
      fetch(`/api/stats?hours=${hours}`),
      fetch(`/api/stats/recent?limit=100`)
    ]);
    const stats = await statsRes.json();
    const recent = await recentRes.json();
    renderCards(stats);
    renderEndpoints(stats.by_endpoint);
    renderStatus(stats.by_status_code);
    renderPaths(stats.top_paths);
    renderChart(stats.by_hour);
    renderLog(recent);
  } catch(e) {
    console.error('Refresh failed:', e);
  }
}

function renderCards(s) {
  const cards = document.getElementById('cards');
  cards.innerHTML = `
    <div class="card"><div class="label">Total Calls</div><div class="value blue">${fmt(s.total_calls)}</div></div>
    <div class="card"><div class="label">Success Rate</div><div class="value ${s.success_rate >= 90 ? 'green' : s.success_rate >= 50 ? 'yellow' : 'red'}">${s.success_rate}%</div><div class="sub">${fmt(s.success_count)} ok / ${fmt(s.error_count)} err</div></div>
    <div class="card"><div class="label">Avg Latency</div><div class="value">${fmtMs(s.avg_latency_ms)}</div><div class="sub">min ${fmtMs(s.min_latency_ms)} / max ${fmtMs(s.max_latency_ms)}</div></div>
    <div class="card"><div class="label">Endpoints</div><div class="value">${s.by_endpoint.length}</div></div>
    <div class="card"><div class="label">Errors</div><div class="value ${s.error_count > 0 ? 'red' : 'green'}">${fmt(s.error_count)}</div></div>
  `;
}

function renderEndpoints(eps) {
  const tbody = document.querySelector('#epTable tbody');
  if (!eps.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No data</td></tr>'; return; }
  const maxCalls = Math.max(...eps.map(e => e.calls));
  tbody.innerHTML = eps.map(e => {
    const pct = Math.round(e.calls / maxCalls * 100);
    const rate = e.calls > 0 ? Math.round(e.success / e.calls * 100) : 0;
    return `<tr>
      <td><code>${e.endpoint}</code></td><td>${fmt(e.calls)}</td>
      <td class="${rate >= 90 ? 'status-ok' : 'status-err'}">${rate}%</td>
      <td>${fmtMs(e.avg_ms)}</td>
      <td><div class="bar-wrap"><div class="bar-fill" style="width:${pct}%;background:var(--accent)"></div></div></td>
    </tr>`;
  }).join('');
}

function renderStatus(codes) {
  const tbody = document.querySelector('#statusTable tbody');
  if (!codes.length) { tbody.innerHTML = '<tr><td colspan="3" class="empty">No data</td></tr>'; return; }
  const maxC = Math.max(...codes.map(c => c.count));
  tbody.innerHTML = codes.map(c => {
    const cls = c.status_code < 400 ? 'status-ok' : 'status-err';
    const pct = Math.round(c.count / maxC * 100);
    const color = c.status_code < 400 ? 'var(--green)' : 'var(--red)';
    return `<tr><td class="${cls}">${c.status_code}</td><td>${fmt(c.count)}</td>
      <td><div class="bar-wrap"><div class="bar-fill" style="width:${pct}%;background:${color}"></div></div></td></tr>`;
  }).join('');
}

function renderPaths(paths) {
  const tbody = document.querySelector('#pathTable tbody');
  if (!paths.length) { tbody.innerHTML = '<tr><td colspan="2" class="empty">No data</td></tr>'; return; }
  tbody.innerHTML = paths.slice(0, 15).map(p =>
    `<tr><td><code>${esc(p.path)}</code></td><td>${fmt(p.calls)}</td></tr>`
  ).join('');
}

function renderChart(hours) {
  if (!chartCanvas) { chartCanvas = document.getElementById('chart'); chartCtx = chartCanvas.getContext('2d'); }
  const rect = chartCanvas.parentElement.getBoundingClientRect();
  chartCanvas.width = rect.width * 2; chartCanvas.height = rect.height * 2;
  const ctx = chartCtx; const w = chartCanvas.width; const h = chartCanvas.height;
  ctx.clearRect(0, 0, w, h);
  if (!hours.length) { ctx.fillStyle = '#8b949e'; ctx.font = '24px sans-serif'; ctx.textAlign = 'center'; ctx.fillText('No data', w/2, h/2); return; }

  const pad = {l:60, r:20, t:20, b:40};
  const cw = w - pad.l - pad.r; const ch = h - pad.t - pad.b;
  const maxVal = Math.max(...hours.map(h => h.calls), 1);
  const maxErr = Math.max(...hours.map(h => h.errors), 0);

  // Grid
  ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (ch / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(w - pad.r, y); ctx.stroke();
    ctx.fillStyle = '#8b949e'; ctx.font = '20px sans-serif'; ctx.textAlign = 'right';
    ctx.fillText(Math.round(maxVal * (4 - i) / 4), pad.l - 8, y + 6);
  }

  // X labels
  ctx.textAlign = 'center'; ctx.font = '18px sans-serif';
  const step = Math.max(1, Math.floor(hours.length / 8));
  hours.forEach((h, i) => {
    if (i % step === 0) {
      const x = pad.l + (i / (hours.length - 1 || 1)) * cw;
      ctx.fillStyle = '#8b949e'; ctx.fillText(h.hour.slice(11, 16), x, pad.t + ch + 28);
    }
  });

  // Calls line
  ctx.beginPath(); ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 3;
  hours.forEach((h, i) => {
    const x = pad.l + (i / (hours.length - 1 || 1)) * cw;
    const y = pad.t + ch - (h.calls / maxVal) * ch;
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Fill under calls
  ctx.lineTo(pad.l + cw, pad.t + ch); ctx.lineTo(pad.l, pad.t + ch); ctx.closePath();
  ctx.fillStyle = 'rgba(88,166,255,0.1)'; ctx.fill();

  // Error bars
  if (maxErr > 0) {
    ctx.fillStyle = 'rgba(248,81,73,0.6)';
    const barW = Math.max(4, cw / hours.length * 0.6);
    hours.forEach((h, i) => {
      if (h.errors > 0) {
        const x = pad.l + (i / (hours.length - 1 || 1)) * cw - barW / 2;
        const bh = (h.errors / maxVal) * ch;
        ctx.fillRect(x, pad.t + ch - bh, barW, bh);
      }
    });
  }

  // Avg latency dots
  const maxMs = Math.max(...hours.map(h => h.avg_ms || 0), 1);
  ctx.fillStyle = '#d29922';
  hours.forEach((h, i) => {
    if (h.avg_ms) {
      const x = pad.l + (i / (hours.length - 1 || 1)) * cw;
      const y = pad.t + ch - (h.avg_ms / maxMs) * ch * 0.8;
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
    }
  });
}

function renderLog(items) {
  const div = document.getElementById('logRows');
  if (!items.length) { div.innerHTML = '<div class="empty">No calls recorded yet</div>'; return; }
  div.innerHTML = items.map(c => {
    const ts = c.timestamp.replace('T', ' ').slice(0, 19);
    const cls = c.status_code < 400 ? 'status-ok' : 'status-err';
    return `<div class="log-row">
      <span>${ts}</span><span class="${cls}">${c.status_code}</span>
      <span>${esc(c.path)}</span><span>${fmtMs(c.latency_ms)}</span>
      <span>${c.method}</span><span style="color:var(--text2)">${esc(c.query).slice(0,60)}</span>
    </div>`;
  }).join('');
}

function fmt(n) { return n == null ? '0' : Number(n).toLocaleString(); }
function fmtMs(n) { return n == null ? '0ms' : (n >= 1000 ? (n/1000).toFixed(1)+'s' : Math.round(n)+'ms'); }
function esc(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

// Initial load + auto-refresh
refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>"""
