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

import {
  fetchDay,
  fetchPoolDetail,
  fetchWeek,
  isoDate,
  weekDates,
} from "./api.js";
import {
  applyLap,
  applyLapWeek,
  classifyPools,
  focusWeekOnPool,
  isStructuralUrlChange,
  type PoolMeta,
  type PoolOption,
} from "./appdata.js";
import {
  BOARD_DAY0,
  BOARD_DAY1,
  BOARD_PLOT,
  createBoard,
} from "./blocks/board.js";
import {
  basinFromPanel,
  panelForBasin,
  type LanePanel,
} from "./blocks/cursor.js";
import {
  createDetailPanel,
  type DetailPanelOpts,
  type FacilityDetail,
} from "./blocks/detailpanel.js";
import { applyTheme, createIdentityHeader } from "./blocks/header.js";
import { createInsightBar } from "./blocks/insightbar.js";
import { createBoardLegend } from "./blocks/legend.js";
import { createStateBlocks, emptyState } from "./blocks/stateblocks.js";
import { createFilterToolbar, DEFAULT_AGE_CHIPS } from "./blocks/toolbar.js";
import { formatLabel } from "./components/datestepper.js";
import { asEl, type El } from "./domtypes.js";
import { createFilterState, merge, type FilterState } from "./filterstate.js";
import { makeTimescale } from "./timescale.js";
import { fromSearch, toSearch, type UrlFilterState } from "./urlstate.js";

// The age value⇆token vocabulary the URL uses, derived from the toolbar's own chips so
// the URL scheme and the UI never drift. `''` (Any age) has no token — it is the omitted
// default. e.g. { value: 8, token: 'child' } … { value: 70, token: 'senior' }.
const AGE_TOKENS = DEFAULT_AGE_CHIPS.filter((c) => c.value !== "").map((c) => ({
  value: Number(c.value),
  token: c.label.toLowerCase(),
}));

const PLACE_PRESETS = [
  { label: "Zürich HB (main station)", lat: 47.3779, lon: 8.5403 },
  { label: "Bellevue", lat: 47.3671, lon: 8.5451 },
  { label: "Zürichhorn", lat: 47.3606, lon: 8.551 },
];

// ---- Local structural types (the urlstate.ts convention) ---------------------------

/** A `/pools` PoolOut row, read structurally. */

const $ = (id: string): El | null => {
  const node = document.getElementById(id);
  return node ? asEl(node) : null;
};

/** A mount point the shell guarantees (ui/router.py renders every id). Missing one is a
 *  programming error, not a runtime condition, so fail loudly rather than render half an app. */
const mustEl = (id: string): El => {
  const el = $(id);
  if (!el) throw new Error(`app: missing mount #${id}`);
  return el;
};

/** Real `document.createElement` yields an HTMLElement; narrow it into the structural
 *  `El` world once, here, exactly as domtypes.asEl documents. */
const newEl = (tag: string): El => asEl(document.createElement(tag));

// Focus a whole day window on ONE shared timescale — the board ribbons AND the
// panel Gantt both draw through it, so a click at T lands on the same x in both.
const TIMESCALE = makeTimescale(BOARD_DAY0, BOARD_DAY1, BOARD_PLOT);

