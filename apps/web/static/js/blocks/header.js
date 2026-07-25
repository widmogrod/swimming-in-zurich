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

// The three theme choices, in cycle order. 'auto' defers to the OS/media query.
export const THEMES = ['auto', 'light', 'dark'];
const THEME_LABEL = { auto: 'Auto', light: 'Light', dark: 'Dark' };
const THEME_ICON = { auto: '◐', light: '☀', dark: '☾' };

/** nextTheme(current) → the next theme in the auto→light→dark→auto cycle. Pure. */
export function nextTheme(current) {
  const i = THEMES.indexOf(current);
  return THEMES[(i + 1) % THEMES.length];
}

/**
 * applyTheme(root, theme) — stamp the viewer's theme onto the document root.
 * 'auto' REMOVES `data-theme` (so `@media (prefers-color-scheme)` decides);
 * 'light'/'dark' set it explicitly (overriding the media query both ways, per the
 * tokens.css contract). Pure w.r.t. everything but `root.dataset`.
 */
export function applyTheme(root, theme) {
  if (!root || !root.dataset) return;
  if (theme === 'auto') delete root.dataset.theme;
  else root.dataset.theme = theme;
}

/**
 * createIdentityHeader(el, opts) — mount the header into `el`.
 * @param {object} opts.props `{ title, dateLabel, theme }`.
 * @param {object} [opts.root] the element to stamp `[data-theme]` on (default: the
 *   document's documentElement).
 * @param {function} [opts.onThemeChange] called with the new theme after a toggle.
 * @returns {{el, setDateLabel, theme, toggle}}
 */
export function createIdentityHeader(el, opts = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const props = opts.props || {};
  const root = opts.root || (doc.documentElement != null ? doc.documentElement : null);
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
  title.textContent = props.title || 'Swimming in Zürich';
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
  copy.setAttribute('aria-label', 'Copy a shareable link to this view');
  const copyIcon = doc.createElement('span');
  copyIcon.setAttribute('aria-hidden', 'true');
  copyIcon.textContent = '🔗';
  const copyLabel = doc.createElement('span');
  copyLabel.className = 'apphdr__copylabel';
  copyLabel.setAttribute('aria-live', 'polite');
  copyLabel.textContent = 'Copy link';
  copy.appendChild(copyIcon);
  copy.appendChild(copyLabel);

  let copyTimer = null;
  function flashCopied() {
    copyLabel.textContent = 'Copied';
    if (copyTimer) clearTimeout(copyTimer);
    copyTimer = setTimeout(() => {
      copyLabel.textContent = 'Copy link';
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
    applyTheme(root, theme);
    renderToggle();
    if (opts.onThemeChange) opts.onThemeChange(theme);
  });

  el.appendChild(brand);
  el.appendChild(datebox);
  el.appendChild(copy);
  el.appendChild(toggle);
  renderToggle();
  applyTheme(root, theme);

  return {
    el,
    toggle,
    copy,
    setDateLabel(text) {
      datebox.textContent = text || '';
    },
    get theme() {
      return theme;
    },
  };
}
