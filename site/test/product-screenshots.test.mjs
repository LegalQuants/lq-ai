import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { describe, it } from 'node:test';
import { addProductScreenshots, renderScreenshots, validateScreenshots } from '../scripts/lib/product-screenshots.mjs';

const config = {
  schemaVersion: 1,
  capture: { note: 'Fictional input; review the output.' },
  screenshots: [{ id: 'answer', file: 'answer.jpg', width: 1280, height: 720,
    alt: 'The answer and its source clause.', caption: 'Compare the answer with the document.' }],
  placements: [{ route: 'overview', source: 'docs/overview.md', heading: '## Explanation', screenshots: ['answer'] }],
};

describe('product screenshot transformation', () => {
  it('keeps source prose and code intact while projecting descriptions into both surfaces', () => {
    const source = '## Explanation\n\nCanonical explanation.\n\n```md\n## Explanation\n```\n\nA qualification.\n\n## Next\n\nNext step.';
    for (const base of ['/', '/lq-ai/']) {
      const options = { route: 'overview', sources: ['docs/overview.md'], config, base };
      const text = addProductScreenshots(source, options);
      const html = addProductScreenshots(source, { ...options, html: true });
      for (const content of ['Canonical explanation.', 'A qualification.', 'Next step.', '```md\n## Explanation\n```', config.capture.note, config.screenshots[0].alt, config.screenshots[0].caption, `${base}product/answer.jpg`]) {
        assert.ok(text.includes(content), content);
        assert.ok(html.includes(content), content);
      }
      assert.ok(text.indexOf('LQ.AI in action') > text.indexOf('Canonical explanation.'));
      assert.ok(text.indexOf('LQ.AI in action') < text.indexOf('A qualification.'));
      assert.ok(!text.includes('<figure'));
      assert.match(html, /<figure/);
      assert.match(html, /loading="lazy"/);
      assert.equal(source.includes('LQ.AI in action'), false);
    }
  });

  it('matches the owning source, refuses missing or ambiguous headings, and supports selected introductions', () => {
    const source = '## Explanation\n\nAn explanation.';
    const options = { route: 'overview', sources: ['docs/overview.md'], config };
    assert.equal(addProductScreenshots(source, { ...options, sources: ['other.md'] }), source);
    assert.throws(() => addProductScreenshots('## Renamed\n\nAn explanation.', options), /0 matches/);
    assert.throws(() => addProductScreenshots(`${source}\n${source}`, options), /2 matches/);
    assert.match(addProductScreenshots('An explanation.', { ...options, heading: '## Explanation' }), /LQ.AI in action/);
    assert.equal(addProductScreenshots('Another answer.', { ...options, heading: '## Other' }), 'Another answer.');
  });

  it('fails on missing images or descriptions instead of shipping an empty gallery', () => {
    const dir = mkdtempSync(path.join(os.tmpdir(), 'lq-product-assets-'));
    try {
      assert.throws(() => validateScreenshots(config, dir), /missing/);
      writeFileSync(path.join(dir, 'answer.jpg'), 'fixture');
      validateScreenshots(config, dir);
      validateScreenshots({ ...config, placements: [{ ...config.placements[0], route: '' }] }, dir);
      assert.throws(() => validateScreenshots({ ...config, screenshots: [{ ...config.screenshots[0], alt: '' }] }, dir), /incomplete/);
      assert.throws(() => validateScreenshots({ ...config, placements: [{ ...config.placements[0], screenshots: ['missing'] }] }, dir), /invalid screenshot placement/);
      const html = renderScreenshots(config.placements[0], { config: { ...config, screenshots: [{ ...config.screenshots[0], caption: '<script> & "quoted"' }] }, html: true });
      assert.ok(!html.includes('<script>'));
      assert.match(html, /&lt;script&gt; &amp; &quot;quoted&quot;/);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('keeps a nested section intact when its capture follows the whole section', () => {
    const source = '## Guide\n\n### Table-mode skills\n\nAn explanation.\n\n```yaml\noutput_format: table\n```\n\nRequired fields.\n\n### Next\n\nNext topic.';
    const nested = { ...config, placements: [{ ...config.placements[0], heading: '### Table-mode skills', position: 'after-section' }] };
    const text = addProductScreenshots(source, { route: 'overview', sources: ['docs/overview.md'], config: nested });
    assert.ok(text.indexOf('#### LQ.AI in action') > text.indexOf('Required fields.'));
    assert.ok(text.indexOf('#### LQ.AI in action') < text.indexOf('### Next'));
    assert.ok(text.includes('```yaml\noutput_format: table\n```'));
  });
});
