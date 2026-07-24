// IconSet — inline line-SVG glyphs for the access families (wave / family /
// person / lock / water-drop). currentColor only (no hex), so they inherit ink
// and adapt per theme. Decorative by default (aria-hidden) — the adjacent label
// carries the meaning; pass a title to promote a glyph to role=img.

const PATHS = {
  wave: '<path d="M2 12c2 0 2-2 4-2s2 2 4 2 2-2 4-2 2 2 4 2"/>',
  family:
    '<circle cx="7" cy="6" r="2"/><circle cx="15" cy="7" r="1.6"/>' +
    '<path d="M3 20v-3a4 4 0 0 1 8 0v3M11 20v-2a3.2 3.2 0 0 1 6.4 0v2"/>',
  person: '<circle cx="12" cy="7" r="3"/><path d="M5 21v-2a5 5 0 0 1 14 0v2"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  'water-drop': '<path d="M12 3c3 4 5 6.5 5 9.5a5 5 0 0 1-10 0C7 9.5 9 7 12 3z"/>',
  // Outbound-link affordances (plan: source-links). external-link = a box with an
  // arrow leaving it; doc = a page with a folded corner (the PDF/document glyph).
  'external-link':
    '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/>' +
    '<path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  doc:
    '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/>' +
    '<path d="M14 3v5h5"/>',
};

export const ICON_NAMES = Object.keys(PATHS);

/** iconSvg('wave') → an inline <svg> string (currentColor, aria-hidden). */
export function iconSvg(name, { title } = {}) {
  const body = PATHS[name] || '';
  const a11y = title ? ` role="img" aria-label="${title}"` : ' aria-hidden="true"';
  return (
    `<svg class="ui-icon" viewBox="0 0 24 24" width="1em" height="1em" ` +
    `fill="none" stroke="currentColor" stroke-width="1.6" ` +
    `stroke-linecap="round" stroke-linejoin="round"${a11y}>${body}</svg>`
  );
}

export function createIconSet(el, { props = {} } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  el.classList.add('ui-iconset');
  const names = props.names || ICON_NAMES;
  names.forEach((n) => {
    const cell = doc.createElement('span');
    cell.classList.add('ui-iconset__cell');
    cell.innerHTML = iconSvg(n);
    const cap = doc.createElement('span');
    cap.classList.add('ui-iconset__cap');
    cap.textContent = n;
    cell.appendChild(cap);
    el.appendChild(cell);
  });
  return { el };
}
