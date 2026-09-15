/**
 * The transform, run end to end against a fixture page tree.
 *
 * `node --test`, `node:assert` — no test framework. The pipeline is four Node
 * scripts and a Python one; a runner would be a dependency in the SBOM for
 * something the platform already does.
 *
 * The fixtures under `test/fixtures/` are a small `docs/site/` tree plus the
 * "canonical repository files" it presents. They resolve against the **real**
 * repository, because that is what the transform does in production — includes,
 * `sources:` and links are repository-relative by definition. Output goes to a
 * temporary directory, so a test run never touches the working copy.
 *
 * What is asserted, and why each one earns a test:
 *
 *  - routes, including the ones the generators contribute;
 *  - every branch of the link table — a mis-resolved link is the failure this
 *    whole script exists to prevent;
 *  - include expansion: whole file, `from`/`to`, `shift`, and the fence-awareness
 *    that keeps a heading-shaped line inside a code block from ending a slice;
 *  - the stamp, on every page;
 *  - the machine surface: a `.md` twin per route, `llms.txt`, `llms-full.txt`.
 */

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

const SITE_ROOT = fileURLToPath(new URL('..', import.meta.url));
const FIXTURES = path.join(SITE_ROOT, 'test', 'fixtures', 'docs-site');

const BASE = '/lq-ai/';
const BLOB = 'https://github.com/LegalQuants/lq-ai/blob/';

let out;
let dist;
let manifest;

const contentOf = (route) => {
  const page = manifest.pages.find((entry) => entry.route === route);
  assert.ok(page, `no page at route "${route}"`);
  return readFileSync(path.join(out, page.contentFile), 'utf8');
};

const run = (script, extraEnv = {}) =>
  execFileSync(process.execPath, [path.join(SITE_ROOT, 'scripts', script)], {
    cwd: SITE_ROOT,
    encoding: 'utf8',
    env: {
      ...process.env,
      DOCS_SITE_DIR: FIXTURES,
      SYNC_OUT_ROOT: out,
      DIST_DIR: dist,
      SITE_BASE: BASE,
      SITE_URL: 'https://legalquants.github.io',
      ...extraEnv,
    },
  });

before(() => {
  out = mkdtempSync(path.join(os.tmpdir(), 'lq-ai-docs-sync-'));
  dist = path.join(out, 'dist');
  mkdirSync(dist, { recursive: true });
  run('sync-content.mjs');
  manifest = JSON.parse(readFileSync(path.join(out, '.sync-manifest.json'), 'utf8'));
});

after(() => {
  if (out) rmSync(out, { recursive: true, force: true });
});

describe('routes', () => {
  it('maps a file path to its route, collapsing index files', () => {
    const routes = manifest.pages.map((page) => page.route);
    assert.ok(routes.includes(''), 'the entry hub takes the root route');
    assert.ok(routes.includes('start'));
    assert.ok(routes.includes('start/links'));
  });

  it('includes the pages the generators contribute', () => {
    const routes = manifest.pages.map((page) => page.route);
    for (const route of [
      'reference/adr-index',
      'reference/configuration',
      'reference/skill-frontmatter',
      'skills/catalogue',
      'skills/coverage',
      'changelog',
    ]) {
      assert.ok(routes.includes(route), `expected a generated page at "${route}"`);
    }
  });

  it('orders the manifest the way the sidebar is ordered', () => {
    const namespaces = manifest.pages.map((page) => page.namespace);
    assert.equal(manifest.pages[0].route, '', 'the entry hub comes first');
    const order = [...new Set(namespaces)].filter(Boolean);
    const expected = manifest.namespaces
      .map((entry) => entry.dir)
      .filter((dir) => order.includes(dir));
    assert.deepEqual(order, expected);
  });
});

