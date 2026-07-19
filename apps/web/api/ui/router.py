"""The UI endpoint: a single self-contained HTML page (no build step, no external assets)
over the JSON API — a swim finder, an all-pools browser, and an access-type legend.

The "Find a swim" results embody the unified monospace visual language (see
``docs/plan/2026-07-19-ux-ascii-design.md``): a fat length badge, orthogonal access
(``≈◇⌂WSX·``) and eligibility (``✓✗?``) glyph axes, the three never-merged terminal
states (open ``·closes`` / closed-with-reason / uncurated), a ``ⓘ valid_as_of · source``
provenance stamp, and the shared legend. The badge carries a ``N lane`` sub-line under the
length when the basin's lane count is known, degrading to length-only when it is not."""

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
  .lenbadge .lanes { font-size: .8rem; opacity: .8; line-height: 1.2; }
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

  /* --- tourist orientation primer --- */
  .primer { border: 1px solid #8886; border-radius: .5rem; padding: .8rem 1rem; margin: 1rem 0; font-size: .9rem; }
  .primer h3 { font-size: .95rem; margin: .2rem 0 .6rem; }
  .primer dt { font-weight: 600; margin-top: .6rem; font-family: var(--mono); font-size: .82rem;
    letter-spacing: .03em; }
  .primer dt .muted { font-weight: 400; }
  .primer dd { margin: .1rem 0 .2rem; opacity: .85; }
  .card .decode { font-size: .82rem; opacity: .85; margin-top: .3rem; }
  .card .decode b { font-weight: 600; }
</style>
</head>
<body>
<h1>🏊 Swimming in Zürich</h1>
<p class="muted">Locations from the city open data (WFS). Schedules are curated/illustrative — verify on-site via the official link.</p>

<nav>
  <button data-tab="find" class="active">Find a swim</button>
  <button data-tab="visit">First time here?</button>
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

<section id="visit">
  <p class="muted">New to Zürich? Start here — the vocabulary you need, then a few pools to try. Closed pools stay on the list (a locked door is worse than a long word).</p>
  <form id="vf">
    <label>Staying near
      <select name="place">
        <option value="47.3779,8.5403">Zürich HB (main station)</option>
        <option value="47.3671,8.5451">Bellevue</option>
        <option value="47.3606,8.5510">Zürichhorn</option>
      </select>
    </label>
    <label>Radius (km)<input type="number" name="radius_km" min="1" max="30" value="5"></label>
    <label>Age<input type="number" name="age" min="0" max="120" placeholder="optional"></label>
    <label>Gender
      <select name="gender">
        <option value="">any</option><option value="female">female</option>
        <option value="male">male</option><option value="diverse">diverse</option>
      </select>
    </label>
    <button type="submit">Show me starter pools</button>
  </form>
  <div class="primer" id="primer"></div>
  <div id="visitOut"></div>
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
  if (b.dataset.tab === 'visit' && !visitLoaded) loadVisit();
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
  // Lane count sub-line — real datum from the basin; absent => length-only (honest degrade).
  const lanes = o.lanes != null ? `<span class="lanes">${esc(o.lanes)} lane</span>` : '';
  // Three terminal states, per card: OPEN (with closing time) vs. an upcoming window today.
  const state = o.open_now
    ? `<span class="state open">OPEN · closes ${esc(o.end)}</span>`
    : `<span class="state upcoming">${esc(o.start)}–${esc(o.end)} today</span>`;
  const el = eligAxis(o);
  const meta = [o.distance_km != null ? o.distance_km + ' km' : null, o.price]
    .filter(Boolean).map(esc).join(' · ');
  return `<article class="card">
    <div class="lenbadge">${badge}${lanes}<span class="kind">${esc(o.kind)}</span></div>
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

// --- First time here? (tourist orientation) ---
// Plain-language primer + a few distance-ranked starter pools with jargon decoded inline.
// Reuses the shared /swim, /pools, /access-types responses and the unified card helpers
// above — no new endpoints, no invented data.
const vf = $('#vf'), visitOut = $('#visitOut');

// Pool TYPES keyed off the catalog `kind` value → the German label + a plain-English gloss.
const POOL_TYPES = {
  indoor: ['Hallenbad', 'indoor pool — open all year, the reliable winter choice'],
  outdoor: ['Freibad', 'outdoor pool — summer season only'],
  river: ['Flussbad', 'river bath on the Limmat — summer only'],
  lake: ['Seebad', 'lake bath on the Zürichsee — summer only'],
  school: ['Schulschwimmanlage', 'school pool — limited public hours'],
  paddling: ['Planschbecken', 'shallow paddling pool for small children'],
  thermal: ['Wärmebad', 'warm / thermal pool'],
};
// A session's access type decoded for a newcomer: German term → what it lets YOU do.
const DECODE = {
  PublicSwim: ['Öffentlich', 'public swim — anyone may enter'],
  LaneSwim: ['Bahnenschwimmen', 'lap swimming — public, organised into lanes'],
  FamilyTime: ['Familienbad', 'family time — public, family-focused'],
  WomenOnly: ['Frauenbad', 'women only'],
  SeniorsOnly: ['Seniorenschwimmen', 'seniors only'],
  SchoolReserved: ['Schule', 'school-reserved — not open to the public'],
  ClubReserved: ['Verein', 'club-reserved — not open to the public'],
  AdultsOnly: ['Erwachsene', 'adults only'],
};
const decodeAccess = a => { const d = DECODE[a]; return d ? d[0] + ' — ' + d[1] : accessLabel(a); };

let visitLoaded = false;
async function loadVisit() {
  visitLoaded = true;
  // Pool-type gloss is keyed off the catalog's kinds; the slot glossary is the /access-types data.
  const [pools, access] = await Promise.all([
    fetch('/pools').then(r => r.json()),
    fetch('/access-types').then(r => r.json()),
  ]);
  const types = pools.kinds.map(k => {
    const t = POOL_TYPES[k];
    return t
      ? `<dt>${esc(t[0])} <span class="muted">(${esc(k)})</span></dt><dd>${esc(t[1])}</dd>`
      : `<dt>${esc(k)}</dt><dd>a Zürich pool category</dd>`;
  }).join('');
  const slots = access.types.map(t =>
    `<dt>${esc(t.label)}</dt><dd>${esc(t.description)}</dd>`).join('');
  $('#primer').innerHTML =
    '<h3>First time here?</h3><dl>'
    + '<dt>POOL TYPES</dt><dd>Zürich names its water by kind:</dd>' + types
    + '<dt>TO ENTER</dt><dd>Walk in and pay in CHF at the door. No booking, no membership card needed.</dd>'
    + '<dt>TO BRING</dt><dd>Swimsuit and towel. Lockers are on site.</dd>'
    + '<dt>THE SLOTS</dt><dd>What each kind of session lets you do:</dd>' + slots
    + '</dl>';
  vf.dispatchEvent(new Event('submit'));  // show starter pools immediately with defaults
}

// A starter-pool card: the S1 badge + orthogonal glyph axes, jargon decoded inline, km only.
// Walk/transit time is deliberately never shown — there is no routing model (gap #4).
function starterCard(o, mark) {
  const badge = o.length_m != null
    ? `<span class="len">${esc(o.length_m)} m</span>`
    : `<span class="len">pool</span>`;
  const lanes = o.lanes != null ? `<span class="lanes">${esc(o.lanes)} lane</span>` : '';
  const state = o.open_now
    ? `<span class="state open">OPEN · closes ${esc(o.end)}</span>`
    : `<span class="state upcoming">${esc(o.start)}–${esc(o.end)} today</span>`;
  const el = eligAxis(o);
  const meta = [o.distance_km != null ? o.distance_km + ' km' : null, o.price]
    .filter(Boolean).map(esc).join(' · ');
  return `<article class="card">
    <div class="lenbadge"><span class="kind">${esc(mark)}</span>${badge}${lanes}</div>
    <div class="body">
      <div class="head"><span class="name">${esc(o.facility)} · ${esc(o.basin)}</span>${state}</div>
      <div class="metaline">
        <span class="glyph axis-access">${esc(accessGlyph(o.access))}</span>
        <span class="glyph axis-elig ${el.cls}">${el.g}</span>
        ${meta ? '&nbsp; ' + meta : ''}
      </div>
      <div class="decode">This slot is <b>${esc(decodeAccess(o.access))}</b>.</div>
    </div>
  </article>`;
}

vf.addEventListener('submit', async e => {
  e.preventDefault();
  const now = new Date(); now.setSeconds(0, 0);
  const [lat, lon] = vf.place.value.split(',');
  const p = new URLSearchParams();
  p.append('at', new Date(now.getTime() - now.getTimezoneOffset()*60000).toISOString().slice(0,16));
  p.append('lat', lat); p.append('lon', lon);
  if (vf.radius_km.value) p.append('radius_km', vf.radius_km.value);
  if (vf.age.value) p.append('age', vf.age.value);
  if (vf.gender.value) p.append('gender', vf.gender.value);
  p.append('eligible_only', 'false');  // a newcomer sees every nearby option, ✓/✗/? and all
  visitOut.innerHTML = '<p class="muted">Finding pools near you…</p>';
  const r = await fetch('/swim?' + p);
  if (!r.ok) { visitOut.innerHTML = '<p class="warn">' + esc((await r.json()).detail) + '</p>'; return; }
  const a = await r.json();
  let h = '<h3>Starter pools near you</h3>';
  const marks = ['①', '②', '③'];
  const starters = a.options.slice(0, 3);  // 2–3 distance-ranked (the service sorts by distance)
  if (!starters.length)
    h += '<p class="muted">No open sessions at this minute — the pools below are not shut, just unscheduled or closed for now.</p>';
  else h += starters.map((o, i) => starterCard(o, marks[i] || (i+1))).join('');
  // Closed / uncurated pools are ALWAYS kept visible for a newcomer — never hidden.
  if (a.statuses.length)
    h += '<div class="notshown"><div class="sep">also nearby — not open right now, but NOT necessarily shut</div>'
       + a.statuses.map(statusLine).join('') + '</div>';
  h += provStamp(a.options);
  h += '<p class="warn">⚠ Only 7 of ~57 Zürich pools have verified timetables. The rest show as “unknown” — which is NOT the same as closed.</p>';
  visitOut.innerHTML = h;
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
