// ChipGroup — age-range selector (a row of pill chips). Same ARIA + key model as
// SegmentedControl (role=group, aria-pressed, arrow keys), different skin.

import { buildSelectGroup } from './_selectgroup.js';

/**
 * @param {import('../domtypes.js').El} el
 * @param {{props?: Record<string, unknown>, onChange?: (...args: any[]) => void}} [opts]
 * @returns {{el: import('../domtypes.js').El, buttons: import('../domtypes.js').El[], readonly value: string, setValue(v: string): void}}
 */
export function createChipGroup(el, opts = {}) {
  return buildSelectGroup(el, opts, { root: 'ui-chipgroup', opt: 'ui-chip' });
}
