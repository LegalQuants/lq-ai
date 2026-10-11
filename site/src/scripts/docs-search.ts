import type { GuideReader } from './guide-reader';

interface SearchData { url: string; excerpt: string; meta: { title?: string }; sub_results?: { url: string; title: string }[] }
interface Pagefind { search(query: string): Promise<{ results: { data(): Promise<SearchData> }[] }> }

/** Pagefind owns matching/ranking; Iris's composer only presents its results. */
export function docsSearch(root: HTMLElement, reader: GuideReader, pauseTour: () => void) {
  const form = root.querySelector<HTMLFormElement>('[data-lq-search-form]')!;
  const input = root.querySelector<HTMLInputElement>('input')!;
  const button = form.querySelector<HTMLButtonElement>('button')!;
  const status = root.querySelector<HTMLElement>('[data-lq-search-status]')!;
  const history = root.querySelector<HTMLElement>('[data-lq-search-history]')!;
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
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault(); event.stopImmediatePropagation();
      if (document.querySelector<HTMLDialogElement>('[data-lq-reader]')?.open) reader.close();
      focusComposer();
    }
  }, true);
  document.querySelector('.lq-explore-search')?.addEventListener('click', (event) => { event.preventDefault(); focusComposer(); });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const query = input.value.trim().slice(0, 1000);
    if (!query || running) return;
    running = true; button.disabled = true; pauseTour();
    status.textContent = 'Searching documentation…';
    try {
      engine ??= import(/* @vite-ignore */ `${reader.base}pagefind/pagefind.js`) as Promise<Pagefind>;
      const [pagefind, index] = await Promise.all([engine, reader.index()]);
      const result = await pagefind.search(query);
      const data = await Promise.all(result.results.slice(0, 6).map((item) => item.data()));
      const section = document.createElement('section'); section.className = 'lq-search-turn';
      const heading = document.createElement('h3'); heading.textContent = `Search: ${query}`; section.append(heading);
      const list = document.createElement('ul'); list.className = 'lq-search-matches';
      for (const match of data) {
        const url = new URL(match.url, location.origin);
        const route = decodeURIComponent(url.pathname.slice(reader.base.length)).replace(/\/+$/, '');
        if (!Object.hasOwn(index.pages, route)) continue;
        const entry = index.pages[route];
        const item = document.createElement('li');
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
        const full = document.createElement('a'); full.href = title.href; full.textContent = 'Open full guide'; full.dataset.noReader = '';
        const text = document.createElement('a'); text.href = entry.markdown; text.textContent = 'Markdown'; text.dataset.noReader = '';
        const badge = document.createElement('span'); badge.className = 'lq-status'; badge.textContent = `Page status: ${entry.status}`;
        links.append(full, text, badge); item.append(links); list.append(item);
      }
      if (list.children.length) section.append(list);
      else { const empty = document.createElement('p'); empty.textContent = 'No matching guides. Try a topic such as Docker, citations, or privacy.'; section.append(empty); }
      history.append(section); input.value = '';
      status.textContent = `${list.children.length} matching guides for ${query}.`;
      section.scrollIntoView({ block: 'start' });
      input.focus({ preventScroll: true });
    } catch {
      engine = undefined;
      status.textContent = 'Search is unavailable in this preview. Browse all documentation or choose a pathway.';
    } finally { running = false; button.disabled = false; }
  });
}
