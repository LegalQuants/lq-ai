// The eight namespaces, in the one fixed order the mini-PRD sets.
//
// Sidebar order, the header nav, the URL map and the entry hub must all agree,
// so the order is written down once, here, and imported by everything that
// needs it (astro.config.mjs and the header).

export const NAMESPACES = [
  { label: 'Start', dir: 'start' },
  { label: 'Operate', dir: 'operate' },
  { label: 'Trust', dir: 'trust' },
  { label: 'Skills', dir: 'skills' },
  { label: 'Deliver', dir: 'deliver' },
  { label: 'Contribute', dir: 'contribute' },
  { label: 'Reference', dir: 'reference' },
  { label: 'Changelog', dir: 'changelog' },
];

/**
 * Join the configured base path to a route. The base is configuration
 * (`SITE_BASE`), so no caller may write it out; every internal URL ends in `/`
 * to match `trailingSlash: 'always'`.
 */
export function withBase(base, route = '') {
  const prefix = base.endsWith('/') ? base : `${base}/`;
  const path = String(route).replace(/^\/+/, '');
  if (!path) return prefix;
  return prefix + (path.endsWith('/') ? path : `${path}/`);
}

/** The namespace a page id belongs to, or undefined for the entry hub. */
export function namespaceOf(id) {
  const first = String(id ?? '').split('/')[0];
  return NAMESPACES.find((ns) => ns.dir === first);
}
