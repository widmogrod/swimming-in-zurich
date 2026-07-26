// detailpanel.js — the DetailPanel / BottomSheet block (plan Part 3 §6).
//
// A facts block built PURELY from S1 primitives (StatePill, LengthLanesBadge,
// EligibilityBadge, ProvenanceStamp) plus one hand-laid headline, followed by the
// LaneGantt. The headline is the crown-jewel number: PUBLIC LANES AT THE CURSOR
// (not the day's peak — the real bug the prototype fixed). It is computed by the
// SAME `publicAt(basin, cursorMin)` the Gantt readout uses, so board readout ==
// panel headline by construction; the day's peak survives only as a small note.
//
// Layering: a BLOCK. It imports primitives + the shared `eligibility` rule + the
// shared `cursor` helpers + the LaneGantt block, lays out DOM, and adds NO colour
// (every hue is a token via a class in blocks.css → no raw hex here).

import { createStatePill } from '../components/statepill.js';
import { createLengthLanesBadge } from '../components/lengthlanesbadge.js';
import { createEligibilityBadge } from '../components/eligibilitybadge.js';
import { createProvenanceStamp } from '../components/provenancestamp.js';
import { createSourceStrip } from '../components/sourcestrip.js';
import { eligForAccess, dayEligibility } from '../eligibility.js';
import { formatCelsius, formatDate, formatKm } from '../datefmt.js';
import { asDoc, type Doc, type El } from '../domtypes.js';
import { type GanttTimescale } from './gantt.js';
import { locale } from '../i18n.js';
import {
  publicAt,
  peakPublic,
  hhmmToMin,
  minToHhmm,
  type Basin,
} from './cursor.js';
import { createGantt } from './gantt.js';

type Gantt = ReturnType<typeof createGantt>;


// ---- Local structural types (the urlstate.ts convention) ---------------------------

/** A basin's lane plan as the panel/Gantt consume it — the SAME shape cursor.js
 *  produces, re-exported so callers have one name for one type. */
export type BasinPlan = Basin;

/** A `/pools/{id}` BasinOut — the physical facts row. */
export interface BasinOut {
  name?: string;
  length_m?: number | null;
  lanes?: number | null;
  measured_temp_c?: number | null;
  nominal_temp_c?: number | null;
  [k: string]: unknown;
}

/** The facility-level Baditicker live water temperature block. */
export interface LiveWaterTemp {
  available?: boolean;
  reason?: string | null;
  celsius?: number | null;
  is_open?: boolean | null;
  age_min?: number | null;
  [k: string]: unknown;
}

/** A `/pools/{id}` FacilityDetailOut, read structurally. */
export interface FacilityDetail {
  facility_name?: string;
  basins?: BasinOut[];
  prices?: { entries?: { display?: string }[]; source_url?: string | null } | null;
  provenance?: {
    curated?: boolean;
    source?: string;
    valid_as_of?: string | null;
  } | null;
  live_water_temp?: LiveWaterTemp;
  [k: string]: unknown;
}

export interface PanelFilter {
  gender?: string;
  age?: number | null;
}

export interface DetailPanelOpts {
  officialUrl?: string | null;
  detail?: FacilityDetail;
  basin?: BasinPlan | null;
  filter?: PanelFilter;
  timescale?: unknown;
  state?: string;
  basinName?: string | null;
  reason?: string | null;
  cursorMin?: number | null;
  distanceKm?: number | null;
  accessTypes?: string[];
  onOpenWeek?: (() => void) | null;
  [k: string]: unknown;
}

// The public open/close span of a basin's day: earliest public start → latest
// public end across all lanes, in minutes-of-day. null when nothing is ever public.
function publicSpan(basin: BasinPlan): { lo: number; hi: number } | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const strip of basin.strips) {
    for (const seg of strip.segments) {
      if (seg.access !== 'PublicSwim') continue;
      lo = Math.min(lo, hhmmToMin(seg.start));
      hi = Math.max(hi, hhmmToMin(seg.end));
    }
  }
  return hi > lo ? { lo, hi } : null;
}

