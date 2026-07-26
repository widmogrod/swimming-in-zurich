// gallery.ts — the dev gallery's client entrypoint. The server renders one empty
// mount per (component × state) inside a light panel and a dark panel; this walks
// those mounts and hydrates each via the registry. Loaded as a deferred ES module
// (`<script type="module">`), so the DOM is ready when it runs.
//
// Not a test file and imported by no test, so the headless runner never loads it (it is
// the only module that touches the real global `document`).

import { asEl } from '../domtypes.js';
import { REGISTRY } from './registry.js';

type RegistryEntry = (typeof REGISTRY)[keyof typeof REGISTRY];

export function hydrateGallery(root: ParentNode = document): void {
  const mounts = root.querySelectorAll('.gallery-item[data-component]');
  mounts.forEach((mount) => {
    const el = asEl(mount);
    const name = el.dataset.component;
    const state = el.dataset.state || 'default';
    const entry = name
      ? (REGISTRY as Record<string, RegistryEntry | undefined>)[name]
      : undefined;
    if (!entry) return;
    const props = entry.props ? entry.props(state) : {};
    entry.create(el, { props, onChange: () => {} });
  });
}

hydrateGallery();
