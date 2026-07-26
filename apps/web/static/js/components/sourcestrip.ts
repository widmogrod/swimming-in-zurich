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

import { asDoc, type El } from '../domtypes.js';
import { t } from '../i18n.js';
import { iconSvg } from './iconset.js';

// hostname for the aria-label; falls back to the raw URL if it can't be parsed
// (we still never fabricate — an unparseable URL is named verbatim).
function hostOf(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

interface ChipSpec {
  kind: string;
  label: string;
  icon: string;
  pdf?: boolean;
}

export interface SourceStripProps {
  officialUrl?: string | null;
  lanePlanUrls?: (string | null | undefined)[];
  pricesUrl?: string | null;
  [k: string]: unknown;
}

export function createSourceStrip<T extends El>(
  el: T,
  { props = {} }: { props?: SourceStripProps } = {},
): { el: T } {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  el.classList.add('ui-sourcestrip');

  const officialUrl = props.officialUrl || null;
  const lanePlanUrls = props.lanePlanUrls || [];
  const pricesUrl = props.pricesUrl || null;

  // Build the candidate list in priority order, deduping by exact URL string across
  // kinds (first wins). `pdf` marks a lane-plan chip.
  const seen = new Set<string>();
  const chips: (ChipSpec & { url: string })[] = [];
  const consider = (url: string | null | undefined, spec: ChipSpec) => {
    if (url == null || url === '') return;
    if (seen.has(url)) return;
    seen.add(url);
    chips.push({ url, ...spec });
  };
  consider(officialUrl, { kind: 'official', label: t('sources.official'), icon: 'external-link' });
  for (const u of lanePlanUrls) {
    consider(u, { kind: 'lane', label: t('sources.lanePlan'), icon: 'doc', pdf: true });
  }
  consider(pricesUrl, { kind: 'prices', label: t('sources.prices'), icon: 'external-link' });

  // Only label the host as a "Sources" group when it actually holds chips — an empty
  // strip stays a bare element so a screen reader never announces an empty group.
  if (chips.length > 0) {
    el.setAttribute('role', 'group');
    el.setAttribute('aria-label', t('sources.label'));
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
      tag.textContent = t('sources.pdf');
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
