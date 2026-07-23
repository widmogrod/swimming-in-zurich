// SegmentedControl — view-mode / gender selector. role=group of aria-pressed
// buttons, arrow-key roving. `variant: 'mode'` paints the selected option in the
// accent (the .modeseg look). Thin skin over the shared select-group.

import { buildSelectGroup } from './_selectgroup.js';

export function createSegmentedControl(el, opts = {}) {
  if (opts.props && opts.props.variant === 'mode') el.classList.add('ui-seg--mode');
  return buildSelectGroup(el, opts, { root: 'ui-seg', opt: 'ui-seg__opt' });
}
