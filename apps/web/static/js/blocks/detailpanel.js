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
import { eligForAccess, dayEligibility } from '../eligibility.js';
import { publicAt, peakPublic, hhmmToMin, minToHhmm } from './cursor.js';
import { createGantt } from './gantt.js';

// The public open/close span of a basin's day: earliest public start → latest
// public end across all lanes, in minutes-of-day. null when nothing is ever public.
function publicSpan(basin) {
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
function accessTypes(basin) {
  const set = new Set();
  for (const strip of basin.strips) {
    for (const seg of strip.segments) set.add(seg.access);
  }
  return [...set];
}

// Pick the physical-facts basin (length / lanes / temp) from a `/pools/{id}` detail
// when there is NO lane plan to derive it from: match the clicked option's basin name,
// else the first basin. null when the facility publishes no basins at all.
function pickBasinOut(detail, name) {
  const basins = (detail && detail.basins) || [];
  if (basins.length === 0) return null;
  if (name != null) {
    const match = basins.find((b) => b.name === name);
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

function factRow(doc, label, valueNode) {
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

function tempText(basinOut) {
  if (!basinOut) return { text: 'Not listed', note: 'Water temperature not published' };
  if (basinOut.measured_temp_c != null) {
    return { text: `${basinOut.measured_temp_c} °C`, note: 'measured' };
  }
  if (basinOut.nominal_temp_c != null) {
    return { text: `${basinOut.nominal_temp_c} °C`, note: 'nominal (design)' };
  }
  return { text: 'Not listed', note: 'Water temperature not published' };
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
 * @param {function} [opts.onOpenWeek] when set, renders a "See this pool's week →"
 *   button in the header that invokes it (Day → Pool continuity for the selected pool).
 * @returns {{el, headlineAt, setCursor, gantt, cursorMin}}
 */
export function createDetailPanel(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const detail = opts.detail || {};
  const basin = opts.basin || null;
  const filter = opts.filter || { gender: '', age: null };
  const ts = opts.timescale;

  // The panel ALWAYS renders facts (plan FIX 3). The lane part degrades honestly:
  //   'lanes'         → a real per-basin lane plan (headline + Gantt).
  //   'lanes-unknown' → curated hours, no per-lane split published.
  //   'closed'        → shut for a stated reason.
  //   'uncurated'     → location only, no timetable yet.
  const panelState = opts.state || (basin ? 'lanes' : 'lanes-unknown');
  const basinOut = basin
    ? (detail.basins || []).find((b) => b.basin_id === basin.id) || null
    : pickBasinOut(detail, opts.basinName);
  const reason = opts.reason || null;

  let cursorMin = null;
  if (basin) {
    cursorMin =
      opts.cursorMin != null
        ? opts.cursorMin
        : basin.best_public
          ? hhmmToMin(basin.best_public.start)
          : null;
    if (cursorMin == null && ts) cursorMin = Math.round((ts.lo + ts.hi) / 2);
  }

  const subName = basin ? basin.name || '' : basinOut ? basinOut.name || '' : '';

  el.classList.add('detail');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', `${detail.facility_name || 'Pool'} — ${subName}`.trim());

  // --- header: facility + basin name, plus the "see this pool's week" affordance ---
  const head = doc.createElement('div');
  head.className = 'detail__head';
  const headText = doc.createElement('div');
  headText.className = 'detail__headtext';
  const title = doc.createElement('h3');
  title.className = 'detail__title';
  title.textContent = detail.facility_name || 'Pool';
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
  if (opts.onOpenWeek) {
    const weekBtn = doc.createElement('button');
    weekBtn.type = 'button';
    weekBtn.className = 'detail__weekbtn';
    weekBtn.textContent = "See this pool's week →";
    weekBtn.addEventListener('click', () => opts.onOpenWeek());
    head.appendChild(weekBtn);
  }
  el.appendChild(head);

  // --- headline: PUBLIC LANES AT CURSOR (not peak) + pips + peak note. ONLY for a
  // real lane plan — the other states have no per-lane number to show honestly. ---
  const peak = basin ? peakPublic(basin) : 0;
  let bignum = null;
  let bigunit = null;
  const pipEls = [];
  let headline = null;
  if (panelState === 'lanes') {
    headline = doc.createElement('div');
    headline.className = 'detail__headline';
    bignum = doc.createElement('span');
    bignum.className = 'detail__bignum tnum';
    bigunit = doc.createElement('span');
    bigunit.className = 'detail__bigunit';
    const pips = doc.createElement('span');
    pips.className = 'detail__pips';
    pips.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < basin.lane_count; i += 1) {
      const pip = doc.createElement('span');
      pip.className = 'detail__pip';
      pips.appendChild(pip);
      pipEls.push(pip);
    }
    const peaknote = doc.createElement('span');
    peaknote.className = 'detail__peaknote';
    peaknote.textContent = `peak ${peak} of ${basin.lane_count}`;
    headline.appendChild(bignum);
    headline.appendChild(bigunit);
    headline.appendChild(pips);
    headline.appendChild(peaknote);
    el.appendChild(headline);
  }

  // --- facts (all S1 primitives + honest text) ---
  const facts = doc.createElement('div');
  facts.className = 'detail__facts';

  // status → StatePill (the branch drives its state; plan FIX 3).
  const pillHost = doc.createElement('span');
  if (panelState === 'lanes') {
    const span = publicSpan(basin);
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
  const dist =
    opts.distanceKm != null ? `${Number(opts.distanceKm).toFixed(1)} km` : 'Not shown';
  facts.appendChild(factRow(doc, 'Distance', dist));

  // price ("Not listed" when null)
  const priceDisplay =
    detail.prices && detail.prices.entries && detail.prices.entries.length > 0
      ? detail.prices.entries[0].display
      : 'Not listed';
  facts.appendChild(factRow(doc, 'Price', priceDisplay));

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
  const freshness = detail.provenance && detail.provenance.valid_as_of
    ? `Checked ${detail.provenance.valid_as_of}`
    : 'Not dated';
  facts.appendChild(factRow(doc, 'Freshness', freshness));

  el.appendChild(facts);

  // --- provenance stamp ---
  const provHost = doc.createElement('div');
  provHost.className = 'detail__prov';
  const prov = detail.provenance || {};
  createProvenanceStamp(provHost, {
    props: { curated: !!prov.curated, source: prov.source, valid_as_of: prov.valid_as_of },
  });
  el.appendChild(provHost);

  // --- the LaneGantt, on the SHARED timescale — ONLY when there is a real lane plan.
  let gantt = null;
  if (ts && basin) {
    const ganttHost = doc.createElement('div');
    ganttHost.className = 'detail__gantt';
    el.appendChild(ganttHost);
    gantt = createGantt(ganttHost, { basin, timescale: ts, cursorMin });
  }

  // Honest degradation NOTE for a non-lanes panel (never the whole panel; plan FIX 3).
  if (panelState !== 'lanes') {
    const note = doc.createElement('div');
    note.className = `detail__note detail__note--${panelState}`;
    note.textContent =
      panelState === 'closed' && reason
        ? `Closed — ${reason}. ${NOTE_COPY.closed}`
        : NOTE_COPY[panelState] || '';
    el.appendChild(note);
  }

  // headlineAt(min) → { public, total } — the SAME publicAt the Gantt readout uses.
  const headlineAt = (min) =>
    basin ? publicAt(basin, min) : { public: 0, total: 0 };

  function paintHeadline() {
    if (panelState !== 'lanes') return; // no per-lane headline for the degraded states
    const { public: n, total: m } = headlineAt(cursorMin);
    bignum.textContent = String(n);
    bigunit.textContent = `of ${m} lanes public · ${minToHhmm(cursorMin)}`;
    pipEls.forEach((pip, i) => {
      pip.classList.toggle('is-on', i < n);
    });
    headline.setAttribute(
      'aria-label',
      `${n} of ${m} lanes public at ${minToHhmm(cursorMin)} (peak ${peak})`,
    );
  }
  paintHeadline();

  function setCursor(min) {
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
