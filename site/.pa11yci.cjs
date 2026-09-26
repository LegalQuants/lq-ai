/**
 * pa11y-ci configuration — the WCAG 2.1 AA gate (ADR 0028 requirement 4).
 *
 * This is `.pa11yci.cjs` rather than a plain-JSON `.pa11yci` because two
 * settings have to branch on the environment: Chrome's sandbox is disabled only
 * inside CI containers (left on locally, where turning it off would reduce
 * isolation for no benefit), and the "needs review" pass is opt-in. pa11y-ci
 * resolves `.pa11yci` → `.pa11yci.cjs` → `.pa11yci.js` → `.pa11yci.json`, so
 * this file is found with no extra flag. CommonJS because `package.json` sets
 * `"type": "module"` and pa11y-ci `require()`s its config.
 *
 * `urls` is deliberately empty: the list is generated from `dist/` by
 * `scripts/a11y-urls.mjs` and passed on the command line by `scripts/a11y.mjs`,
 * so the gate covers exactly the routes that were built — generated pages
 * included — and keeps working when the site's base path changes.
 *
 * ── What fails the build, and what does not ───────────────────────────────────
 *
 * axe returns two kinds of finding. `violations` are failures axe determined.
 * `incomplete` are checks axe ran but could not decide — for example
 * `color-contrast` on an element whose content is a single symbol ("Element
 * content contains only non-text characters"). pa11y reports both, and by
 * default calls both an error.
 *
 * The gate fails on violations. Incomplete findings are capped to `warning`, so
 * they do not fail a build a tool has explicitly declined to judge — but they
 * are not hidden either: `npm run check:a11y:review` re-runs the same URLs with
 * warnings included and prints every one of them. The palette behind them is
 * separately proved by `npm run check:contrast`, which measures the token pairs
 * directly.
 */

const isCI = Boolean(process.env.CI);
const includeNeedsReview = Boolean(process.env.PA11Y_INCLUDE_WARNINGS);

module.exports = {
  defaults: {
    // axe is the runner: it names the WCAG success criterion behind each issue,
    // which is what a reviewer needs in order to act on a failure.
    runners: ['axe'],
    standard: 'WCAG2AA',
    // Cap axe's "incomplete" results at warning level — see the note above.
    levelCapWhenNeedsReview: 'warning',
    includeWarnings: includeNeedsReview,
    includeNotices: false,
    timeout: 60000,
    // Starlight's theme script and Pagefind's UI both run on load; half a second
    // settles the page before axe reads computed styles.
    wait: 500,
    concurrency: 2,
    // pa11y-ci's default is one incognito BrowserContext per URL in a shared
    // browser. Tearing those down concurrently races Chrome's DevTools protocol
    // and fails unrelated URLs with "Target.closeTarget: No target with given id
    // found". Plain pages in the shared context are stable, and the gate reads
    // static pages with no cookies or storage to isolate.
    useIncognitoBrowserContext: false,
    chromeLaunchConfig: {
      args: isCI
        ? // GitHub's runner has no user namespace for Chrome's sandbox.
          ['--no-sandbox', '--disable-dev-shm-usage']
        : [],
    },
  },
  urls: [],
};