// Distinct access classes appearing in the basin's lane plan (drives eligibility).
function accessTypes(basin: BasinPlan): string[] {
  const set = new Set<string>();
  for (const strip of basin.strips) {
    for (const seg of strip.segments) set.add(seg.access);
  }
  return [...set];
}

// Pick the physical-facts basin (length / lanes / temp) from a `/pools/{id}` detail
// when there is NO lane plan to derive it from: match the clicked option's basin name,
// else the first basin. null when the facility publishes no basins at all.
function pickBasinOut(detail: FacilityDetail | null, name?: string | null): BasinOut | null {
  const basins: BasinOut[] = (detail && detail.basins) || [];
  if (basins.length === 0) return null;
  if (name != null) {
    const match = basins.find((b: BasinOut) => b.name === name);
    if (match) return match;
  }
  return basins[0];
}

// The honest degradation note for a non-lanes panel (plan FIX 3). It is a NOTE inside
// a fully-populated facts panel — never the whole panel.
const NOTE_COPY = {
  'lanes-unknown':
    'No published lane plan for this pool yet — the hours are curated, but the per-lane public/reserved split isn’t.',
  closed:
    'This pool is closed for a stated reason on this day — it is not merged with pools we simply lack data for.',
  uncurated:
    'We have this pool’s location but no session timetable yet. Unknown is not the same as closed — it may well be open.',
};

function factRow(doc: Doc, label: string, valueNode: El | string): El {
  const row = doc.createElement('div');
  row.className = 'detail__fact';
  const key = doc.createElement('span');
  key.className = 'detail__factlabel';
  key.textContent = label;
  row.appendChild(key);
  if (typeof valueNode === 'string') {
    const val = doc.createElement('span');
    val.className = 'detail__factval';
    val.textContent = valueNode;
    row.appendChild(val);
  } else {
    valueNode.classList.add('detail__factval');
    row.appendChild(valueNode);
  }
  return row;
}

function tempText(basinOut: BasinOut | null) {
  if (!basinOut) return { text: 'Not listed', note: 'Water temperature not published' };
  if (basinOut.measured_temp_c != null) {
    return { text: formatCelsius(basinOut.measured_temp_c, locale()), note: 'measured' };
  }
  if (basinOut.nominal_temp_c != null) {
    return { text: formatCelsius(basinOut.nominal_temp_c, locale()), note: 'nominal (design)' };
  }
  return { text: 'Not listed', note: 'Water temperature not published' };
}

// Human-readable "how long ago" from the API's whole-minute age. min → h → days, so a fresh
// reading reads "3 min ago" and a stale one "2 days ago" (the freshness the API already derived).
function humanizeAge(ageMin: number | null | undefined): string {
  if (ageMin == null) return '';
  if (ageMin < 60) return `${ageMin} min`;
  if (ageMin < 60 * 24) return `${Math.round(ageMin / 60)} h`;
  const days = Math.round(ageMin / (60 * 24));
  return `${days} ${days === 1 ? 'day' : 'days'}`;
}

// The facility-level LIVE water temperature (Baditicker `live_water_temp`), rendered HONESTLY —
// never a stale or invented number. Returns null when the detail carries no live block at all
// (older payloads / callers that don't thread it), so the row is simply omitted. Four states:
//   * a live reading with a temp   → "23 °C" + "· measured N min ago" (muted+stale when old).
//   * a live reading, empty cell   → "Not yet measured" (+ open/closed) — a live answer, not 0.
//   * unavailable (no key / error) → the reason, muted, and NEVER a number.
function liveTempText(lwt: LiveWaterTemp | null | undefined) {
  if (!lwt) return null;
  if (!lwt.available) {
    return { text: lwt.reason || 'Not available', note: '', muted: true, stale: false };
  }
  if (lwt.celsius == null) {
    const openNote = lwt.is_open === true ? 'open' : lwt.is_open === false ? 'closed' : '';
    return { text: 'Not yet measured', note: openNote, muted: true, stale: false };
  }
  const age = humanizeAge(lwt.age_min);
  return {
    text: `${lwt.celsius} °C`,
    note: age ? `measured ${age} ago` : 'measured',
    muted: !!lwt.is_stale,
    stale: !!lwt.is_stale,
  };
}

