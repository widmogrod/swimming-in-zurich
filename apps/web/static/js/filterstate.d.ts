// filterstate.d.ts — types for the one immutable filter context (filterstate.js).
//
// The implementation stays plain JS during the TypeScript migration; this declares its
// shape so the converted `.ts` blocks that consume it (app, toolbar, board) type-check at
// full strictness instead of importing `any` — which is what the `no-unsafe-*` lint rules
// exist to catch. Delete this file when filterstate.js itself converts.

export interface FilterPlace {
  lat: number | null;
  lon: number | null;
  label: string;
}

/** The currently-selected pool, shared by Day and Pool views. */
export interface FilterPool {
  id: string | null;
  name: string | null;
}

/** The whole global query surface every block reads. */
export interface FilterState {
  place: FilterPlace;
  /** ISO date (YYYY-MM-DD) — Day mode. */
  date: string | null;
  /** ISO Monday (YYYY-MM-DD) — Pool/week mode. */
  week: string | null;
  gender: "" | "female" | "male" | "diverse";
  age: number | null;
  mode: "day" | "pool";
  selectedPool: FilterPool | null;
  lapOnly: boolean;
  eligibleOnly: boolean;
}

/** A partial update. `place` is merged shallowly; every other key is overwritten. */
export type FilterPatch = Partial<Omit<FilterState, "place">> & {
  place?: Partial<FilterPlace>;
};

export declare const DEFAULT_FILTER: Readonly<FilterState>;

/** Returns a NEW state with `patch` applied; neither argument is mutated. */
export declare function merge(
  state: FilterState,
  patch?: FilterPatch,
): FilterState;

/** Build a state from partial input, filling gaps from DEFAULT_FILTER. */
export declare function createFilterState(init?: FilterPatch): FilterState;

export declare function serialize(state: FilterState): string;

export declare function deserialize(text: string): FilterState;
