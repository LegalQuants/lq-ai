import { TourState } from '../lib/explore-state.mjs';

/** All answers exist in static HTML. Opt-in playback highlights, never deletes them. */
export function tourPlayback(root: HTMLElement) {
  const steps = [...root.querySelectorAll<HTMLElement>('[data-lq-tour-step]')];
  const button = root.querySelector<HTMLButtonElement>('[data-lq-tour-play]')!;
  const label = root.querySelector<HTMLElement>('[data-lq-tour-status]')!;
  const state = new TourState(steps.length);
  let timer: ReturnType<typeof setTimeout> | undefined;
  button.hidden = false;
  // Each step carries its own place ("Introduction 2 of 4") above its
  // question, so it scrolls with it; shown once the tour has started. The
  // status line announces the same to screen readers, so these are hidden
  // from them.
  steps.forEach((step, index) => {
    const place = document.createElement('p');
    place.className = 'lq-tour-place';
    place.setAttribute('aria-hidden', 'true');
    place.textContent = `Introduction ${index + 1} of ${steps.length}`;
    step.prepend(place);
  });
  const sync = () => {
    button.setAttribute('aria-pressed', String(state.playing));
    button.textContent = state.playing ? 'Pause introduction' : state.at >= steps.length - 1 ? 'Replay introduction' : state.at >= 0 ? 'Resume introduction' : 'Play introduction';
  };
  const pause = () => { clearTimeout(timer); state.pause(); sync(); };
  const advance = () => {
    const at = state.next();
    if (at === null) return;
    root.toggleAttribute('data-tour-started', true);
    steps.forEach((step, index) => step.toggleAttribute('data-tour-active', at === index));
    const title = steps[at].querySelector('h2')!.textContent;
    label.textContent = `Introduction ${at + 1} of ${steps.length}: ${title}`;
    steps[at].scrollIntoView({ block: 'start', behavior: document.documentElement.dataset.motion === 'reduced' || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
    sync();
    if (state.playing) timer = setTimeout(advance, 8000);
  };
  button.addEventListener('click', () => { if (state.playing) pause(); else { state.play(); advance(); } });
  matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', pause);
  return pause;
}
