// gallery.js — the dev gallery's client entrypoint. The server renders one empty
// mount per (component × state) inside a light panel and a dark panel; this walks
// those mounts and hydrates each via the registry. Loaded as a deferred ES module
// (`<script type="module">`), so the DOM is ready when it runs.
//
// Not a test file and imported by no test, so `node --test` never loads it (it is
// the only module that touches the real global `document`).

import { REGISTRY } from './registry.js';

export function hydrateGallery(root = document) {
  const mounts = root.querySelectorAll('.gallery-item[data-component]');
  mounts.forEach((mount) => {
    const name = mount.dataset.component;
    const state = mount.dataset.state || 'default';
    const entry = REGISTRY[name];
    if (!entry) return;
    const props = entry.props ? entry.props(state) : {};
    entry.create(mount, { props, onChange: () => {} });
  });
}

hydrateGallery();
