// Toggle — a native-checkbox switch (lap-only, or a disabled busyness toggle
// carrying its reason). Uses the ARIA switch pattern over a real <input> so it
// stays keyboard- and screen-reader-native; a disabled toggle exposes
// aria-disabled + its reason as title/aria-description and refuses change.

export function createToggle(el, { props = {}, onChange } = {}) {
  const doc = el.ownerDocument || globalThis.document;
  const disabled = !!props.disabled;
  let checked = !!props.checked;

  el.classList.add('ui-toggle');

  const input = doc.createElement('input');
  input.setAttribute('type', 'checkbox');
  input.type = 'checkbox';
  input.checked = checked;
  input.setAttribute('role', 'switch');
  input.setAttribute('aria-checked', String(checked));
  if (props.label) input.setAttribute('aria-label', props.label);

  const track = doc.createElement('span');
  track.classList.add('ui-toggle__track');
  track.setAttribute('aria-hidden', 'true');

  const label = doc.createElement('span');
  label.classList.add('ui-toggle__label');
  label.textContent = props.label || '';

  if (disabled) {
    input.disabled = true;
    input.setAttribute('aria-disabled', 'true');
    el.classList.add('is-disabled');
    if (props.reason) {
      el.setAttribute('title', props.reason);
      input.setAttribute('aria-description', props.reason);
    }
  }

  input.addEventListener('change', () => {
    if (disabled) {
      input.checked = checked; // refuse; restore
      return;
    }
    checked = !!input.checked;
    input.setAttribute('aria-checked', String(checked));
    el.classList.toggle('is-on', checked);
    if (onChange) onChange(checked);
  });

  el.appendChild(input);
  el.appendChild(track);
  el.appendChild(label);
  el.classList.toggle('is-on', checked);

  return {
    el,
    input,
    get checked() {
      return checked;
    },
  };
}
