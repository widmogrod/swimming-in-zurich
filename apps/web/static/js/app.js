// app.js — the composition root of the unified two-mode UI (plan S4).
//
// It assembles IdentityHeader + FilterToolbar + InsightBar + RibbonBoard +
// DetailPanel + BoardLegend + StateBlocks over the live JSON API, and wires the
// ONE FilterState through them: a toolbar edit refetches (`/swim` for Day, the 7
// weekday `/swim` calls for Pool) and re-renders every block; a click on a board
// ribbon opens the DetailPanel on the SHARED time cursor, resolving the clicked
// board row to the SAME basin's `/pools/{id}` day_view so the board readout and
// the panel headline agree on real data.
//
// This module is browser-only (it touches a real `document`, canvas, geolocation)
// and is imported by no test. The PURE pieces it leans on (api URL builders,
// insight, state selection, filterstate, timescale, cursor, board row derivation)
// are unit-tested in isolation. No colour, no hex lives here.

import { createIdentityHeader, applyTheme } from './blocks/header.js';
import { createFilterToolbar, DEFAULT_AGE_CHIPS } from './blocks/toolbar.js';
import { createInsightBar } from './blocks/insightbar.js';
import { createBoard, BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './blocks/board.js';
import { createDetailPanel } from './blocks/detailpanel.js';
import { createBoardLegend } from './blocks/legend.js';
import { createStateBlocks, emptyState } from './blocks/stateblocks.js';
import { createFilterState, merge } from './filterstate.js';
import { makeTimescale } from './timescale.js';
import { basinFromPanel, panelForBasin } from './blocks/cursor.js';
import { formatLabel } from './components/datestepper.js';
import { fetchDay, fetchWeek, fetchPoolDetail, isoDate, weekDates } from './api.js';
import { toSearch, fromSearch } from './urlstate.js';

// The age value⇆token vocabulary the URL uses, derived from the toolbar's own chips so
// the URL scheme and the UI never drift. `''` (Any age) has no token — it is the omitted
// default. e.g. { value: 8, token: 'child' } … { value: 70, token: 'senior' }.
const AGE_TOKENS = DEFAULT_AGE_CHIPS.filter((c) => c.value !== '').map((c) => ({
  value: Number(c.value),
  token: c.label.toLowerCase(),
}));

const PLACE_PRESETS = [
  { label: 'Zürich HB (main station)', lat: 47.3779, lon: 8.5403 },
  { label: 'Bellevue', lat: 47.3671, lon: 8.5451 },
  { label: 'Zürichhorn', lat: 47.3606, lon: 8.551 },
];

// Lap-friendly access types: real lane-swim + public swim (both are lap-swimmable in
// a pool). The "Lap lanes only" toggle filters the fetched options to these client-side
// — there is no `/swim` lap param, so the board itself does the filtering (plan item 6).
const LAP_FRIENDLY = new Set(['LaneSwim', 'PublicSwim']);

const $ = (id) => document.getElementById(id);

// Focus a whole day window on ONE shared timescale — the board ribbons AND the
// panel Gantt both draw through it, so a click at T lands on the same x in both.
const TIMESCALE = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);

// Keep only the selected pool's options/statuses in a Pool-mode week, so the board
// shows that one pool across seven days (not every nearby pool). When the pool is
// unplannable (no options — only a closed/uncurated status), this leaves the honest
// ghost/closed rows and NO fabricated ribbons (plan item 4).
function focusWeekOnPool(week, poolLabel) {
  if (!poolLabel) return week;
  return {
    facility: poolLabel,
    days: week.days.map((d) => ({
      ...d,
      answer: {
        ...d.answer,
        options: d.answer.options.filter((o) => o.facility === poolLabel),
        statuses: d.answer.statuses.filter((s) => s.facility === poolLabel),
      },
    })),
  };
}

