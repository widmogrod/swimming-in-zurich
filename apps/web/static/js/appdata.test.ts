import { expect, test } from "vitest";
import type { Answer, SwimOption, SwimStatus, Week } from "./api.js";
import {
  applyLap,
  applyLapWeek,
  classifyPools,
  focusWeekOnPool,
  isStructuralUrlChange,
  rowFacilityName,
  type PoolMeta,
} from "./appdata.js";

const opt = (
  facility: string,
  extra: Partial<SwimOption> = {},
): SwimOption => ({
  facility,
  access: "PublicSwim",
  ...extra,
});

const answer = (
  options: SwimOption[] = [],
  statuses: SwimStatus[] = [],
): Answer => ({
  options,
  statuses,
  warnings: [],
  notices: [],
});

const week = (days: { iso: string; answer: Answer }[]): Week => ({
  facility: null,
  days: days.map((d) => ({ label: d.iso, iso: d.iso, answer: d.answer })),
});

// ---- focusWeekOnPool -----------------------------------------------------------------

test("focusWeekOnPool keeps only the selected pool's rows", () => {
  const w = week([
    {
      iso: "2026-07-20",
      answer: answer(
        [opt("Hallenbad Oerlikon"), opt("Hallenbad City")],
        [
          {
            facility: "Hallenbad City",
            status: "closed",
            detail: "Sommerpause",
          },
        ],
      ),
    },
  ]);
  const focused = focusWeekOnPool(w, "Hallenbad Oerlikon");
  expect(focused.facility).toBe("Hallenbad Oerlikon");
  expect(focused.days[0].answer.options.map((o) => o.facility)).toEqual([
    "Hallenbad Oerlikon",
  ]);
  expect(focused.days[0].answer.statuses).toEqual([]);
});

test("focusWeekOnPool keeps an unplannable pool's honest status rows", () => {
  // The pool has NO options, only a closed status. Focusing must leave that status
  // standing (the board draws a closed row) rather than emptying the week — an empty
  // week would read as "nothing known", which is a different claim.
  const w = week([
    {
      iso: "2026-07-20",
      answer: answer(
        [opt("Hallenbad City")],
        [
          {
            facility: "Hallenbad Oerlikon",
            status: "closed",
            detail: "Revision",
          },
        ],
      ),
    },
  ]);
  const focused = focusWeekOnPool(w, "Hallenbad Oerlikon");
  expect(focused.days[0].answer.options).toEqual([]);
  expect(focused.days[0].answer.statuses).toEqual([
    { facility: "Hallenbad Oerlikon", status: "closed", detail: "Revision" },
  ]);
});

test("focusWeekOnPool is a no-op without a pool, and never mutates its input", () => {
  const w = week([{ iso: "2026-07-20", answer: answer([opt("A"), opt("B")]) }]);
  expect(focusWeekOnPool(w, null)).toBe(w);
  focusWeekOnPool(w, "A");
  expect(w.days[0].answer.options).toHaveLength(2); // original untouched
});

// ---- applyLap ------------------------------------------------------------------------

test("applyLap keeps only lap-swimmable access types", () => {
  const a = answer([
    opt("A", { access: "LaneSwim" }),
    opt("B", { access: "PublicSwim" }),
    opt("C", { access: "WomenOnly" }),
    opt("D", { access: "SchoolReserved" }),
  ]);
  expect(applyLap(a, true).options.map((o) => o.facility)).toEqual(["A", "B"]);
});

test("applyLap is a no-op when the toggle is off", () => {
  const a = answer([opt("A", { access: "WomenOnly" })]);
  expect(applyLap(a, false)).toBe(a);
});

test("applyLap leaves an empty day empty rather than inventing a session", () => {
  // An honest "no lap swim here" — the row renders empty, it does not fall back to
  // showing non-lap sessions as if they were lap sessions.
  const a = answer([opt("A", { access: "SchoolReserved" })]);
  expect(applyLap(a, true).options).toEqual([]);
});

test("applyLapWeek filters every day of the week", () => {
  const w = week([
    { iso: "2026-07-20", answer: answer([opt("A", { access: "LaneSwim" })]) },
    {
      iso: "2026-07-21",
      answer: answer([opt("A", { access: "ClubReserved" })]),
    },
  ]);
  const out = applyLapWeek(w, true);
  expect(out.days[0].answer.options).toHaveLength(1);
  expect(out.days[1].answer.options).toHaveLength(0);
  expect(applyLapWeek(w, false)).toBe(w);
});

// ---- classifyPools -------------------------------------------------------------------

const meta = (pool_id: string, name: string): PoolMeta => ({ pool_id, name });

test("classifyPools ranks plannable pools first, nearest first", () => {
  const pools = [
    meta("far", "Far"),
    meta("near", "Near"),
    meta("shut", "Shut"),
  ];
  const day = answer(
    [opt("Far", { distance_km: 4 }), opt("Near", { distance_km: 1 })],
    [{ facility: "Shut", status: "closed", detail: "Sommerpause" }],
  );
  const out = classifyPools(pools, day);
  expect(out.map((o) => o.label)).toEqual(["Near", "Far", "Shut"]);
  expect(out[0].distanceKm).toBe(1);
});