/**
 * createDetailPanel(el, opts) — mount the DetailPanel + LaneGantt into `el`.
 * @param {object} opts
 * @param {object} opts.detail a `/pools/{id}` response (facility_name, basins, prices, provenance).
 * @param {object} opts.basin canonical basin `{ id, lane_count, strips, best_public }`.
 * @param {object} opts.timescale the SHARED timescale (passed straight to the Gantt).
 * @param {object} [opts.filter] `{ gender, age }` for the eligibility badge.
 * @param {number} [opts.cursorMin] initial cursor minutes-of-day.
 * @param {number|null} [opts.distanceKm] distance from the `/swim` option (null → "not shown").
 * @param {string|null} [opts.officialUrl] the pool's official-page URL (listing `PoolOut.url`),
 *   threaded by app.js; drives the SourceStrip's Official-page chip in every state.
 * @param {function} [opts.onOpenWeek] when set, renders a "See this pool's week →"
 *   button in the header that invokes it (Day → Pool continuity for the selected pool).
 * @returns {{el, headlineAt, setCursor, gantt, cursorMin}}
 */

/**
 * The panel header: facility + basin name, and the Day→Pool "see this pool's week"
 * affordance. Split out of createDetailPanel so that function stays a readable assembly
 * of sections rather than one very long builder (it was the CRAP gate's worst offender).
 */
function buildHeader(
  doc: Doc,
  detail: FacilityDetail,
  subName: string,
  panelState: string,
  reason: string | null,
  onOpenWeek: (() => void) | null,
): El {
  // --- header: facility + basin name, plus the "see this pool's week" affordance ---
  const head = doc.createElement('div');
  head.className = 'detail__head';
  const headText = doc.createElement('div');
  headText.className = 'detail__headtext';
  const title = doc.createElement('h3');
  title.className = 'detail__title';
  title.textContent = detail.facility_name ?? 'Pool';
  const sub = doc.createElement('div');
  sub.className = 'detail__sub';
  sub.textContent = subName;
  headText.appendChild(title);
  headText.appendChild(sub);
  head.appendChild(headText);
  // "See this pool's week →" — the single affordance that carries the SELECTED pool
  // from Day view into Pool view. Present for EVERY selected pool (plannable AND
  // unplannable: an unplannable pool opens an honest, closed/uncurated week — the
  // button is never disabled). Token-styled, keyboard-accessible.
  if (onOpenWeek) {
    const weekBtn = doc.createElement('button');
    weekBtn.type = 'button';
    weekBtn.className = 'detail__weekbtn';
    weekBtn.textContent = "See this pool's week →";
    weekBtn.addEventListener('click', () => onOpenWeek());
    head.appendChild(weekBtn);
  }
  return head;
}


/**
 * The facts block: status pill, basin badge, distance, price, water temperature, live
 * temperature, eligibility, busyness and freshness.
 *
 * Extracted from createDetailPanel because it carried most of that function's branching
 * (every row degrades honestly on its own, so each is a conditional). Keeping it inline
 * made createDetailPanel the CRAP gate's worst offender at CC=69 — a score no amount of
 * test coverage could bring under the threshold, since the complexity term dominates.
 */
