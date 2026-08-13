import { expect, test } from "vitest";

import {
  fetchDay,
  fetchPoolDetail,
  fetchWeek,
  isoDate,
  mondayOf,
  poolUrl,
  shiftIso,
  swimParams,
  swimUrl,
  weekDates,
  type Answer,
  type SwimFilter,
} from "./api.js";
import { dayParts } from "./datefmt.js";
import { locale } from "./i18n.js";

test("isoDate/shiftIso are UTC and never drift a day", () => {
  expect(isoDate(new Date(Date.UTC(2026, 6, 23)))).toBe("2026-07-23");
  expect(shiftIso("2026-07-23", 2)).toBe("2026-07-25");
  expect(shiftIso("2026-07-01", -1)).toBe("2026-06-30"); // month underflow
});

test("mondayOf snaps to the ISO Monday (Mon=0)", () => {
  expect(mondayOf("2026-07-23")).toBe("2026-07-20"); // Thu → Mon
  expect(mondayOf("2026-07-20")).toBe("2026-07-20"); // Mon → itself
  expect(mondayOf("2026-07-26")).toBe("2026-07-20"); // Sun → the same Mon
});

test("weekDates yields the 7 Mon…Sun dates in order", () => {
  const dates = weekDates("2026-07-23");
  expect(dates).toEqual([
    "2026-07-20",
    "2026-07-21",
    "2026-07-22",
    "2026-07-23",
    "2026-07-24",
    "2026-07-25",
    "2026-07-26",
  ]);
  // Seven days; the LABELS are no longer a hardcoded English table — they come from
  // Intl per locale (see datefmt.dayParts), so there is no table length to compare to.
  expect(dates.length).toBe(7);
});

test("swimParams: eligible_only is always false and place/gender/age are conditional", () => {
  const base = swimParams(
    { place: { lat: null, lon: null }, gender: "", age: null },
    "2026-07-23",
  );
  expect(base.at).toBe("2026-07-23T12:00");
  expect(base.eligible_only).toBe("false");
  expect(!("lat" in base) && !("lon" in base)).toBeTruthy();
  expect(!("gender" in base) && !("age" in base)).toBeTruthy();

  const full = swimParams(
    { place: { lat: 47.37, lon: 8.54 }, gender: "female", age: 34 },
    "2026-07-23",
  );
  expect(full.lat).toBe("47.37");
  expect(full.lon).toBe("8.54");
  expect(full.gender).toBe("female");
  expect(full.age).toBe("34");
});

test("swimUrl encodes the params; a lone lat (no lon) is dropped", () => {
  const url = swimUrl(
    { place: { lat: 47.37, lon: null }, gender: "male" },
    "2026-07-23",
  );
  expect(url.startsWith("/swim?")).toBeTruthy();
  expect(url.includes("at=2026-07-23T12%3A00")).toBeTruthy();
  expect(url.includes("gender=male")).toBeTruthy();
  expect(!url.includes("lat=")).toBeTruthy();
});

test("poolUrl carries the at moment only when a date is given", () => {
  expect(poolUrl("hallenbad-oerlikon")).toBe("/pools/hallenbad-oerlikon");
  expect(poolUrl("a/b", "2026-07-23")).toBe(
    "/pools/a%2Fb?at=2026-07-23T12%3A00",
  );
});

// A tiny fake fetch so the thin wrappers exercise headless (no browser).
function fakeFetch(routes: Record<string, unknown>) {
  return (url: string) =>
    Promise.resolve(
      url in routes
        ? { ok: true, json: () => Promise.resolve(routes[url]) }
        : { ok: false, json: () => Promise.resolve({}) },
    );
}

test("fetchDay returns the answer; a non-ok response degrades to an empty answer", async () => {
  const filter: SwimFilter = { place: { lat: null, lon: null } };
  const url = swimUrl(filter, "2026-07-23");
  const answer = {
    options: [{ facility: "X" }],
    statuses: [],
    warnings: [],
    notices: [],
  };
  const ok = await fetchDay(filter, "2026-07-23", fakeFetch({ [url]: answer }));
  expect(ok.options).toEqual(answer.options);
  const bad = await fetchDay(filter, "2026-07-23", fakeFetch({}));
  expect(bad).toEqual({ options: [], statuses: [], warnings: [], notices: [] });
});

test("fetchWeek assembles the 7 weekday answers in Mon…Sun order", async () => {
  const filter: SwimFilter = {
    place: { lat: null, lon: null },
    selectedPool: { id: "oer", name: "Oerlikon" },
  };
  const routes: Record<string, Answer> = {};
  for (const iso of weekDates("2026-07-23")) {
    routes[swimUrl(filter, iso)] = {
      options: [{ facility: "Oerlikon", day: iso }],
      statuses: [],
      warnings: [],
      notices: [],
    };
  }
  const week = await fetchWeek(filter, "2026-07-23", fakeFetch(routes));
  expect(week.facility).toBe("Oerlikon");
  expect(week.days.length).toBe(7);
  // Labels are derived from each date via Intl (not a fixed English table), so assert
  // they match what the formatter yields for those dates in the active locale.
  expect(week.days.map((d) => d.label)).toEqual(
    weekDates("2026-07-23").map((iso) => dayParts(iso, locale()).weekday),
  );
  expect(week.days[0].iso).toBe("2026-07-20");
  expect(week.days[0].answer.options[0].day).toBe("2026-07-20");
});

test("fetchPoolDetail returns the detail or null on failure", async () => {
  const detail = { facility_id: "x", lane_panels: [] };
  const ok = await fetchPoolDetail(
    "x",
    "2026-07-23",
    fakeFetch({ [poolUrl("x", "2026-07-23")]: detail }),
  );
  expect(ok).toEqual(detail);
  const bad = await fetchPoolDetail("x", "2026-07-23", fakeFetch({}));
  expect(bad).toBe(null);
});
