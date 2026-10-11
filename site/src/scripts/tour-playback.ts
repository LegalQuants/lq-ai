import { TourState } from '../lib/explore-state.mjs';

/** All answers exist in static HTML. Opt-in playback highlights, never deletes them. */
export function tourPlayback(root: HTMLElement) {
  const steps = [...root.querySelectorAll<HTMLElement>('[data-lq-tour-step]')];
  const button = root.querySelector<HTMLButtonElement>('[data-lq-tour-play]')!;
  const label = root.querySelector<HTMLElement>('[data-lq-tour-status]')!;
  const state = new TourState(steps.length);
  let timer: ReturnType<typeof setTimeout> | undefined;
  button.hidden = false;
  const sync = () => {
    button.setAttribute('aria-pressed', String(state.playing));
    button.textContent = state.playing ? 'Pause introduction' : state.at >= steps.length - 1 ? 'Replay introduction' : state.at >= 0 ? 'Resume introduction' : 'Play introduction';
  };
  const pause = () => { clearTimeout(timer); state.pause(); sync(); };
  const advance = () => {
    const at = state.next();
    if (at === null) return;
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