test("classifyPools NEVER labels an uncurated pool as closed (unknown ≠ closed)", () => {
  // The honesty invariant: a pool we simply have no timetable for must not be presented
  // as shut. It gets its own state and its own note.
  const out = classifyPools([meta("x", "Uncurated")], answer());
  expect(out[0].state).toBe("unknown");
  expect(out[0].note).toBe("no timetable yet");
  expect(out[0].closed).toBeUndefined();
});

test("classifyPools marks a genuinely closed pool closed, with no note", () => {
  const day = answer(
    [],
    [{ facility: "Shut", status: "closed", detail: "Revision" }],
  );
  const out = classifyPools([meta("shut", "Shut")], day);
  expect(out[0].state).toBe("closed");
  expect(out[0].closed).toBe(true);
  expect(out[0].note).toBeUndefined();
});

test("classifyPools keeps the NEAREST distance when a pool has several options", () => {
  const day = answer([
    opt("Pool", { distance_km: 3 }),
    opt("Pool", { distance_km: 1.2 }),
    opt("Pool", { distance_km: 2 }),
  ]);
  expect(classifyPools([meta("p", "Pool")], day)[0].distanceKm).toBe(1.2);
});

test("classifyPools tolerates an option with no distance at all", () => {
  const day = answer([opt("Pool")]);
  const out = classifyPools([meta("p", "Pool")], day);
  expect(out[0].state).toBe("plannable"); // has sessions → plannable even without a distance
  expect(out[0].distanceKm).toBeNull();
});

test("classifyPools sorts equal-rank pools alphabetically", () => {
  const out = classifyPools([meta("b", "Bravo"), meta("a", "Alpha")], answer());
  expect(out.map((o) => o.label)).toEqual(["Alpha", "Bravo"]);
});

// ---- isStructuralUrlChange -----------------------------------------------------------

test("a view switch is structural (Back must return to the previous view)", () => {
  expect(isStructuralUrlChange({ mode: "day" }, { mode: "pool" })).toBe(true);
});

test("a pool switch is structural", () => {
  expect(
    isStructuralUrlChange(
      { mode: "day", selectedPool: { id: "a" } },
      { mode: "day", selectedPool: { id: "b" } },
    ),
  ).toBe(true);
});

test("selecting a pool from none, and clearing it, are both structural", () => {
  expect(
    isStructuralUrlChange(
      { mode: "day" },
      { mode: "day", selectedPool: { id: "a" } },
    ),
  ).toBe(true);
  expect(
    isStructuralUrlChange(
      { mode: "day", selectedPool: { id: "a" } },
      { mode: "day" },
    ),
  ).toBe(true);
});

test("a plain filter toggle is NOT structural (no history spam)", () => {
  const same = { mode: "day", selectedPool: { id: "a" } };
  expect(isStructuralUrlChange(same, { ...same })).toBe(false);
});

test("an absent mode is treated as day, not as a distinct view", () => {
  expect(isStructuralUrlChange({}, { mode: "day" })).toBe(false);
});

// --- rowFacilityName: the ONE row→pool identity both views' panels are built from ------

test("a Day-view row IS a pool, so the row label names the facility", () => {
  expect(rowFacilityName("day", "Hallenbad City", null)).toBe("Hallenbad City");
  // even when another pool happens to be selected — the CLICKED row wins in Day view
  expect(rowFacilityName("day", "Hallenbad City", "Hallenbad Oerlikon")).toBe(
    "Hallenbad City",
  );
});

test("a Pool-view row is a DAY, so the facility is the selection, not the label", () => {
  expect(rowFacilityName("pool", "Mon · 20 Jul", "Hallenbad City")).toBe(
    "Hallenbad City",
  );
});

test("a URL-restored pool takes its name from the ROW, never from a weekday label", () => {
  // `?view=pool&pool=<id>` arrives with an id and no name; /pools backfills the name only
  // AFTER the first render's auto-open. Before this, the weekday label was written into
  // `selectedPool.name` — and since backfillPoolName skips a filter that already has a
  // name, the weekday stuck and every later render filtered the week down to nothing.
  expect(
    rowFacilityName("pool", "pon. \u00b7 3 sie", null, "Hallenbad Altstetten"),
  ).toBe("Hallenbad Altstetten");
  // An explicit selection still wins over the row's facility.
  expect(
    rowFacilityName(
      "pool",
      "pon. \u00b7 3 sie",
      "Hallenbad City",
      "Hallenbad Altstetten",
    ),
  ).toBe("Hallenbad City");
});

test("Pool view with no selection falls back to the row label, never null", () => {
  expect(rowFacilityName("pool", "Hallenbad City", null)).toBe(
    "Hallenbad City",
  );
  expect(rowFacilityName(undefined, "Hallenbad City", null)).toBe(
    "Hallenbad City",
  );
});
