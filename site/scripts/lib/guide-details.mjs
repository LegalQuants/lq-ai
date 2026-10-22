/**
 * What Explore's details sidebar says about a guide: the manifest's facts
 * (status, audience, sources, the commit it was checked against) plus the
 * guide's sections, read from the same compiled HTML as the full page so a
 * section link can never point at an anchor the page does not have.
 */
import { load } from 'cheerio';
import { KIND_LABELS } from './routes.mjs';
import { blobUrl, REPO_URL } from '../../src/repo.mjs';
import { releaseLabel } from '../../src/lib/release-label.mjs';

/**
 * Navigation pages (pathway hubs, All documentation) carry no `url` in the
 * manifest. Derive it from the route rather than publish "undefined".
 */
export function detailsPage(page, base) {
  return page.url ? page : { ...page, url: `${base}${page.route}/` };
}

/** One guide's entry in `_guides/index.json`. Text only; the page builds its own markup. */
export function guideDetails(html, page) {
  const dom = load(html);
  const article = dom('main .sl-markdown-content').first();
  if (!article.length) throw new Error(`${page.route}: no compiled documentation article`);
  const sections = article.find('h2[id]').map((_index, element) => ({
    id: dom(element).attr('id'), title: dom(element).text().trim(),
  })).get().filter((section) => section.title);
  const kind = page.contentKind ?? page.kind;
  return {
    title: page.title, url: page.url, status: page.status,
    kind, kindLabel: KIND_LABELS[kind] ?? null,
    description: page.description ?? '', audience: page.audience ?? [],
    sections,
    checkedAgainst: page.sha ? { sha: page.sha, date: page.date, href: `${REPO_URL}/commit/${page.sha}`,
      release: releaseLabel({ release: page.release, released: page.released }) ?? null } : null,
    sources: page.sha ? (page.sources ?? []).map((path) => ({ path, href: blobUrl(page.sha, path) })) : [],
  };
}
