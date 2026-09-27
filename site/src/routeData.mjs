/**
 * Starlight route middleware — how the pathways layout differs per page, and
 * the compare banner either layout can carry while the two are compared.
 *
 * Registered in astro.config.mjs only when there is something to do, so a
 * default (classic, no-banner) build never runs it.
 *
 * In the pathways layout (`SITE_LAYOUT=pathways`):
 *   - there is no sidebar: the header's pathway tabs and the pathway pages are
 *     the navigation (Iris's design), so `hasSidebar` is off on every page;
 *   - each page takes the accent of the pathway it sits in, set as one custom
 *     property the theme reads (`--lq-page-accent`);
 *   - Previous / Next follow the pathway reading order instead of the classic
 *     sidebar's, which this layout never shows.
 */
import { defineRouteMiddleware } from '@astrojs/starlight/route-data';
import { getCollection } from 'astro:content';

import { SITE_COMPARE, SITE_LAYOUT } from '../scripts/lib/paths.mjs';
import { OVERVIEW_ROUTE, pathwayOf, readingOrder } from './pathways.mjs';
import { withBase } from './namespaces.mjs';

const base = import.meta.env.BASE_URL;

const MOTION_INIT =
  "try{var m=localStorage.getItem('lq-motion');" +
  "if(!m)m=matchMedia('(prefers-reduced-motion: reduce)').matches?'reduced':'full';" +
  'document.documentElement.dataset.motion=m}catch(e){}';

/** Route → title for every content page, read once per build. */
let titles;
async function titleByRoute() {
  titles ??= getCollection('docs').then(
    (entries) => new Map(entries.map((entry) => [entry.id, entry.data.title]))
  );
  return titles;
}

const link = (route, label) => ({
  type: 'link',
  label,
  href: withBase(base, route),
  isCurrent: false,
  badge: undefined,
  attrs: {},
});

/**
 * The same page on the other layout, where it exists there, with the trailing
 * slash every URL on this site carries (`trailingSlash: 'always'`).
 */
function comparePath(route) {
  const layoutOnly = [OVERVIEW_ROUTE, 'all', '404'];
  if (!route || layoutOnly.includes(route) || route.startsWith('pathways/')) return '';
  return `${route}/`;
}

export const onRequest = defineRouteMiddleware(async (context) => {
  const route = context.locals.starlightRoute;
  const id = String(route.id ?? '').replace(/\/+$/, '');

  if (SITE_COMPARE) {
    const href = new URL(comparePath(id), `${SITE_COMPARE.url.replace(/\/+$/, '')}/`).href;
    route.entry.data.banner = {
      content: `${SITE_COMPARE.label} · <a href="${href}">Compare with the other layout</a>`,
    };
  }

  if (SITE_LAYOUT !== 'pathways') return;

  route.hasSidebar = false;

  const pathway = pathwayOf(id);
  const isLanding = id === '';
  // Pathway, landing and sitemap pages are navigation, laid out wide.
  const isNavPage = isLanding || id === 'all' || id.startsWith('pathways/');
  // `:root:root` outranks the theme's own `:root` rules, whatever order the
  // stylesheets load in.
  const declarations = [`--lq-page-accent:var(--lq-tone-${pathway?.tone ?? 'a'})`];
  if (isLanding) declarations.push('--lq-tabs-row:0px');
  if (isNavPage) declarations.push('--sl-content-width:77.5rem');
  route.head.push({
    tag: 'style',
    attrs: {},
    content: `:root:root{${declarations.join(';')}}`,
  });
  // The reduced-motion button's saved choice (else the system setting), applied
  // before first paint so a reader who turned motion off never sees any.
  route.head.push({ tag: 'script', attrs: {}, content: MOTION_INIT });

  // …and they get no pager.
  if (isNavPage) {
    route.pagination = { prev: undefined, next: undefined };
    return;
  }

  const byRoute = await titleByRoute();
  const order = readingOrder([...byRoute.keys()]).filter((r) => byRoute.has(r));
  const at = order.indexOf(id);
  if (at === -1) return;
  const prev = order[at - 1];
  const next = order[at + 1];
  route.pagination = {
    prev: prev === undefined ? undefined : link(prev, byRoute.get(prev)),
    next: next === undefined ? undefined : link(next, byRoute.get(next)),
  };
});
