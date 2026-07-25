import { describe, expect, it } from "vitest";

import {
  fromParams,
  fromSearch,
  toParams,
  toSearch,
  type FilterPatch,
  type UrlFilterState,
  type UrlStateContext,
} from "./urlstate.js";

// The receiver context: a fixed today + the age value⇆token vocabulary (mirrors the
// toolbar's DEFAULT_AGE_CHIPS: Child 8 / Teen 16 / Adult 34 / Senior 70).
const TODAY = "2026-07-24";
const CTX: UrlStateContext = {
  today: TODAY,
  ageTokens: [
    { value: 8, token: "child" },
    { value: 16, token: "teen" },
    { value: 34, token: "adult" },
    { value: 70, token: "senior" },
  ],
};

// A fully-defaulted Day/today state — what app.js seeds on load. `urlstate` reads only
// this slice of FilterState, so the test builds it directly (typed, no `any` boundary).
function seed(overrides: Partial<UrlFilterState> = {}): UrlFilterState {
  return {
    mode: "day",
    date: TODAY,
    gender: "",
    age: null,
    lapOnly: false,
    eligibleOnly: false,
    selectedPool: null,
    ...overrides,
  };
}

// A round-trip helper: encode a state, decode the string, and apply the patch back over
// a fresh Day/today seed (exactly what app.js does on load).
function roundTrip(state: UrlFilterState): UrlFilterState {
  const patch: FilterPatch = fromSearch(toSearch(state, CTX), CTX);
  return { ...seed(), ...patch };
}

describe("toParams / toSearch", () => {
  it("projects the default view to EMPTY params (bare /)", () => {
    const def = seed();
    expect(toParams(def, CTX).toString()).toBe("");
    expect(toSearch(def, CTX)).toBe("");
  });

  it("round-trips a fully-loaded pool state (pool + filters)", () => {
    const s = seed({
      mode: "pool",
      date: "2026-08-03", // a Monday
      gender: "female",
      age: 34,
      lapOnly: true,
      eligibleOnly: true,
      selectedPool: { id: "hallenbad-oerlikon", name: "Hallenbad Oerlikon" },
    });
    // Fixed order: view, date, who, age, lap, elig, pool.
    expect(toSearch(s, CTX)).toBe(
      "?view=pool&date=2026-08-03&who=female&age=adult&lap=1&elig=1&pool=hallenbad-oerlikon",
    );
    const back = roundTrip(s);
    expect(back.mode).toBe("pool");
    expect(back.date).toBe("2026-08-03");
    expect(back.gender).toBe("female");
    expect(back.age).toBe(34);
    expect(back.lapOnly).toBe(true);
    expect(back.eligibleOnly).toBe(true);
    // pool comes back as {id, name:null} — the label is backfilled later from /pools.
    expect(back.selectedPool).toEqual({ id: "hallenbad-oerlikon", name: null });
  });

  it("normalizes a Pool-mode date to that week's Monday before writing", () => {
    const wed = seed({
      mode: "pool",
      date: "2026-08-05", // a Wednesday
      selectedPool: { id: "city", name: "Hallenbad City" },
    });
    expect(toParams(wed, CTX).get("date")).toBe("2026-08-03"); // → the Monday
    expect(roundTrip(wed).date).toBe("2026-08-03");
  });

  it("omits a Day-mode date equal to today, writes a future date", () => {
    const todayState = seed({ mode: "day", date: TODAY });
    expect(toParams(todayState, CTX).has("date")).toBe(false);

    const future = seed({ mode: "day", date: "2026-08-01" });
    expect(toParams(future, CTX).get("date")).toBe("2026-08-01");
    expect(roundTrip(future).date).toBe("2026-08-01");
  });

  it("encodes age as a token, with a numeric fallback for off-chip ages", () => {
    const senior = seed({ age: 70 });
    expect(toParams(senior, CTX).get("age")).toBe("senior");

    const odd = seed({ age: 50 }); // no chip → numeric fallback
    expect(toParams(odd, CTX).get("age")).toBe("50");
    expect(roundTrip(odd).age).toBe(50);
  });
});

describe("fromParams / fromSearch", () => {
  it("is TOTAL & tolerant — garbage/unknown params are dropped, never throws", () => {
    const patch = fromParams(
      new URLSearchParams(
        "view=weird&date=not-a-date&who=alien&age=nope&lap=yes&elig=0&pool=&junk=1",
      ),
      CTX,
    );
    expect(patch).toEqual({}); // every param invalid → empty patch
  });

  it("drops an out-of-range date (before today / beyond +60d) and an impossible date", () => {
    expect(
      fromParams(new URLSearchParams("date=2026-07-23"), CTX).date,
    ).toBeUndefined(); // yesterday
    expect(
      fromParams(new URLSearchParams("date=2026-12-01"), CTX).date,
    ).toBeUndefined(); // > +60d
    expect(
      fromParams(new URLSearchParams("date=2026-02-31"), CTX).date,
    ).toBeUndefined(); // impossible
    expect(fromParams(new URLSearchParams("date=2026-08-10"), CTX).date).toBe(
      "2026-08-10",
    ); // in range
  });

  it("recognizes only `view=pool`; a bare pool param yields {id, name:null}", () => {
    expect(fromParams(new URLSearchParams("view=pool"), CTX).mode).toBe("pool");
    expect(
      fromParams(new URLSearchParams("view=day"), CTX).mode,
    ).toBeUndefined();
    expect(
      fromParams(new URLSearchParams("pool=seebad-enge"), CTX).selectedPool,
    ).toEqual({
      id: "seebad-enge",
      name: null,
    });
  });

  it("accepts a known age token OR a numeric string, dropping unknown tokens", () => {
    expect(fromParams(new URLSearchParams("age=teen"), CTX).age).toBe(16);
    expect(fromParams(new URLSearchParams("age=42"), CTX).age).toBe(42);
    expect(
      fromParams(new URLSearchParams("age=grandparent"), CTX).age,
    ).toBeUndefined();
  });

  it("turns lap/elig on only for the literal `1`", () => {
    expect(fromParams(new URLSearchParams("lap=1&elig=1"), CTX).lapOnly).toBe(
      true,
    );
    expect(
      fromParams(new URLSearchParams("lap=1&elig=1"), CTX).eligibleOnly,
    ).toBe(true);
    expect(
      fromParams(new URLSearchParams("lap=true"), CTX).lapOnly,
    ).toBeUndefined();
    expect(
      fromParams(new URLSearchParams("elig=0"), CTX).eligibleOnly,
    ).toBeUndefined();
  });

  it("accepts a leading `?` and an empty string in fromSearch", () => {
    expect(fromSearch("", CTX)).toEqual({});
    expect(fromSearch("?who=male", CTX).gender).toBe("male");
  });
});
