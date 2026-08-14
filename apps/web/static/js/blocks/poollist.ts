// poollist.ts — the phone's ranked pool list (variant E).
//
// One card per pool: a verdict sentence, four facts, and a full-width DAY TAIL painting
// the desktop's ribbon encoding (see daytail.ts). Tapping a card expands it in place —
// no sheet, no route — which is why the phone has no equivalent of the bottom-sheet bug
// this work started from.
//
// The block is deliberately thin. Every decision worth arguing about (which tier, what
// the verdict says, what counts as "open to you") lives in poolrank.ts under test; what
// happens here is DOM assembly and painting.
//
// Layering: imports the pure ranking, the shared ribbon model, the shared tail renderer
// and the EligibilityBadge primitive. It introduces no colour — canvas fills are resolved
// from the `.fam-*` classes exactly as the board does.

import { asDoc, type Doc, type El } from '../domtypes.js';
import { fairWeatherText } from '../appdata.js';
import { t } from '../i18n.js';
import { formatHour, formatKm } from '../datefmt.js';
import { locale } from '../i18n.js';
import { ribbonsFor } from './ribbonmodel.js';
import { drawDayTail, STRIP_HOURS, TAIL_H, tickPercent } from './daytail.js';
import { asCanvas, resolveFamilyPalette, type CanvasEl, type Palette } from './ribbonrender.js';
import {
  countOpenToYou,
  rankRows,
  rowKey,
  TIER_KEY,
  TIERS,
  type RankedRow,
  type RankRow,
  type Tier,
} from './poolrank.js';

export interface PoolListOpts {
  rows?: RankRow[];
  /** Minutes-of-day "now", or null when the shown day is not today (no cursor, and the
   *  summary must not claim "now" — see phonebar.ts). */
  nowMin?: number | null;
  reducedMotion?: boolean;
  /** Called with the opened row's `rowKey` and the card's own body host, so the caller
   *  can mount the SAME DetailPanel the desktop uses rather than a second, divergent
   *  detail view. The key is facility + basin, NEVER the label (invariant I6). */
  onOpen?: (key: string, host: El) => void;
}

interface Card {
  canvas: CanvasEl;
  ranked: RankedRow;
  body: El;
}

/** The four facts a row shows. Never five: a fifth wraps onto a second line at 390px. */
function factsFor(ranked: RankedRow): string[] {
  const facts: string[] = [];
  const km = ranked.distanceKm;
  if (km != null) facts.push(formatKm(km, locale()));
  const options = ranked.row.options ?? [];
  const first = options[0];
  const basin = typeof first?.basin === 'string' ? first.basin : null;
  // …but not when the heading already names it. Since S3 a multi-basin pool's label
  // carries its basin (rule L1), and repeating it below reads as a stutter:
  // "Hallenbad City · Schwimmerbecken" over "1.2 km · Schwimmerbecken".
  //
  // The row TELLS us (`basinInLabel`, set where L1 is applied); this block does not read
  // the label back to find out. Parsing it here was a third private definition of the
  // label's format, and the format is exactly the thing L1 is free to change.
  if (basin && !ranked.row.basinInLabel) facts.push(basin);
  return facts.slice(0, 4);
}

