// The four reader pathways — the navigation of the `pathways` layout
// (`SITE_LAYOUT=pathways`).
//
// This is Iris's `shared/pathways.json` from her UI review (#lqai, 2026-09-25,
// lq-docs-v2), kept verbatim: pathway and group names, group order, page order.
// Only the page ids are rewritten into this site's route form
// (`start/quickstart/index` → `start/quickstart`). Her map places the entry
// page (`index`) first under "Start here"; in this layout `/` is the pathway
// landing, so that page is served at `overview/` instead (the sync moves it).
//
// Pages are *grouped* here, never copied or renamed: titles come from each
// page's own frontmatter at build time. A group lists its pages by route, with
// one exception — release notes are matched by rule, so a new release joins
// "Release notes" without anyone editing this file.
//
// `validatePathways()` is what keeps the map honest: every built page must sit
// in exactly one group, and every listed route must exist. `check:orphans`
// runs it against the sync manifest in the pathways layout.

/** Pathway id → the accent tone it takes (`--lq-tone-a|b|c` in the theme). */
export const PATHWAYS = [
  {
    id: 'about',
    title: 'Getting started',
    tone: 'a',
    groups: [
      {
        title: 'Start here',
        pages: ['overview', 'start', 'start/is-it-for-you'],
      },
      {
        title: 'Understand and use skills',
        pages: [
          'skills',
          'skills/what-a-skill-is',
          'skills/catalogue',
          'skills/playbooks',
          'skills/where-skills-live',
          'skills/your-prompt-files-are-skills',
        ],
      },
      {
        title: 'Find skills by task and jurisdiction',
        pages: [
          'skills/coverage',
          'skills/coverage/practice-area/contracts',
          'skills/coverage/practice-area/employment',
          'skills/coverage/practice-area/ip',
          'skills/coverage/practice-area/litigation',
          'skills/coverage/practice-area/privacy',
          'skills/coverage/jurisdiction/agnostic',
          'skills/coverage/jurisdiction/global',
          'skills/coverage/jurisdiction/eu',
          'skills/coverage/jurisdiction/regime-aware',
          'skills/coverage/jurisdiction/us',
        ],
      },
      // Her map lists v0-7-1, v0-7-0, v0-4-0: every release, newest first.
      { title: 'Release notes', pages: ['changelog'], releases: true },
    ],
  },
  {
    id: 'install',
    title: 'How to install',
    tone: 'b',
    groups: [
      {
        title: 'Prepare and get started',
        pages: [
          'start/what-it-touches',
          'start/choose-your-path',
          'operate/hardware-sizing',
          'start/quickstart',
        ],
      },
      {
        title: 'Choose an installation',
        pages: [
          'operate',
          'operate/install-macos',
          'operate/install-docker-compose',
          'operate/install-helm',
          'operate/headless-boot',
          'operate/air-gapped',
          'operate/reverse-proxy-tls',
        ],
      },
      {
        title: 'Example setups',
        pages: [
          'operate/recipes',
          'operate/recipes/caddy-tailscale',
          'operate/recipes/tailnet-ollama',
          'operate/recipes/observability',
        ],
      },
      {
        title: 'Maintain and troubleshoot',
        pages: [
          'operate/logs-and-monitoring',
          'operate/backup-and-restore',
          'operate/upgrade',
          'operate/something-is-wrong',
          'operate/troubleshooting',
          'operate/move-or-uninstall',
          'start/where-help-lives',
        ],
      },
      {
        title: 'Technical reference',
        pages: [
          'operate/architecture',
          'reference',
          'reference/configuration',
          'reference/versioning',
        ],
      },
      {
        title: 'Client handover',
        pages: ['deliver', 'deliver/branding-and-licensing'],
      },
    ],
  },
  {
    id: 'security',
    title: 'Security & privacy',
    tone: 'c',
    groups: [
      {
        title: 'Data handling and risks',
        pages: [
          'trust',
          'trust/what-leaves-my-deployment',
          'trust/anonymization',
          'trust/threat-model',
        ],
      },
      {
        title: 'Review the evidence',
        pages: [
          'trust/published-gaps',
          'trust/verify-these-claims',
          'trust/audit-and-evidence',
          'trust/compliance-mappings',
          'trust/questionnaires',
        ],
      },
      {
        title: 'Protect the deployment',
        pages: [
          'trust/supply-chain',
          'operate/rotate-a-leaked-key',
          'trust/security-disclosure',
          'trust/continuity',
        ],
      },
      { title: 'Skill assurance', pages: ['skills/attestation'] },
    ],
  },
  {
    id: 'contribute',
    title: 'Contribute',
    tone: 'a',
    groups: [
      {
        title: 'Choose how to contribute',
        pages: [
          'contribute',
          'contribute/lawyers',
          'contribute/engineers',
          'contribute/compliance-professionals',
          'contribute/board',
        ],
      },
      {
        title: 'Development',
        pages: ['contribute/dev-environment', 'contribute/coding-agents', 'reference/adr-index'],
      },
      {
        title: 'Create and share skills',
        pages: [
          'skills/author-your-first-skill',
          'skills/test-your-skill',
          'reference/skill-frontmatter',
        ],
      },
      {
        title: 'Membership and governance',
        pages: ['contribute/membership', 'contribute/code-of-conduct', 'trust/governance'],
      },
    ],
  },
];

