import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { auditRoutes } from '../scripts/lib/a11y.mjs';

const urls = ['http://localhost/lq-ai/', 'http://localhost/lq-ai/guide/', 'http://localhost/lq-ai/404.html'];
const results = Object.fromEntries(urls.map((url) => [url, []]));

describe('accessibility route coverage', () => {
  it('passes literal trailing-slash URLs and the configured options to the runner', async () => {
    const options = { includeWarnings: true, concurrency: 2 };
    assert.equal(await auditRoutes(urls, options, async (actualUrls, actualOptions) => {
      assert.deepEqual(actualUrls, urls);
      assert.equal(actualOptions, options);
      return { total: 3, passes: 3, errors: 0, results };
    }), 0);
  });

  it('rejects the old false-green result that checked only the 404 page', async () => {
    await assert.rejects(auditRoutes(urls, {}, async () => ({
      total: 1, passes: 1, errors: 0, results: { [urls[2]]: [] },
    })), /incomplete route coverage/);
  });

  it('rejects a correct total with a missing or substituted result', async () => {
    const substituted = { ...results };
    delete substituted[urls[1]];
    substituted['http://localhost/unexpected/'] = [];
    for (const actual of [{ [urls[0]]: [] }, substituted]) {
      await assert.rejects(auditRoutes(urls, {}, async () => ({ total: 3, passes: 3, results: actual })), /incomplete route coverage/);
    }
  });

  it('fails on violations and browser errors even when errors is zero', async () => {
    for (const errors of [1, 0]) {
      assert.equal(await auditRoutes(urls, {}, async () => ({ total: 3, passes: 2, errors, results })), 2);
    }
  });

  it('rejects empty or duplicate input before running an audit', async () => {
    const unexpected = () => assert.fail('runner must not be called');
    await assert.rejects(auditRoutes([], {}, unexpected), /non-empty/);
    await assert.rejects(auditRoutes([urls[0], urls[0]], {}, unexpected), /unique/);
  });
});