describe('links', () => {
  let page;
  before(() => {
    page = contentOf('start/links');
  });

  it('sends a link to another page to that page’s route, with the base', () => {
    assert.match(page, /\[the namespace hub\]\(\/lq-ai\/start\/\)/);
  });

  it('resolves a link to an MDX page', () => {
    assert.match(page, /\[home\]\(\/lq-ai\/\)/);
  });

  it('sends a link to an intro file to the page it introduces', () => {
    assert.match(page, /\[ADR index\]\(\/lq-ai\/reference\/adr-index\/\)/);
  });

  it('sends a link to a page’s primary source to that page', () => {
    // `guide.md` is the first `sources:` entry of the curation page and of no
    // other page, so a link to the file lands on the page that presents it.
    assert.match(page, /\[the fixture guide\]\(\/lq-ai\/start\/curation\/\)/);
  });

  it('keeps the repository URL when the link carries an anchor', () => {
    assert.match(
      page,
      /\[the install section\]\(https:\/\/github\.com\/LegalQuants\/lq-ai\/blob\/[^)]+\/site\/test\/fixtures\/repo\/guide\.md#install\)/
    );
  });

  it('pins any other repository file to a blob URL', () => {
    assert.match(page, new RegExp(`\\[the project README\\]\\(${BLOB}[^)]+/README\\.md\\)`));
  });

  it('pins a repository directory to a tree URL', () => {
    assert.match(page, /\[the ADR folder\]\(https:\/\/github\.com\/LegalQuants\/lq-ai\/tree\/[^)]+\/docs\/adr\)/);
  });

  it('copies an image into the site and rewrites it with the base', () => {
    assert.match(page, /!\[the launcher home screen\]\(\/lq-ai\/_repo\/docs\/images\/launcher-home\.png\)/);
    readFileSync(path.join(out, 'public', '_repo', 'docs', 'images', 'launcher-home.png'));
  });

  it('leaves an external URL and a bare anchor alone', () => {
    assert.match(page, /\[the repository\]\(https:\/\/github\.com\/LegalQuants\/lq-ai\)/);
    assert.match(page, /\[back to the top\]\(#fixture-link-cases\)/);
  });

  it('maps a JSX href attribute on an MDX page', () => {
    const hub = contentOf('');
    assert.match(hub, /href="\/lq-ai\/start\/"/);
    assert.match(hub, /href="\/lq-ai\/start\/links\/"/);
  });

  it('writes no literal base path into a page source', () => {
    // The base belongs to the URLs the transform emits, never to the tree it
    // reads: a page that hard-codes it cannot be moved to a custom domain.
    const sources = readFileSync(path.join(FIXTURES, 'start', 'links.md'), 'utf8');
    assert.ok(!sources.includes(BASE));
  });
});

describe('includes', () => {
  let page;
  before(() => {
    page = contentOf('start/curation');
  });

  it('expands a whole file and drops its H1', () => {
    assert.ok(page.includes('This file stands in for something like'));
    assert.ok(!page.includes('# A canonical repository file'));
  });

  it('resolves links inside the included text from the source file’s directory', () => {
    // `nested/deep.md` is relative to test/fixtures/repo/, not to the page.
    assert.match(
      page,
      new RegExp(`\\[the nested note\\]\\(${BLOB}[^)]+/site/test/fixtures/repo/nested/deep\\.md\\)`)
    );
    assert.match(page, /\[launcher home screen\]\(\/lq-ai\/_repo\/docs\/images\/launcher-home\.png\)/);
  });

  it('slices between two exact heading lines, `to` exclusive', () => {
    const section = page.split('## Only the install section')[1].split('## The whole file, demoted')[0];
    assert.ok(section.includes('Two steps.'));
    assert.ok(!section.includes('Everything after the `to=` heading'));
  });

  it('does not treat a heading-shaped line inside a code fence as a heading', () => {
    const section = page.split('## Only the install section')[1].split('## The whole file, demoted')[0];
    assert.ok(
      section.includes('echo "not a heading"'),
      'the slice stopped at a `## Install` line inside a fenced block'
    );
  });

  it('demotes every heading by `shift`', () => {
    const section = page.split('## The whole file, demoted')[1];
    assert.ok(section.includes('### Install'), 'an H2 in the source became an H3');
    assert.ok(section.includes('#### A subheading under Install'));
  });

  it('leaves a fenced code block on the page itself untouched', () => {
    assert.ok(page.includes('[not a real link](../../../../../README.md)'));
    assert.ok(page.includes('<!-- include: site/test/fixtures/repo/guide.md -->'));
  });
});

describe('frontmatter and the stamp', () => {
  it('stamps every page with a commit and a date', () => {
    for (const page of manifest.pages) {
      assert.ok(page.sha, `${page.route || '/'} has no sha`);
      assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(page.date), `${page.route || '/'} has no ISO date`);
      assert.ok(page.title, `${page.route || '/'} has no title`);
      assert.ok(page.description, `${page.route || '/'} has no description`);
    }
  });

  it('writes the stamp into the page frontmatter', () => {
    const page = contentOf('start/links');
    assert.match(page, /checkedAgainst:\n\s+sha: /);
    assert.match(page, /sourceFiles:\n\s+- site\/test\/fixtures\/docs-site\/start\/links\.md/);
  });

  it('keeps the author’s own frontmatter', () => {
    assert.match(contentOf('start'), /status: reviewed/);
    assert.match(contentOf('start'), /audience:\n\s+- agent/);
  });

  it('forces a generated page to `status: draft`', () => {
    // A generated page cannot have been reviewed against its sources by a human
    // who has not seen it; `reviewed` is a claim only a person can make.
    for (const page of manifest.pages.filter((entry) => entry.kind === 'generated')) {
      assert.equal(page.status, 'draft', `${page.route} is generated but not a draft`);
    }
  });
});