/** The route the classic entry page moves to in this layout. */
export const OVERVIEW_ROUTE = 'overview';

/** Routes this layout adds for its own navigation — not content pages. */
export const NAV_ROUTES = {
  landing: '',
  all: 'all',
  pathway: (id) => `pathways/${id}`,
};

const RELEASE = /^changelog\/v(\d+)-(\d+)-(\d+)$/;

/** Newest release first: `changelog/v0-8-0` before `changelog/v0-7-1`. */
function byVersionDesc(a, b) {
  const va = RELEASE.exec(a).slice(1).map(Number);
  const vb = RELEASE.exec(b).slice(1).map(Number);
  for (let i = 0; i < 3; i++) if (va[i] !== vb[i]) return vb[i] - va[i];
  return 0;
}

/**
 * The map with every group's pages resolved against the routes that exist:
 * listed routes as written, plus — for the release-notes group — every release
 * page, newest first. Routes that do not exist are kept (validation reports
 * them); nothing is silently dropped.
 */
export function expandPathways(routes) {
  const releases = [...routes].filter((route) => RELEASE.test(route)).sort(byVersionDesc);
  return PATHWAYS.map((pathway) => ({
    ...pathway,
    groups: pathway.groups.map((group) => ({
      title: group.title,
      pages: group.releases ? [...group.pages, ...releases] : [...group.pages],
    })),
  }));
}

/** Which pathway a route belongs to, or undefined for none. */
export function pathwayOf(route) {
  const clean = String(route ?? '').replace(/^\/+|\/+$/g, '');
  if (clean === NAV_ROUTES.all || clean === NAV_ROUTES.landing) return undefined;
  const hub = /^pathways\/([\w-]+)$/.exec(clean);
  if (hub) return PATHWAYS.find((p) => p.id === hub[1]);
  if (RELEASE.test(clean)) return PATHWAYS.find((p) => p.groups.some((g) => g.releases));
  return PATHWAYS.find((p) => p.groups.some((g) => g.pages.includes(clean)));
}

/** Every content route in reading order: pathway, then group, then page. */
export function readingOrder(routes) {
  return expandPathways(routes).flatMap((p) => p.groups.flatMap((g) => g.pages));
}

/**
 * Problems with the map against the routes that were actually built:
 * a route in no group, a route in two groups, a listed route that does not
 * exist. Empty when the map is sound.
 */
export function validatePathways(routes) {
  const known = new Set(routes);
  const seen = new Map();
  const problems = [];
  for (const pathway of expandPathways(routes)) {
    for (const group of pathway.groups) {
      for (const route of group.pages) {
        const where = `${pathway.title} › ${group.title}`;
        if (!known.has(route)) problems.push(`"${route}" (${where}) is not a built page`);
        if (seen.has(route)) problems.push(`"${route}" is in both ${seen.get(route)} and ${where}`);
        else seen.set(route, where);
      }
    }
  }
  for (const route of known) {
    if (!seen.has(route)) problems.push(`"${route}" is in no pathway group`);
  }
  return problems;
}
