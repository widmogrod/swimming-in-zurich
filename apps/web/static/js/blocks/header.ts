// header.js — the IdentityHeader block (plan Part 3 §1).
//
// Logo + title on the left, an absolute date (Day mode) or week range (Pool mode)
// in the middle, and a theme toggle on the right that cycles light → dark → auto
// by stamping `[data-theme]` on the document root (auto = remove the attribute so
// the `prefers-color-scheme` media query rules — the tokens.css theming contract).
//
// The theme cycle (`nextTheme`) and the root stamp (`applyTheme`) are PURE enough
// to unit-test headless; the toggle button's ARIA is asserted on the fake DOM. No
// colour, no hex — the header borrows tokens through its blocks.css classes.

import { asDoc, type El } from '../domtypes.js';
import {
  chooseLocale,
  locale,
  LOCALE_NAMES,
  OFFERED_LOCALES,
  t,
} from '../i18n.js';
import { isLocale } from '../plurals.js';

/** The three theme choices, in cycle order. 'auto' defers to the OS/media query. */
export type Theme = 'auto' | 'light' | 'dark';

// The three theme choices, in cycle order. 'auto' defers to the OS/media query.
export const THEMES: readonly Theme[] = ['auto', 'light', 'dark'];
const THEME_LABEL = { auto: t('theme.auto'), light: t('theme.light'), dark: t('theme.dark') };
const THEME_ICON = { auto: '◐', light: '☀', dark: '☾' };

/** nextTheme(current) → the next theme in the auto→light→dark→auto cycle. Pure. */
export function nextTheme(current: string): Theme {
  const i = THEMES.indexOf(current as Theme);
  return THEMES[(i + 1) % THEMES.length];
}

/**
 * applyTheme(root, theme) — stamp the viewer's theme onto the document root.
 * 'auto' REMOVES `data-theme` (so `@media (prefers-color-scheme)` decides);
 * 'light'/'dark' set it explicitly (overriding the media query both ways, per the
 * tokens.css contract). Pure w.r.t. everything but `root.dataset`.
 */
