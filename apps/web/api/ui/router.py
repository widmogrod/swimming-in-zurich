"""The UI endpoint: a single self-contained HTML page (no build step, no external assets)
over the JSON API — a swim finder, an all-pools browser, and an access-type legend.

The "Find a swim" results embody the unified monospace visual language (see
``docs/plan/2026-07-19-ux-ascii-design.md``): a fat length badge, orthogonal access
(``≈◇⌂WSX·``) and eligibility (``✓✗?``) glyph axes, the three never-merged terminal
states (open ``·closes`` / closed-with-reason / uncurated), a ``ⓘ valid_as_of · source``
provenance stamp, and the shared legend. Lane count is deferred to a later slice, so the
badge degrades to length-only."""

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
  :root { color-scheme: light dark; --mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace; }
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

  /* --- unified monospace swim-card language --- */
  .glyphlegend { font-family: var(--mono); font-size: .8rem; white-space: pre; overflow-x: auto;
    border: 1px solid #8886; border-radius: .4rem; padding: .6rem .8rem; margin: 1rem 0; opacity: .85; }
  .card { display: flex; gap: .8rem; align-items: stretch; border: 1px solid #8886;
    border-radius: .5rem; padding: .7rem; margin: .8rem 0; }
  .lenbadge { font-family: var(--mono); flex: 0 0 auto; min-width: 5.5rem; display: flex;
    flex-direction: column; align-items: center; justify-content: center; text-align: center;
    border: 2px solid #8888; border-radius: .4rem; padding: .4rem .3rem; }
  .lenbadge .len { font-size: 1.5rem; font-weight: 700; line-height: 1.1; }
  .lenbadge .kind { font-size: .7rem; opacity: .7; text-transform: uppercase; letter-spacing: .05em; }
  .card .body { flex: 1 1 auto; min-width: 0; }
  .card .head { display: flex; justify-content: space-between; gap: .6rem; flex-wrap: wrap; }
  .card .name { font-weight: 600; }
  .glyph { font-family: var(--mono); font-weight: 700; }
  .axis-access { }
  .axis-elig.in { color: #15803d; }
  .axis-elig.out { color: #b91c1c; }
  .axis-elig.unk { color: #b45309; }
  .state { font-family: var(--mono); font-size: .85rem; white-space: nowrap; }
  .state.open { color: #15803d; }
  .state.upcoming { opacity: .8; }
  .card .metaline { font-size: .85rem; opacity: .8; margin-top: .2rem; }
  .card .reason { font-size: .8rem; opacity: .65; margin-top: .2rem; }
  .notshown { margin-top: 1.2rem; }
  .notshown .sep { font-family: var(--mono); opacity: .6; font-size: .8rem;
    border-top: 1px dashed #8886; padding-top: .5rem; }
  .status { font-family: var(--mono); font-size: .85rem; padding: .2rem 0; }
  .status.closed { color: #b91c1c; }
  .status.uncurated { color: #b45309; }
  .prov { font-family: var(--mono); font-size: .8rem; opacity: .7; margin-top: 1rem;
    border-top: 1px solid #8884; padding-top: .5rem; }
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
  <pre class="glyphlegend">ACCESS   ≈ lane   ◇ public   ⌂ family   W women   S seniors   X reserved   · closed
FOR YOU  ✓ in     ✗ not you   ? unknown
STATUS   OPEN ·closes HH:MM     CLOSED ⊘ reason     UNCURATED ? schedule unknown
PROV     ⓘ valid_as_of · source · (curated|scraped)</pre>
  <div id="findOut"></div>
  <div class="legend"><h3>Access types</h3><dl id="legend"></dl></div>
</section>

<section id="all">
  <div class="chips" id="kinds"></div>
  <div id="allOut"></div>
</section>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
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

// Access glyph axis (what the water IS) — orthogonal to eligibility.
const ACCESS_GLYPH = { LaneSwim:'≈', PublicSwim:'◇', FamilyTime:'⌂',
  WomenOnly:'W', SeniorsOnly:'S', SchoolReserved:'X', ClubReserved:'X', AdultsOnly:'◇' };
const ACCESS_LABEL = { LaneSwim:'LANE', PublicSwim:'PUBLIC', FamilyTime:'FAMILY',
  WomenOnly:'WOMEN', SeniorsOnly:'SENIORS', SchoolReserved:'SCHOOL', ClubReserved:'CLUB',
  AdultsOnly:'ADULTS' };
const accessGlyph = a => ACCESS_GLYPH[a] || '◇';
const accessLabel = a => ACCESS_LABEL[a] || a;
// Eligibility glyph axis (whether it's YOU) — ? = not determinable (unknown), never merged with ✗.
function eligAxis(o) {
  if (o.eligible) return { g:'✓', cls:'in' };
  if (/determine eligibility|confirm admission/.test(o.reason)) return { g:'?', cls:'unk' };
  return { g:'✗', cls:'out' };
}
function optionCard(o) {
  const badge = o.length_m != null
    ? `<span class="len">${esc(o.length_m)} m</span>`
    : `<span class="len">pool</span>`;
  // Three terminal states, per card: OPEN (with closing time) vs. an upcoming window today.
  const state = o.open_now
    ? `<span class="state open">OPEN · closes ${esc(o.end)}</span>`
    : `<span class="state upcoming">${esc(o.start)}–${esc(o.end)} today</span>`;
  const el = eligAxis(o);
  const meta = [o.distance_km != null ? o.distance_km + ' km' : null, o.price]
    .filter(Boolean).map(esc).join(' · ');
  return `<article class="card">
    <div class="lenbadge">${badge}<span class="kind">${esc(o.kind)}</span></div>
    <div class="body">
      <div class="head"><span class="name">${esc(o.facility)} · ${esc(o.basin)}</span>${state}</div>
      <div class="metaline">
        <span class="glyph axis-access">${esc(accessGlyph(o.access))}</span> ${esc(accessLabel(o.access))}
        &nbsp; <span class="glyph axis-elig ${el.cls}">${el.g}</span>
        ${meta ? '&nbsp; ' + meta : ''}
      </div>
      <div class="reason">${esc(o.reason)}</div>
    </div>
  </article>`;
}

// The three terminal states are never merged: closed-with-reason and uncurated are
// rendered distinctly here, below the open options.
function statusLine(s) {
  if (s.status === 'closed')
    return `<div class="status closed">⊘ ${esc(s.facility)} CLOSED — ${esc(s.detail)}</div>`;
  if (s.status === 'uncurated')
    return `<div class="status uncurated">? ${esc(s.facility)} UNCURATED — schedule unknown, NOT closed</div>`;
  return `<div class="status">${esc(s.facility)} — ${esc(s.detail)}</div>`;
}

// ⓘ provenance stamp aggregated across the shown options (freshness + source + curated).
function provStamp(options) {
  const dates = options.map(o => o.valid_as_of).filter(Boolean).sort();
  if (!dates.length && !options.length) return '';
  const sources = [...new Set(options.map(o => o.source).filter(Boolean))];
  const allCurated = options.every(o => o.curated);
  const noneCurated = options.every(o => !o.curated);
  const mode = allCurated ? 'curated' : noneCurated ? 'scraped' : 'mixed';
  const asOf = dates.length ? 'valid as of ' + esc(dates[0]) + ' · ' : '';
  return `<div class="prov">ⓘ schedules ${asOf}${esc(sources.join(', ') || 'unknown source')} (${mode})</div>`;
}

f.addEventListener('submit', async e => {
  e.preventDefault();
  const p = new URLSearchParams();
  for (const [k, v] of new FormData(f)) if (v !== '') p.append(k, v);
  findOut.innerHTML = '<p class="muted">Searching…</p>';
  const r = await fetch('/swim?' + p);
  if (!r.ok) { findOut.innerHTML = '<p class="warn">' + esc((await r.json()).detail) + '</p>'; return; }
  const a = await r.json();
  let h = a.notices.map(n => '<p class="warn">📣 <strong>' + esc(n.facility) + '</strong>: ' + esc(n.text) + '</p>').join('');
  h += a.warnings.map(w => '<p class="warn">⚠ ' + esc(w) + '</p>').join('');
  if (!a.options.length) h += '<p>No open, eligible sessions for that moment.</p>';
  else h += a.options.map(optionCard).join('');
  if (a.statuses.length)
    h += '<div class="notshown"><div class="sep">not shown as options</div>'
       + a.statuses.map(statusLine).join('') + '</div>';
  h += provStamp(a.options);
  findOut.innerHTML = h;
});

// access legend
fetch('/access-types').then(r => r.json()).then(a => {
  $('#legend').innerHTML = a.types.map(t => `<dt>${esc(t.label)}</dt><dd>${esc(t.description)}</dd>`).join('');
});

// --- All pools ---
let allLoaded = false, currentKind = null;
async function loadPools() {
  allLoaded = true;
  const r = await fetch('/pools');
  const a = await r.json();
  $('#kinds').innerHTML = ['<button class="chip active" data-kind="">all (' + a.count + ')</button>']
    .concat(a.kinds.map(k => `<button class="chip" data-kind="${esc(k)}">${esc(k)}</button>`)).join('');
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
    h += `<tr><td>${esc(p.name)}</td><td><span class="badge">${esc(p.kind)}</span></td><td>${esc(p.address)}</td><td>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">official ↗</a>` : ''}</td></tr>`;
  $('#allOut').innerHTML = h + '</tbody></table>';
}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=_PAGE)
