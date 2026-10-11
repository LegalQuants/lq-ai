/** Small state/URL contracts shared by enhanced reading and its regression tests. */
export function guideLocation(href, { base, origin, pages }) {
  try {
    const url = new URL(href, origin);
    if (url.origin !== origin || !url.pathname.startsWith(base)) return null;
    const route = decodeURIComponent(url.pathname.slice(base.length)).replace(/\/+$/, '');
    if (!Object.hasOwn(pages, route)) return null;
    return { route, anchor: decodeURIComponent(url.hash.slice(1)), url: `${pages[route].url}${url.hash}` };
  } catch { return null; }
}

export class ReadingState {
  visits = new Map();
  save(route, { scroll = 0, expanded = [], filter = '' }) {
    this.visits.set(route, { scroll, expanded: [...expanded], filter });
  }
  restore(route) { return this.visits.get(route) ?? { scroll: 0, expanded: [], filter: '' }; }
}

export class TourState {
  constructor(length) { this.length = length; this.at = -1; this.playing = false; }
  play() { if (this.at >= this.length - 1) this.at = -1; this.playing = true; }
  pause() { this.playing = false; }
  next() { if (!this.playing) return null; this.at++; if (this.at >= this.length - 1) this.playing = false; return this.at; }
}
