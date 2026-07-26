import { expect, test } from 'vitest';

import { nextTheme, applyTheme, createIdentityHeader, THEMES } from './header.js';
import { mount } from '../components/_fakedom.js';
import { fake, must } from '../testutil.js';
import type { FakeElement } from '../components/_fakedom.js';

test('nextTheme cycles auto → light → dark → auto', () => {
  expect(nextTheme('auto')).toBe('light');
  expect(nextTheme('light')).toBe('dark');
  expect(nextTheme('dark')).toBe('auto');
  // Unknown → treated as before the start, so the cycle still resolves.
  expect(THEMES.includes(nextTheme('nonsense'))).toBeTruthy();
});

test('applyTheme stamps [data-theme]; auto REMOVES it (media query decides)', () => {
  const root = mount(); // has a `.dataset` object
  applyTheme(root, 'dark');
  expect(root.dataset.theme).toBe('dark');
  applyTheme(root, 'light');
  expect(root.dataset.theme).toBe('light');
  applyTheme(root, 'auto');
  expect(root.dataset.theme).toBe(undefined);
});

test('createIdentityHeader renders brand + datebox and an accessible theme toggle', () => {
  const el = mount();
  const header = createIdentityHeader(el, {
    props: { title: 'Swimming in Zürich', dateLabel: 'Thu 23 Jul', theme: 'auto' },
    root: mount(),
  });
  expect(must(el.query((c: FakeElement) => c.classList.contains('apphdr__brand')))).toBeTruthy();
  const datebox = must(el.query((c: FakeElement) => c.classList.contains('apphdr__datebox')));
  expect(datebox.textContent).toBe('Thu 23 Jul');
  const toggle = header.toggle;
  expect(toggle.tagName).toBe('BUTTON');
  expect(must(toggle.getAttribute('aria-label')).includes('Theme')).toBeTruthy();
});

test('clicking the toggle cycles the theme, stamps the root, and reports it', () => {
  const el = mount();
  const root = mount();
  const seen: unknown[] = [];
  const header = createIdentityHeader(el, {
    props: { theme: 'auto' },
    root,
    onThemeChange: (t) => seen.push(t),
  });
  expect(header.theme).toBe('auto');
  expect(root.dataset.theme).toBe(undefined); // auto → no stamp

  header.toggle.click();
  expect(header.theme).toBe('light');
  expect(root.dataset.theme).toBe('light');
  expect(seen).toEqual(['light']);

  header.toggle.click();
  expect(header.theme).toBe('dark');
  expect(root.dataset.theme).toBe('dark');
});

test('setDateLabel updates the datebox (Day → Pool week range)', () => {
  const el = mount();
  const header = createIdentityHeader(el, { props: { dateLabel: 'Thu 23 Jul' }, root: mount() });
  header.setDateLabel('Week of Mon 20 Jul');
  const datebox = must(el.query((c: FakeElement) => c.classList.contains('apphdr__datebox')));
  expect(datebox.textContent).toBe('Week of Mon 20 Jul');
});

test('renders an accessible Copy-link button that copies the current href and confirms', () => {
  // Stub the two browser globals the copy handler touches (headless node has neither).
  const savedNav = globalThis.navigator;
  const savedLoc = globalThis.location;
  const copied: unknown[] = [];
  Object.defineProperty(globalThis, 'navigator', {
    value: { clipboard: { writeText: (t: string) => copied.push(t) } },
    configurable: true,
  });
  Object.defineProperty(globalThis, 'location', {
    value: { href: 'https://swim.example/?view=pool&pool=hallenbad-oerlikon' },
    configurable: true,
  });
  try {
    const el = mount();
    const header = createIdentityHeader(el, { props: {}, root: mount() });
    const copy = header.copy;
    expect(copy.tagName).toBe('BUTTON');
    expect(
      must(copy.getAttribute('aria-label')).toLowerCase().includes('copy'),
    ).toBeTruthy();
    const label = must(fake(copy).query((c: FakeElement) => c.classList.contains('apphdr__copylabel')));
    expect(label.textContent).toBe('Copy link');

    copy.click();
    // The current href was written to the clipboard, and the label flashed "Copied".
    expect(copied).toEqual(['https://swim.example/?view=pool&pool=hallenbad-oerlikon']);
    expect(label.textContent).toBe('Copied');
  } finally {
    if (savedNav === undefined) delete (globalThis as Record<string, unknown>).navigator;
    else Object.defineProperty(globalThis, 'navigator', { value: savedNav, configurable: true });
    if (savedLoc === undefined) delete (globalThis as Record<string, unknown>).location;
    else Object.defineProperty(globalThis, 'location', { value: savedLoc, configurable: true });
  }
});

test('the Copy-link handler does not throw when no clipboard is available', () => {
  const savedNav = globalThis.navigator;
  const savedLoc = globalThis.location;
  if (savedNav !== undefined) delete (globalThis as Record<string, unknown>).navigator;
  if (savedLoc !== undefined) delete (globalThis as Record<string, unknown>).location;
  try {
    const el = mount();
    const header = createIdentityHeader(el, { props: {}, root: mount() });
    expect(() => header.copy.click()).not.toThrow(); // guarded — no navigator/location
    const label = must(fake(header.copy).query((c: FakeElement) => c.classList.contains('apphdr__copylabel')));
    expect(label.textContent).toBe('Copied'); // still confirms optimistically
  } finally {
    if (savedNav !== undefined)
      Object.defineProperty(globalThis, 'navigator', { value: savedNav, configurable: true });
    if (savedLoc !== undefined)
      Object.defineProperty(globalThis, 'location', { value: savedLoc, configurable: true });
  }
});
