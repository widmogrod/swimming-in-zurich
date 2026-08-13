// rowkey.ts — the ONE definition of a board row's identity string.
//
// A row is a facility + a basin, and every surface that has to recognise the same row
// again (the board's `dayRows` grouping map, the phone list's open-card state, `app.ts`'s
// row→panel join) must spell that pair the same way. This lived in two places once —
// `board.ts` built the grouping key and `poolrank.ts` re-derived the identical format for
// the card state — and because those two strings never met, a divergence between them
// would have been SILENT: two different keys for one row, each self-consistent.
//
// It is a leaf on purpose. `board.ts` is a DOM/canvas block and `poolrank.ts` is
// deliberately pure (no DOM, no canvas), so neither may import the other; the shared fact
// lives below both instead.

/** The row key's separator. NUL rather than a space: a space would let
 *  `facility="A B" + basin="C"` collide with `facility="A" + basin="B C"`, and a collided
 *  row is a silently mis-rendered one. */
const ROW_KEY_SEP = '\u0000';

/**
 * rowKeyFor(facility, basinId) — the stable identity of the row about `basinId` of
 * `facility`. A row about no particular basin (a status-only row, a Pool-mode day row)
 * keys on the empty basin, which is a real, distinct row — not a missing one.
 *
 * NEVER the row's LABEL: under rule L1 a pool's label gains a `· <basin>` suffix only
 * while that pool contributes options from more than one basin in this answer, so the
 * label of the very pools this exists for changes between days (invariant I6).
 */
export function rowKeyFor(facility: string, basinId: string | undefined): string {
  return `${facility}${ROW_KEY_SEP}${basinId ?? ''}`;
}