function buildFacts(
  doc: Doc,
  detail: FacilityDetail,
  basin: BasinPlan | null,
  basinOut: BasinOut | null,
  panelState: string,
  reason: string | null,
  filter: PanelFilter,
  opts: DetailPanelOpts,
): El {
  const facts = doc.createElement('div');
  facts.className = 'detail__facts';

  // status → StatePill (the branch drives its state; plan FIX 3).
  const pillHost = doc.createElement('span');
  if (panelState === 'lanes') {
    const span = basin ? publicSpan(basin) : null;
    if (span) {
      createStatePill(pillHost, {
        props: { state: 'open', label: `Open · ${minToHhmm(span.lo)}–${minToHhmm(span.hi)}` },
      });
    } else {
      createStatePill(pillHost, { props: { state: 'unknown', label: 'No public lanes today' } });
    }
  } else if (panelState === 'lanes-unknown') {
    createStatePill(pillHost, {
      props: { state: 'open', label: 'Open · lane split not published' },
    });
  } else if (panelState === 'closed') {
    createStatePill(pillHost, {
      props: { state: 'closed', label: reason ? `Closed · ${reason}` : 'Closed' },
    });
  } else {
    createStatePill(pillHost, {
      props: { state: 'unknown', label: 'Hours not listed — may well be open' },
    });
  }
  facts.appendChild(factRow(doc, 'Today', pillHost));

  // length · lanes → LengthLanesBadge
  const lenHost = doc.createElement('span');
  createLengthLanesBadge(lenHost, {
    props: { length_m: basinOut ? basinOut.length_m : null, lanes: basinOut ? basinOut.lanes : null },
  });
  facts.appendChild(factRow(doc, 'Basin', lenHost));

  // distance
  // formatKm, not `.toFixed(1) + ' km'`: de/fr/it/pl use a comma decimal separator, and
  // CLDR supplies the unit form (so there is no plural entry in the catalog to get wrong).
  const dist =
    opts.distanceKm != null ? formatKm(Number(opts.distanceKm), locale()) : 'Not shown';
  facts.appendChild(factRow(doc, 'Distance', dist));

  // price ("Not listed" when null)
  const priceDisplay =
    detail.prices && detail.prices.entries && detail.prices.entries.length > 0
      ? detail.prices.entries[0].display
      : 'Not listed';
  facts.appendChild(factRow(doc, 'Price', priceDisplay ?? 'Not listed'));

  // water temp (nominal / measured + honesty note)
  const t = tempText(basinOut);
  const tempVal = doc.createElement('span');
  tempVal.className = 'detail__factval';
  const tempMain = doc.createElement('span');
  tempMain.textContent = t.text;
  const tempNote = doc.createElement('span');
  tempNote.className = 'detail__factnote';
  tempNote.textContent = ` ${t.note}`;
  tempVal.appendChild(tempMain);
  tempVal.appendChild(tempNote);
  facts.appendChild(factRow(doc, 'Water', tempVal));

  // live water temp (facility-level Baditicker) — additive + labelled, distinct from the
  // per-basin design/measured "Water" row above; honest empty / unavailable / stale states.
  const live = liveTempText(detail.live_water_temp);
  if (live) {
    const liveVal = doc.createElement('span');
    liveVal.className = 'detail__live';
    if (live.muted) liveVal.classList.add('detail__live--muted');
    if (live.stale) liveVal.classList.add('detail__live--stale');
    const liveMain = doc.createElement('span');
    liveMain.textContent = live.text;
    liveVal.appendChild(liveMain);
    if (live.note) {
      const liveNote = doc.createElement('span');
      liveNote.className = 'detail__factnote';
      liveNote.textContent = ` · ${live.note}`;
      liveVal.appendChild(liveNote);
    }
    facts.appendChild(factRow(doc, 'Live water', liveVal));
  }

  // eligibility (shared eligibility.js) — from the lane plan's access types, or the
  // clicked row's access types when there is no lane plan; unknown when we have neither
  // (a closed / uncurated pool has no sessions to judge → '?', never a bogus '✕').
  const at = basin ? accessTypes(basin) : opts.accessTypes || [];
  const eligState = at.length
    ? dayEligibility(at.map((a) => eligForAccess(a, filter.gender, filter.age)))
    : 'chk';
  const eligHost = doc.createElement('span');
  createEligibilityBadge(eligHost, { props: { state: eligState } });
  facts.appendChild(factRow(doc, 'Eligibility', eligHost));

  // busyness — future, never faked
  facts.appendChild(factRow(doc, 'Busyness', 'Not available yet'));

  // freshness
  // A raw ISO date was shown to the user here; render it in the viewer's locale.
  const freshness = detail.provenance && detail.provenance.valid_as_of
    ? `Checked ${formatDate(detail.provenance.valid_as_of, locale())}`
    : 'Not dated';
  facts.appendChild(factRow(doc, 'Freshness', freshness));

  return facts;
}


/**
 * The provenance stamp + the "verify at the source" strip, shown in EVERY panel state
 * (an uncurated pool still gets its official-page link). Extracted alongside buildFacts
 * to keep createDetailPanel an assembly of named sections.
 */
