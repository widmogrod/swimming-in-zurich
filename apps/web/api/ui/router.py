"""The UI endpoint: a single self-contained HTML page (no build step, no external assets)
over the JSON API — a swim finder, an all-pools browser, and an access-type legend."""

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
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 1.5rem auto; padding: 0 1rem; }
  h1 { font-size: 1.4rem; margin-bottom: .2rem; }
  .muted { opacity: .7; font-size: .85rem; }
  .warn { color: #b45309; }
  nav { display: flex; gap: .5rem; margin: 1rem 0; }
  nav button { padding: .5rem 1rem; cursor: pointer; border: 1px solid #8886; background: transparent; border-radius: .4rem; font-size: 1rem; }
  nav button.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
  section { display: none; } section.active { display: block; }
  form { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: .75rem; align-items: end; }
  label { display: flex; flex-direction: column; font-size: .85rem; gap: .25rem; }
  input, select, button { padding: .5rem; font-size: 1rem; }
  form button { grid-column: 1 / -1; cursor: pointer; }
  table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
  th, td { text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #8884; font-size: .9rem; vertical-align: top; }
  .badge { display: inline-block; padding: .05rem .4rem; border-radius: .4rem; background: #8882; font-size: .8rem; }
  .chips { display: flex; flex-wrap: wrap; gap: .4rem; margin: .8rem 0; }
  .chip { padding: .3rem .7rem; border: 1px solid #8886; border-radius: 1rem; cursor: pointer; font-size: .85rem; background: transparent; }
  .chip.active { background: #3b82f6; color: #fff; border-color: #3b82f6; }
  .legend { margin-top: 1.5rem; font-size: .85rem; }
  .legend dt { font-weight: 600; margin-top: .5rem; }
  a { color: #3b82f6; }
</style>
</head>
<body>
<h1>🏊 Swimming in Zürich</h1>
<p class="muted">Locations from the city open data (WFS). Schedules are curated/illustrative — verify on-site via the official link.</p>

<nav>
  <button data-tab="find" class="active">Find a swim</button>
  <button data-tab="all">All pools</button>
</nav>

<section id="find" class="active">
  <form id="f">
    <label>When<input type="datetime-local" name="at" required></label>
    <label>Gender
      <select name="gender">
        <option value="">any</option><option value="female">female</option>
        <option value="male">male</option><option value="diverse">diverse</option>
      </select>
    </label>
    <label>Age<input type="number" name="age" min="0" max="120" placeholder="optional"></label>
    <label>Only eligible
      <select name="eligible_only"><option value="true">yes</option><option value="false">no</option></select>
    </label>
    <button type="submit">Find pools</button>
  </form>
  <div id="findOut"></div>
  <div class="legend"><h3>Access types</h3><dl id="legend"></dl></div>
</section>

<section id="all">
  <div class="chips" id="kinds"></div>
  <div id="allOut"></div>
</section>

<script>
const $ = s => document.querySelector(s);
// tabs
document.querySelectorAll('nav button').forEach(b => b.addEventListener('click', () => {
  document.querySelectorAll('nav button').forEach(x => x.classList.remove('active'));
  document.querySelectorAll('section').forEach(x => x.classList.remove('active'));
  b.classList.add('active'); $('#' + b.dataset.tab).classList.add('active');
  if (b.dataset.tab === 'all' && !allLoaded) loadPools();
}));

// --- Find a swim ---
const f = $('#f'), findOut = $('#findOut');
const now = new Date(); now.setSeconds(0, 0);
f.at.value = new Date(now.getTime() - now.getTimezoneOffset()*60000).toISOString().slice(0,16);
f.addEventListener('submit', async e => {
  e.preventDefault();
  const p = new URLSearchParams();
  for (const [k, v] of new FormData(f)) if (v !== '') p.append(k, v);
  findOut.innerHTML = '<p class="muted">Searching…</p>';
  const r = await fetch('/swim?' + p);
  if (!r.ok) { findOut.innerHTML = '<p class="warn">' + (await r.json()).detail + '</p>'; return; }
  const a = await r.json();
  let h = a.notices.map(n => '<p class="warn">📣 <strong>' + n.facility + '</strong>: ' + n.text + '</p>').join('');
  h += a.warnings.map(w => '<p class="warn">⚠ ' + w + '</p>').join('');
  if (!a.options.length) h += '<p>No open, eligible sessions for that moment.</p>';
  else {
    h += '<table><thead><tr><th>Pool</th><th>Basin</th><th>Time</th><th>Access</th><th>Price</th><th></th></tr></thead><tbody>';
    for (const o of a.options)
      h += `<tr><td>${o.facility}</td><td>${o.basin}</td><td>${o.start}–${o.end}</td><td>${o.access}</td><td>${o.price ?? '—'}</td><td>${o.open_now ? '<span class="badge">open now</span>' : ''}</td></tr>`;
    h += '</tbody></table>';
  }
  if (a.statuses.length) h += '<p class="muted">Not available: ' + a.statuses.map(s => `${s.facility} (${s.detail})`).join('; ') + '</p>';
  findOut.innerHTML = h;
});

// access legend
fetch('/access-types').then(r => r.json()).then(a => {
  $('#legend').innerHTML = a.types.map(t => `<dt>${t.label}</dt><dd>${t.description}</dd>`).join('');
});

// --- All pools ---
let allLoaded = false, currentKind = null;
async function loadPools() {
  allLoaded = true;
  const r = await fetch('/pools');
  const a = await r.json();
  $('#kinds').innerHTML = ['<button class="chip active" data-kind="">all (' + a.count + ')</button>']
    .concat(a.kinds.map(k => `<button class="chip" data-kind="${k}">${k}</button>`)).join('');
  document.querySelectorAll('#kinds .chip').forEach(c => c.addEventListener('click', () => {
    document.querySelectorAll('#kinds .chip').forEach(x => x.classList.remove('active'));
    c.classList.add('active'); currentKind = c.dataset.kind || null; renderPools(a.pools);
  }));
  renderPools(a.pools);
}
function renderPools(pools) {
  const items = currentKind ? pools.filter(p => p.kind === currentKind) : pools;
  let h = `<p class="muted">${items.length} pools</p><table><thead><tr><th>Name</th><th>Kind</th><th>Address</th><th></th></tr></thead><tbody>`;
  for (const p of items)
    h += `<tr><td>${p.name}</td><td><span class="badge">${p.kind}</span></td><td>${p.address}</td><td>${p.url ? `<a href="${p.url}" target="_blank" rel="noopener">official ↗</a>` : ''}</td></tr>`;
  $('#allOut').innerHTML = h + '</tbody></table>';
}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=_PAGE)
