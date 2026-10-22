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

/**
 * One search, one place for its results. The composer on every page other
 * than Explore hands its question to Explore in the URL fragment, which a
 * browser never sends to the server — no host sees what a reader searched
 * for. Explore reads it back, runs the search and drops the fragment.
 */
const SEARCH_PREFIX = '#q=';
const MAX_QUERY = 1000;

export function exploreSearchHref(base, query) {
  const text = String(query ?? '').trim().slice(0, MAX_QUERY);
  return text ? `${base}${SEARCH_PREFIX}${encodeURIComponent(text)}` : base;
}

export function searchFromHash(hash) {
  const value = String(hash ?? '');
  if (!value.startsWith(SEARCH_PREFIX)) return null;
  try {
    const text = decodeURIComponent(value.slice(SEARCH_PREFIX.length)).trim().slice(0, MAX_QUERY);
    return text || null;
  } catch {
    return null;
  }
}

export class ReadingState {
  visits = new Map();
  save(route, { scroll = 0, expanded = [] }) {
    this.visits.set(route, { scroll, expanded: [...expanded] });
  }
  restore(route) { return this.visits.get(route) ?? { scroll: 0, expanded: [] }; }
}

export class TourState {
  constructor(length) { this.length = length; this.at = -1; this.playing = false; }
  play() { if (this.at >= this.length - 1) this.at = -1; this.playing = true; }
  pause() { this.playing = false; }
  next() { if (!this.playing) return null; this.at++; if (this.at >= this.length - 1) this.playing = false; return this.at; }
}