// Filter a `/swim` answer's options to the lap-friendly access types (no-op unless
// the toggle is on). A day left with no lap-friendly session shows as an empty row —
// an honest "no lap swim here" — rather than inventing a lane session.
function applyLap(answer, lapOnly) {
  if (!lapOnly || !answer) return answer;
  return { ...answer, options: (answer.options || []).filter((o) => LAP_FRIENDLY.has(o.access)) };
}

function applyLapWeek(week, lapOnly) {
  if (!lapOnly) return week;
  return { ...week, days: week.days.map((d) => ({ ...d, answer: applyLap(d.answer, lapOnly) })) };
}

// Classify the poolsMeta (/pools) against a day's `/swim` answer into the pool-picker
// options, HONESTLY (plan item 4): a pool with sessions is PLANNABLE (listed first,
// no badge, carrying its distance), a genuinely closed pool is 'closed', and a pool
// with no curated timetable is 'no timetable yet' (NEVER "closed" — unknown ≠ closed).
function classifyPools(poolsMeta, dayAnswer) {
  const dist = new Map(); // facility name → nearest distance_km
  for (const o of dayAnswer.options || []) {
    const cur = dist.get(o.facility);
    if (o.distance_km != null && (cur == null || o.distance_km < cur)) dist.set(o.facility, o.distance_km);
    else if (!dist.has(o.facility)) dist.set(o.facility, o.distance_km);
  }
  const closed = new Set(
    (dayAnswer.statuses || []).filter((s) => s.status === 'closed').map((s) => s.facility),
  );
  const plannableNames = new Set(dist.keys());

  const rank = (p) => (plannableNames.has(p.name) ? 0 : closed.has(p.name) ? 1 : 2);
  const items = poolsMeta.map((p) => {
    const state = plannableNames.has(p.name) ? 'plannable' : closed.has(p.name) ? 'closed' : 'unknown';
    return {
      value: p.pool_id,
      label: p.name,
      state,
      distanceKm: dist.has(p.name) ? dist.get(p.name) : null,
      // Combobox badges: plannable → none; closed → 'closed'; unknown → 'no timetable yet'.
      ...(state === 'closed' ? { closed: true } : {}),
      ...(state === 'unknown' ? { note: 'no timetable yet' } : {}),
    };
  });
  items.sort((a, b) => {
    const ra = rank({ name: a.label });
    const rb = rank({ name: b.label });
    if (ra !== rb) return ra - rb;
    if (ra === 0) return (a.distanceKm ?? 1e9) - (b.distanceKm ?? 1e9); // plannable: nearest first
    return a.label.localeCompare(b.label);
  });
  return items;
}

