import { guideLocation, ReadingState } from '../lib/explore-state.mjs';

export interface GuideEntry {
  title: string; url: string; asset: string; markdown: string;
  status: string; kind: string; pathway: string | null; tone: string;
}
export interface GuideIndex { schemaVersion: number; base: string; pages: Record<string, GuideEntry> }
interface Payload {
  schemaVersion: number; title: string; html: string; metadataHtml: string;
  sourceHtml: string; styles: string[]; anchors: Record<string, string>;
}

/** No captured corpus: one small registry, then one current article per visit. */
export class GuideReader {
  private indexPromise?: Promise<GuideIndex>;
  private cache = new Map<string, Promise<Payload>>();
  private states = new ReadingState();
  private current: string | null = null;
  private anchors: Record<string, string> = {};
  private request = 0;
  private opener?: HTMLElement;
  private wide = matchMedia('(min-width: 78rem)');
  private rootUrl = location.href;
  private rootTitle = document.title;
  private scroll: HTMLElement;
  private body: HTMLElement;
  private status: HTMLElement;

  constructor(private dialog: HTMLDialogElement, readonly base: string) {
    this.scroll = dialog.querySelector('[data-lq-reader-scroll]')!;
    this.body = dialog.querySelector('[data-lq-reader-body]')!;
    this.status = dialog.querySelector('[data-lq-reader-status]')!;
    history.scrollRestoration = 'manual';
    history.replaceState({ ...history.state, lqExplore: true }, '', this.rootUrl);
    dialog.querySelector('[data-lq-reader-close]')!.addEventListener('click', () => this.close());
    dialog.addEventListener('cancel', (event) => { event.preventDefault(); this.close(); });
    this.wide.addEventListener('change', () => { if (dialog.open) this.show(); });
    window.addEventListener('resize', () => this.pictures());
    window.addEventListener('popstate', (event) => {
      if (event.state?.lqReader) void this.open(event.state.lqReader, undefined, false);
      else this.close(false);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && dialog.open && !dialog.matches(':modal')) this.close();
    });
    document.addEventListener('click', (event) => {
      const target = event.target as HTMLElement;
      const link = target.closest<HTMLAnchorElement>('a[href]');
      if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.target || link.hasAttribute('download') || link.hasAttribute('data-no-reader')) return;
      const url = new URL(link.href);
      if (url.origin === location.origin && url.pathname === base && !url.hash) {
        event.preventDefault(); this.close(this.dialog.open); return;
      }
      if (url.origin !== location.origin || !url.pathname.startsWith(base) || !url.pathname.endsWith('/')) return;
      event.preventDefault();
      void this.open(url.href, link);
    });
    this.body.addEventListener('click', (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-lq-copy]');
      if (button) void this.copyCode(button);
    });
  }

  async index(): Promise<GuideIndex> {
    this.indexPromise ??= fetch(`${this.base}_reader/index.json`).then(async (response) => {
      if (!response.ok) throw new Error('Guide registry unavailable');
      const index = await response.json();
      if (index.schemaVersion !== 1 || index.base !== this.base) throw new Error('Guide registry does not match this build');
      return index;
    }).catch((error) => { this.indexPromise = undefined; throw error; });
    return this.indexPromise;
  }

  private save() {
    if (this.current && this.dialog.open) this.states.save(this.current, { scroll: this.scroll.scrollTop,
      expanded: [...this.body.querySelectorAll('details')].map((details) => details.open) });
  }

  private show() {
    const menu = document.getElementById('starlight__sidebar');
    if (menu?.matches(':popover-open')) menu.hidePopover();
    const modal = !this.wide.matches;
    const top = this.scroll.scrollTop;
    if (this.dialog.open && this.dialog.matches(':modal') !== modal) this.dialog.close();
    if (!this.dialog.open) modal ? this.dialog.showModal() : this.dialog.show();
    document.body.classList.toggle('lq-reader-wide', !modal);
    this.scroll.scrollTop = top;
    this.pictures();
  }

  private pictures() {
    for (const source of document.querySelectorAll<HTMLSourceElement>('[data-lq-explore] .lq-diagram source[media]')) {
      const width = source.closest<HTMLElement>('.lq-diagram')!.getBoundingClientRect().width;
      source.dataset.originalMedia ??= source.media;
      source.media = width <= 600 ? 'all' : source.dataset.originalMedia;
    }
  }

  async open(href: string, opener?: HTMLElement, push = true) {
    const ticket = ++this.request;
    try {
      const index = await this.index();
      // Closing or choosing another guide can cancel the initial registry fetch.
      if (ticket !== this.request) return;
      const target = guideLocation(href, { base: this.base, origin: location.origin, pages: index.pages });
      if (!target) { location.assign(href); return; }
      const entry = index.pages[target.route];
      this.save();
      if (opener && !this.dialog.contains(opener)) this.opener = opener;
      if (this.current !== target.route) { this.body.replaceChildren(); this.current = null; }
      this.show();
      this.status.textContent = 'Loading documentation…';
      if (!this.cache.has(target.route)) this.cache.set(target.route, fetch(entry.asset).then(async (response) => {
        if (!response.ok) throw new Error('Guide unavailable');
        const payload = await response.json();
        if (payload.schemaVersion !== 1) throw new Error('Unsupported guide asset');
        return payload;
      }).catch((error) => { this.cache.delete(target.route); throw error; }));
      const payload = await this.cache.get(target.route)!;
      if (ticket !== this.request) return;
      for (const href of payload.styles) {
        const url = new URL(href, location.origin);
        if (url.origin !== location.origin || !url.pathname.startsWith(this.base) || !url.pathname.endsWith('.css')) continue;
        if (![...document.querySelectorAll<HTMLLinkElement>('link[rel="stylesheet"]')].some((link) => link.href === url.href)) {
          const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = url.href; document.head.append(link);
        }
      }
      this.current = target.route;
      this.anchors = payload.anchors;
      this.dialog.querySelector('#lq-reader-title')!.textContent = entry.title;
      const full = this.dialog.querySelector<HTMLAnchorElement>('[data-lq-full-guide]')!;
      full.href = target.url;
      this.dialog.querySelector<HTMLAnchorElement>('[data-lq-guide-markdown]')!.href = entry.markdown;
      this.dialog.style.setProperty('--lq-page-accent', `var(--lq-tone-${entry.tone})`);
      // These fragments are generated from this build's trusted full pages.
      this.body.innerHTML = payload.html;
      this.dialog.querySelector('[data-lq-reader-meta]')!.innerHTML = payload.metadataHtml;
      this.dialog.querySelector('[data-lq-reader-sources]')!.innerHTML = payload.sourceHtml;
      this.status.textContent = '';
      const state = this.states.restore(target.route);
      this.body.querySelectorAll('details').forEach((details, at) => { if (at < state.expanded.length) details.open = state.expanded[at]; });
      this.pictures();
      this.scroll.scrollTop = state.scroll;
      this.scroll.focus({ preventScroll: true });
      if (target.anchor && (push || !this.states.visits.has(target.route))) {
        const anchor = this.body.querySelector<HTMLElement>(`[id="${CSS.escape(this.anchors[target.anchor] ?? '')}"]`);
        if (anchor) {
          for (let parent = anchor.parentElement; parent && parent !== this.body; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
          anchor.scrollIntoView({ block: 'start' });
        }
      }
      this.pictures();
      this.navigation(target.route, entry.pathway);
      document.title = `${entry.title} | LQ.AI`;
      if (push) history.pushState({ lqReader: target.url }, '', target.url);
      this.dialog.dispatchEvent(new Event('lq-reader-open'));
    } catch {
      if (ticket !== this.request) return;
      this.close(false);
      location.assign(href);
    }
  }

  close(push = true) {
    this.request++;
    this.save(); this.dialog.close();
    document.body.classList.remove('lq-reader-wide');
    this.navigation('', null);
    document.title = this.rootTitle;
    if (push) history.pushState({ lqExplore: true }, '', this.rootUrl);
    const opener = this.opener?.isConnected && this.opener.getClientRects().length && !this.opener.closest('[inert]') ? this.opener : document.getElementById('lq-docs-question');
    opener?.focus({ preventScroll: true });
    this.pictures();
  }

  private navigation(route: string, pathway: string | null) {
    for (const link of document.querySelectorAll<HTMLAnchorElement>('[data-lq-pathways] a')) {
      link.removeAttribute('aria-current');
      if (link.dataset.route === route) link.setAttribute('aria-current', 'page');
      else if (link.dataset.pathway === pathway) link.setAttribute('aria-current', route.startsWith('pathways/') ? 'page' : 'true');
    }
  }

  private async copyCode(button: HTMLButtonElement) {
    const pre = this.body.querySelector<HTMLElement>(`pre[data-lq-code="${button.dataset.lqCopy}"]`)!;
    const lines = [...pre.querySelectorAll('.ec-line')];
    const text = lines.length ? lines.map((line) => line.textContent).join('\n') : (pre.querySelector('code') ?? pre).textContent!;
    try { await navigator.clipboard.writeText(text); button.textContent = 'Copied'; }
    catch {
      const selection = getSelection(), range = document.createRange();
      range.selectNodeContents(pre); selection?.removeAllRanges(); selection?.addRange(range);
      button.textContent = 'Select code to copy';
    }
  }
}
