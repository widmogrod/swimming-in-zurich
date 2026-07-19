"""The UI endpoint: a single self-contained HTML page (no build step, no external assets)
over the JSON API — a swim finder, a weekly planner grid, a tourist primer, and an
all-pools browser.

The "Plan my week" tab (Screen 2 in ``docs/plan/2026-07-19-ux-ascii-design.md``) is a
read-only days×time grid for the nearest pool: it assembles seven ``/swim`` calls — one per
weekday (Option A; ``find_swim_options`` returns a whole day's sessions per call) — into a
grid whose cells carry the same orthogonal access (``≈◇⌂WSX·``) and eligibility (``✓✗?``)
glyph axes plus the session's time range as VISIBLE cell text (not hover-only, invisible on
touch), inside a horizontal-scroll container so it stays a grid on a phone; busyness is
un-wired, so the grid states plainly "Busyness: not available yet." Closed and unknown days
are called out explicitly, never left as a blank that reads as "closed".

The "Find a swim" card leads with the ANSWER, not the filter (S4 #7): the facility name is the
hero (and the S3 link), then a bold colored status pill (open = green / an upcoming window =
amber, never opacity-only) paired with an eligibility WORD ("you're in" / "not for you" /
"check"), then distance/price, with the length + lane count demoted to a compact secondary tag
(kept — it's a real lap-swimmer filter — only shrunk). It still embodies the unified visual
language (see ``docs/plan/2026-07-19-ux-ascii-design.md``): orthogonal access (``≈◇⌂WSX·``)
and eligibility (``✓✗?``) glyph axes, the three never-merged terminal states (open ``·closes``
/ closed-with-reason / "Hours not listed yet"), an ``ⓘ Schedule last checked … · source``
provenance stamp in plain words, and — below the results in a default-closed "What do the
symbols mean?" expander — the shared glyph legend. The access word (sentence-cased from
``accessLabel``) reads on each card, not just the bare glyph. The length tag carries a
``N lane`` note when the basin's lane count is known, degrading to length-only when it is not."""

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
    border: 1px solid #8886; border-radius: .4rem; padding: .6rem .8rem; margin: .4rem 0 1rem; opacity: .85; }
  .symbols { margin: 1rem 0; }
  .symbols summary { cursor: pointer; opacity: .8; font-size: .85rem; }
  /* --- swim-card visual hierarchy (S4 #7): the facility NAME is the hero, then a bold
     colored status pill + an eligibility WORD, then distance/price, with length/lanes
     demoted to a small secondary tag (kept — it's a real lap-swimmer filter). --- */
  .card { border: 1px solid #8886; border-radius: .5rem; padding: .7rem .9rem; margin: .8rem 0; }
  .card .cardname { font-size: 1.15rem; font-weight: 700; line-height: 1.25; }
  .card .cardname .mark { font-family: var(--mono); font-weight: 400; opacity: .6; margin-right: .25rem; }
  .card .statusrow { display: flex; flex-wrap: wrap; align-items: center; gap: .5rem; margin: .35rem 0; }
  .glyph { font-family: var(--mono); font-weight: 700; }
  .axis-elig.in { color: #15803d; }
  .axis-elig.out { color: #b91c1c; }
  .axis-elig.unk { color: #b45309; }
  /* Open-vs-later is a bold COLORED pill, not an opacity difference (opacity reads as disabled
     and washes out on some screens): open = green, an upcoming window = amber. */
  .state { font-family: var(--mono); font-size: .78rem; font-weight: 700; white-space: nowrap;
    color: #fff; padding: .12rem .55rem; border-radius: 1rem; }
  .state.open { background: #15803d; }
  .state.upcoming { background: #b45309; }
  .eligword { font-size: .85rem; font-weight: 600; display: inline-flex; align-items: center; gap: .25rem; }
  .eligword.in { color: #15803d; }
  .eligword.out { color: #b91c1c; }
  .eligword.unk { color: #b45309; }
  /* length + lanes: kept as a real lap-swimmer filter, demoted to a compact monospace tag */
  .lenbadge { display: inline-block; font-family: var(--mono); font-size: .74rem; white-space: nowrap;
    border: 1px solid #8886; border-radius: .3rem; padding: .04rem .4rem; opacity: .9; }
  .lenbadge .len { font-weight: 600; }
  .lenbadge .lanes { opacity: .8; }
  .card .metaline { font-size: .85rem; opacity: .85; margin-top: .2rem; }
  .card .reason { font-size: .8rem; opacity: .65; margin-top: .2rem; }
  /* pool-as-object detail line: address · tel · official ↗ · directions ↗ */
  .pooldetail { font-size: .8rem; opacity: .8; margin-top: .3rem; }
  .status a { white-space: nowrap; }
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
  .primer .primerlead { margin: .1rem 0; font-weight: 600; }
  .primer .primerdetails { margin-top: .5rem; }
  .primer .primerdetails summary { cursor: pointer; opacity: .8; font-size: .85rem; }
  .card .decode { font-size: .82rem; opacity: .85; margin-top: .3rem; }
  .card .decode b { font-weight: 600; }

  /* --- week planner grid (read-only) --- */
  .planfilters { display: flex; flex-wrap: wrap; gap: 1rem; margin: .8rem 0; font-size: .88rem; }
  .planfilters label { flex-direction: row; align-items: center; gap: .35rem; }
  .chip.closedchip { opacity: .55; text-decoration: line-through; }
  .chip.closedchip.active { opacity: 1; text-decoration: none; }
  .planhead { font-family: var(--mono); font-size: .85rem; margin: .8rem 0 .3rem; }
  /* The grid is wider than a phone: wrap it in a horizontal-scroll container with a sensible
     min-width so it stays a grid on mobile (persona 2 plans on a phone) instead of collapsing. */
  .gridscroll { overflow-x: auto; margin: .3rem 0; }
  .weekgrid { font-family: var(--mono); border-collapse: collapse; width: 100%; min-width: 40rem; font-size: .9rem; }
  .weekgrid th, .weekgrid td { border: 1px solid #8884; padding: .3rem .45rem; text-align: center; }
  .weekgrid th { font-weight: 600; opacity: .85; }
  .weekgrid td.time { text-align: right; opacity: .8; white-space: nowrap; }
  .weekgrid td.closed-day { opacity: .45; }        /* no session at this slot (·) */
  .weekgrid td.unknown-day { color: #b45309; }     /* no data — ? , NEVER blank */
  /* Session time ranges are VISIBLE cell text, not title=-hover-only (invisible on touch). */
  .weekgrid .cellglyphs { display: block; line-height: 1.3; }
  .weekgrid .celltime { display: block; font-size: .66rem; opacity: .7; white-space: nowrap; margin-top: .05rem; }
  .cell-elig.in { color: #15803d; } .cell-elig.out { color: #b91c1c; } .cell-elig.unk { color: #b45309; }
  .daynote { font-family: var(--mono); font-size: .82rem; margin: .15rem 0; }
  .daynote.closed { color: #b91c1c; } .daynote.unknown { color: #b45309; }

  /* --- All-pools hub (S5): name filter, schedule indicator, jump-to-plan action --- */
  .poolfilter { max-width: 22rem; margin: 1rem 0 .4rem; }
  .poolfilter input { width: 100%; }
  .sched-yes { color: #15803d; font-weight: 600; white-space: nowrap; }
  .sched-no { opacity: .6; font-size: .82rem; }        /* honest: no timetable yet, NOT closed */
  tr.norow { opacity: .72; }                            /* location-only rows sit back, not hidden */
  button.jump { padding: .25rem .6rem; font-size: .85rem; cursor: pointer; white-space: nowrap;
    border: 1px solid #3b82f6; color: #3b82f6; background: transparent; border-radius: .4rem; }
  button.jump:hover { background: #3b82f6; color: #fff; }
</style>
</head>
<body>
<h1>🏊 Swimming in Zürich</h1>
<p class="muted">Locations from the city open data (WFS). Schedules are curated/illustrative — verify on-site via the official link.</p>

<nav>
  <button data-tab="find" class="active">Find a swim</button>
  <button data-tab="plan">Plan my week</button>
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
  <div id="findOut"></div>
  <details class="symbols"><summary>What do the symbols mean?</summary>
  <pre class="glyphlegend">ACCESS   ≈ lane   ◇ public   ⌂ family   W women   S seniors   X reserved   · closed
FOR YOU  ✓ in     ✗ not you   ? unknown
STATUS   OPEN · closes HH:MM     CLOSED — reason     Hours not listed yet
PROV     ⓘ Schedule last checked … · source · official / from the website / mixed</pre>
  </details>
  <div class="legend"><h3>Access types</h3><dl id="legend"></dl></div>
</section>

<section id="plan">
  <p class="muted">Plan recurring lap windows across the week near home. Read-only — a days×time grid for one nearby pool at a time. (Saving a routine is not built yet.)</p>
  <form id="pf">
    <label>Near
      <select name="place">
        <option value="47.3779,8.5403">Zürich HB (main station)</option>
        <option value="47.3671,8.5451">Bellevue</option>
        <option value="47.3606,8.5510">Zürichhorn</option>
      </select>
    </label>
    <label>Gender
      <select name="gender">
        <option value="">any</option><option value="female">female</option>
        <option value="male">male</option><option value="diverse">diverse</option>
      </select>
    </label>
    <label>Age<input type="number" name="age" min="0" max="120" placeholder="optional"></label>
    <label>Radius (km)<input type="number" name="radius_km" min="1" max="30" value="10"></label>
    <button type="submit">Show my week</button>
  </form>
  <div class="planfilters">
    <label><input type="checkbox" id="pf-lap" checked> lap only</label>
    <label><input type="checkbox" id="pf-reserved"> show reserved</label>
    <label><input type="checkbox" id="pf-elig"> eligible-to-me only</label>
  </div>
  <div id="poolSwitch" class="chips"></div>
  <p id="planNote" class="muted"></p>
  <div id="planOut"></div>
  <details class="symbols"><summary>What do the symbols mean?</summary>
  <pre class="glyphlegend">ACCESS   ≈ lane   ◇ public   ⌂ family   W women   S seniors   X reserved   · no session
FOR YOU  ✓ in     ✗ not you   ? unknown</pre>
  </details>
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
  <div id="visitOut"></div>
  <div class="primer" id="primer"></div>
</section>

<section id="all">
  <p class="muted">Every pool in the city catalog. Pools with a ✓ schedule can be planned — jump straight to the weekly grid; the rest are locations we list honestly without a timetable yet.</p>
  <label class="poolfilter">Filter by name
    <input type="search" id="poolFilter" placeholder="type a pool name…" autocomplete="off">
  </label>
  <div class="chips" id="kinds"></div>
  <div id="allOut"></div>
</section>

<script>
const $ = s => document.querySelector(s);
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
// tabs — activateTab is also the programmatic entry point for the All-pools "Plan ›" jump.
function activateTab(tab) {
  document.querySelectorAll('nav button').forEach(x => x.classList.toggle('active', x.dataset.tab === tab));
  document.querySelectorAll('section').forEach(x => x.classList.toggle('active', x.id === tab));
  if (tab === 'all' && !allLoaded) loadPools();
  if (tab === 'visit' && !visitLoaded) loadVisit();
  if (tab === 'plan' && !planLoaded) loadPlan();
}
document.querySelectorAll('nav button').forEach(b =>
  b.addEventListener('click', () => activateTab(b.dataset.tab)));

// --- Pool catalog join: the facility as a first-class, actionable object ---
// /swim carries only the facility NAME; /pools carries url/phone/address/lat/lon per pool.
// Join key = the facility display name (verified: every /swim facility matches a /pools name).
// Fetch /pools ONCE (memoized, shared by every tab) into a name->record map, so a card can
// link its pool and show contact/route detail. Helpers degrade to plain text / '' when a
// facility has no catalog match — never a broken or empty href.
let poolsPromise = null;   // in-flight/settled /pools fetch, shared so it runs at most once
let poolMap = new Map();   // facility name -> { url, phone, address, lat, lon, ... }
function loadPoolsData() {
  if (!poolsPromise) poolsPromise = fetch('/pools')
    .then(r => r.ok ? r.json() : { count: 0, kinds: [], pools: [] })
    .then(a => { poolMap = new Map((a.pools || []).map(p => [p.name, p])); return a; });
  return poolsPromise;
}
function poolInfo(name) { return poolMap.get(name) || null; }  // the catalog record, or null

// Which catalog pools actually HAVE a curated timetable (S5 #11)? /swim answers it: a facility
// appears in `options` (it produced sessions) or in `statuses` as `closed` (it has a schedule but
// is shut that day) IFF it is curated/scheduled. `uncurated` statuses are pools with NO timetable
// — deliberately EXCLUDED, so the All-pools row honestly reads "no timetable yet", never "closed"
// (honesty invariant #1). One representative no-location call (verified to enumerate the full
// scheduled set on any day) is memoized so it runs at most once.
let scheduledPromise = null;
let scheduledPools = new Set();  // facility names that have a schedule the app can show
function loadScheduledFacilities() {
  if (!scheduledPromise) {
    const t = new Date(); t.setSeconds(0, 0);
    const at = new Date(t.getTime() - t.getTimezoneOffset()*60000).toISOString().slice(0, 16);
    scheduledPromise = fetch('/swim?' + new URLSearchParams({ at, eligible_only: 'false' }))
      .then(r => r.ok ? r.json() : { options: [], statuses: [] })
      .then(a => {
        scheduledPools = new Set([
          ...(a.options || []).map(o => o.facility),
          ...(a.statuses || []).filter(s => s.status === 'closed').map(s => s.facility),
        ]);
        return scheduledPools;
      });
  }
  return scheduledPromise;
}

// The facility name as a link (only when a catalog url exists; else plain, escaped text).
function poolNameHTML(name) {
  const info = poolInfo(name);
  return info && info.url
    ? `<a href="${esc(info.url)}" target="_blank" rel="noopener">${esc(name)}</a>`
    : esc(name);
}
// 🗺 directions link built from lat/lon (Google Maps directions); '' when geo is absent.
function directionsHTML(info) {
  return info && info.lat != null && info.lon != null
    ? `<a href="https://www.google.com/maps/dir/?api=1&amp;destination=${esc(info.lat)},${esc(info.lon)}" target="_blank" rel="noopener">🗺 directions ↗</a>`
    : '';
}
// A compact one-line pool detail: address · tel: phone · official ↗ · 🗺 directions ↗.
// Returns '' when the facility has no catalog match (graceful degrade to just the card text).
function poolDetailHTML(name) {
  const info = poolInfo(name);
  if (!info) return '';
  const parts = [];
  if (info.address) parts.push(esc(info.address));
  if (info.phone) parts.push(`<a href="tel:${esc(info.phone.replaceAll(' ', ''))}">${esc(info.phone)}</a>`);
  if (info.url) parts.push(`<a href="${esc(info.url)}" target="_blank" rel="noopener">official ↗</a>`);
  const dir = directionsHTML(info);
  if (dir) parts.push(dir);
  return parts.length ? `<div class="pooldetail">${parts.join(' · ')}</div>` : '';
}
// The status-line variant: just the actionable links (official ↗ · 🗺 directions ↗), inline —
// so "we don't know its hours" still resolves to "here's where to find out". '' when no match.
function poolLinksHTML(name) {
  const info = poolInfo(name);
  if (!info) return '';
  const parts = [];
  if (info.url) parts.push(`<a href="${esc(info.url)}" target="_blank" rel="noopener">official ↗</a>`);
  const dir = directionsHTML(info);
  if (dir) parts.push(dir);
  return parts.length ? ' · ' + parts.join(' · ') : '';
}

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
// Sentence-case the (shouty upper-case) access label so a card reads "Lane", not "LANE".
const sentence = s => s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s;
// Eligibility glyph axis (whether it's YOU) — ? = not determinable (unknown), never merged with ✗.
function eligAxis(o) {
  if (o.eligible) return { g:'✓', cls:'in' };
  if (/determine eligibility|confirm admission/.test(o.reason)) return { g:'?', cls:'unk' };
  return { g:'✗', cls:'out' };
}
// The eligibility axis paired with a plain WORD (derived, via eligAxis, from o.reason) so ✓/✗/?
// is not the only signal: "you're in" / "not for you" / "check".
const ELIG_WORD = { in: "you're in", out: 'not for you', unk: 'check' };
function eligWord(o) { return ELIG_WORD[eligAxis(o).cls]; }
// Open-vs-later terminal state as a bold COLORED pill (see .state CSS) — never opacity-only.
function statePill(o) {
  return o.open_now
    ? `<span class="state open">OPEN · closes ${esc(o.end)}</span>`
    : `<span class="state upcoming">${esc(o.start)}–${esc(o.end)} today</span>`;
}
// Length + lane count as a compact secondary tag: a real lap-swimmer filter, kept but demoted.
// Lane count is a real datum from the basin — absent => length-only (honest degrade, no faked N).
function lenTagHTML(o) {
  const len = o.length_m != null ? `${esc(o.length_m)} m` : 'pool';
  const lanes = o.lanes != null ? `<span class="lanes"> · ${esc(o.lanes)} lane</span>` : '';
  return `<span class="lenbadge"><span class="len">${len}</span>${lanes}</span>`;
}
// Visual hierarchy (S4 #7): the eye lands on the ANSWER, not the filter — facility name (big,
// the S3 link) → bold status pill + eligibility WORD → distance/price → length demoted to a
// small tag. The redundant `indoor` kind is dropped (every Find result is indoor).
function optionCard(o) {
  const el = eligAxis(o);
  const meta = [o.distance_km != null ? o.distance_km + ' km' : null, o.price]
    .filter(Boolean).map(esc).join(' · ');
  return `<article class="card">
    <div class="cardname">${poolNameHTML(o.facility)} · ${esc(o.basin)}</div>
    <div class="statusrow">
      ${statePill(o)}
      <span class="eligword ${el.cls}"><span class="glyph axis-elig ${el.cls}">${el.g}</span> ${esc(eligWord(o))}</span>
    </div>
    <div class="metaline">
      <span class="glyph axis-access">${esc(accessGlyph(o.access))}</span> ${esc(sentence(accessLabel(o.access)))}
      ${meta ? '&nbsp; · ' + meta : ''}
      &nbsp; ${lenTagHTML(o)}
    </div>
    <div class="reason">${esc(o.reason)}</div>
    ${poolDetailHTML(o.facility)}
  </article>`;
}

// The three terminal states are never merged: closed-with-reason and uncurated are
// rendered distinctly here, below the open options.
function statusLine(s) {
  const name = poolNameHTML(s.facility);
  const links = poolLinksHTML(s.facility);  // #6: "we don't know" resolves to "find out here"
  if (s.status === 'closed')
    return `<div class="status closed">⊘ ${name} CLOSED — ${esc(s.detail)}${links}</div>`;
  if (s.status === 'uncurated')
    return `<div class="status uncurated">? ${name} — Hours not listed yet — may well be open, we just don't have its timetable.${links}</div>`;
  return `<div class="status">${name} — ${esc(s.detail)}${links}</div>`;
}

// ⓘ provenance stamp aggregated across the shown options (freshness + source + curated).
function provStamp(options) {
  const dates = options.map(o => o.valid_as_of).filter(Boolean).sort();
  if (!dates.length && !options.length) return '';
  const sources = [...new Set(options.map(o => o.source).filter(Boolean))];
  const allCurated = options.every(o => o.curated);
  const noneCurated = options.every(o => !o.curated);
  const provenance = allCurated ? 'official schedule'
    : noneCurated ? "read from the pool's website" : 'mixed sources';
  const asOf = dates.length ? 'Schedule last checked ' + esc(dates[0]) + ' · ' : '';
  return `<div class="prov">ⓘ ${asOf}${esc(sources.join(', ') || 'unknown source')} · ${provenance}</div>`;
}

f.addEventListener('submit', async e => {
  e.preventDefault();
  const p = new URLSearchParams();
  for (const [k, v] of new FormData(f)) if (v !== '') p.append(k, v);
  findOut.innerHTML = '<p class="muted">Searching…</p>';
  const r = await fetch('/swim?' + p);
  if (!r.ok) { findOut.innerHTML = '<p class="warn">' + esc((await r.json()).detail) + '</p>'; return; }
  const a = await r.json();
  await loadPoolsData();  // memoized /pools — so every card can link its pool + show detail
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
let visitAccess = null;  // /access-types glossary, fetched once and reused by renderPrimer
async function loadVisit() {
  visitLoaded = true;
  // The slot glossary is the /access-types data; POOL TYPES is keyed off the kinds actually
  // present in the results (see renderPrimer), so no /pools fetch is needed here.
  visitAccess = await fetch('/access-types').then(r => r.json());
  vf.dispatchEvent(new Event('submit'));  // show starter pools immediately with defaults
}

// The primer is deliberately small: one always-visible line (the only thing a newcomer must
// know to get in the water) + a default-closed <details> holding the glossary. POOL TYPES is
// keyed to the `kind`s actually present in these results (not all 7 catalog categories), so a
// tourist looking at indoor pools does not wade through river/lake/thermal glosses.
function renderPrimer(options) {
  const kinds = [...new Set(options.map(o => o.kind).filter(Boolean))];
  const types = kinds.map(k => {
    const t = POOL_TYPES[k];
    return t
      ? `<dt>${esc(t[0])} <span class="muted">(${esc(k)})</span></dt><dd>${esc(t[1])}</dd>`
      : `<dt>${esc(k)}</dt><dd>a Zürich pool category</dd>`;
  }).join('');
  const slots = (visitAccess ? visitAccess.types : []).map(t =>
    `<dt>${esc(t.label)}</dt><dd>${esc(t.description)}</dd>`).join('');
  $('#primer').innerHTML =
    '<p class="primerlead">Just walk in and pay in CHF at the door — no booking, no card.</p>'
    + '<details class="primerdetails"><summary>New here? What the words mean</summary><dl>'
    + '<dt>POOL TYPES</dt><dd>Zürich names its water by kind:</dd>' + types
    + '<dt>THE SLOTS</dt><dd>What each kind of session lets you do:</dd>' + slots
    + '</dl></details>';
}

// A starter-pool card: the S1 badge + orthogonal glyph axes, jargon decoded inline, km only.
// Walk/transit time is deliberately never shown — there is no routing model (gap #4).
function starterCard(o, mark) {
  const el = eligAxis(o);
  const meta = [o.distance_km != null ? o.distance_km + ' km' : null, o.price]
    .filter(Boolean).map(esc).join(' · ');
  return `<article class="card">
    <div class="cardname"><span class="mark">${esc(mark)}</span>${poolNameHTML(o.facility)} · ${esc(o.basin)}</div>
    <div class="statusrow">
      ${statePill(o)}
      <span class="eligword ${el.cls}"><span class="glyph axis-elig ${el.cls}">${el.g}</span> ${esc(eligWord(o))}</span>
    </div>
    <div class="metaline">
      <span class="glyph axis-access">${esc(accessGlyph(o.access))}</span>
      ${meta ? '&nbsp; ' + meta : ''}
      &nbsp; ${lenTagHTML(o)}
    </div>
    <div class="decode">This slot is <b>${esc(decodeAccess(o.access))}</b>.</div>
    ${poolDetailHTML(o.facility)}
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
  await loadPoolsData();  // memoized /pools — link each starter pool + its contact/route detail
  renderPrimer(a.options);  // keep the glossary keyed to the kinds these results actually contain
  let h = '<h3>Starter pools near you</h3>';
  const marks = ['①', '②', '③'];
  // Distinct FACILITIES, not sessions: slicing raw sessions showed the same pool (e.g.
  // Oerlikon) twice, reading as ~one pool. Options are distance-then-time ordered, so the
  // FIRST session seen per facility is its earliest/next window — the best representative for
  // "here's a pool you can go to". Keep the first (set only when the key is absent, since a
  // Map built from entries would otherwise keep the LAST, i.e. the day's latest session).
  const byFacility = new Map();
  for (const o of a.options) if (!byFacility.has(o.facility)) byFacility.set(o.facility, o);
  const starters = [...byFacility.values()].slice(0, 3);
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

// --- Plan my week (read-only weekly grid) ---
// DISCOVERY (Option A): /swim takes a single `at` moment, but find_swim_options resolves
// and returns EVERY session of that moment's DAY (each option carries its own start/end;
// `open_now` is just a per-session flag), so 7 calls — one per weekday at a representative
// noon — assemble the whole week with no API change. Eligibility (✓✗?) is per-session and
// time-independent; only holiday-correct schedules need the real date, which each call has.
const pf = $('#pf'), planOut = $('#planOut'), poolSwitch = $('#poolSwitch'), planNote = $('#planNote');
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
let planLoaded = false;
let planWeek = null;      // [{ label, iso, answer }] for Mon..Sun
let planPools = [];       // [{ facility, distance_km, closed }] — open pools first (by distance), then closed
let planSelected = null;  // selected facility name
let planPreselect = null; // facility the All-pools "Plan ›" jump asked to select once resolved
let catalogCount = null;  // total pools in the WFS catalog (the "All pools" universe)

function localISO(d) {
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function mondayOf(d) {
  const m = new Date(d); m.setHours(12, 0, 0, 0);
  m.setDate(m.getDate() - ((m.getDay() + 6) % 7));  // ISO week: Monday = 0
  return m;
}

async function loadPlan() { planLoaded = true; pf.dispatchEvent(new Event('submit')); }

pf.addEventListener('submit', async e => {
  e.preventDefault();
  const [lat, lon] = pf.place.value.split(',');
  const monday = mondayOf(new Date());
  planOut.innerHTML = '<p class="muted">Resolving the week…</p>';
  const days = WEEKDAYS.map((label, i) => {
    const d = new Date(monday); d.setDate(monday.getDate() + i);
    return { label, iso: localISO(d) };
  });
  // Option A: one /swim call per weekday (7), assembled client-side.
  const answers = await Promise.all(days.map(async day => {
    const p = new URLSearchParams({ at: day.iso, lat, lon, eligible_only: 'false' });
    if (pf.radius_km.value) p.append('radius_km', pf.radius_km.value);
    if (pf.age.value) p.append('age', pf.age.value);
    if (pf.gender.value) p.append('gender', pf.gender.value);
    const r = await fetch('/swim?' + p);
    return r.ok ? r.json() : { options: [], statuses: [], warnings: [], notices: [] };
  }));
  planWeek = days.map((day, i) => ({ ...day, answer: answers[i] }));
  // Memoized /pools: the pool-detail map for the linked planhead + the catalog count for the
  // honesty note below the switcher (the "All pools" universe). One shared fetch, not two.
  const catalog = await loadPoolsData();
  if (catalogCount === null) catalogCount = catalog.count;

  // Distance-sorted pool switcher: nearest facility (min distance across the week) first.
  const dist = new Map();
  for (const { answer } of planWeek)
    for (const o of answer.options) {
      const cur = dist.get(o.facility);
      if (cur === undefined || (o.distance_km != null && o.distance_km < cur))
        dist.set(o.facility, o.distance_km != null ? o.distance_km : cur ?? null);
    }
  const openPools = [...dist.entries()].map(([facility, distance_km]) => ({ facility, distance_km, closed: false }))
    .sort((a, b) => (a.distance_km ?? Infinity) - (b.distance_km ?? Infinity));
  // Pools closed ALL week produce no options, so they'd silently vanish — invariant #1 forbids that.
  // Surface them as closed chips (distance unknown: `statuses` carry none — S4 tech debt).
  const closedNames = new Set();
  for (const { answer } of planWeek)
    for (const s of answer.statuses)
      if (s.status === 'closed' && !dist.has(s.facility)) closedNames.add(s.facility);
  const closedPools = [...closedNames].sort().map(facility => ({ facility, distance_km: null, closed: true }));
  planPools = [...openPools, ...closedPools];
  planSelected = openPools.length ? openPools[0].facility : (planPools[0]?.facility ?? null);  // nearest OPEN pool by default
  // S5 jump: if the All-pools "Plan ›" button requested a pool and it resolved within the
  // current place/radius, preselect it (else fall back to the nearest — recorded tech debt).
  if (planPreselect) {
    if (planPools.some(p => p.facility === planPreselect)) planSelected = planPreselect;
    planPreselect = null;
  }
  renderPlan();
});

['pf-lap', 'pf-reserved', 'pf-elig'].forEach(id =>
  $('#' + id).addEventListener('change', () => { if (planWeek) renderPlan(); }));

function renderPoolSwitch() {
  if (!planPools.length) { poolSwitch.innerHTML = ''; planNote.textContent = ''; return; }
  poolSwitch.innerHTML = planPools.map(p => {
    const mark = p.closed ? '⊘' : (p.facility === planSelected ? '●' : '○');
    const km = p.distance_km != null ? ' ' + p.distance_km + 'km' : '';
    const suffix = p.closed ? ' (closed)' : '';
    let cls = 'chip';
    if (p.facility === planSelected) cls += ' active';
    if (p.closed) cls += ' closedchip';
    return `<button class="${cls}" data-pool="${esc(p.facility)}">${mark} ${esc(p.facility)}${esc(km)}${suffix}</button>`;
  }).join('');
  poolSwitch.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
    planSelected = c.dataset.pool; renderPlan();
  }));
  // Explain the gap vs the "All pools" tab: only pools WITH a curated timetable can be planned.
  const withSchedule = planPools.length;
  const openN = planPools.filter(p => !p.closed).length;
  let note = `Showing ${openN} open + ${withSchedule - openN} closed pool(s) — only pools with a curated timetable can be planned.`;
  if (catalogCount != null)
    note += ` The “All pools” tab lists all ${catalogCount} catalog locations; the rest have no schedule yet (locations only, not shown here).`;
  planNote.textContent = note;
}

// One session -> its filtered access glyph, or null if the filters hide it.
function cellSession(o) {
  const reserved = o.access === 'ClubReserved' || o.access === 'SchoolReserved';
  if ($('#pf-lap').checked && o.access !== 'LaneSwim') return null;
  if (!$('#pf-reserved').checked && reserved) return null;
  if ($('#pf-elig').checked && !o.eligible) return null;
  return o;
}

// Resolve the selected facility's state for one day. The three states are NEVER merged:
//  - 'open'    : the pool produced sessions that day (some slots may still be empty '·')
//  - 'closed'  : the pool is in `statuses` as closed that day (with reason)
//  - 'unknown' : no options AND no closed status -> '?', never a blank that reads as closed
function dayState(answer) {
  const opts = answer.options.filter(o => o.facility === planSelected);
  if (opts.length) return { state: 'open', sessions: opts };
  const st = answer.statuses.find(s => s.facility === planSelected);
  if (st && st.status === 'closed') return { state: 'closed', detail: st.detail };
  if (st && st.status === 'uncurated') return { state: 'unknown', detail: 'schedule unknown, NOT closed' };
  return { state: 'unknown', detail: 'no schedule data for this day, NOT closed' };
}

function renderPlan() {
  renderPoolSwitch();
  if (!planSelected) {
    planOut.innerHTML = '<p class="muted">No pools with schedules near that spot — widen the radius.</p>';
    return;
  }
  const states = planWeek.map(d => dayState(d.answer));
  // Row set = union of visible session start times for the selected pool across the week.
  const times = [...new Set(
    states.flatMap(s => s.state === 'open' ? s.sessions.filter(cellSession).map(o => o.start) : [])
  )].sort();

  const badgePool = poolNameHTML(planSelected);        // #2: the planned pool is a link
  const poolDetail = poolDetailHTML(planSelected);     // address · tel · official ↗ · directions
  if (!times.length) {
    planOut.innerHTML = `<div class="planhead">${badgePool}</div>` + poolDetail
      + '<p class="muted">No sessions match the current filters this week — try unchecking “lap only”.</p>';
    return;
  }

  let h = `<div class="planhead">${badgePool}</div>` + poolDetail;
  // Horizontal-scroll container (#9): the grid stays a grid on a phone instead of collapsing.
  h += '<div class="gridscroll"><table class="weekgrid"><thead><tr><th>time</th>'
     + planWeek.map(d => `<th>${esc(d.label)}</th>`).join('') + '</tr></thead><tbody>';
  for (const t of times) {
    h += `<tr><td class="time">${esc(t)}</td>`;
    for (let i = 0; i < planWeek.length; i++) {
      const s = states[i];
      if (s.state === 'unknown') { h += '<td class="unknown-day" title="' + esc(s.detail) + '">?</td>'; continue; }
      if (s.state === 'closed') { h += '<td class="closed-day" title="closed — ' + esc(s.detail) + '">·</td>'; continue; }
      const here = s.sessions.filter(o => o.start === t).map(cellSession).filter(Boolean);
      if (!here.length) { h += '<td class="closed-day" title="no session at this time">·</td>'; continue; }
      const o = here.find(x => x.access === 'LaneSwim') || here[0];  // one glyph pair per cell
      const el = eligAxis(o);
      const title = here.map(x => x.start + '–' + x.end + ' ' + accessLabel(x.access)).join(' · ');
      // The time range is VISIBLE cell text (#9), not title=-hover-only — hover is invisible on
      // touch. Glyphs stay for scannability; the full stacked-session detail stays in title=.
      h += `<td title="${esc(title)}">`
         + `<span class="cellglyphs"><span class="glyph">${esc(accessGlyph(o.access))}</span>`
         + `<span class="glyph cell-elig ${el.cls}">${el.g}</span></span>`
         + `<span class="celltime">${esc(o.start)}–${esc(o.end)}</span></td>`;
    }
    h += '</tr>';
  }
  h += '</tbody></table></div>';

  // Closed / unknown days are called out explicitly below the grid — never left as a silent blank.
  const notes = planWeek.map((d, i) => {
    const s = states[i];
    if (s.state === 'closed') return `<div class="daynote closed">⊘ ${esc(d.label)} CLOSED — ${esc(s.detail)}</div>`;
    if (s.state === 'unknown') return `<div class="daynote unknown">? ${esc(d.label)} — ${esc(s.detail)}</div>`;
    return '';
  }).filter(Boolean).join('');
  h += notes;
  h += '<p class="muted">Busyness: not available yet.</p>';
  h += provStamp(planWeek.flatMap(d => d.answer.options.filter(o => o.facility === planSelected)));
  planOut.innerHTML = h;
}

// --- All pools: a navigation HUB, not a dead-end (S5) ---
// One /pools fetch TOTAL: fold onto the memoized loadPoolsData() (S3 left this tab
// double-fetching). A second, distinct call — the memoized /swim scheduled set — tells each row
// whether it has a timetable. Rows WITH a schedule get a "Plan ›" jump; rows WITHOUT read
// "location only — no timetable yet" (honest, never "closed"). A name-filter box narrows the 57.
let allLoaded = false, currentKind = null, nameFilter = '', allPools = [];
async function loadPools() {
  allLoaded = true;
  const [a] = await Promise.all([loadPoolsData(), loadScheduledFacilities()]);
  allPools = a.pools || [];
  $('#kinds').innerHTML = ['<button class="chip active" data-kind="">all (' + a.count + ')</button>']
    .concat(a.kinds.map(k => `<button class="chip" data-kind="${esc(k)}">${esc(k)}</button>`)).join('');
  document.querySelectorAll('#kinds .chip').forEach(c => c.addEventListener('click', () => {
    document.querySelectorAll('#kinds .chip').forEach(x => x.classList.remove('active'));
    c.classList.add('active'); currentKind = c.dataset.kind || null; renderPools();
  }));
  renderPools();
}
// Client-side name filter (#13): case-insensitive `includes` on p.name, the jump-to-schedule
// entry point. Wired once (the input lives in static markup); a no-op until the tab is loaded.
$('#poolFilter').addEventListener('input', e => {
  nameFilter = e.target.value.trim().toLowerCase();
  if (allLoaded) renderPools();
});
function renderPools() {
  let items = allPools;
  if (currentKind) items = items.filter(p => p.kind === currentKind);
  if (nameFilter) items = items.filter(p => p.name.toLowerCase().includes(nameFilter));
  let h = `<p class="muted">${items.length} pools</p><table><thead><tr>`
    + '<th>Name</th><th>Kind</th><th>Schedule</th><th>Address</th><th></th></tr></thead><tbody>';
  for (const p of items) {
    const scheduled = scheduledPools.has(p.name);
    // #11: a schedule indicator + a "Plan ›" jump for pools we can actually plan; the rest are
    // honestly "location only — no timetable yet" (NOT closed — invariant #1).
    const schedCell = scheduled
      ? '<span class="sched-yes">✓ schedule</span>'
      : '<span class="sched-no">location only — no timetable yet</span>';
    const action = scheduled
      ? `<button class="jump" data-pool="${esc(p.name)}">Plan ›</button>`
      : (p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">official ↗</a>` : '');
    h += `<tr${scheduled ? '' : ' class="norow"'}><td>${poolNameHTML(p.name)}</td>`
      + `<td><span class="badge">${esc(p.kind)}</span></td><td>${schedCell}</td>`
      + `<td>${esc(p.address)}</td><td>${action}</td></tr>`;
  }
  $('#allOut').innerHTML = h + '</tbody></table>';
  // Wire the jumps: switch to Plan and preselect this pool (see jumpToPlan).
  $('#allOut').querySelectorAll('button.jump').forEach(b =>
    b.addEventListener('click', () => jumpToPlan(b.dataset.pool)));
}
// The All-pools → Plan jump: switch tabs and ask the planner to preselect this pool. If the plan
// is already resolved, apply the selection now (when the pool is within the current place/radius);
// otherwise loadPlan()'s submit consumes planPreselect once the week resolves.
function jumpToPlan(facility) {
  planPreselect = facility;
  const wasLoaded = planLoaded;
  activateTab('plan');
  if (wasLoaded) {
    if (planPools.some(p => p.facility === facility)) planSelected = facility;
    planPreselect = null;
    renderPlan();
  }
}
</script>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse(content=_PAGE)