async function main() {
  const root = document.documentElement;

  // --- initial FilterState: absolute today (UTC), first place preset, Day mode ---
  const today = isoDate(new Date());
  // The URL projection context: the receiver's today + the age vocabulary. `place` is
  // deliberately NEVER encoded (a client-side choice), so it lives only in the seed.
  const urlCtx = { today, ageTokens: AGE_TOKENS };
  const makeSeed = () =>
    createFilterState({ mode: 'day', date: today, place: { ...PLACE_PRESETS[0] } });

  // Hydrate: the URL patch wins OVER the default seed, so a shared link restores the
  // exact pool + filters + view. A URL `pool=` beats the nearest-plannable auto-select
  // (the Pool-entry seed only fills `selectedPool` when null — see buildToolbar). The
  // pool label is `null` here; hydratePoolPicker backfills it from /pools.
  let filter = merge(makeSeed(), fromSearch(location.search, urlCtx));

  // Backfill a URL-restored pool's display name from the classified /pools list (matched
  // by id). An unknown/old slug has no match → drop to null: graceful fallback to the
  // auto-select / plain view, never a crash. A no-op unless a pool id is set without a name.
  function backfillPoolName(f) {
    if (!f.selectedPool || !f.selectedPool.id || f.selectedPool.name) return f;
    const match = poolOptions.find((o) => o.value === f.selectedPool.id);
    return merge(f, {
      selectedPool: match ? { id: match.value, name: match.label } : null,
    });
  }

  // syncUrl(next) — mirror the current filter into the address bar (the URL is a pure
  // PROJECTION of `filter`, never a second source of truth). pushState when the VIEW or
  // POOL changed vs the current URL (so Back steps between pools/views); replaceState for
  // plain filter toggles (no history spam). Guard: if the computed search already equals
  // location.search, do nothing — a no-op that also breaks any popstate feedback loop.
  function syncUrl(next) {
    const search = toSearch(next, urlCtx);
    if (search === location.search) return;
    const prev = fromSearch(location.search, urlCtx);
    const prevPool = prev.selectedPool?.id ?? null;
    const nextPool = next.selectedPool?.id ?? null;
    const prevView = prev.mode === 'pool' ? 'pool' : 'day';
    const nextView = next.mode === 'pool' ? 'pool' : 'day';
    const structural = prevView !== nextView || prevPool !== nextPool;
    const url = `${location.pathname}${search}`;
    if (structural) history.pushState(null, '', url);
    else history.replaceState(null, '', url);
  }

  // --- header ---
  const header = createIdentityHeader($('app-header'), {
    props: { dateLabel: formatLabel(today), theme: 'auto' },
    root,
    onThemeChange: (t) => applyTheme(root, t),
  });

  // --- insight + legend ---
  const insight = createInsightBar($('app-insight'), {});
  createBoardLegend($('app-legend'));

  // --- board + panel hosts (rebuilt per render) ---
  const boardHost = $('app-board');
  const panelHost = $('app-panel');
  let board = null;
  let cursorLines = [];
  let poolOptions = []; // classified pool-picker options (nearest plannable first)
  let defaultPool = null; // { value, label } — the nearest plannable pool
  const poolIdByName = new Map(); // facility name → pool_id (to open closed/uncurated rows)

  // The persisted shared cursor (minutes-of-day) + the pool it belongs to. It survives
  // re-renders so a mode-only switch (Day↔Pool on the SAME pool) KEEPS the cursor for
  // continuity; changing the pool (a new combobox pick or a Day row click on a different
  // pool) RESETS it to that pool's best-public (plan item 8).
  let cursorMin = null;
  let cursorPoolId = null;

  function headerLabel() {
    if (filter.mode === 'pool') {
      const [monIso] = weekDates(filter.date || today);
      return `Week of ${formatLabel(monIso)}`;
    }
    return formatLabel(filter.date || today);
  }

  // Overlay ONE shared cursor line on the board's single scroll track (positioned at
  // TIMESCALE.X(min)); it spans every row and moves in lock-step with the panel.
  function seedCursors() {
    cursorLines = [];
    boardHost.querySelectorAll('.board__track').forEach((track) => {
      track.style.position = 'relative';
      const line = document.createElement('div');
      line.className = 'gantt__cursor';
      line.style.left = '0px';
      track.appendChild(line);
      cursorLines.push(line);
    });
  }
  function moveCursors(min) {
    for (const line of cursorLines) line.style.left = `${TIMESCALE.X(min)}px`;
  }

  let panel = null;
  // The panel-rail helper shown until a pool is opened — never a blank rail (plan FIX 4).
  function renderPanelHelper() {
    panelHost.textContent = '';
    panel = null;
    const msg = document.createElement('p');
    msg.className = 'app__panelempty';
    msg.textContent = 'Click any pool to see its hours, price and lane plan.';
    panelHost.appendChild(msg);
  }

  // The DetailPanel ALWAYS opens (plan FIX 3): a plannable pool resolves to its OWN
  // basin's lane plan (board readout == panel headline); a pool with hours but no lane
  // split degrades to 'lanes-unknown'; a closed / uncurated pool opens in that state.
  function openPanel(detail, opts = {}) {
    panelHost.textContent = '';
    panel = createDetailPanel(panelHost, {
      detail: detail || {},
      basin: opts.basin || null,
      timescale: TIMESCALE,
      filter,
      cursorMin: opts.cursorMin != null ? opts.cursorMin : null,
      distanceKm: opts.distanceKm != null ? opts.distanceKm : null,
      basinName: opts.basinName || null,
      state: opts.state || null,
      reason: opts.reason || null,
      accessTypes: opts.accessTypes || [],
      // The single Day→Pool continuity affordance: open Pool view on the SAME pool.
      // `selectedPool` is left untouched (it is already the clicked pool), so the week
      // renders for it — plannable or honestly closed/uncurated (plan item 3).
      onOpenWeek: () => {
        filter = merge(filter, { mode: 'pool' });
        buildToolbar(); // rebuild so VIEW shows Pool + the date stepper swaps to the pool picker + week stepper
        render();
        syncUrl(filter); // Day→Pool on the same pool is a VIEW change → pushState (Back returns)
      },
    });
    // Align the shared board cursor to the panel's resolved cursor (only the lane
    // panel drives a cursor; the degraded states have none to align). Persist that
    // resolved cursor so a later mode-only switch on the same pool keeps it.
    if (opts.basin && panel.cursorMin != null) {
      cursorMin = panel.cursorMin;
      moveCursors(cursorMin);
    }
  }

  function setCursor(min) {
    moveCursors(min);
    if (panel) panel.setCursor(min);
  }
  function minFromEvent(canvas, ev) {
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(TIMESCALE.PLOT, ev.clientX - rect.left));
    return TIMESCALE.inverse(x);
  }

  // Open the DetailPanel for ANY board row (plan FIX 2 + FIX 3). A row WITH options
  // resolves to the SAME basin's /pools/{id} lane plan (or degrades to lanes-unknown
  // when no split is published); a closed / uncurated row opens in its own state,
  // fetching the facility facts by name→id so the panel still carries facts + prov.
  async function onRowClick(rowIndex, min, opts = {}) {
    // A real user click mirrors the chosen pool into the URL (so it's shareable/linkable);
    // the load-time auto-open passes { fromUser: false } so a bare default link stays bare.
    const fromUser = opts.fromUser !== false;
    const row = board.rows[rowIndex];
    if (!row) return;
    if (row.options.length > 0) {
      const opt = row.options[0];
      // Persist the selection into the SHARED filter BEFORE opening the panel, so it
      // survives re-renders and carries into Pool view (plan item 2).
      const poolId = opt.facility_id;
      filter = merge(filter, { selectedPool: { id: poolId, name: row.label } });
      // Cursor: an explicit canvas click (min != null) places the cursor; otherwise a
      // pool change resets to best-public (cursorMin=null → the panel picks it) while a
      // same-pool open keeps the persisted cursor for continuity (plan item 8).
      let openAt = min;
      if (min == null) openAt = cursorPoolId === poolId ? cursorMin : null;
      cursorPoolId = poolId;
      const detail = await fetchPoolDetail(poolId, filter.date || today);
      const lanePanels = (detail && detail.lane_panels) || [];
      const lp = panelForBasin(lanePanels, opt.basin);
      const basin = lp ? basinFromPanel(lp) : null;
      const accessTypes = [...new Set(row.options.map((o) => o.access))];
      openPanel(detail, {
        basin,
        cursorMin: openAt,
        distanceKm: opt.distance_km,
        basinName: opt.basin,
        accessTypes,
      });
      if (fromUser) syncUrl(filter); // clicked pool → shareable URL (pool change → pushState)
      return;
    }
    // Closed / uncurated row: no option to fetch by, so resolve the facility by name.
    // The selection still persists (an unplannable pool is a legitimate choice — it
    // opens an honest closed/uncurated week in Pool view; plan items 2 + 5).
    const id = poolIdByName.get(row.label);
    filter = merge(filter, { selectedPool: { id: id ?? null, name: row.label } });
    cursorPoolId = id ?? null;
    cursorMin = null;
    const closed = row.statuses.find((s) => s.status === 'closed');
    const state = closed ? 'closed' : 'uncurated';
    const st = closed || row.statuses.find((s) => s.status === 'uncurated') || row.statuses[0];
    const detail = id ? await fetchPoolDetail(id, filter.date || today) : null;
    openPanel(detail, { state, reason: st ? st.detail : null, basinName: null });
    if (fromUser) syncUrl(filter); // clicked a closed/uncurated pool → still a shareable selection
  }

  function wireBoardCursor() {
    seedCursors();
    const canvases = [...boardHost.querySelectorAll('.board__canvas')];
    canvases.forEach((canvas, i) => {
      canvas.style.cursor = 'crosshair';
      canvas.addEventListener('mousemove', (ev) => setCursor(minFromEvent(canvas, ev)));
      canvas.addEventListener('click', (ev) => onRowClick(i, minFromEvent(canvas, ev)));
    });
    // EVERY row label opens the panel too (plan FIX 2) — Day mode included. A label
    // click opens on the row's best cursor (min=null → the panel picks best_public).
    const labels = [...boardHost.querySelectorAll('.board__labelsbody .board__rowlabel')];
    labels.forEach((label, i) => {
      label.addEventListener('click', () => onRowClick(i, null));
    });
  }

  // Auto-open the panel on (re)paint. Day→Pool continuity (plan item 6): if a pool is
  // already selected AND a row with its name exists (Day mode), open THAT row so the
  // panel follows the selection across a mode switch; otherwise fall back to the nearest
  // PLANNABLE pool (the API orders nearest-first, so the first option-bearing row). No
  // matching / plannable row → the helper stays. Out-of-range keeps `selectedPool` in
  // state and only falls the PANEL back — the selection is never silently cleared.
  async function autoOpenSelectedOrNearest() {
    if (!board) return;
    if (filter.selectedPool && filter.selectedPool.name) {
      const sel = board.rows.findIndex((r) => r.label === filter.selectedPool.name);
      if (sel >= 0) {
        await onRowClick(sel, null, { fromUser: false });
        return;
      }
    }
    const idx = board.rows.findIndex((r) => r.options && r.options.length > 0);
    if (idx < 0) return;
    await onRowClick(idx, null, { fromUser: false });
  }

  async function render() {
    header.setDateLabel(headerLabel());
    // Tear down the previous board FIRST so its shared RAF loop stops — otherwise every
    // filter change would leave an orphaned loop redrawing detached canvases forever.
    if (board) board.destroy();
    boardHost.textContent = '';
    let data;
    let answerForEmpty; // the /swim answer the no-pools empty state is judged against
    if (filter.mode === 'pool') {
      const week = await fetchWeek(filter, filter.date || today);
      const focused = focusWeekOnPool(week, filter.selectedPool?.name ?? week.facility);
      data = { week: applyLapWeek(focused, filter.lapOnly) };
      answerForEmpty = {
        options: data.week.days.flatMap((d) => d.answer.options),
        statuses: data.week.days.flatMap((d) => d.answer.statuses),
      };
    } else {
      const day = applyLap(await fetchDay(filter, filter.date || today), filter.lapOnly);
      data = { day };
      answerForEmpty = day;
    }
    board = createBoard(boardHost, { data, filter, timescale: TIMESCALE, today });
    insight.update(data, filter);
    wireBoardCursor();
    // A SINGLE board-level empty state, shown ONLY when the answer has neither options
    // nor statuses (plan FIX 1). Closed/uncurated pools read on their own rows above —
    // there is no duplicate below-board section anymore.
    if (emptyState(answerForEmpty)) {
      const emptyHost = document.createElement('div');
      emptyHost.className = 'app__boardempty';
      createStateBlocks(emptyHost, { answer: answerForEmpty });
      boardHost.appendChild(emptyHost);
    }
    // Never a blank rail: show the helper, then auto-open the selected (or nearest) pool.
    renderPanelHelper();
    await autoOpenSelectedOrNearest();
  }

  // Rebuild the toolbar with the current classified pool list (called after /pools +
  // the first day answer resolve, so the pool picker is honest from the first open).
  function buildToolbar() {
    $('app-toolbar').textContent = '';
    createFilterToolbar($('app-toolbar'), {
      props: {
        filter,
        places: PLACE_PRESETS,
        pools: poolOptions,
        dateBounds: { today, min: today, max: isoDate(addDays(new Date(), 60)) },
      },
      onChange: (next) => {
        // Entering Pool mode with NO pool selected yet → seed the nearest plannable pool
        // so the combobox + board open on a real, named pool (plan item 5). A non-null
        // selectedPool is NEVER overridden — an already-chosen (even unplannable) pool is
        // kept and its week renders honestly.
        if (next.mode === 'pool' && !next.selectedPool && defaultPool) {
          filter = merge(next, {
            selectedPool: { id: defaultPool.value, name: defaultPool.label },
          });
          buildToolbar(); // re-mount so the combobox shows the auto-selected pool name
        } else {
          filter = next;
        }
        render();
        syncUrl(filter); // mirror every toolbar edit (incl. the Pool-entry seed) into the URL
      },
    });
  }

  // --- toolbar: one FilterState drives the whole page (rebuilt once pools resolve) ---
  buildToolbar();

  // Classify the pools against the current day, pick a default plannable pool, and
  // rebuild the toolbar so Pool mode opens on a named, plannable pool.
  await hydratePoolPicker();

  await render();

  // Back/forward: re-parse the URL, rebuild the filter over a FRESH seed, backfill the
  // pool label, and repaint. We NEVER call syncUrl here (popstate READS the URL, it does
  // not write it) — that, plus the string-compare guard in syncUrl, prevents a loop.
  window.addEventListener('popstate', async () => {
    filter = backfillPoolName(merge(makeSeed(), fromSearch(location.search, urlCtx)));
    buildToolbar();
    await render();
  });

  // --- helpers scoped to main ---
  function addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }
  async function hydratePoolPicker() {
    try {
      const [poolsRes, dayAnswer] = await Promise.all([
        fetch('/pools'),
        fetchDay(filter, filter.date || today),
      ]);
      if (!poolsRes.ok) return;
      const body = await poolsRes.json();
      const poolsMeta = body.pools || [];
      // name → id, so a closed / uncurated board row (which carries only a facility
      // NAME, no option) can still resolve its /pools/{id} facts for the panel.
      poolIdByName.clear();
      for (const p of poolsMeta) poolIdByName.set(p.name, p.pool_id);
      poolOptions = classifyPools(poolsMeta, dayAnswer);
      // A URL-restored pool arrives as { id, name:null } — resolve its display name now
      // (or drop an unknown/old slug to null; the pool_alias crosswalk resolves renames
      // server-side, so a live slug still matches here).
      filter = backfillPoolName(filter);
      const nearestPlannable = poolOptions.find((p) => p.state === 'plannable');
      if (nearestPlannable) {
        // The nearest plannable pool — the default seeded into `selectedPool` when the
        // user first enters Pool mode without a choice (see buildToolbar onChange). We do
        // NOT pre-write it here: Day mode's first paint auto-opens (and thus selects) the
        // nearest pool on its own, and a non-null selectedPool must never be overridden.
        defaultPool = { value: nearestPlannable.value, label: nearestPlannable.label };
      }
      buildToolbar();
    } catch {
      /* the pool picker is a nicety for Pool mode; Day mode works without it */
    }
  }
}

main();
