// The mechanical part of launch gate 2 (scripts/lib/rules.mjs): Annex A's
// rules 10, 11 and 12 as `check:rules` applies them to dist/. These cases pin
// what counts as an onward route, a program a reader must have, and a page's
// place in llms.txt.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { llmsPlaces, onwardRoutes, shellPrograms, unnamedTools } from '../scripts/lib/rules.mjs';

describe('rule 10: onward routes', () => {
  const known = new Set(['operate/upgrade', 'changelog', 'trust']);
  const onward = (hrefs) => [...onwardRoutes(hrefs, { route: 'trust', base: '/lq-ai/', known })];

  it('counts a link to another built page, with or without its trailing slash or anchor', () => {
    assert.deepEqual(onward(['/lq-ai/operate/upgrade/', '/lq-ai/changelog#v0-9-0']), ['operate/upgrade', 'changelog']);
  });

  it("doesn't count the page itself, its anchors, the machine surface or other sites", () => {
    assert.deepEqual(onward(['/lq-ai/trust/', '#threat-model', '/lq-ai/_repo/README.md', 'https://github.com/LegalQuants/lq-ai']), []);
  });

  it("doesn't count a link to a page that wasn't built", () => {
    assert.deepEqual(onward(['/lq-ai/operate/gone/']), []);
  });

  it('counts a Markdown twin as its page', () => {
    assert.deepEqual(onward(['/lq-ai/changelog.md']), ['changelog']);
  });
});

describe('rule 12: programs a page runs', () => {
  const programs = (text) => [...shellPrograms(text.split('\n'))];

  it('takes the first word of every command, through pipes, && and sudo', () => {
    assert.deepEqual(programs('curl -s http://x | jq .a && sudo docker compose up'), ['curl', 'jq', 'docker']);
  });

  it('skips builtins, the commonest file utilities, and environment assignments', () => {
    assert.deepEqual(programs('cd lq-ai\nFOO=1 cat .env | grep KEY\nexport X=1'), []);
  });

  it('reads a continued line as one command, and ignores comments and prompts', () => {
    assert.deepEqual(programs('# Inspect the config\n$ docker compose \\\n  -f a.yml \\\n  build web # rebuild'), ['docker']);
  });

  it('ignores capitalised words, which are prose, not programs', () => {
    assert.deepEqual(programs('Weekly archive'), []);
  });
});

describe('rule 12: unnamed tools', () => {
  it('reports a program the text never names', () => {
    assert.deepEqual(unnamedTools(new Set(['jq', 'git']), 'Run git to fetch the tag.'), ['jq']);
  });

  it('matches whole words only, so "digital" does not name git', () => {
    assert.deepEqual(unnamedTools(new Set(['git']), 'A digital signature.'), ['git']);
  });

  it('accepts the name inside inline code', () => {
    assert.deepEqual(unnamedTools(new Set(['python3']), 'Generate them with Python 3 (python3).'), []);
  });
});

describe('rule 11: llms.txt places', () => {
  const text = [
    '# LQ.AI documentation',
    '## Find instructions by goal',
    '- [Set up](https://x.test/lq-ai/start/quickstart.md): steps',
    '## How to install',
    '### Prepare and get started',
    '- [Set up](https://x.test/lq-ai/start/quickstart/): text [Markdown](https://x.test/lq-ai/start/quickstart.md)',
    '## Security & privacy',
    '### Review the evidence',
    '- [Threat model](https://x.test/lq-ai/trust/threat-model/): text',
    '- [Explore](https://x.test/lq-ai/): text',
  ].join('\n');
  const places = llmsPlaces(text, 'https://x.test/lq-ai/');

  it('records the pathway and group above each entry', () => {
    assert.deepEqual(places.get('trust/threat-model'), [['Security & privacy', 'Review the evidence']]);
  });

  it('keeps every place a page is listed, so two homes are visible', () => {
    assert.deepEqual(places.get('start/quickstart'), [['Find instructions by goal'], ['How to install', 'Prepare and get started']]);
  });

  it('maps the site root to the empty route', () => {
    assert.ok(places.has(''));
  });
});
