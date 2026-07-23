// app.js — the composition root of the unified two-mode UI (plan S4).
//
// It assembles IdentityHeader + FilterToolbar + InsightBar + RibbonBoard +
// DetailPanel + BoardLegend + StateBlocks over the live JSON API, and wires the
// ONE FilterState through them: a toolbar edit refetches (`/swim` for Day, the 7
// weekday `/swim` calls for Pool) and re-renders every block; a click on a board
// ribbon opens the DetailPanel on the SHARED time cursor, resolving the clicked
// board row to the SAME basin's `/pools/{id}` day_view so the board readout and
// the panel headline agree on real data (the S3 identity, preserved live).
//
// This module is browser-only (it touches a real `document`, canvas, geolocation)
// and is imported by no test — `node --test` never loads it. The PURE pieces it
// leans on (api URL builders, insight, state selection, filterstate, timescale,
// cursor) are unit-tested in isolation. No colour, no hex lives here.

import { createIdentityHeader, applyTheme } from './blocks/header.js';
import { createFilterToolbar } from './blocks/toolbar.js';
import { createInsightBar } from './blocks/insightbar.js';
import { createBoard, BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './blocks/board.js';
import { createDetailPanel } from './blocks/detailpanel.js';
import { createBoardLegend } from './blocks/legend.js';
import { createStateBlocks } from './blocks/stateblocks.js';
import { createFilterState, merge } from './filterstate.js';
import { makeTimescale } from './timescale.js';
import { basinFromPanel } from './blocks/cursor.js';
import { formatLabel } from './components/datestepper.js';
import { fetchDay, fetchWeek, fetchPoolDetail, isoDate, weekDates } from './api.js';

const PLACE_PRESETS = [
  { label: 'Zürich HB (main station)', lat: 47.3779, lon: 8.5403 },
  { label: 'Bellevue', lat: 47.3671, lon: 8.5451 },
  { label: 'Zürichhorn', lat: 47.3606, lon: 8.551 },
];

const $ = (id) => document.getElementById(id);

// Focus a whole day window on ONE shared timescale — the board ribbons AND the
// panel Gantt both draw through it, so a click at T lands on the same x in both.
const TIMESCALE = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);

// Keep only the selected pool's options/statuses in a Pool-mode week, so the board
// shows that one pool across seven days (not every nearby pool).
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

  function headerLabel() {
    if (filter.mode === 'pool') {
      const [monIso] = weekDates(filter.date || today);
      return `Week of ${formatLabel(monIso)}`;
    }
    return formatLabel(filter.date || today);
  }

  // Overlay a shared cursor line on every board row track (positioned at
  // TIMESCALE.X(min)), and move them together with the panel (S3 shared cursor).
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
  function openPanel(detail, cursorMin, distanceKm) {
    panelHost.textContent = '';
    if (!detail || !detail.lane_panels || detail.lane_panels.length === 0) {
      const msg = document.createElement('p');
      msg.className = 'app__panelempty';
      msg.textContent = 'No published lane plan for this pool yet.';
      panelHost.appendChild(msg);
      panel = null;
      return;
    }
    const basin = basinFromPanel(detail.lane_panels[0]);
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

  // Resolve a clicked board row to the SAME basin's /pools/{id} detail, then open
  // the panel there — so "board readout == panel headline" holds on live data.
  async function onRowClick(rowIndex, min) {
    const row = board.rows[rowIndex];
    if (!row || row.options.length === 0) return;
    const opt = row.options[0];
    const detail = await fetchPoolDetail(opt.facility_id, filter.date || today);
    openPanel(detail, min, opt.distance_km);
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
    boardHost.textContent = '';
    let data;
    if (filter.mode === 'pool') {
      const week = await fetchWeek(filter, filter.date || today);
      data = { week: focusWeekOnPool(week, filter.pool ? filter.pool.label : week.facility) };
      states.update({ options: data.week.days.flatMap((d) => d.answer.options), statuses: [] });
    } else {
      const day = await fetchDay(filter, filter.date || today);
      data = { day };
      states.update(day);
    }
    board = createBoard(boardHost, { data, filter, timescale: TIMESCALE });
    insight.update(data, filter);
    wireBoardCursor();
    panelHost.textContent = '';
    panel = null;
  }

  // --- toolbar: one FilterState drives the whole page ---
  createFilterToolbar($('app-toolbar'), {
    props: {
      filter,
      places: PLACE_PRESETS,
      pools: [],
      dateBounds: { today, min: today, max: isoDate(addDays(new Date(), 60)) },
    },
    onChange: (next) => {
      filter = next;
      render();
    },
  });

  // Populate the pool Combobox from /pools once (name → id), for Pool mode.
  hydratePoolOptions();

  await render();

  // --- helpers scoped to main ---
  function addDays(date, days) {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }
  async function hydratePoolOptions() {
    try {
      const res = await fetch('/pools');
      if (!res.ok) return;
      const body = await res.json();
      const pools = (body.pools || []).map((p) => ({
        value: p.pool_id,
        label: p.name,
        closed: !p.curated,
      }));
      // Rebuild the toolbar with the resolved pool list (cheap; keeps the module thin).
      $('app-toolbar').textContent = '';
      createFilterToolbar($('app-toolbar'), {
        props: {
          filter,
          places: PLACE_PRESETS,
          pools,
          dateBounds: { today, min: today, max: isoDate(addDays(new Date(), 60)) },
        },
        onChange: (next) => {
          filter = next;
          render();
        },
      });
    } catch {
      /* pools list is a nicety for Pool mode; Day mode works without it */
    }
  }
}

main();