describe('generators', () => {
  it('prepends a writer’s intro file and maps its links', () => {
    const page = contentOf('reference/adr-index');
    assert.ok(page.includes('A generated page may carry a hand-written lead-in.'));
    assert.match(page, /\[the link fixture\]\(\/lq-ai\/start\/links\/\)/);
  });

  it('renders the ADR index from the repository’s own ADR files', () => {
    const page = contentOf('reference/adr-index');
    assert.match(page, /\| ADR \| Decision \| Status \|/);
    assert.match(page, /\| 0001 \| \[/);
  });

  it('renders the skill catalogue with an attestation column', () => {
    const page = contentOf('skills/catalogue');
    assert.match(page, /\| Skill \| Practice area \| Jurisdiction \| Version \| Author \| Attested by \|/);
    assert.ok(page.includes('not recorded in frontmatter'));
  });

  it('builds a coverage page per declared jurisdiction and practice area', () => {
    const routes = manifest.pages.map((page) => page.route);
    // The fixture notes file groups `us` and `US-default` under one facet via
    // `match:`, so both raw values must land on the same page.
    assert.ok(routes.includes('skills/coverage/jurisdiction/us'));
    assert.ok(!routes.includes('skills/coverage/jurisdiction/us-default'));
    assert.ok(routes.includes('skills/coverage/practice-area/contracts'));
    assert.ok(routes.includes('skills/coverage/practice-area/employment'));
  });

  it('says so, rather than blanking, on a practice area with no skill', () => {
    const page = contentOf('skills/coverage/practice-area/employment');
    assert.ok(page.includes('No first-party skill carries this practice area'));
    assert.ok(page.includes('gap in coverage, not a statement that the area is out of scope'));
  });

  it('lists ungrouped tags on the index instead of giving each one a page', () => {
    const index = contentOf('skills/coverage');
    assert.ok(index.includes('not grouped into a practice area'));
    assert.ok(!manifest.pages.some((page) => page.route === 'skills/coverage/practice-area/tabular'));
  });

  it('renders the configuration reference from the Pydantic settings classes', () => {
    const page = contentOf('reference/configuration');
    assert.match(page, /### `Settings`/);
    assert.match(page, /`database_url`/);
    assert.ok(page.includes('gateway.yaml.example'));
  });

  it('renders the skill-frontmatter reference from the loader’s schema', () => {
    const page = contentOf('reference/skill-frontmatter');
    assert.match(page, /\| Field \| Type \| Required \| Default \| What it is \|/);
    assert.ok(page.includes('`trigger_examples`'));
  });

  it('lists every tag in the changelog, with or without release notes', () => {
    const page = contentOf('changelog');
    assert.ok(page.includes('no release notes in the repository'));
    assert.match(page, /\| v\d+\.\d+\.\d+ \| \d{4}-\d{2}-\d{2} \|/);
  });

  it('gives a release page a hyphenated, slug-safe route', () => {
    const routes = manifest.pages.map((page) => page.route);
    const releases = routes.filter((route) => /^changelog\/v/.test(route));
    assert.ok(releases.length > 0, 'no release pages were generated');
    for (const route of releases) {
      assert.ok(/^[a-z0-9][a-z0-9/-]*$/.test(route), `"${route}" is not slug-shaped`);
    }
  });
});

describe('accessibility of the rendered Markdown', () => {
  it('turns a GFM task list into a plain one, and leaves fenced samples alone', () => {
    const page = contentOf('start/checklist');
    assert.ok(page.includes('- ☐ An unticked item'));
    assert.ok(page.includes('- ✓ A ticked item'));
    assert.ok(page.includes('- [ ] shown as syntax, inside a fence'));
    assert.ok(!/^- \[[ x]\] /m.test(page.split('```')[0]));
  });

  it('does not mistake a link for a checkbox', () => {
    assert.ok(contentOf('start/checklist').includes('[x](/lq-ai/start/)'));
  });
});

describe('the supported-shapes directive', () => {
  let page;
  before(() => {
    page = contentOf('start/shapes');
  });

  it('replaces the directive with a table built from the data file', () => {
    assert.ok(!page.includes('<!-- supported-shapes -->'));
    assert.match(page, /\| Topology \| Status \| Recipe \| Notes \|/);
    assert.ok(page.includes('Docker Compose, cloud provider keys'));
  });

  it('normalises `known-to-work` and `known to work` to one status', () => {
    assert.ok(page.includes('| known to work |'));
  });

  it('renders a shape with no recipe as "none", not as a blank', () => {
    assert.match(page, /\| Windows host \| not tried \| none \|/);
  });

  it('links a published recipe through the base path', () => {
    assert.ok(page.includes('](/lq-ai/operate/install-docker-compose/)'));
  });
});

describe('the machine surface', () => {
  before(() => {
    run('postbuild-machine-surface.mjs');
  });

  it('writes a .md twin for every route', () => {
    for (const page of manifest.pages) {
      const twin = path.join(dist, page.route ? `${page.route}.md` : 'index.md');
      const text = readFileSync(twin, 'utf8');
      const [title, description, url, checked] = text.split('\n');
      assert.equal(title, `title: ${page.title}`);
      assert.equal(description, `description: ${page.description}`);
      assert.equal(url, `url: https://legalquants.github.io${BASE}${page.route ? `${page.route}/` : ''}`);
      assert.match(checked, /^checked-against: /);
    }
  });

  it('reduces an MDX hub to Markdown in its twin', () => {
    const twin = readFileSync(path.join(dist, 'index.md'), 'utf8');
    assert.ok(!twin.includes('<LinkCard'), 'JSX survived into the twin');
    assert.ok(!twin.includes('import {'), 'an import statement survived into the twin');
    assert.match(twin, /^- \[Start\]\(\/lq-ai\/start\/\) — The fixture namespace hub\.$/m);
  });

  it('lists every page in llms.txt, grouped by namespace', () => {
    const llms = readFileSync(path.join(dist, 'llms.txt'), 'utf8');
    assert.match(llms, /^# LQ\.AI documentation$/m);
    for (const page of manifest.pages) {
      assert.ok(
        llms.includes(`](https://legalquants.github.io${BASE}${page.route ? `${page.route}/` : ''}): `),
        `llms.txt has no entry for "${page.route || '/'}"`
      );
    }
    assert.match(llms, /^## Reference$/m);
  });

  it('concatenates every page into llms-full.txt', () => {
    const full = readFileSync(path.join(dist, 'llms-full.txt'), 'utf8');
    for (const page of manifest.pages) {
      assert.ok(full.includes(`title: ${page.title}`), `llms-full.txt is missing "${page.title}"`);
    }
  });
});

describe('failure modes', () => {
  const failing = (tree) => {
    try {
      execFileSync(process.execPath, [path.join(SITE_ROOT, 'scripts', 'sync-content.mjs')], {
        cwd: SITE_ROOT,
        encoding: 'utf8',
        env: {
          ...process.env,
          DOCS_SITE_DIR: path.join(SITE_ROOT, 'test', 'fixtures', tree),
          SYNC_OUT_ROOT: mkdtempSync(path.join(os.tmpdir(), 'lq-ai-docs-fail-')),
          SITE_BASE: BASE,
        },
      });
      return undefined;
    } catch (error) {
      return `${error.stdout ?? ''}${error.stderr ?? ''}`;
    }
  };

  it('fails on a missing include file, naming the page and line', () => {
    const output = failing('broken-include');
    assert.ok(output, 'the sync exited 0 on a missing include');
    assert.match(output, /start\/broken\.md:\d+ — include target "docs\/does-not-exist\.md" does not exist/);
  });

  it('fails on a `from=` heading that is not in the source', () => {
    const output = failing('broken-include');
    assert.match(output, /heading from="## Nowhere" is not in the file/);
  });

  it('fails on a `.md` link that resolves to nothing', () => {
    const output = failing('broken-include');
    assert.match(output, /points at a page that does not exist yet/);
  });

  it('fails on a page with no description', () => {
    const output = failing('broken-include');
    assert.match(output, /frontmatter has no `description`/);
  });
});
