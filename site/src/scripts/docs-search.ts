import { loadGuides, type GuideIndex } from './guide-index';
import type { GuideDetails } from './guide-details';
import { recallSearches, rememberSearches } from '../lib/explore-state.mjs';

interface SearchData { url: string; excerpt: string; meta: { title?: string }; sub_results?: { url: string; title: string }[] }
interface Pagefind { search(query: string): Promise<{ results: { data(): Promise<SearchData> }[] }> }

const MEMORY = 'lq-explore-searches';

/**
 * Pagefind owns matching/ranking; Iris's composer only presents its results.
 * A result's title opens the guide's own page. On wide screens a result can
 * also be selected, and the sidebar beside the conversation shows its details
 * (guide-details.ts); the first result of a new search is selected for you.
 *
 * `handedOver` is a search another page's composer sent here (`#q=…`); it runs
 * as soon as the composer is ready, like a question typed on this page.
 */
export function docsSearch(root: HTMLElement, details: GuideDetails, pauseTour: () => void, handedOver: string | null = null) {
  const base = root.dataset.base!;
  const form = root.querySelector<HTMLFormElement>('[data-lq-search-form]')!;
  const input = root.querySelector<HTMLInputElement>('input')!;
  const button = form.querySelector<HTMLButtonElement>('button')!;
  const status = root.querySelector<HTMLElement>('[data-lq-search-status]')!;
  const history = root.querySelector<HTMLElement>('[data-lq-search-history]')!;
  const queries: string[] = [];
  let engine: Promise<Pagefind> | undefined;
  let running = false;
  const focusComposer = () => {
    const menu = document.getElementById('starlight__sidebar');
    if (menu?.matches(':popover-open')) {
      const closed = (event: Event) => {
        if ((event as ToggleEvent).newState !== 'closed') return;
        menu.removeEventListener('toggle', closed);
        input.focus({ preventScroll: true });
      };
      menu.addEventListener('toggle', closed);
      menu.hidePopover();
    }
    else input.focus({ preventScroll: true });
  };
  input.disabled = button.disabled = false;
  form.hidden = false;
  input.addEventListener('focus', pauseTour);
  // ⌘K puts the cursor in the composer from anywhere on the page.
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); event.stopImmediatePropagation();
      focusComposer();
    }
  }, true);

  // The browser would restore the scroll position before the searches are
  // back, and again as the page grows; Explore puts it back itself.
  history.scrollRestoration = 'manual';
  // The result last selected or opened: where Back brings the reader.
  let anchor: { route: string; turn: number } | null = null;
  const remember = () => {
    try { sessionStorage.setItem(MEMORY, rememberSearches({ queries, selected: anchor?.route ?? null, turn: anchor?.turn ?? null, scroll: scrollY })); } catch { /* private window: nothing kept */ }
  };
  const anchorOn = (item: HTMLElement) => {
    anchor = { route: item.dataset.route!, turn: Number(item.closest<HTMLElement>('[data-turn]')!.dataset.turn) };
  };
  addEventListener('pagehide', remember);

  const search = async (query: string) => {
    engine ??= import(/* @vite-ignore */ `${base}pagefind/pagefind.js`) as Promise<Pagefind>;
    const [pagefind, index] = await Promise.all([engine, loadGuides(base)]);
    const result = await pagefind.search(query);
    return { index, data: await Promise.all(result.results.slice(0, 6).map((item) => item.data())) };
  };

  const toggleOf = (item: Element) => item.querySelector<HTMLButtonElement>('[data-lq-details-toggle]')!;
  const clearSelection = () => {
    for (const item of history.querySelectorAll<HTMLElement>('li[data-selected]')) {
      delete item.dataset.selected; toggleOf(item).setAttribute('aria-expanded', 'false');
    }
  };
  let guides: GuideIndex | undefined;
  const select = (item: HTMLElement, focus = false) => {
    const route = item.dataset.route!;
    if (!guides?.pages[route]) return;
    clearSelection();
    item.dataset.selected = '';
    toggleOf(item).setAttribute('aria-expanded', 'true');
    details.show(route, guides.pages[route], { focus, opener: toggleOf(item) });
    anchorOn(item); remember();
  };
  details.panel.addEventListener('lq-details-close', () => { clearSelection(); remember(); });
  history.addEventListener('click', (event) => {
    const target = event.target as HTMLElement;
    const item = target.closest<HTMLElement>('li[data-route]');
    if (!item) return;
    if (target.closest('a')) { anchorOn(item); remember(); return; }
    if (target.closest('[data-lq-details-toggle]')) {
      if (item.hasAttribute('data-selected')) details.close(true);
      else select(item, true);
    }
    // Clicking a result's free space selects it, as a row does in the app.
    else if (details.available && !item.hasAttribute('data-selected')) select(item);
  });

  const render = (query: string, index: GuideIndex, data: SearchData[]) => {
    const section = document.createElement('section'); section.className = 'lq-search-turn';
    section.dataset.turn = String(queries.length);
    const heading = document.createElement('h3'); heading.textContent = `Search: ${query}`; section.append(heading);
    const list = document.createElement('ul'); list.className = 'lq-search-matches';
    for (const match of data) {
      const url = new URL(match.url, location.origin);
      const route = decodeURIComponent(url.pathname.slice(base.length)).replace(/\/+$/, '');
      if (!Object.hasOwn(index.pages, route)) continue;
      const entry = index.pages[route];
      const item = document.createElement('li'); item.dataset.route = route;
      const title = document.createElement('a'); title.href = `${entry.url}${url.hash}`; title.textContent = entry.title; title.className = 'lq-match-title';
      item.append(title);
      const snippet = document.createElement('p');
      // Decode Pagefind's excerpt in an inert template; insert text only.
      const template = document.createElement('template'); template.innerHTML = match.excerpt;
      snippet.textContent = template.content.textContent;
      item.append(snippet);
      const sections = document.createElement('div'); sections.className = 'lq-match-links';
      for (const part of (match.sub_results ?? []).filter((part) => { const hash = new URL(part.url, location.origin).hash; return hash && hash !== '#_top'; }).slice(0, 2)) {
        const target = new URL(part.url, location.origin);
        const sectionLink = document.createElement('a'); sectionLink.href = `${entry.url}${target.hash}`; sectionLink.textContent = part.title;
        sections.append(sectionLink);
      }
      if (sections.children.length) item.append(sections);
      const links = document.createElement('div'); links.className = 'lq-match-links';
      const text = document.createElement('a'); text.href = entry.markdown; text.textContent = 'Markdown';
      // The same chip as the page title's StatusBadge: the word, with its
      // label for screen readers only (the chip capitalises what it shows).
      const badge = document.createElement('span');
      badge.className = /^[a-z]+$/.test(entry.status) ? `lq-status lq-status--${entry.status}` : 'lq-status';
      const label = document.createElement('span'); label.className = 'sr-only'; label.textContent = 'Page status: ';
      badge.append(label, entry.status);
      const toggle = document.createElement('button');
      toggle.type = 'button'; toggle.className = 'lq-match-details'; toggle.dataset.lqDetailsToggle = '';
      toggle.setAttribute('aria-controls', details.panel.id); toggle.setAttribute('aria-expanded', 'false');
      toggle.textContent = 'Details'; toggle.append(Object.assign(document.createElement('span'), { className: 'sr-only', textContent: ` for ${entry.title}` }));
      links.append(text, badge, toggle); item.append(links); list.append(item);
    }
    if (list.children.length) section.append(list);
    else { const empty = document.createElement('p'); empty.textContent = 'No matching guides. Try a topic such as Docker, citations, or privacy.'; section.append(empty); }
    history.append(section);
    return { section, list };
  };

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = input.value.trim().slice(0, 1000);
    if (!query || running) return;
    running = true; button.disabled = true; pauseTour();
    status.textContent = 'Searching documentation…';
    try {
      const { index, data } = await search(query);
      guides = index;
      const { section, list } = render(query, index, data);
      queries.push(query); input.value = '';
      status.textContent = `${list.children.length} matching guides for ${query}.`;
      section.scrollIntoView({ block: 'start' });
      const first = list.querySelector<HTMLElement>('li[data-route]');
      if (first && details.available) select(first);
      remember();
      input.focus({ preventScroll: true });
    } catch {
      engine = undefined;
      status.textContent = 'Search is unavailable in this preview. Browse all documentation or choose a pathway.';
    } finally { running = false; button.disabled = false; }
  });

  // This tab's earlier searches come back first, then any handed-over one
  // joins them as the newest turn.
  const restore = async () => {
    let memory = null;
    let item: HTMLElement | null = null;
    try { memory = recallSearches(sessionStorage.getItem(MEMORY) ?? ''); } catch { /* storage blocked */ }
    if (memory?.queries.length) {
      try {
        for (const query of memory.queries) {
          const { index, data } = await search(query);
          guides = index; render(query, index, data); queries.push(query);
        }
        item = memory.selected === null ? null
          : history.querySelector<HTMLElement>(`[data-turn="${memory.turn}"] li[data-route="${CSS.escape(memory.selected)}"]`);
        if (item) { anchorOn(item); if (details.available) select(item); }
      } catch { engine = undefined; }
    }
    const how = (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined)?.type;
    if (memory && !handedOver && (how === 'back_forward' || how === 'reload')) {
      if (item) item.scrollIntoView({ block: 'center' });
      else scrollTo(0, memory.scroll);
    }
    if (handedOver) { input.value = handedOver; form.requestSubmit(); }
  };
  void restore();
}
