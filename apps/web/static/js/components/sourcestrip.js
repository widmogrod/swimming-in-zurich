// SourceStrip — the "verify at the source" affordance (plan: source-links).
//
// One outbound chip per PRESENT source URL — Official page, Lane plan PDF(s),
// Prices — each a new-tab link the swimmer can trust: target=_blank +
// rel="noopener noreferrer", an honest aria-label naming the destination host,
// and a trailing ↗. Lane-plan chips carry a visible "PDF" tag so a tap is never a
// surprise download.
//
// Honesty rules: a null / empty URL renders NO chip; when nothing is present the
// strip renders an element with no chips (never a dead link, never an empty label).
// Chips dedup by URL across kinds using plain exact-string equality, keeping the
// first in priority order (Official → Lane plan → Prices) — so a city pool whose
// prices page IS its pool page collapses Prices into Official rather than doubling.
//
// A COMPONENT (peer of provenancestamp.js): currentColor icons via iconSvg, no raw
// hue (every colour is a token via a class in components.css).

import { iconSvg } from './iconset.js';

// hostname for the aria-label; falls back to the raw URL if it can't be parsed
// (we still never fabricate — an unparseable URL is named verbatim).
function hostOf(url) {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

export function createSourceStrip(el, { props = {} } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  el.classList.add('ui-sourcestrip');

  const officialUrl = props.officialUrl || null;
  const lanePlanUrls = props.lanePlanUrls || [];
  const pricesUrl = props.pricesUrl || null;

  // Build the candidate list in priority order, deduping by exact URL string across
  // kinds (first wins). `pdf` marks a lane-plan chip.
  const seen = new Set();
  const chips = [];
  const consider = (url, spec) => {
    if (url == null || url === '') return;
    if (seen.has(url)) return;
    seen.add(url);
    chips.push({ url, ...spec });
  };
  consider(officialUrl, { kind: 'official', label: 'Official page', icon: 'external-link' });
  for (const u of lanePlanUrls) {
    consider(u, { kind: 'lane', label: 'Lane plan', icon: 'doc', pdf: true });
  }
  consider(pricesUrl, { kind: 'prices', label: 'Prices', icon: 'external-link' });

  // Only label the host as a "Sources" group when it actually holds chips — an empty
  // strip stays a bare element so a screen reader never announces an empty group.
  if (chips.length > 0) {
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', 'Sources');
  }

  for (const chip of chips) {
    const a = doc.createElement('a');
    a.classList.add('ui-sourcestrip__chip', `ui-sourcestrip__chip--${chip.kind}`);
    a.setAttribute('href', chip.url);
    a.setAttribute('target', '_blank');
    a.setAttribute('rel', 'noopener noreferrer');
    const aName = chip.pdf ? `${chip.label} PDF` : chip.label;
    a.setAttribute('aria-label', `${aName} — opens ${hostOf(chip.url)} in a new tab`);

    const icon = doc.createElement('span');
    icon.classList.add('ui-sourcestrip__icon');
    icon.setAttribute('aria-hidden', 'true');
    icon.innerHTML = iconSvg(chip.icon);
    a.appendChild(icon);

    const label = doc.createElement('span');
    label.classList.add('ui-sourcestrip__label');
    label.textContent = chip.label;
    a.appendChild(label);

    if (chip.pdf) {
      const tag = doc.createElement('span');
      tag.classList.add('ui-sourcestrip__tag');
      tag.textContent = 'PDF';
      a.appendChild(tag);
    }

    const ext = doc.createElement('span');
    ext.classList.add('ui-sourcestrip__ext');
    ext.setAttribute('aria-hidden', 'true');
    ext.textContent = '↗';
    a.appendChild(ext);

    el.appendChild(a);
  }

  return { el };
}
