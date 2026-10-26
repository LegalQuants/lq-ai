import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it } from 'node:test';
import { optionalDetails, reduceMdx, selectSection } from '../scripts/lib/markdown.mjs';
import { resolveViews } from '../scripts/lib/views.mjs';

const SITE = fileURLToPath(new URL('..', import.meta.url));

describe('guidance semantics', () => {
  it('keeps code examples intact and labels mutually exclusive MDX alternatives', () => {
    const input = '<Tabs>\n<TabItem label="Cloud">\nCloud requires a provider key.\n</TabItem>\n<TabItem label="Local">\nLocal chat does not imply local embeddings.\n</TabItem>\n</Tabs>\n```astro\n<TabItem label="Example">\n```';
    const output = reduceMdx(input);
    assert.match(output, /### Cloud\s+Cloud requires a provider key/);
    assert.match(output, /### Local\s+Local chat does not imply local embeddings/);
    assert.match(output, /```astro\n<TabItem label="Example">\n```/);
    assert.throws(() => reduceMdx('<TabItem>Unlabelled instructions</TabItem>'), /literal label/);
    assert.throws(() => reduceMdx('<UnknownWidget>Important instructions</UnknownWidget>'), /Unsupported/);
  });

  it('selects a complete source section, ignoring heading-shaped fenced examples', () => {
    const source = '## Answer\nKeep this qualification.\n```md\n## Answer\n```\n### Details\nKeep these too.\n## Other\nExclude this.';
    const section = selectSection(source, '## Answer');
    assert.match(section.markdown, /Keep this qualification/);
    assert.match(section.markdown, /Keep these too/);
    assert.ok(!section.markdown.includes('Exclude this'));
    assert.throws(() => selectSection(source, '## Missing'), /0 matches/);
    assert.throws(() => selectSection('## Answer\nA\n## Answer\nB', '## Answer'), /2 matches/);
  });

  it('discloses optional explanation without losing content in the text output', () => {
    const input = 'Required action.\n<!-- docsite:optional -->\n### Details\nExtra explanation.\n<!-- /docsite:optional -->\nRequired check.';
    assert.match(optionalDetails(input, { html: true }), /<details[\s\S]*Extra explanation[\s\S]*<\/details>/);
    assert.equal(optionalDetails(input).trim(), 'Required action.\n### Details\nExtra explanation.\nRequired check.');
    for (const body of ['> [!CAUTION]\n> Never do this.', ':::danger[Stop]', '**Professional duty** — check this']) {
      assert.throws(() => optionalDetails(`<!-- docsite:optional -->\n### Details\n${body}\n<!-- /docsite:optional -->`), /critical caution/);
    }
    assert.throws(() => optionalDetails('<!-- docsite:optional -->\n### Details'), /unclosed/);
    assert.throws(() => optionalDetails('<!-- /docsite:optional -->'), /unexpected/);
    assert.throws(() => optionalDetails('<!-- docsite:optional -->\n<!-- docsite:optional -->'), /nested/);
  });

  it('refuses missing source sections and unknown metadata instead of blank answers', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'lq-view-validation-'));
    try {
      writeFileSync(path.join(dir, 'explore.yaml'), 'schemaVersion: 1\nquestions:\n  - id: answer\n    content: { route: overview, heading: "## Missing" }\n');
      const pages = [{ route: 'overview', markdown: '## Present\nAn answer.' }];
      assert.throws(() => resolveViews({ dataDir: dir, pages }), /0 matches/);
      writeFileSync(path.join(dir, 'explore.yaml'), 'schemaVersion: 1\nquestions:\n  - id: answer\n    answer: "A copied answer"\n    content: { route: overview, heading: "## Present" }\n');
      assert.throws(() => resolveViews({ dataDir: dir, pages }), /unknown keys: answer/);
      writeFileSync(path.join(dir, 'explore.yaml'), 'schemaVersion: 1\nquestions:\n  - id: answer\n    content: { route: overview, heading: "## Present" }\n');
      pages[0].markdown = '## Present\n[Details](#details)\n```md\n[Example](#details)\n```';
      const question = resolveViews({ dataDir: dir, pages }).questions[0];
      assert.ok(question.markdown.includes(`](${new URL(question.url).pathname}#details)`));
      assert.match(question.markdown, /\[Example\]\(#details\)/);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});

describe('source to agent output', () => {
  it('exports the same answer, prerequisites, alternatives, and checks under both base paths', () => {
    const root = mkdtempSync(path.join(os.tmpdir(), 'lq-guidance-flow-'));
    try {
      const docs = path.join(root, 'docs');
      mkdirSync(path.join(docs, '_data'), { recursive: true });
      mkdirSync(path.join(docs, 'routes'));
      writeFileSync(path.join(docs, 'routes/start.yaml'), '- route: overview\n  source: site/test/fixtures/repo/guidance.md\n  description: A fictional procedure fixture.\n  kind: how-to\n');
      writeFileSync(path.join(docs, '_data/explore.yaml'), 'schemaVersion: 1\nquestions:\n  - id: explanation\n    content: { route: overview, heading: "## What is it?" }\n');
      writeFileSync(path.join(docs, '_data/journeys.yaml'), 'schemaVersion: 1\njourneys:\n  - id: try-fixture\n    route: overview\n    before: "## Before you start"\n    steps: ["## 1. Try it"]\n    choices:\n      - { id: cloud, section: "### Cloud" }\n      - { id: local, section: "### Local" }\n    check: "## Check that it worked"\n');
      for (const base of ['/', '/lq-ai/']) {
        const out = path.join(root, base === '/' ? 'root' : 'subpath');
        const dist = path.join(out, 'dist');
        mkdirSync(dist, { recursive: true });
        const env = { ...process.env, DOCS_SITE_DIR: docs, SYNC_OUT_ROOT: out,
          DIST_DIR: dist, SITE_BASE: base, SITE_LAYOUT: 'classic', SITE_URL: 'https://legalquants.github.io' };
        for (const script of ['sync-content.mjs', 'postbuild-machine-surface.mjs']) {
          execFileSync(process.execPath, [path.join(SITE, 'scripts', script)], { cwd: SITE, env, stdio: 'pipe' });
        }
        const text = readFileSync(path.join(dist, 'overview.md'), 'utf8');
        for (const required of ['Source answer and its qualification.', 'Use fictional information.', '### Cloud', '### Local', 'Check the result.', 'Extra explanation.']) assert.ok(text.includes(required), required);
        assert.ok(!text.includes('<details'));
        const intro = readFileSync(path.join(out, 'src/content/explore/explanation.md'), 'utf8');
        assert.match(intro, /Source answer and its qualification/);
        const tasks = JSON.parse(readFileSync(path.join(dist, 'tasks.json'), 'utf8')).tasks;
        assert.equal(tasks[0].markdownUrl, `https://legalquants.github.io${base}overview.md`);
        assert.deepEqual(tasks[0].alternatives.map((choice) => choice.label), ['Cloud', 'Local']);
        assert.equal(tasks[0].verification.heading, '## Check that it worked');
        assert.match(readFileSync(path.join(dist, 'llms.txt'), 'utf8'), /Find instructions by goal/);
      }
    } finally { rmSync(root, { recursive: true, force: true }); }
  });
});
