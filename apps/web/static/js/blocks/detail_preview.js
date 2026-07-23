// detail_preview.js — the client entrypoint for the DEV-only /ui/detail preview.
//
// The server (apps/web/api/detail_preview/router.py) inlines a saved `/swim`
// fixture (the board) and a saved `/pools/{id}` fixture (the panel + Gantt) and
// renders the mount points; this reads them and mounts a RibbonBoard + a
// DetailPanel/LaneGantt that ALL share ONE timescale. Clicking a board ribbon at
// time T sets one cursor: the Gantt cursor lands on T's gridline, and the board
// readout + panel headline both show the SAME `publicAt(basin, T)` — the S3 crown
// jewel, made visible for the human review at the S3 pause.
//
// Not a test file and imported by no test, so `node --test` never loads it (it is
// a real-`document` module, like board_preview.js and components/gallery.js).

import { createBoard, BOARD_DAY0, BOARD_DAY1, BOARD_PLOT } from './board.js';
import { createDetailPanel } from './detailpanel.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, publicAt, minToHhmm } from './cursor.js';

function readJSON(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  try {
    return JSON.parse(el.textContent);
  } catch {
    return null;
  }
}

export function hydrateDetailPreview(root = document) {
  const day = readJSON('detail-day-data');
  const pool = readJSON('detail-pool-data');
  if (!day || !pool || !pool.lane_panels || pool.lane_panels.length === 0) return null;

  // ONE timescale, shared by the board and the panel's Gantt — the anti-desync anchor.
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const basin = basinFromPanel(pool.lane_panels[0]);

  const boardMount = root.querySelector('#detail-board');
  const panelMount = root.querySelector('#detail-panel');
  const readoutEl = root.querySelector('#detail-readout');
  if (!boardMount || !panelMount) return null;

  createBoard(boardMount, {
    data: { day },
    filter: { mode: 'day', gender: '', age: null },
    timescale: ts,
  });
  const panel = createDetailPanel(panelMount, {
    detail: pool,
    basin,
    timescale: ts,
    cursorMin: basin.best_public ? undefined : Math.round((ts.lo + ts.hi) / 2),
  });

  // Overlay a movable cursor line on every board row track (positioned at ts.X(min),
  // the SAME mapping the Gantt uses), and wire click/hover on each row's canvas.
  const cursors = [];
  const tracks = boardMount.querySelectorAll('.board__track');
  tracks.forEach((track) => {
    track.style.position = 'relative';
    const line = document.createElement('div');
    line.className = 'gantt__cursor'; // reuse the token-styled cursor rule
    line.style.left = '0px';
    track.appendChild(line);
    cursors.push(line);
  });

  function setCursor(min) {
    for (const line of cursors) line.style.left = `${ts.X(min)}px`;
    panel.setCursor(min);
    const { public: n, total: m } = publicAt(basin, min);
    if (readoutEl) {
      readoutEl.textContent = `Board readout — ${minToHhmm(min)} · ${n} of ${m} lanes public`;
    }
  }

  function minFromEvent(canvas, ev) {
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(ts.PLOT, ev.clientX - rect.left));
    return ts.inverse(x);
  }

  boardMount.querySelectorAll('.board__canvas').forEach((canvas) => {
    canvas.style.cursor = 'crosshair';
    canvas.addEventListener('click', (ev) => setCursor(minFromEvent(canvas, ev)));
    canvas.addEventListener('mousemove', (ev) => setCursor(minFromEvent(canvas, ev)));
  });

  // Seed the shared cursor at the panel's initial position.
  setCursor(panel.cursorMin);
  return { panel, ts, basin };
}

hydrateDetailPreview();
