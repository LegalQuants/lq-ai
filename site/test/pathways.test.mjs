// The pathways layout's map (src/pathways.mjs): release notes join by rule,
// every page must sit in exactly one group, and a page's pathway decides its
// accent. `check:orphans` runs `validatePathways` against the real build; these
// cases pin its behaviour on small route lists.

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import {
  PATHWAYS,
  expandPathways,
  pathwayOf,
  readingOrder,
  validatePathways,
} from '../src/pathways.mjs';

const listed = PATHWAYS.flatMap((p) => p.groups.flatMap((g) => g.pages));

describe('pathways map', () => {
  it('keeps her four pathways, in her order', () => {
    assert.deepEqual(
      PATHWAYS.map((p) => p.title),
      ['What is LQAI', 'How to install', 'Security & privacy', 'Contribute']
    );
  });

  it('lists no route twice', () => {
    assert.equal(new Set(listed).size, listed.length);
  });

  it('adds every release to Release notes, newest first', () => {
    const routes = [...listed, 'changelog/v0-4-0', 'changelog/v0-10-0', 'changelog/v0-8-0'];
    const notes = expandPathways(routes)
      .flatMap((p) => p.groups)
      .find((g) => g.title === 'Release notes');
    assert.deepEqual(notes.pages, [
      'changelog',
      'changelog/v0-10-0',
      'changelog/v0-8-0',
      'changelog/v0-4-0',
    ]);
  });

  it('passes when every built page is placed once', () => {
    assert.deepEqual(validatePathways([...listed, 'changelog/v0-8-0']), []);
  });

  it('reports a built page that no group places', () => {
    const problems = validatePathways([...listed, 'operate/new-page']);
    assert.deepEqual(problems, ['"operate/new-page" is in no pathway group']);
  });

  it('reports a listed route that was not built', () => {
    const problems = validatePathways(listed.filter((route) => route !== 'trust/threat-model'));
    assert.equal(problems.length, 1);
    assert.match(problems[0], /"trust\/threat-model" .* is not a built page/);
  });

  it('gives a page, a release and a pathway page their pathway', () => {
    assert.equal(pathwayOf('start/quickstart')?.id, 'install');
    assert.equal(pathwayOf('skills/attestation')?.id, 'security');
    assert.equal(pathwayOf('changelog/v0-8-0')?.id, 'about');
    assert.equal(pathwayOf('pathways/contribute')?.id, 'contribute');
    assert.equal(pathwayOf(''), undefined);
    assert.equal(pathwayOf('all'), undefined);
  });

  it('reads pathway by pathway, group by group', () => {
    const order = readingOrder(listed);
    assert.equal(order[0], 'overview');
    assert.equal(order.at(-1), 'trust/governance');
    assert.ok(order.indexOf('start/quickstart') < order.indexOf('operate'));
  });
});