function newEl(doc: Doc, tag: string, cls?: string, text?: string): El {
  const n = doc.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

/**
 * createPoolList(el, opts) — mount the list into `el`.
 *
 * Returns a handle whose `setRows` re-ranks and repaints, and whose `paint(phase)` drives
 * the waterline. The caller owns the animation loop (app.ts already has one for the
 * board), so this block never installs a rAF of its own.
 */
export function createPoolList<T extends El>(el: T, opts: PoolListOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  let cards: Card[] = [];
  let pal: Palette | null = null;
  let nowMin: number | null = opts.nowMin ?? null;
  // The OPEN card, held by its `rowKey` (facility + basin). Holding it by label would
  // break exactly for the multi-basin pools this feature exists for: L1 rewrites their
  // labels per answer, so the card would never match itself back.
  let open: string | null = null;

  el.classList.add('plist');

  function paint(phase: number): void {
    if (!pal) pal = resolveFamilyPalette(doc, el);
    const width = tailWidth();
    for (const card of cards) {
      drawDayTail(card.canvas, ribbonsFor(card.ranked.row), pal, {
        width,
        devicePixelRatio: readDpr(),
        phase: opts.reducedMotion ? 0 : phase,
        cursorMin: nowMin,
        cursorColor: pal?.cursor,
      });
    }
  }

  function readDpr(): number {
    const dpr = (globalThis as { devicePixelRatio?: number }).devicePixelRatio;
    return typeof dpr === 'number' ? dpr : 1;
  }

  // The tails are laid out by CSS, so their width comes from a mounted card. Headless
  // (no layout) falls back to a sane plot width so the model still runs.
  function tailWidth(): number {
    const first = cards[0]?.canvas as ({ clientWidth?: number } | undefined);
    const w = first?.clientWidth;
    return typeof w === 'number' && w > 0 ? w : 340;
  }

  /**
   * The hour strip — the labels the tail's bars are read against.
   *
   * DOM, not canvas, because a lane-stack ribbon leaves only ~4.6px of gutter and an
   * in-canvas label collides with the bands there; the strip gets its own row instead.
   * Positioned purely in percent (`tickPercent`), so it needs no layout measurement and
   * cannot fall out of step with the canvas mapping — both come from `tailTimescale`.
   *
   * `aria-hidden`: six bare numbers per card, times ~58 cards, is noise no screen-reader
   * user wants between one pool's verdict and the next.
   */
  function hourStrip(): El {
    const strip = newEl(doc, 'div', 'plist__ticks');
    strip.setAttribute('aria-hidden', 'true');
    const loc = locale();
    for (const hour of STRIP_HOURS) {
      const label = newEl(doc, 'span', 'tnum', formatHour(hour, loc));
      label.style.left = `${tickPercent(hour)}%`;
      strip.appendChild(label);
    }
    return strip;
  }

  function buildCard(ranked: RankedRow): El {
    const card = newEl(doc, 'article', 'plist__card');
    const key = rowKey(ranked.row);
    if (open === key) card.classList.add('is-open');
    if (!ranked.openToYou) card.classList.add('is-muted');

    const btn = newEl(doc, 'button', 'plist__btn');
    btn.setAttribute('type', 'button');
    btn.setAttribute('aria-expanded', String(open === key));

    const head = newEl(doc, 'div', 'plist__head');
    head.appendChild(newEl(doc, 'span', `plist__dot is-${ranked.tier}`));
    const text = newEl(doc, 'div', 'plist__text');
    text.appendChild(newEl(doc, 'h3', 'plist__name', ranked.row.label));

    const verdict = newEl(doc, 'p', 'plist__verdict');
    verdict.appendChild(
      newEl(doc, 'b', undefined, t(ranked.verdict.key, ranked.verdict.params)),
    );
    if (ranked.verdict.tailKey) {
      const tail = newEl(doc, 'span', 'plist__vtail');
      tail.textContent = ` · ${t(ranked.verdict.tailKey, ranked.verdict.tailParams)}`;
      verdict.appendChild(tail);
    }
    text.appendChild(verdict);

    // Fair-weather marker (seasonal-hours S4) — the same fact the desktop board's label
    // column carries, so the phone never presents a conditional block as a promise. It
    // names the conditional SPANS and leaves the card's tier/verdict alone: the pool really
    // is open, and only part of its published day depends on the weather.
    const fair = fairWeatherText(ranked.row.options);
    if (fair) {
      text.appendChild(newEl(doc, 'p', 'plist__fair', fair));
    }

    head.appendChild(text);
    btn.appendChild(head);

    const facts = factsFor(ranked);
    if (facts.length) {
      const meta = newEl(doc, 'p', 'plist__meta');
      for (const f of facts) meta.appendChild(newEl(doc, 'span', undefined, f));
      btn.appendChild(meta);
    }

    // The plot — an hour strip over the day tail — lives INSIDE the button: tapping the
    // bars is the natural gesture for opening a card, and a sibling node would never reach
    // the handler (`_fakedom`'s dispatch does not bubble, and a real tap on a sibling is
    // simply not on the button). A strip outside the button would also punch a dead 12px
    // gap through the middle of that tap target. `.plist__more` deliberately stays OUTSIDE
    // it — a <button> may not contain the scrollable, focusable Gantt.
    //
    // `.plist__plot` is the CSS contract, not decoration: it supplies the ONE inline
    // padding both children share, so the strip's percentages and the canvas's own
    // mapping resolve against the same content box. Neither child pads itself inline —
    // if the strip did, every label would land ~7% (about one hour) off its bar.
    const plot = newEl(doc, 'div', 'plist__plot');
    plot.appendChild(hourStrip());

    // `.plist__tail` STAYS, wrapping the canvas: `blocks.css`'s
    // `.plist__tail canvas { width: 100% }` is what makes the canvas fill its box. Hoisted
    // straight into `.plist__plot` it would lay out at its ATTRIBUTE width (the backing
    // store, up to 2x dpr), which `tailWidth()` reads back through `clientWidth` and feeds
    // into the next paint — the same misalignment, arriving via the DOM instead.
    const tailBox = newEl(doc, 'div', 'plist__tail');
    const canvas = asCanvas(doc.createElement('canvas'));
    canvas.setAttribute('role', 'img');
    canvas.setAttribute('aria-label', ranked.row.label);
    // A <button> computes its accessible name from its contents, and the h3 above
    // already carries `row.label` — without this every one of the ~58 rows would
    // announce its pool name twice. `role`/`aria-label` stay but are now inert.
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.height = `${TAIL_H}px`;
    tailBox.appendChild(canvas);
    plot.appendChild(tailBox);
    btn.appendChild(plot);
    card.appendChild(btn);

    // The expanded body: empty until opened, filled by the caller. Detail is INLINE —
    // no sheet, no route — which is why the phone has no equivalent of the bottom-sheet
    // bug this work started from.
    const body = newEl(doc, 'div', 'plist__more');
    card.appendChild(body);

    btn.addEventListener('click', () => {
      const next = open === key ? null : key;
      open = next;
      render();
      if (next && opts.onOpen) {
        const reopened = cards.find((c) => rowKey(c.ranked.row) === next);
        if (reopened?.body) opts.onOpen(next, reopened.body);
      }
    });

    cards.push({ canvas, ranked, body });
    return card;
  }

  let rows: RankRow[] = opts.rows ?? [];

  function render(): void {
    el.textContent = '';
    cards = [];
    const ranked = rankRows(rows, nowMin ?? 0);
    const byTier = new Map<Tier, RankedRow[]>();
    for (const r of ranked) {
      const bucket = byTier.get(r.tier) ?? [];
      bucket.push(r);
      byTier.set(r.tier, bucket);
    }
    for (const tier of TIERS) {
      const bucket = byTier.get(tier);
      if (!bucket || !bucket.length) continue;
      const hd = newEl(doc, 'div', 'plist__group');
      hd.appendChild(newEl(doc, 'span', undefined, t(TIER_KEY[tier])));
      hd.appendChild(newEl(doc, 'b', undefined, String(bucket.length)));
      el.appendChild(hd);
      for (const r of bucket) el.appendChild(buildCard(r));
    }
    paint(0);
  }

  render();

  return {
    el,
    get cards() {
      return cards;
    },
    /** The open card's `rowKey`, or null. Deliberately not a label — see `rowKey`. */
    get openKey() {
      return open;
    },
    countOpenToYou(): number {
      return countOpenToYou(rankRows(rows, nowMin ?? 0));
    },
    /** Drop the cached palette and repaint. A CSS variable cannot reach pixels that are
     *  already rasterised, so a theme change leaves the tails in the OLD ramp until the
     *  canvas is redrawn — proven by identical pixel data across a light→dark flip. */
    repaint(): void {
      pal = null;
      paint(0);
    },
    setRows(next: RankRow[], min: number | null): void {
      rows = next;
      nowMin = min;
      open = null;
      render();
    },
    paint,
  };
}
