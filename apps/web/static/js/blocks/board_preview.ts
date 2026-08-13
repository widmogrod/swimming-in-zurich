// board_preview.js — the client entrypoint for the DEV-only /ui/board preview.
//
// The server (apps/web/api/board_preview/router.py) inlines two saved `/swim`
// fixtures as <script type="application/json"> blocks and renders two mount
// points; this reads them and mounts a RibbonBoard in Day and Pool mode. A tiny
// gender/age control demonstrates the FilterState-driven re-render (setFilter).
//
// Not a test file and imported by no test, so `node --test` never loads it (it is
// a real-`document` module, like components/gallery.js).

import { asEl } from '../domtypes.js';
import { createBoard, type BoardData } from './board.js';
import { createFilterState, merge, type FilterState } from '../filterstate.js';

function readJSON<T>(id: string): T | null {
  const el = document.getElementById(id);
  if (!el) return null;
  try {
    return JSON.parse(el.textContent ?? '') as T;
  } catch {
    return null;
  }
}

export function hydrateBoardPreview(root: ParentNode = document) {
  const data: BoardData = {
    day: readJSON('board-day-data') ?? undefined,
    week: readJSON('board-week-data') ?? undefined,
  };
  const boards: ReturnType<typeof createBoard>[] = [];

  const dayMount = root.querySelector('#board-day');
  if (dayMount && data.day) {
    boards.push(createBoard(asEl(dayMount), { data, filter: createFilterState({ mode: 'day' }) }));
  }
  const poolMount = root.querySelector('#board-pool');
  if (poolMount && data.week) {
    boards.push(createBoard(asEl(poolMount), { data, filter: createFilterState({ mode: 'pool' }) }));
  }

  // FilterState-driven demo: gender/age changes re-render every board's row badges.
  let filter = createFilterState({});
  const rerender = () => {
    const genderSel = root.querySelector('#board-gender');
    const ageInput = root.querySelector('#board-age');
    const ageEl = ageInput ? asEl(ageInput) : null;
    const age = ageEl && ageEl.value !== '' ? Number(ageEl.value) : null;
    filter = merge(filter, {
      gender: (genderSel ? asEl(genderSel).value : '') as FilterState['gender'],
      age,
    });
    boards.forEach((b, i) => b.setFilter(merge(filter, { mode: i === 0 ? 'day' : 'pool' })));
  };
  root.querySelectorAll('#board-gender, #board-age').forEach((el) => {
    el.addEventListener('change', rerender);
    el.addEventListener('input', rerender);
  });

  return boards;
}

hydrateBoardPreview();
