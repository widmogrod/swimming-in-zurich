"""The UI endpoint: a single self-contained HTML page that calls /swim and renders it.

Intentionally dependency-free (no build step, no external assets) — a thin front-end over
the JSON API. Kept as one string so the service stays a single deployable with no static
files to package.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Swimming in Zürich</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; max-width: 820px; margin: 2rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; }
  form { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .75rem; align-items: end; }
  label { display: flex; flex-direction: column; font-size: .85rem; gap: .25rem; }
  input, select, button { padding: .5rem; font-size: 1rem; }
  button { grid-column: 1 / -1; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #8884; font-size: .9rem; }
  .muted { opacity: .7; font-size: .85rem; }
  .warn { color: #b45309; }
  .badge { display: inline-block; padding: .05rem .4rem; border-radius: .4rem; background: #8882; font-size: .8rem; }
</style>
</head>
<body>
<h1>🏊 Where can I swim in Zürich?</h1>
<p class="muted">Indoor pools. Data is curated and illustrative &mdash; verify on-site.</p>
<form id="f">
  <label>When<input type="datetime-local" name="at" required></label>
  <label>Gender
    <select name="gender">
      <option value="">any</option>
      <option value="female">female</option>
      <option value="male">male</option>
      <option value="diverse">diverse</option>
    </select>
  </label>
  <label>Age<input type="number" name="age" min="0" max="120" placeholder="optional"></label>
  <label>Only eligible
    <select name="eligible_only"><option value="true">yes</option><option value="false">no</option></select>
  </label>
  <button type="submit">Find pools</button>
</form>
<div id="out"></div>
<script>
const f = document.getElementById('f'), out = document.getElementById('out');
// default "when" to now (local)
const now = new Date(); now.setSeconds(0, 0);
f.at.value = new Date(now.getTime() - now.getTimezoneOffset()*60000).toISOString().slice(0,16);
f.addEventListener('submit', async (e) => {
  e.preventDefault();
  const p = new URLSearchParams();
  for (const [k, v] of new FormData(f)) if (v !== '') p.append(k, v);
  out.innerHTML = '<p class="muted">Searching…</p>';
  const r = await fetch('/swim?' + p.toString());
  if (!r.ok) { out.innerHTML = '<p class="warn">' + (await r.json()).detail + '</p>'; return; }
  const a = await r.json();
  let html = '';
  for (const w of a.warnings) html += '<p class="warn">⚠ ' + w + '</p>';
  if (a.options.length === 0) html += '<p>No open, eligible sessions for that moment.</p>';
  else {
    html += '<table><thead><tr><th>Pool</th><th>Basin</th><th>Time</th><th>Access</th><th>Price</th><th></th></tr></thead><tbody>';
    for (const o of a.options) {
      html += '<tr><td>' + o.facility + '</td><td>' + o.basin + '</td><td>' + o.start + '–' + o.end +
        '</td><td>' + o.access + '</td><td>' + (o.price ?? '—') + '</td><td>' +
        (o.open_now ? '<span class="badge">open now</span>' : '') + '</td></tr>';
    }
    html += '</tbody></table>';
  }
  if (a.statuses.length) {
    html += '<p class="muted">Not available: ' +
      a.statuses.map(s => s.facility + ' (' + s.detail + ')').join('; ') + '</p>';
  }
  out.innerHTML = html;
});
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=_PAGE)