export function applyTheme(root: El, theme: string): void {
  if (!root || !root.dataset) return;
  if (theme === 'auto') delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/**
 * createIdentityHeader(el, opts) — mount the header into `el`.
 * @param {{title?: string, dateLabel?: string, theme?: string}} opts.props
 * @param {object} [opts.root] the element to stamp `[data-theme]` on (default: the
 *   document's documentElement).
 * @param {function} [opts.onThemeChange] called with the new theme after a toggle.
 * @returns {{el: import('../domtypes.js').El, toggle: import('../domtypes.js').El,
 *            copy: import('../domtypes.js').El, setDateLabel(text: string): void,
 *            readonly theme: string}}
 */
export interface HeaderProps {
  title?: string;
  dateLabel?: string;
  theme?: Theme;
}

export interface HeaderOpts {
  props?: HeaderProps;
  root?: El;
  onThemeChange?: (theme: Theme) => void;
}

export function createIdentityHeader<T extends El>(el: T, opts: HeaderOpts = {}) {
  const doc = el.ownerDocument || asDoc(globalThis.document);
  const props = opts.props || {};
  const root = opts.root ?? doc.documentElement ?? null;
  let theme = props.theme && THEMES.includes(props.theme) ? props.theme : 'auto';

  el.classList.add('apphdr');

  // --- brand: logo + title ---
  const brand = doc.createElement('div');
  brand.className = 'apphdr__brand';
  const logo = doc.createElement('span');
  logo.className = 'apphdr__logo';
  logo.setAttribute('aria-hidden', 'true');
  logo.textContent = '🏊';
  const title = doc.createElement('h1');
  title.className = 'apphdr__title';
  title.textContent = props.title || t('app.title');
  brand.appendChild(logo);
  brand.appendChild(title);

  // --- datebox: the absolute date / week range ---
  const datebox = doc.createElement('div');
  datebox.className = 'apphdr__datebox tnum';
  datebox.textContent = props.dateLabel || '';

  // --- copy link: the "share as a link" surface (the URL already auto-mirrors the
  // filter, so this just copies the current href). It touches `navigator.clipboard`
  // and `location` — the ONLY impure bit of the header — guarded so a headless / no-
  // clipboard context (or a test stub) never throws.
  const copy = doc.createElement('button');
  copy.setAttribute('type', 'button');
  copy.className = 'apphdr__copy';
  copy.setAttribute('aria-label', t('header.copyAria'));
  const copyIcon = doc.createElement('span');
  copyIcon.setAttribute('aria-hidden', 'true');
  copyIcon.textContent = '🔗';
  const copyLabel = doc.createElement('span');
  copyLabel.className = 'apphdr__copylabel';
  copyLabel.setAttribute('aria-live', 'polite');
  copyLabel.textContent = t('header.copyLink');
  copy.appendChild(copyIcon);
  copy.appendChild(copyLabel);

  let copyTimer: ReturnType<typeof setTimeout> | null = null;
  function flashCopied() {
    copyLabel.textContent = t('header.copied');
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copyLabel.textContent = t('header.copyLink');
    }, 1600);
    if (copyTimer && typeof copyTimer.unref === 'function') copyTimer.unref();
  }
  copy.addEventListener('click', () => {
    const href = globalThis.location != null ? globalThis.location.href : '';
    const clip = globalThis.navigator != null ? globalThis.navigator.clipboard : null;
    if (clip && typeof clip.writeText === 'function') clip.writeText(href);
    flashCopied();
  });

  // --- theme toggle: cycles auto → light → dark ---
  const toggle = doc.createElement('button');
  toggle.setAttribute('type', 'button');
  toggle.className = 'apphdr__theme';

  function renderToggle() {
    toggle.textContent = `${THEME_ICON[theme]} ${THEME_LABEL[theme]}`;
    toggle.setAttribute('aria-label', `Theme: ${THEME_LABEL[theme]} (click to change)`);
    toggle.dataset.theme = theme;
  }

  toggle.addEventListener('click', () => {
    theme = nextTheme(theme);
    if (root) applyTheme(root, theme);
    renderToggle();
    if (opts.onThemeChange) opts.onThemeChange(theme);
  });

  // --- language switcher ---
  //
  // A native <select>: five options is too many for a segmented control, and the platform
  // control brings keyboard navigation, screen-reader semantics and mobile pickers for
  // free. The option LABELS are endonyms (Deutsch, Polski) — see LOCALE_NAMES.
  // Structured like its neighbours — a glyph plus a label inside one pill — so the three
  // header controls read as one family. The <select> keeps native semantics (keyboard,
  // screen reader, mobile picker) but is stripped of its OS chrome in CSS; the PILL lives
  // on the wrapper, because a bare styled <select> cannot hold a leading glyph.
  const langWrap = doc.createElement('span');
  langWrap.className = 'apphdr__lang';
  const langIcon = doc.createElement('span');
  langIcon.className = 'apphdr__langicon';
  langIcon.setAttribute('aria-hidden', 'true');
  langIcon.textContent = '🌐';
  const lang = doc.createElement('select');
  lang.className = 'apphdr__langselect';
  lang.setAttribute('aria-label', t('header.language'));
  for (const code of OFFERED_LOCALES) {
    const option = doc.createElement('option');
    option.value = code;
    option.textContent = LOCALE_NAMES[code];
    if (code === locale()) option.setAttribute('selected', 'selected');
    lang.appendChild(option);
  }
  lang.value = locale();
  lang.addEventListener('change', () => {
    const next = lang.value;
    if (isLocale(next) && next !== locale()) chooseLocale(next);
  });
  langWrap.appendChild(langIcon);
  langWrap.appendChild(lang);

  el.appendChild(brand);
  el.appendChild(datebox);
  el.appendChild(langWrap);
  el.appendChild(copy);
  el.appendChild(toggle);
  renderToggle();
  if (root) applyTheme(root, theme);

  return {
    el,
    lang,
    toggle,
    copy,
    setDateLabel(text: string) {
      datebox.textContent = text || '';
    },
    get theme() {
      return theme;
    },
  };
}
