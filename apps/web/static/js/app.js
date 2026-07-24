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
import { createFilterToolbar } from './blocks/toolbar.js';
import { createInsightBar } from './blocks/insightbar.js';
import { createBoard, BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './blocks/board.js';
import { createDetailPanel } from './blocks/detailpanel.js';
import { createBoardLegend } from './blocks/legend.js';
import { createStateBlocks, emptyState } from './blocks/stateblocks.js';
import { createFilterState } from './filterstate.js';
import { makeTimescale } from './timescale.js';
import { basinFromPanel, panelForBasin } from './blocks/cursor.js';
import { formatLabel } from './components/datestepper.js';
import { fetchDay, fetchWeek, fetchPoolDetail, isoDate, weekDates } from './api.js';

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
  let filter = createFilterState({
    mode: 'day',
    date: today,
    place: { ...PLACE_PRESETS[0] },
  });

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
    });
    // Align the shared board cursor to the panel's resolved cursor (only the lane
    // panel drives a cursor; the degraded states have none to align).
    if (opts.basin && panel.cursorMin != null) moveCursors(panel.cursorMin);
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
  async function onRowClick(rowIndex, min) {
    const row = board.rows[rowIndex];
    if (!row) return;
    if (row.options.length > 0) {
      const opt = row.options[0];
      const detail = await fetchPoolDetail(opt.facility_id, filter.date || today);
      const lanePanels = (detail && detail.lane_panels) || [];
      const lp = panelForBasin(lanePanels, opt.basin);
      const basin = lp ? basinFromPanel(lp) : null;
      const accessTypes = [...new Set(row.options.map((o) => o.access))];
      openPanel(detail, {
        basin,
        cursorMin: min,
        distanceKm: opt.distance_km,
        basinName: opt.basin,
        accessTypes,
      });
      return;
    }
    // Closed / uncurated row: no option to fetch by, so resolve the facility by name.
    const closed = row.statuses.find((s) => s.status === 'closed');
    const state = closed ? 'closed' : 'uncurated';
    const st = closed || row.statuses.find((s) => s.status === 'uncurated') || row.statuses[0];
    const id = poolIdByName.get(row.label);
    const detail = id ? await fetchPoolDetail(id, filter.date || today) : null;
    openPanel(detail, { state, reason: st ? st.detail : null, basinName: null });
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

  // Auto-open the nearest PLANNABLE pool on first paint so the panel + board↔gantt
  // alignment are visible immediately (plan FIX 4). The API orders nearest-first, so
  // the first option-bearing row is the nearest plannable pool. No plannable row →
  // the helper stays.
  async function autoOpenNearest() {
    if (!board) return;
    const idx = board.rows.findIndex((r) => r.options && r.options.length > 0);
    if (idx < 0) return;
    await onRowClick(idx, null);
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
      const focused = focusWeekOnPool(week, filter.pool ? filter.pool.label : week.facility);
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
    // Never a blank rail: show the helper, then auto-open the nearest plannable pool.
    renderPanelHelper();
    await autoOpenNearest();
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
        // Entering Pool mode with no pool chosen yet → default to the nearest plannable
        // pool so the board opens on a real, named pool (plan item 3).
        if (next.mode === 'pool' && !next.pool && defaultPool) {
          filter = { ...next, pool: { ...defaultPool } };
          buildToolbar(); // re-mount so the combobox shows the auto-selected pool name
        } else {
          filter = next;
        }
        render();
      },
    });
  }

  // --- toolbar: one FilterState drives the whole page (rebuilt once pools resolve) ---
  buildToolbar();

  // Classify the pools against the current day, pick a default plannable pool, and
  // rebuild the toolbar so Pool mode opens on a named, plannable pool.
  await hydratePoolPicker();

  await render();

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
      const nearestPlannable = poolOptions.find((p) => p.state === 'plannable');
      if (nearestPlannable) {
        defaultPool = { value: nearestPlannable.value, label: nearestPlannable.label };
        // Seed filter.pool so a switch to Pool mode surfaces the pool's identity even
        // before the user touches the picker.
        if (!filter.pool) filter = { ...filter, pool: { ...defaultPool } };
      }
      buildToolbar();
    } catch {
      /* the pool picker is a nicety for Pool mode; Day mode works without it */
    }
  }
}

main();
