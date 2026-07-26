// keynav.d.ts — types for the shared keyboard-navigation helpers (keynav.js).
//
// The implementation stays plain JS during the TypeScript migration; this declares its
// shape so the converted combobox/place-typeahead type-check at full strictness instead
// of importing `any`. Delete this file when keynav.js converts.

/** Roving-tabindex movement for a radio/toolbar group: the next index for `key`, or
 *  `null` when the key does not move focus. */
export declare function rovingIndex(
  current: number,
  length: number,
  key: string,
  opts?: { wrap?: boolean },
): number | null;

/** Listbox active-descendant movement. Returns -1 when the list is empty. */
export declare function listboxIndex(active: number, length: number, key: string): number;

/** Filter options by a free-text query. Falls back to a case-insensitive `label` match
 *  when no custom predicate is supplied. Generic so the caller keeps its option type. */
export declare function filterOptions<T extends { label?: unknown }>(
  options: T[],
  query: string,
  filterFn?: (option: T, query: string) => boolean,
): T[];