function buildProvenance(
  doc: Doc,
  detail: FacilityDetail,
  basin: BasinPlan | null,
  basinOut: BasinOut | null,
  opts: DetailPanelOpts,
): El[] {
  // --- provenance stamp ---
  const provHost = doc.createElement('div');
  provHost.className = 'detail__prov';
  const prov = detail.provenance || {};
  createProvenanceStamp(provHost, {
    props: {
      curated: !!prov.curated,
      source: prov.source,
      valid_as_of: prov.valid_as_of ?? undefined,
    },
  });


  // --- Sources strip ("verify at the source"), in EVERY panel state ---
  // Official page comes from the listing URL threaded by app.js (reaches uncurated
  // pools whose /pools/{id} 404s). Lane-plan URLs are the SELECTED basin's PDF when a
  // basin is opened, else EVERY basin's PDF (a basin-less mount shows them all). Prices
  // is the price table's source URL. The strip itself dedups + omits missing sources.
  const lanePlanUrls: (string | null | undefined)[] = basin
    ? basinOut?.lane_plan_url
      ? [String(basinOut.lane_plan_url)]
      : []
    : (detail.basins || [])
        .map((b) => b.lane_plan_url as string | null | undefined)
        .filter((u) => u);
  const sourcesHost = doc.createElement('div');
  sourcesHost.className = 'detail__sources';
  createSourceStrip(sourcesHost, {
    props: {
      officialUrl: opts.officialUrl || null,
      lanePlanUrls,
      pricesUrl: (detail.prices && detail.prices.source_url) || null,
    },
  });

  return [provHost, sourcesHost];
}


/** The headline nodes for a real lane plan: the big number, its unit, one pip per lane
 *  and the peak note. `null` for every degraded state — those have no per-lane number to
 *  show honestly, so the panel simply omits the headline rather than inventing one. */
interface Headline {
  el: El;
  bignum: El;
  bigunit: El;
  pips: El[];
}

function buildHeadline(
  doc: Doc,
  basin: BasinPlan | null,
  peak: number,
): Headline | null {
  if (!basin) return null;
  const el = doc.createElement('div');
  el.className = 'detail__headline';
  const bignum = doc.createElement('span');
  bignum.className = 'detail__bignum tnum';
  const bigunit = doc.createElement('span');
  bigunit.className = 'detail__bigunit';
  const pipHost = doc.createElement('span');
  pipHost.className = 'detail__pips';
  pipHost.setAttribute('aria-hidden', 'true');
  const pips: El[] = [];
  for (let i = 0; i < Number(basin.lane_count ?? 0); i += 1) {
    const pip = doc.createElement('span');
    pip.className = 'detail__pip';
    pipHost.appendChild(pip);
    pips.push(pip);
  }
  const peaknote = doc.createElement('span');
  peaknote.className = 'detail__peaknote';
  peaknote.textContent = `peak ${peak} of ${basin.lane_count ?? 0}`;
  el.appendChild(bignum);
  el.appendChild(bigunit);
  el.appendChild(pipHost);
  el.appendChild(peaknote);
  return { el, bignum, bigunit, pips };
}

/** The honest "why is this panel thin" note for a non-lanes state. `null` for a real
 *  lane plan, which needs no explanation. Never replaces the panel — it sits inside a
 *  fully-populated one (plan FIX 3). */
function buildDegradationNote(
  doc: Doc,
  panelState: string,
  reason: string | null,
): El | null {
  if (panelState === 'lanes') return null;
  const note = doc.createElement('div');
  note.className = `detail__note detail__note--${panelState}`;
  note.textContent =
    panelState === 'closed' && reason
      ? `Closed — ${reason}. ${NOTE_COPY.closed}`
      : (NOTE_COPY as Record<string, string>)[panelState] || '';
  return note;
}

/** The physical-facts basin: the one matching the opened lane plan, else the one named
 *  by the clicked option, else the facility's first. */
function resolveBasinOut(
  detail: FacilityDetail,
  basin: BasinPlan | null,
  basinName: string | null | undefined,
): BasinOut | null {
  if (!basin) return pickBasinOut(detail, basinName);
  return (detail.basins || []).find((b) => b.basin_id === basin.id) || null;
}

