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

import {
  createBoard,
  BOARD_DAY0,
  BOARD_DAY1,
  BOARD_PLOT,
  type BoardAnswer,
} from './board.js';
import { asEl } from '../domtypes.js';
import { createDetailPanel, type BasinPlan, type FacilityDetail } from './detailpanel.js';
import { makeTimescale } from '../timescale.js';
import { basinFromPanel, publicAt, minToHhmm, type LanePanel } from './cursor.js';

function readJSON<T>(id: string): T | null {
  const el = document.getElementById(id);
  if (!el) return null;
  try {
    return JSON.parse(el.textContent ?? '') as T;
  } catch {
    return null;
  }
}

export function hydrateDetailPreview(root: ParentNode = document) {
  const day = readJSON<Record<string, unknown>>('detail-day-data');
  const pool = readJSON<FacilityDetail & { lane_panels?: unknown[] }>('detail-pool-data');
  if (!day || !pool || !pool.lane_panels || pool.lane_panels.length === 0) return null;

  // ONE timescale, shared by the board and the panel's Gantt — the anti-desync anchor.
  const ts = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);
  const basin = basinFromPanel(pool.lane_panels[0] as LanePanel) as BasinPlan;

  const boardMount = root.querySelector('#detail-board');
  const panelMount = root.querySelector('#detail-panel');
  const readoutEl = root.querySelector('#detail-readout');
  if (!boardMount || !panelMount) return null;

  createBoard(asEl(boardMount), {
    data: { day: day as unknown as BoardAnswer },
    filter: { mode: 'day', gender: '', age: null },
    timescale: ts,
  });
  const panel = createDetailPanel(asEl(panelMount), {
    detail: pool,
    basin,
    timescale: ts,
    cursorMin: basin.best_public ? undefined : Math.round((ts.lo + ts.hi) / 2),
  });

  // Overlay a movable cursor line on every board row track (positioned at ts.X(min),
  // the SAME mapping the Gantt uses), and wire click/hover on each row's canvas.
  const cursors: HTMLElement[] = [];
  const tracks = boardMount.querySelectorAll('.board__track');
  tracks.forEach((track) => {
    (track as HTMLElement).style.position = 'relative';
    const line = document.createElement('div');
    line.className = 'gantt__cursor'; // reuse the token-styled cursor rule
    line.style.left = '0px';
    track.appendChild(line);
    cursors.push(line);
  });

  function setCursor(min: number) {
    for (const line of cursors) line.style.left = `${ts.X(min)}px`;
    panel.setCursor(min);
    const { public: n, total: m } = publicAt(basin, min);
    if (readoutEl) {
      readoutEl.textContent = `Board readout — ${minToHhmm(min)} · ${n} of ${m} lanes public`;
    }
  }

  function minFromEvent(canvas: HTMLElement, ev: MouseEvent): number {
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(ts.PLOT, ev.clientX - rect.left));
    return ts.inverse(x);
  }

  boardMount.querySelectorAll('.board__canvas').forEach((node) => {
    const canvas = node as HTMLElement;
    canvas.style.cursor = 'crosshair';
    canvas.addEventListener('click', (ev) => setCursor(minFromEvent(canvas, ev as MouseEvent)));
    canvas.addEventListener('mousemove', (ev) =>
      setCursor(minFromEvent(canvas, ev as MouseEvent)),
    );
  });

  // Seed the shared cursor at the panel's initial position.
  setCursor(panel.cursorMin ?? 0);
  return { panel, ts, basin };
}

hydrateDetailPreview();
