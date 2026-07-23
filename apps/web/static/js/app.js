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
import { createStateBlocks } from './blocks/stateblocks.js';
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

  // --- insight + legend + state blocks ---
  const insight = createInsightBar($('app-insight'), {});
  createBoardLegend($('app-legend'));
  const states = createStateBlocks($('app-states'), {});

  // --- board + panel hosts (rebuilt per render) ---
  const boardHost = $('app-board');
  const panelHost = $('app-panel');
  let board = null;
  let cursorLines = [];
  let poolOptions = []; // classified pool-picker options (nearest plannable first)
  let defaultPool = null; // { value, label } — the nearest plannable pool

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
  function openPanel(detail, cursorMin, distanceKm, basinName) {
    panelHost.textContent = '';
    if (!detail || !detail.lane_panels || detail.lane_panels.length === 0) {
      const msg = document.createElement('p');
      msg.className = 'app__panelempty';
      msg.textContent = 'No published lane plan for this pool yet.';
      panelHost.appendChild(msg);
      panel = null;
      return;
    }
    // Resolve the clicked row's OWN basin (not always lane_panels[0]) so the panel
    // headline reads the same basin the board readout does on multi-basin facilities.
    const basin = basinFromPanel(panelForBasin(detail.lane_panels, basinName));
    panel = createDetailPanel(panelHost, {
      detail,
      basin,
      timescale: TIMESCALE,
      filter,
      cursorMin,
      distanceKm,
    });
    moveCursors(panel.cursorMin);
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

  // Resolve a clicked board row to the SAME basin's /pools/{id} detail, then open the
  // panel there — so "board readout == panel headline" holds on live data. A row with
  // no options (a ghost/closed/no-lap day) has nothing to open.
  async function onRowClick(rowIndex, min) {
    const row = board.rows[rowIndex];
    if (!row || row.options.length === 0) return;
    const opt = row.options[0];
    const detail = await fetchPoolDetail(opt.facility_id, filter.date || today);
    openPanel(detail, min, opt.distance_km, opt.basin);
    setCursor(min);
  }

  function wireBoardCursor() {
    seedCursors();
    const canvases = [...boardHost.querySelectorAll('.board__canvas')];
    canvases.forEach((canvas, i) => {
      canvas.style.cursor = 'crosshair';
      canvas.addEventListener('mousemove', (ev) => setCursor(minFromEvent(canvas, ev)));
      canvas.addEventListener('click', (ev) => onRowClick(i, minFromEvent(canvas, ev)));
    });
  }

  async function render() {
    header.setDateLabel(headerLabel());
    // Tear down the previous board FIRST so its shared RAF loop stops — otherwise every
    // filter change would leave an orphaned loop redrawing detached canvases forever.
    if (board) board.destroy();
    boardHost.textContent = '';
    let data;
    if (filter.mode === 'pool') {
      const week = await fetchWeek(filter, filter.date || today);
      const focused = focusWeekOnPool(week, filter.pool ? filter.pool.label : week.facility);
      data = { week: applyLapWeek(focused, filter.lapOnly) };
      states.update({ options: data.week.days.flatMap((d) => d.answer.options), statuses: [] });
    } else {
      const day = applyLap(await fetchDay(filter, filter.date || today), filter.lapOnly);
      data = { day };
      states.update(day);
    }
    board = createBoard(boardHost, { data, filter, timescale: TIMESCALE, today });
    insight.update(data, filter);
    wireBoardCursor();
    panelHost.textContent = '';
    panel = null;
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