async function main() {
  const root = document.documentElement;

  // --- initial FilterState: absolute today (UTC), first place preset, Day mode ---
  const today = isoDate(new Date());
  // The URL projection context: the receiver's today + the age vocabulary. `place` is
  // deliberately NEVER encoded (a client-side choice), so it lives only in the seed.
  const urlCtx = { today, ageTokens: AGE_TOKENS };
  const makeSeed = () =>
    createFilterState({
      mode: "day",
      date: today,
      place: { ...PLACE_PRESETS[0] },
    });

  // Hydrate: the URL patch wins OVER the default seed, so a shared link restores the
  // exact pool + filters + view. A URL `pool=` beats the nearest-plannable auto-select
  // (the Pool-entry seed only fills `selectedPool` when null — see buildToolbar). The
  // pool label is `null` here; hydratePoolPicker backfills it from /pools.
  let filter = merge(makeSeed(), fromSearch(location.search, urlCtx));

  // Backfill a URL-restored pool's display name from the classified /pools list (matched
  // by id). An unknown/old slug has no match → drop to null: graceful fallback to the
  // auto-select / plain view, never a crash. A no-op unless a pool id is set without a name.
  function backfillPoolName(f: FilterState): FilterState {
    if (!f.selectedPool || !f.selectedPool.id || f.selectedPool.name) return f;
    const match = poolOptions.find((o) => o.value === f.selectedPool?.id);
    return merge(f, {
      selectedPool: match ? { id: match.value, name: match.label } : null,
    });
  }

  // syncUrl(next) — mirror the current filter into the address bar (the URL is a pure
  // PROJECTION of `filter`, never a second source of truth). pushState when the VIEW or
  // POOL changed vs the current URL (so Back steps between pools/views); replaceState for
  // plain filter toggles (no history spam). Guard: if the computed search already equals
  // location.search, do nothing — a no-op that also breaks any popstate feedback loop.
  function syncUrl(next: FilterState) {
    const search = toSearch(next as unknown as UrlFilterState, urlCtx);
    if (search === location.search) return;
    const prev = fromSearch(location.search, urlCtx);
    const structural = isStructuralUrlChange(prev, next);
    const url = `${location.pathname}${search}`;
    if (structural) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
  }

  // --- header ---
  const header = createIdentityHeader(mustEl("app-header"), {
    props: { dateLabel: formatLabel(today), theme: "auto" },
    root,
    onThemeChange: (t: string) => applyTheme(root, t),
  });

  // --- insight + legend ---
  const insight = createInsightBar(mustEl("app-insight"), {});
  createBoardLegend($("app-legend"));

  // --- board + panel hosts (rebuilt per render) ---
  const boardHost = mustEl("app-board");
  const panelHost = mustEl("app-panel");
  let board: ReturnType<typeof createBoard> | null = null;
  let cursorLines: El[] = [];
  let poolOptions: PoolOption[] = []; // classified pool-picker options (nearest plannable first)
  let defaultPool: PoolOption | null = null; // the nearest plannable pool
  const poolIdByName = new Map<string, string>(); // facility name → pool_id
  const poolUrlByName = new Map<string, string>(); // facility name → official-page URL

  // The persisted shared cursor (minutes-of-day) + the pool it belongs to. It survives
  // re-renders so a mode-only switch (Day↔Pool on the SAME pool) KEEPS the cursor for
  // continuity; changing the pool (a new combobox pick or a Day row click on a different
  // pool) RESETS it to that pool's best-public (plan item 8).
  let cursorMin: number | null = null;
  let cursorPoolId: string | null = null;

  function headerLabel() {
    if (filter.mode === "pool") {
      const [monIso] = weekDates(filter.date || today);
      return `Week of ${formatLabel(monIso)}`;
    }
    return formatLabel(filter.date || today);
  }

  // Overlay ONE shared cursor line on the board's single scroll track (positioned at
  // TIMESCALE.X(min)); it spans every row and moves in lock-step with the panel.
  function seedCursors() {
    cursorLines = [];
    for (const track of boardHost.querySelectorAll?.(".board__track") ?? []) {
      track.style.position = "relative";
      const line = newEl("div");
      line.className = "gantt__cursor";
      line.style.left = "0px";
      track.appendChild(line);
      cursorLines.push(line);
    }
  }
  function moveCursors(min: number) {
    for (const line of cursorLines) line.style.left = `${TIMESCALE.X(min)}px`;
  }

  let panel: ReturnType<typeof createDetailPanel> | null = null;
  // The panel-rail helper shown until a pool is opened — never a blank rail (plan FIX 4).
  function renderPanelHelper() {
    panelHost.textContent = "";
    panel = null;
    const msg = newEl("p");
    msg.className = "app__panelempty";
    msg.textContent = "Click any pool to see its hours, price and lane plan.";
    panelHost.appendChild(msg);
  }

  // The DetailPanel ALWAYS opens (plan FIX 3): a plannable pool resolves to its OWN
  // basin's lane plan (board readout == panel headline); a pool with hours but no lane
  // split degrades to 'lanes-unknown'; a closed / uncurated pool opens in that state.
  function openPanel(
    detail: FacilityDetail | null,
    opts: DetailPanelOpts = {},
  ) {
    panelHost.textContent = "";
    panel = createDetailPanel(panelHost, {
      detail: detail || {},
      basin: opts.basin || null,
      timescale: TIMESCALE,
      filter,
      cursorMin: opts.cursorMin != null ? opts.cursorMin : null,
      distanceKm: opts.distanceKm != null ? opts.distanceKm : null,
      basinName: opts.basinName ?? undefined,
      state: opts.state ?? undefined,
      reason: opts.reason ?? null,
      accessTypes: opts.accessTypes || [],
      officialUrl: opts.officialUrl || null,
      // The single Day→Pool continuity affordance: open Pool view on the SAME pool.
      // `selectedPool` is left untouched (it is already the clicked pool), so the week
      // renders for it — plannable or honestly closed/uncurated (plan item 3).
      onOpenWeek: () => {
        filter = merge(filter, { mode: "pool" });
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

  function setCursor(min: number) {
    moveCursors(min);
    if (panel) panel.setCursor(min);
  }
  function minFromEvent(canvas: El, ev: MouseEvent): number {
    const rect = (canvas as unknown as HTMLElement).getBoundingClientRect();
    const x = Math.max(0, Math.min(TIMESCALE.PLOT, ev.clientX - rect.left));
    return TIMESCALE.inverse(x);
  }

  // Open the DetailPanel for ANY board row (plan FIX 2 + FIX 3). A row WITH options
  // resolves to the SAME basin's /pools/{id} lane plan (or degrades to lanes-unknown
  // when no split is published); a closed / uncurated row opens in its own state,
  // fetching the facility facts by name→id so the panel still carries facts + prov.
  async function onRowClick(
    rowIndex: number,
    min: number | null,
    opts: { fromUser?: boolean } = {},
  ) {
    // A real user click mirrors the chosen pool into the URL (so it's shareable/linkable);
    // the load-time auto-open passes { fromUser: false } so a bare default link stays bare.
    const fromUser = opts.fromUser !== false;
    if (!board) return;
    const row = board.rows[rowIndex];
    if (!row) return;
    if (row.options.length > 0) {
      const opt = row.options[0];
      // Persist the selection into the SHARED filter BEFORE opening the panel, so it
      // survives re-renders and carries into Pool view (plan item 2).
      const poolId = String(opt.facility_id);
      filter = merge(filter, { selectedPool: { id: poolId, name: row.label } });
      // Cursor: an explicit canvas click (min != null) places the cursor; otherwise a
      // pool change resets to best-public (cursorMin=null → the panel picks it) while a
      // same-pool open keeps the persisted cursor for continuity (plan item 8).
      let openAt: number | null = min;
      if (min == null) openAt = cursorPoolId === poolId ? cursorMin : null;
      cursorPoolId = poolId;
      const detail = await fetchPoolDetail(poolId, filter.date || today);
      const lanePanels = (detail?.lane_panels as LanePanel[]) ?? [];
      const lp = panelForBasin(
        lanePanels,
        opt.basin ? String(opt.basin) : null,
      );
      const basin = lp ? basinFromPanel(lp) : null;
      const accessTypes = [
        ...new Set(row.options.map((o) => String(o.access))),
      ];
      openPanel(detail, {
        basin,
        cursorMin: openAt,
        distanceKm: opt.distance_km ?? null,
        basinName: opt.basin ? String(opt.basin) : null,
        accessTypes,
        officialUrl: poolUrlByName.get(row.label) || null,
      });
      if (fromUser) syncUrl(filter); // clicked pool → shareable URL (pool change → pushState)
      return;
    }
    // Closed / uncurated row: no option to fetch by, so resolve the facility by name.
    // The selection still persists (an unplannable pool is a legitimate choice — it
    // opens an honest closed/uncurated week in Pool view; plan items 2 + 5).
    const id = poolIdByName.get(row.label);
    filter = merge(filter, {
      selectedPool: { id: id ?? null, name: row.label },
    });
    cursorPoolId = id ?? null;
    cursorMin = null;
    const closed = row.statuses.find((s) => s.status === "closed");
    const state = closed ? "closed" : "uncurated";
    const st =
      closed ||
      row.statuses.find((s) => s.status === "uncurated") ||
      row.statuses[0];
    const detail = id ? await fetchPoolDetail(id, filter.date || today) : null;
    openPanel(detail, {
      state,
      reason: st ? st.detail : null,
      basinName: null,
      officialUrl: poolUrlByName.get(row.label) || null,
    });
    if (fromUser) syncUrl(filter); // clicked a closed/uncurated pool → still a shareable selection
  }

  function wireBoardCursor() {
    seedCursors();
    const canvases = [
      ...(boardHost.querySelectorAll?.(".board__canvas") ?? []),
    ];
    canvases.forEach((canvas, i) => {
      canvas.style.cursor = "crosshair";
      canvas.addEventListener("mousemove", (ev) =>
        setCursor(minFromEvent(canvas, ev as unknown as MouseEvent)),
      );
      canvas.addEventListener(
        "click",
        (ev) =>
          void onRowClick(i, minFromEvent(canvas, ev as unknown as MouseEvent)),
      );
    });
    // EVERY row label opens the panel too (plan FIX 2) — Day mode included. A label
    // click opens on the row's best cursor (min=null → the panel picks best_public).
    const labels = [
      ...(boardHost.querySelectorAll?.(".board__labelsbody .board__rowlabel") ??
        []),
    ];
    labels.forEach((label, i) => {
      label.addEventListener("click", () => void onRowClick(i, null));
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
      const sel = board.rows.findIndex(
        (r) => r.label === filter.selectedPool?.name,
      );
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
    boardHost.textContent = "";
    let data;
    let answerForEmpty; // the /swim answer the no-pools empty state is judged against
    if (filter.mode === "pool") {
      const week = await fetchWeek(filter, filter.date || today);
      const focused = focusWeekOnPool(
        week,
        filter.selectedPool?.name ?? week.facility,
      );
      data = { week: applyLapWeek(focused, filter.lapOnly) };
      answerForEmpty = {
        options: data.week.days.flatMap((d) => d.answer.options),
        statuses: data.week.days.flatMap((d) => d.answer.statuses),
      };
    } else {
      const day = applyLap(
        await fetchDay(filter, filter.date || today),
        filter.lapOnly,
      );
      data = { day };
      answerForEmpty = day;
    }
    board = createBoard(boardHost, {
      data,
      filter,
      timescale: TIMESCALE,
      today,
    });
    insight.update(data, filter);
    wireBoardCursor();
    // A SINGLE board-level empty state, shown ONLY when the answer has neither options
    // nor statuses (plan FIX 1). Closed/uncurated pools read on their own rows above —
    // there is no duplicate below-board section anymore.
    if (emptyState(answerForEmpty)) {
      const emptyHost = newEl("div");
      emptyHost.className = "app__boardempty";
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
    const toolbarHost = mustEl("app-toolbar");
    toolbarHost.textContent = "";
    createFilterToolbar(toolbarHost, {
      props: {
        filter,
        places: PLACE_PRESETS,
        pools: poolOptions,
        dateBounds: {
          today,
          min: today,
          max: isoDate(addDays(new Date(), 60)),
        },
      },
      onChange: (next) => {
        // Entering Pool mode with NO pool selected yet → seed the nearest plannable pool
        // so the combobox + board open on a real, named pool (plan item 5). A non-null
        // selectedPool is NEVER overridden — an already-chosen (even unplannable) pool is
        // kept and its week renders honestly.
        if (next.mode === "pool" && !next.selectedPool && defaultPool) {
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
  window.addEventListener("popstate", async () => {
    filter = backfillPoolName(
      merge(makeSeed(), fromSearch(location.search, urlCtx)),
    );
    buildToolbar();
    await render();
  });

  // --- helpers scoped to main ---
  function addDays(date: string | Date, days: number): Date {
    const d = new Date(date);
    d.setDate(d.getDate() + days);
    return d;
  }
  async function hydratePoolPicker() {
    try {
      const [poolsRes, dayAnswer] = await Promise.all([
        fetch("/pools"),
        fetchDay(filter, filter.date || today),
      ]);
      if (!poolsRes.ok) return;
      const body = (await poolsRes.json()) as { pools?: PoolMeta[] };
      const poolsMeta = body.pools ?? [];
      // name → id, so a closed / uncurated board row (which carries only a facility
      // NAME, no option) can still resolve its /pools/{id} facts for the panel.
      poolIdByName.clear();
      poolUrlByName.clear();
      for (const p of poolsMeta) {
        poolIdByName.set(p.name, p.pool_id);
        // PoolOut.url is the catalog official page, non-null on all 57 pools — the
        // ONLY official-page source that also reaches uncurated pools (their
        // /pools/{id} detail 404s), so it is threaded into the panel frontend-side.
        if (p.url) poolUrlByName.set(p.name, String(p.url));
      }
      poolOptions = classifyPools(poolsMeta, dayAnswer);
      // A URL-restored pool arrives as { id, name:null } — resolve its display name now
      // (or drop an unknown/old slug to null; the pool_alias crosswalk resolves renames
      // server-side, so a live slug still matches here).
      filter = backfillPoolName(filter);
      const nearestPlannable = poolOptions.find((p) => p.state === "plannable");
      if (nearestPlannable) {
        // The nearest plannable pool — the default seeded into `selectedPool` when the
        // user first enters Pool mode without a choice (see buildToolbar onChange). We do
        // NOT pre-write it here: Day mode's first paint auto-opens (and thus selects) the
        // nearest pool on its own, and a non-null selectedPool must never be overridden.
        defaultPool = nearestPlannable;
      }
      buildToolbar();
    } catch {
      /* the pool picker is a nicety for Pool mode; Day mode works without it */
    }
  }
}

main();
