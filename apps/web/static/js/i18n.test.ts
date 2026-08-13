import { afterEach, expect, test, vi } from "vitest";
import {
  LOCALE_COOKIE,
  locale,
  pseudo,
  resolveLocale,
  resolveLocaleFromBrowser,
  setLocale,
  t,
} from "./i18n.js";

afterEach(() => {
  setLocale("en");
  vi.unstubAllGlobals();
});

test("t returns a plain message", () => {
  expect(t("common.today")).toBe("Today");
});

test("t interpolates {name} params", () => {
  expect(t("board.poolCount", { count: 3 })).toBe("3 pools");
});

test("t selects the plural form by CLDR category", () => {
  expect(t("board.poolCount", { count: 1 })).toBe("1 pool");
  expect(t("board.poolCount", { count: 0 })).toBe("0 pools");
  expect(t("basin.laneCount", { count: 1 })).toBe("1 lane");
  expect(t("basin.laneCount", { count: 6 })).toBe("6 lanes");
});

test("a plural entry without a numeric count falls back to `other` rather than guessing", () => {
  expect(t("board.poolCount")).toBe("{count} pools");
});

test("an unknown placeholder is left visible, not blanked", () => {
  // A missing param should be obvious in the UI (and in a screenshot diff), never an
  // empty gap that reads as intentional copy.
  expect(t("board.poolCount", {})).toContain("{count}");
});

test("locale defaults to en and setLocale moves it", () => {
  expect(locale()).toBe("en");
  setLocale("pl");
  expect(locale()).toBe("pl");
});

test("every locale renders its OWN copy, not the English fallback", () => {
  setLocale("de");
  expect(t("common.today")).toBe("Heute");
  setLocale("pl");
  expect(t("common.today")).toBe("Dzisiaj");
  setLocale("fr");
  expect(t("common.today")).toBe("Aujourd’hui");
  setLocale("it");
  expect(t("common.today")).toBe("Oggi");
});

// ---- resolveLocale: the single seam --------------------------------------------------

test("the cookie wins over localStorage and the browser languages", () => {
  // The cookie is canonical because it is the only channel the SERVER can read, and the
  // server-rendered shell must emit <html lang>.
  const got = resolveLocale({
    cookie: `${LOCALE_COOKIE}=de`,
    stored: "fr",
    languages: ["it"],
  });
  expect(got).toBe("de");
});

test("localStorage is consulted when no cookie is set", () => {
  expect(resolveLocale({ stored: "fr", languages: ["it"] })).toBe("fr");
});

test("browser languages are the last signal, and region tags match on their base", () => {
  expect(resolveLocale({ languages: ["pl-PL", "en-GB"] })).toBe("pl");
});

test("an unsupported language is skipped rather than accepted", () => {
  expect(resolveLocale({ languages: ["es-ES", "it-CH"] })).toBe("it");
});

test("everything absent or unsupported falls back to en", () => {
  expect(resolveLocale()).toBe("en");
  expect(
    resolveLocale({ cookie: "other=1", stored: "es", languages: ["ja"] }),
  ).toBe("en");
});

test("the locale cookie is found among other cookies", () => {
  expect(
    resolveLocale({ cookie: `theme=dark; ${LOCALE_COOKIE}=it; tz=CET` }),
  ).toBe("it");
});

// ---- resolveLocaleFromBrowser: the ambient-env reader ---------------------------------

test("with no browser globals at all it still resolves (headless / SSR)", () => {
  expect(resolveLocaleFromBrowser()).toBe("en");
});

test("it reads document.cookie ahead of navigator.languages", () => {
  vi.stubGlobal("document", { cookie: `${LOCALE_COOKIE}=pl` });
  vi.stubGlobal("navigator", { languages: ["de-CH"] });
  expect(resolveLocaleFromBrowser()).toBe("pl");
});

test("it reads localStorage when no cookie is present", () => {
  vi.stubGlobal("document", { cookie: "" });
  vi.stubGlobal("localStorage", { getItem: () => "it" });
  expect(resolveLocaleFromBrowser()).toBe("it");
});

test("a localStorage that throws does not break locale resolution", () => {
  // Private-mode and blocked-cookie browsers throw on localStorage access. The cookie is
  // the canonical channel anyway, so this must degrade rather than crash the whole UI.
  vi.stubGlobal("document", { cookie: `${LOCALE_COOKIE}=fr` });
  vi.stubGlobal("localStorage", {
    getItem: () => {
      throw new Error("SecurityError");
    },
  });
  expect(resolveLocaleFromBrowser()).toBe("fr");
});

test("it falls back to navigator.languages when cookie and storage are empty", () => {
  vi.stubGlobal("document", { cookie: "" });
  vi.stubGlobal("localStorage", { getItem: () => null });
  vi.stubGlobal("navigator", { languages: ["pl-PL"] });
  expect(resolveLocaleFromBrowser()).toBe("pl");
});

// ---- pseudolocale ---------------------------------------------------------------------

test("pseudo accents letters, pads for expansion, and BRACKETS the string", () => {
  const out = pseudo("Closed");
  expect(out).toMatch(/^⟦/);
  expect(out).toMatch(/⟧$/);
  expect(out).not.toContain("Closed"); // every letter is accented
  expect(out.length).toBeGreaterThan("Closed".length);
});

test("pseudo leaves {placeholders} intact", () => {
  // Accenting `{count}` would break interpolation and hide the very bug the pass exists
  // to expose — a padded string with no number in it.
  const out = pseudo("Closed · {reason} at {facility}");
  expect(out).toContain("{reason}");
  expect(out).toContain("{facility}");
});

test("pseudo padding is proportional, so long strings expand more", () => {
  const short = pseudo("Open");
  const long = pseudo("Hours not listed yet, may well be open");
  expect(
    long.length - "Hours not listed yet, may well be open".length,
  ).toBeGreaterThan(short.length - "Open".length);
});
