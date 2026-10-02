DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SMS simulation metrics</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #09111f; color: #e8edf7; }
    main { width: min(1100px, calc(100% - 32px)); margin: 40px auto; }
    header { display: flex; align-items: end; justify-content: space-between; gap: 20px; }
    h1 { margin: 0; font-size: clamp(1.7rem, 4vw, 2.7rem); }
    .muted { color: #9aa9c2; }
    #connection { font-size: .9rem; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 28px 0; }
    .card, .table-wrap { background: #101b2d; border: 1px solid #22324c; border-radius: 14px; box-shadow: 0 16px 45px #0004; }
    .card { padding: 18px; }
    .label { color: #9aa9c2; font-size: .78rem; text-transform: uppercase; letter-spacing: .08em; }
    .value { font-size: 1.8rem; font-variant-numeric: tabular-nums; margin-top: 8px; }
    .sent { color: #67e8a5; } .failed { color: #ff8e9a; }
    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; min-width: 760px; }
    th, td { text-align: left; padding: 13px 16px; border-bottom: 1px solid #22324c; }
    th { color: #9aa9c2; font-size: .75rem; text-transform: uppercase; letter-spacing: .06em; }
    tr:last-child td { border-bottom: 0; }
    .pill { display: inline-block; padding: 3px 9px; border-radius: 999px; background: #1b2a42; }
    @media (max-width: 600px) { main { margin: 24px auto; } header { align-items: start; flex-direction: column; } }
  </style>
</head>
<body>
<main>
  <header><div><div class="muted">Live dashboard</div><h1>SMS delivery metrics</h1></div><div id="connection" class="muted">Connecting…</div></header>
  <section class="grid">
    <div class="card"><div class="label">Attempts</div><div class="value" id="total">0</div></div>
    <div class="card"><div class="label">Sent</div><div class="value sent" id="sent">0</div></div>
    <div class="card"><div class="label">Failed</div><div class="value failed" id="failed">0</div></div>
    <div class="card"><div class="label">Failure rate</div><div class="value" id="rate">0%</div></div>
    <div class="card"><div class="label">Average duration</div><div class="value" id="duration">0 ms</div></div>
    <div class="card"><div class="label">P90 duration</div><div class="value" id="p90-duration">0 ms</div></div>
    <div class="card"><div class="label">P99 duration</div><div class="value" id="p99-duration">0 ms</div></div>
    <div class="card"><div class="label">Active senders</div><div class="value" id="senders">0</div></div>
  </section>
  <h2>Recent attempts</h2>
  <div class="table-wrap"><table><thead><tr><th>Time</th><th>Status</th><th>Sender</th><th>Duration</th><th>Message</th><th>Error</th></tr></thead><tbody id="events"><tr><td colspan="6" class="muted">No events yet</td></tr></tbody></table></div>
</main>
<script>
const byId = id => document.getElementById(id);
const shortId = value => value.slice(0, 8);
function renderEvents(events) {
  const body = byId('events');
  body.replaceChildren();
  if (!events.length) {
    const cell = document.createElement('td');
    cell.colSpan = 6; cell.className = 'muted'; cell.textContent = 'No events yet';
    const row = document.createElement('tr'); row.appendChild(cell); body.appendChild(row);
    return;
  }
  for (const event of events) {
    const row = document.createElement('tr');
    const values = [
      new Date(event.occurred_at).toLocaleTimeString(), event.status,
      event.sender_id, event.processing_duration_ms.toFixed(1) + ' ms',
      shortId(event.message_id), event.error_code ?? '—'
    ];
    values.forEach((value, index) => {
      const cell = document.createElement('td');
      if (index === 1) {
        const pill = document.createElement('span');
        pill.className = 'pill ' + event.status; pill.textContent = value;
        cell.appendChild(pill);
      } else { cell.textContent = value; }
      if (index === 4) cell.title = event.message_id;
      row.appendChild(cell);
    });
    body.appendChild(row);
  }
}
async function refresh() {
  try {
    const [summaryResponse, eventsResponse] = await Promise.all([
      fetch('/metrics/summary', {cache: 'no-store'}),
      fetch('/metrics?limit=25', {cache: 'no-store'})
    ]);
    if (!summaryResponse.ok || !eventsResponse.ok) throw new Error('API unavailable');
    const summary = await summaryResponse.json();
    const page = await eventsResponse.json();
    byId('total').textContent = summary.total.toLocaleString();
    byId('sent').textContent = summary.sent.toLocaleString();
    byId('failed').textContent = summary.failed.toLocaleString();
    byId('rate').textContent = (summary.failure_rate * 100).toFixed(1) + '%';
    byId('duration').textContent = summary.average_processing_duration_ms.toFixed(1) + ' ms';
    byId('p90-duration').textContent = summary.p90_processing_duration_ms.toFixed(1) + ' ms';
    byId('p99-duration').textContent = summary.p99_processing_duration_ms.toFixed(1) + ' ms';
    byId('senders').textContent = summary.sender_count.toLocaleString();
    renderEvents(page.items);
    byId('connection').textContent = 'Live · updated ' + new Date().toLocaleTimeString();
  } catch (error) { byId('connection').textContent = 'Disconnected · retrying'; }
}
refresh(); setInterval(refresh, 1000);
</script>
</body>
</html>
"""
