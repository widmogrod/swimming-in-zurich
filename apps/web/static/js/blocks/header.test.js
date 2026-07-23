import test from 'node:test';
import assert from 'node:assert/strict';

import { nextTheme, applyTheme, createIdentityHeader, THEMES } from './header.js';
import { mount } from '../components/_fakedom.js';

test('nextTheme cycles auto → light → dark → auto', () => {
  assert.equal(nextTheme('auto'), 'light');
  assert.equal(nextTheme('light'), 'dark');
  assert.equal(nextTheme('dark'), 'auto');
  // Unknown → treated as before the start, so the cycle still resolves.
  assert.ok(THEMES.includes(nextTheme('nonsense')));
});

test('applyTheme stamps [data-theme]; auto REMOVES it (media query decides)', () => {
  const root = mount(); // has a `.dataset` object
  applyTheme(root, 'dark');
  assert.equal(root.dataset.theme, 'dark');
  applyTheme(root, 'light');
  assert.equal(root.dataset.theme, 'light');
  applyTheme(root, 'auto');
  assert.equal(root.dataset.theme, undefined);
});

test('createIdentityHeader renders brand + datebox and an accessible theme toggle', () => {
  const el = mount();
  const header = createIdentityHeader(el, {
    props: { title: 'Swimming in Zürich', dateLabel: 'Thu 23 Jul', theme: 'auto' },
    root: mount(),
  });
  assert.ok(el.query((c) => c.classList.contains('apphdr__brand')));
  const datebox = el.query((c) => c.classList.contains('apphdr__datebox'));
  assert.equal(datebox.textContent, 'Thu 23 Jul');
  const toggle = header.toggle;
  assert.equal(toggle.tagName, 'BUTTON');
  assert.ok(toggle.getAttribute('aria-label').includes('Theme'));
});

test('clicking the toggle cycles the theme, stamps the root, and reports it', () => {
  const el = mount();
  const root = mount();
  const seen = [];
  const header = createIdentityHeader(el, {
    props: { theme: 'auto' },
    root,
    onThemeChange: (t) => seen.push(t),
  });
  assert.equal(header.theme, 'auto');
  assert.equal(root.dataset.theme, undefined); // auto → no stamp

  header.toggle.click();
  assert.equal(header.theme, 'light');
  assert.equal(root.dataset.theme, 'light');
  assert.deepEqual(seen, ['light']);

  header.toggle.click();
  assert.equal(header.theme, 'dark');
  assert.equal(root.dataset.theme, 'dark');
});

test('setDateLabel updates the datebox (Day → Pool week range)', () => {
  const el = mount();
  const header = createIdentityHeader(el, { props: { dateLabel: 'Thu 23 Jul' }, root: mount() });
  header.setDateLabel('Week of Mon 20 Jul');
  const datebox = el.query((c) => c.classList.contains('apphdr__datebox'));
  assert.equal(datebox.textContent, 'Week of Mon 20 Jul');
});
