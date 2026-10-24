import type { GuideEntry } from './guide-index';

/**
 * Explore's right sidebar: the details of the selected search result, as the
 * app's right sidebar shows whatever is open or selected (interface redesign
 * C19). It can be closed, and it is not drawn at all where there is nothing
 * selected or the window is too narrow for a third column (explore.css). The
 * guide itself is read on its own page; this only says what it is.
 *
 * Everything is built from the build's own guide data with textContent.
 */
export class GuideDetails {
  route: string | null = null;
  private body: HTMLElement;
  private opener: HTMLElement | null = null;
  private wide = matchMedia('(min-width: 72rem)');

  constructor(readonly panel: HTMLElement) {
    this.body = panel.querySelector('[data-lq-details-body]')!;
    panel.querySelector('[data-lq-details-close]')!.addEventListener('click', () => this.close(true));
    panel.addEventListener('keydown', (event) => { if (event.key === 'Escape') this.close(true); });
  }

  /** Whether there is room for the sidebar beside the conversation. */
  get available() { return this.wide.matches; }

  show(route: string, entry: GuideEntry, { focus = false, opener = null as HTMLElement | null } = {}) {
    this.route = route;
    this.opener = opener;
    this.body.replaceChildren(...this.render(entry));
    this.panel.hidden = false;
    document.body.classList.add('lq-details-open');
    if (focus) this.panel.querySelector<HTMLElement>('#lq-details-title')!.focus();
  }

  close(returnFocus = false) {
    if (this.panel.hidden) return;
    this.panel.hidden = true;
    this.route = null;
    document.body.classList.remove('lq-details-open');
    this.panel.dispatchEvent(new Event('lq-details-close'));
    if (returnFocus && this.opener?.isConnected) this.opener.focus();
  }

  private render(entry: GuideEntry): Node[] {
    const make = <K extends keyof HTMLElementTagNameMap>(tag: K, text?: string, className?: string) => {
      const element = document.createElement(tag);
      if (text !== undefined) element.textContent = text;
      if (className) element.className = className;
      return element;
    };
    const link = (href: string, text: string, className?: string) => { const a = make('a', text, className); a.href = href; return a; };
    const nodes: Node[] = [];

    const chips = make('p', undefined, 'lq-details-chips');
    if (entry.kindLabel) chips.append(make('span', entry.kindLabel, 'lq-chip lq-chip--kind'));
    // The page title's StatusBadge, shown like it only for a reviewed page.
    if (entry.status === 'reviewed') {
      const badge = make('span', undefined, 'lq-status lq-status--reviewed');
      badge.append(make('span', 'Page status: ', 'sr-only'), entry.status);
      chips.append(badge);
    }
    if (chips.childNodes.length) nodes.push(chips);

    const title = make('h2'); title.id = 'lq-details-title'; title.tabIndex = -1;
    title.append(link(entry.url, entry.title, entry.governance ? 'lq-mark' : undefined));
    nodes.push(title);
    if (entry.checkedAgainst?.release) nodes.push(make('p', entry.checkedAgainst.release, 'lq-details-release'));
    if (entry.description) nodes.push(make('p', entry.description, 'lq-details-summary'));

    const actions = make('p', undefined, 'lq-details-actions');
    actions.append(link(entry.url, 'Open guide', 'lq-details-open'), link(entry.markdown, 'Markdown'));
    nodes.push(actions);

    const list = (heading: string, items: Node[], className?: string) => {
      if (!items.length) return;
      const section = make('section', undefined, 'lq-details-section');
      const ul = make('ul', undefined, className);
      for (const item of items) { const li = make('li'); li.append(item); ul.append(li); }
      section.append(make('h3', heading), ul);
      nodes.push(section);
    };
    list('In this guide', entry.sections.map((section) => link(`${entry.url}#${encodeURIComponent(section.id)}`, section.title)));
    list('Written for', entry.audience.map((who) => make('span', who, 'lq-chip')), 'lq-details-audience');
    list('Sources', entry.sources.map((source) => { const a = link(source.href, source.path); a.rel = 'nofollow'; return a; }), 'lq-details-sources');
    if (entry.checkedAgainst) {
      const checked = make('p', 'Checked against ', 'lq-details-checked');
      const sha = link(entry.checkedAgainst.href, ''); sha.rel = 'nofollow'; sha.append(make('code', entry.checkedAgainst.sha));
      const date = make('time', entry.checkedAgainst.date); date.dateTime = entry.checkedAgainst.date;
      checked.append(sha, ' · ', date);
      nodes.push(checked);
    }
    return nodes;
  }
}
