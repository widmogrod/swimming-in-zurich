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
 * @returns {{el, headlineAt, setCursor, gantt, cursorMin}}
 */
export function createDetailPanel(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const detail = opts.detail || {};
  const basin = opts.basin || { id: '', lane_count: 0, strips: [], best_public: null };
  const filter = opts.filter || { gender: '', age: null };
  const basinOut = (detail.basins || []).find((b) => b.basin_id === basin.id) || null;
  const ts = opts.timescale;

  let cursorMin =
    opts.cursorMin != null
      ? opts.cursorMin
      : basin.best_public
        ? hhmmToMin(basin.best_public.start)
        : null;
  if (cursorMin == null && ts) cursorMin = Math.round((ts.lo + ts.hi) / 2);

  el.classList.add('detail');
  el.setAttribute('role', 'region');
  el.setAttribute('aria-label', `${detail.facility_name || 'Pool'} — ${basin.name || ''}`.trim());

  // --- header: facility + basin name ---
  const head = doc.createElement('div');
  head.className = 'detail__head';
  const title = doc.createElement('h3');
  title.className = 'detail__title';
  title.textContent = detail.facility_name || 'Pool';
  const sub = doc.createElement('div');
  sub.className = 'detail__sub';
  sub.textContent = basin.name || '';
  head.appendChild(title);
  head.appendChild(sub);
  el.appendChild(head);

  // --- headline: PUBLIC LANES AT CURSOR (not peak) + pips + secondary peak note ---
  const peak = peakPublic(basin);
  const headline = doc.createElement('div');
  headline.className = 'detail__headline';
  const bignum = doc.createElement('span');
  bignum.className = 'detail__bignum tnum';
  const bigunit = doc.createElement('span');
  bigunit.className = 'detail__bigunit';
  const pips = doc.createElement('span');
  pips.className = 'detail__pips';
  pips.setAttribute('aria-hidden', 'true');
  const pipEls = [];
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

  // --- facts (all S1 primitives + honest text) ---
  const facts = doc.createElement('div');
  facts.className = 'detail__facts';

  // open / closes → StatePill
  const span = publicSpan(basin);
  const pillHost = doc.createElement('span');
  if (span) {
    createStatePill(pillHost, {
      props: { state: 'open', label: `Open · ${minToHhmm(span.lo)}–${minToHhmm(span.hi)}` },
    });
  } else {
    createStatePill(pillHost, { props: { state: 'unknown', label: 'No public lanes today' } });
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

  // eligibility (shared eligibility.js)
  const eligState = dayEligibility(
    accessTypes(basin).map((a) => eligForAccess(a, filter.gender, filter.age)),
  );
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

  // --- the LaneGantt, on the SHARED timescale ---
  const ganttHost = doc.createElement('div');
  ganttHost.className = 'detail__gantt';
  el.appendChild(ganttHost);
  const gantt = ts
    ? createGantt(ganttHost, { basin, timescale: ts, cursorMin })
    : null;

  // headlineAt(min) → { public, total } — the SAME publicAt the Gantt readout uses.
  const headlineAt = (min) => publicAt(basin, min);

  function paintHeadline() {
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
