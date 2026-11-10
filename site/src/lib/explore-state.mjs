/** Small state/URL contracts shared by Explore's scripts and their regression tests. */

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

/**
 * Explore's conversation outlives a visit to a guide. A result's title opens
 * the guide page itself, so Back (or a reload) has to bring the searches back:
 * their questions, the result last selected or opened (its route and which
 * search it was in) and the scroll position are kept in this tab's
 * sessionStorage, never sent anywhere, and the searches run again. Back
 * returns to that result rather than to a pixel offset, which images loading
 * above it would move. `recallSearches` accepts only what `rememberSearches`
 * could have written.
 */
const MAX_SEARCHES = 20;

export function rememberSearches({ queries = [], selected = null, turn = null, scroll = 0 }) {
  return JSON.stringify(recallSearches(JSON.stringify({ queries, selected, turn, scroll })));
}

export function recallSearches(raw) {
  let value;
  try { value = JSON.parse(raw); } catch { return null; }
  if (!value || typeof value !== 'object' || !Array.isArray(value.queries)) return null;
  const all = value.queries.filter((query) => typeof query === 'string')
    .map((query) => query.trim().slice(0, MAX_QUERY)).filter(Boolean);
  const queries = all.slice(-MAX_SEARCHES);
  const dropped = all.length - queries.length;
  let selected = typeof value.selected === 'string' && value.selected.length <= 300 ? value.selected : null;
  let turn = Number.isInteger(value.turn) ? value.turn - dropped : null;
  if (selected === null || turn === null || turn < 0 || turn >= queries.length) selected = turn = null;
  const scroll = Number.isFinite(value.scroll) && value.scroll > 0 ? Math.round(value.scroll) : 0;
  return { queries, selected, turn, scroll };
}

export class TourState {
  constructor(length) { this.length = length; this.at = -1; this.playing = false; }
  play() { if (this.at >= this.length - 1) this.at = -1; this.playing = true; }
  pause() { this.playing = false; }
  next() { if (!this.playing) return null; this.at++; if (this.at >= this.length - 1) this.playing = false; return this.at; }
}