/** Where the shared cursor starts: an explicit position, else the basin's best-public
 *  window, else the middle of the visible day. `null` when there is no lane plan to
 *  put a cursor on at all. */
function resolveCursorMin(
  basin: BasinPlan | null,
  explicit: number | null | undefined,
  ts: GanttTimescale | undefined,
): number | null {
  if (!basin) return null;
  if (explicit != null) return explicit;
  if (basin.best_public) return hhmmToMin(basin.best_public.start);
  return ts ? Math.round((ts.lo + ts.hi) / 2) : null;
}

export function createDetailPanel<T extends El>(el: T, opts: DetailPanelOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const detail = opts.detail || {};
  const basin = opts.basin || null;
  const filter = opts.filter || { gender: '', age: null };
  const ts = opts.timescale as GanttTimescale | undefined;

  // The panel ALWAYS renders facts (plan FIX 3). The lane part degrades honestly:
  //   'lanes'         → a real per-basin lane plan (headline + Gantt).
  //   'lanes-unknown' → curated hours, no per-lane split published.
  //   'closed'        → shut for a stated reason.
  //   'uncurated'     → location only, no timetable yet.
  const panelState = opts.state || (basin ? 'lanes' : 'lanes-unknown');
  const basinOut = resolveBasinOut(detail, basin, opts.basinName);
  const reason = opts.reason || null;
  let cursorMin: number | null = resolveCursorMin(basin, opts.cursorMin, ts);
  const subName = (basin ? basin.name : basinOut?.name) || '';

  el.classList.add('detail');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', `${detail.facility_name || 'Pool'} — ${subName}`.trim());

  el.appendChild(
    buildHeader(doc, detail, subName, panelState, reason, opts.onOpenWeek ?? null),
  );

  // --- headline: PUBLIC LANES AT CURSOR (not peak) + pips + peak note. ONLY for a
  // real lane plan — the other states have no per-lane number to show honestly. ---
  const peak = basin ? peakPublic(basin) : 0;
  const headline = panelState === 'lanes' ? buildHeadline(doc, basin, peak) : null;
  if (headline) el.appendChild(headline.el);

  el.appendChild(
    buildFacts(doc, detail, basin, basinOut, panelState, reason, filter, opts),
  );

  for (const node of buildProvenance(doc, detail, basin, basinOut, opts)) {
    el.appendChild(node);
  }

  // --- the LaneGantt, on the SHARED timescale — ONLY when there is a real lane plan.
  let gantt: Gantt | null = null;
  if (ts && basin) {
    const ganttHost = doc.createElement('div');
    ganttHost.className = 'detail__gantt';
    el.appendChild(ganttHost);
    gantt = createGantt(ganttHost, {
      basin,
      timescale: ts,
      cursorMin: cursorMin ?? undefined,
    });
  }

  // Honest degradation NOTE for a non-lanes panel (never the whole panel; plan FIX 3).
  const note = buildDegradationNote(doc, panelState, reason);
  if (note) el.appendChild(note);

  // headlineAt(min) → { public, total } — the SAME publicAt the Gantt readout uses.
  const headlineAt = (min: number) =>
    basin
      ? publicAt(basin, min)
      : { public: 0, total: 0 };

  function paintHeadline() {
    // No per-lane headline for the degraded states — and in 'lanes' the headline nodes
    // and cursor were all created above, so they are non-null here.
    if (!headline) return;
    const at = cursorMin ?? 0;
    const { public: n, total: m } = headlineAt(at);
    headline.bignum.textContent = String(n);
    headline.bigunit.textContent = `of ${m} lanes public · ${minToHhmm(at)}`;
    headline.pips.forEach((pip, i) => {
      pip.classList.toggle('is-on', i < n);
    });
    headline.el.setAttribute(
      'aria-label',
      `${n} of ${m} lanes public at ${minToHhmm(at)} (peak ${peak})`,
    );
  }
  paintHeadline();

  function setCursor(min: number) {
    cursorMin = min;
    paintHeadline();
    if (gantt) gantt.setCursor(min);
  }

  return {
    el,
    gantt,
    headlineAt,
    setCursor,
    get cursorMin() {
      return cursorMin;
    },
  };
}
