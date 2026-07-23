// board_preview.js — the client entrypoint for the DEV-only /ui/board preview.
//
// The server (apps/web/api/board_preview/router.py) inlines two saved `/swim`
// fixtures as <script type="application/json"> blocks and renders two mount
// points; this reads them and mounts a RibbonBoard in Day and Pool mode. A tiny
// gender/age control demonstrates the FilterState-driven re-render (setFilter).
//
// Not a test file and imported by no test, so `node --test` never loads it (it is
// a real-`document` module, like components/gallery.js).

import { createBoard } from './board.js';
import { createFilterState, merge } from '../filterstate.js';

function readJSON(id) {
  const el = document.getElementById(id);
  if (!el) return null;
  try {
    return JSON.parse(el.textContent);
  } catch {
    return null;
  }
}

export function hydrateBoardPreview(root = document) {
  const data = { day: readJSON('board-day-data'), week: readJSON('board-week-data') };
  const boards = [];

  const dayMount = root.querySelector('#board-day');
  if (dayMount && data.day) {
    boards.push(createBoard(dayMount, { data, filter: createFilterState({ mode: 'day' }) }));
  }
  const poolMount = root.querySelector('#board-pool');
  if (poolMount && data.week) {
    boards.push(createBoard(poolMount, { data, filter: createFilterState({ mode: 'pool' }) }));
  }

  // FilterState-driven demo: gender/age changes re-render every board's row badges.
  let filter = createFilterState({});
  const rerender = () => {
    const genderSel = root.querySelector('#board-gender');
    const ageInput = root.querySelector('#board-age');
    const age = ageInput && ageInput.value !== '' ? Number(ageInput.value) : null;
    filter = merge(filter, { gender: genderSel ? genderSel.value : '', age });
    boards.forEach((b, i) => b.setFilter(merge(filter, { mode: i === 0 ? 'day' : 'pool' })));
  };
  root.querySelectorAll('#board-gender, #board-age').forEach((el) => {
    el.addEventListener('change', rerender);
    el.addEventListener('input', rerender);
  });

  return boards;
}

hydrateBoardPreview();
