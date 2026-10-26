/**
 * Browser journeys for Version C's Explore and guide pages, against the built
 * site (`npm run build` first). Run with `npm run check:e2e`.
 *
 * What they guard, each decided on 2026-10-22/23:
 * - Explore is one conversation: searches are appended after "Where do I go
 *   from here?", each answer names its term, and the bubbles sit on the left.
 * - The right sidebar shows the selected result (C19) from 72rem; below that
 *   there is no sidebar and nothing to select.
 * - A result's title opens the guide; Back and reload bring the conversation
 *   back with the opened result selected; another page's composer hands its
 *   question over without losing the earlier ones.
 * - Explore stays one tap away on a phone; a guide's facts move to the right
 *   column on wide screens; nothing scrolls sideways.
 */
import assert from 'node:assert/strict';
import { after, before, describe, it } from 'node:test';
import { BASE, openPage, searchOnExplore, startSite, url } from './site.mjs';

let site;
before(async () => { site = await startSite(); });
after(async () => { await site?.stop(); });

const GUIDE = 'operate/install-macos/';
const asks = (page) => page.$$eval('.lq-explore .lq-answer > .lq-ask', (els) => els.map((el) => el.textContent.trim()));
const selected = (page) => page.$eval('[data-lq-search-history]', (h) => h.querySelector('li[data-selected]')?.dataset.route ?? null);
const panelOpen = (page) => page.$eval('[data-lq-details]', (panel) => !panel.hidden && getComputedStyle(panel).display !== 'none');
const noErrors = (page) => assert.deepEqual(page.errors, [], 'no script errors');

describe('Explore is one conversation', () => {
  it('appends each search after "Where do I go from here?", naming its term', async () => {
    const page = await openPage(site.browser, 1440);
    await page.goto(url(), { waitUntil: 'load' });
    const intro = await asks(page);
    assert.equal(intro.length, 4);
    assert.equal(intro[3], 'Where do I go from here?');
    await searchOnExplore(page, 'docker');
    await searchOnExplore(page, 'backup');
    const all = await asks(page);
    assert.deepEqual(all.slice(4), ['Search for “docker”', 'Search for “backup”'], 'newest search last');
    const answers = await page.$$eval('.lq-search-turn .lq-answer-body > p:first-child', (ps) => ps.map((p) => p.textContent));
    assert.match(answers[0], /^Here's what I found for “docker”: (\d+ guides|one guide)\.$/);
    assert.match(answers[1], /“backup”/);
    // The reader's bubble sits on the left, in line with the conversation.
    const [bubble, column] = await page.$eval('.lq-search-turn:last-child', (turn) => [
      turn.querySelector('.lq-ask').getBoundingClientRect().left, turn.getBoundingClientRect().left]);
    assert.ok(Math.abs(bubble - column) < 2, `bubble at ${bubble}, turn at ${column}`);
    noErrors(page);
  });

  it('answers a search with no match in words, naming the term', async () => {
    const page = await openPage(site.browser, 1024);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'zzqxjv');
    const answer = await page.$eval('.lq-search-turn .lq-answer-body > p', (p) => p.textContent);
    assert.match(answer, /^I found no guides for “zzqxjv”\./);
    noErrors(page);
  });
});

describe('the introduction tour', () => {
  it('has four steps, each showing its place above its question once played', async () => {
    const page = await openPage(site.browser, 390, 844);
    await page.goto(url(), { waitUntil: 'load' });
    const places = () => page.$$eval('[data-lq-tour-step]', (steps) => steps.map((step) => {
      const place = step.querySelector(':scope > .lq-tour-place');
      return { place: place && getComputedStyle(place).display !== 'none' ? place.textContent : null,
        ask: step.querySelector('.lq-ask').textContent.trim(), active: step.hasAttribute('data-tour-active') };
    }));
    const before = await places();
    assert.equal(before.length, 4);
    assert.equal(before[3].ask, 'Where do I go from here?', 'the last step is "Where do I go from here?"');
    assert.ok(before.every((step) => step.place === null), 'no places before the tour starts');
    await page.click('[data-lq-tour-play]');
    const after = await places();
    assert.deepEqual(after.map((step) => step.place), [1, 2, 3, 4].map((n) => `Introduction ${n} of 4`));
    assert.deepEqual(after.map((step) => step.active), [true, false, false, false]);
    assert.match(await page.$eval('[data-lq-tour-status]', (s) => s.textContent), /^Introduction 1 of 4: /);
    await page.click('[data-lq-tour-play]'); // pause, so no timer outlives the test
    noErrors(page);
  });
});

describe('the right sidebar shows the selected result', () => {
  it('selects the first result, follows a row click, and moves focus on Details', async () => {
    const page = await openPage(site.browser, 1440);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'audit log');
    const routes = await page.$$eval('.lq-search-turn li[data-route]', (lis) => lis.map((li) => li.dataset.route));
    assert.ok(routes.length >= 3, 'at least three results');
    assert.equal(await selected(page), routes[0], 'a new search selects its first result');
    assert.ok(await panelOpen(page));

    await page.click(`.lq-search-turn li[data-route="${routes[1]}"] p`);
    assert.equal(await selected(page), routes[1], 'clicking a row selects it');
    const title = await page.$eval('#lq-details-title', (h) => h.textContent.trim());
    const rowTitle = await page.$eval(`li[data-route="${routes[1]}"] .lq-match-title`, (a) => a.textContent.trim());
    assert.equal(title, rowTitle);

    const details = `li[data-route="${routes[2]}"] [data-lq-details-toggle]`;
    await page.click(details);
    assert.equal(await page.evaluate(() => document.activeElement?.id), 'lq-details-title', 'Details moves focus to the sidebar');
    assert.equal(await page.$eval(details, (b) => b.getAttribute('aria-expanded')), 'true');
    await page.keyboard.press('Escape');
    assert.equal(await panelOpen(page), false, 'Escape closes it');
    assert.equal(await page.evaluate(() => document.activeElement?.matches('[data-lq-details-toggle]')), true, 'focus returns to Details');
    noErrors(page);
  });

  it('has no sidebar and nothing to select below 72rem', async () => {
    const page = await openPage(site.browser, 1024);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'audit log');
    assert.equal(await selected(page), null);
    assert.equal(await panelOpen(page), false);
    assert.equal(await page.$eval('[data-lq-details-toggle]', (b) => getComputedStyle(b).display), 'none');
    noErrors(page);
  });
});

describe('the conversation outlives a visit to a guide', () => {
  it('opens the guide from a title, and Back returns to that result', async () => {
    const page = await openPage(site.browser, 1440);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'audit log');
    const route = await page.$eval('.lq-search-turn li[data-route]:nth-child(2)', (li) => li.dataset.route);
    await Promise.all([page.waitForNavigation({ waitUntil: 'load' }), page.click(`li[data-route="${route}"] .lq-match-title`)]);
    assert.equal(new URL(page.url()).pathname, `${BASE}${route}/`, 'the title opens the guide page');

    await page.goBack({ waitUntil: 'load' });
    await page.waitForFunction((r) => document.querySelector('li[data-selected]')?.dataset.route === r, { timeout: 20000 }, route);
    const inView = await page.$eval('li[data-selected]', (li) => { const r = li.getBoundingClientRect(); return r.bottom > 0 && r.top < innerHeight; });
    assert.ok(inView, 'the opened result is in view');
    noErrors(page);
  });

  it('keeps the conversation through a reload', async () => {
    const page = await openPage(site.browser, 1024);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'docker');
    await page.reload({ waitUntil: 'load' });
    await page.waitForFunction(() => document.querySelectorAll('.lq-search-turn').length === 1, { timeout: 20000 });
    noErrors(page);
  });

  it('takes a question from a guide page to Explore, after the earlier ones', async () => {
    const page = await openPage(site.browser, 1440);
    await page.goto(url(), { waitUntil: 'load' });
    await searchOnExplore(page, 'docker');
    await page.goto(url(GUIDE), { waitUntil: 'load' });
    await page.waitForSelector('[data-lq-composer]:not([hidden]) input');
    await page.type('[data-lq-composer] input', 'privacy');
    await Promise.all([page.waitForNavigation({ waitUntil: 'load' }), page.keyboard.press('Enter')]);
    await page.waitForFunction(() => document.querySelectorAll('.lq-search-turn').length === 2, { timeout: 20000 });
    assert.deepEqual((await asks(page)).slice(4), ['Search for “docker”', 'Search for “privacy”']);
    const address = new URL(page.url());
    assert.equal(address.pathname, BASE);
    assert.equal(address.hash, '', 'the question is not left in the address');
    noErrors(page);
  });
});

describe('guide pages', () => {
  it('keep Explore one tap away on a phone', async () => {
    const page = await openPage(site.browser, 375, 812);
    await page.goto(url(GUIDE), { waitUntil: 'load' });
    const box = await page.$eval('.lq-pw-actions a[aria-label="Explore"]', (a) => { const r = a.getBoundingClientRect(); return { left: r.left, right: r.right, top: r.top, width: r.width }; });
    assert.ok(box.width >= 44 && box.left >= 0 && box.right <= 375 && box.top >= 0, `Explore button on screen (${JSON.stringify(box)})`);
    await Promise.all([page.waitForNavigation({ waitUntil: 'load' }), page.click('.lq-pw-actions a[aria-label="Explore"]')]);
    assert.equal(new URL(page.url()).pathname, BASE);
    noErrors(page);
  });

  it('move their facts to the right column on wide screens only', async () => {
    const visible = (page, selector) => page.$eval(selector, (el) => getComputedStyle(el).display !== 'none' && el.getClientRects().length > 0);
    const wide = await openPage(site.browser, 1440);
    await wide.goto(url(GUIDE), { waitUntil: 'load' });
    assert.equal(await visible(wide, '.lq-facts--about'), true);
    assert.equal(await visible(wide, '.lq-pw-page-title .lq-page-title__meta'), false);
    assert.match(await wide.$eval('.lq-facts--about', (el) => el.textContent), /Applies to v|Newer than v/, 'names the release');
    const narrow = await openPage(site.browser, 1024);
    await narrow.goto(url(GUIDE), { waitUntil: 'load' });
    assert.equal(await visible(narrow, '.lq-pw-page-title .lq-page-title__meta'), true);
    noErrors(wide); noErrors(narrow);
  });
});

describe('no page scrolls sideways', () => {
  for (const width of [375, 1024, 1440]) {
    it(`at ${width}px, on Explore with a search and on a guide`, async () => {
      const page = await openPage(site.browser, width, 812);
      await page.goto(url(), { waitUntil: 'load' });
      await searchOnExplore(page, 'docker');
      const wider = () => page.evaluate(() => document.documentElement.scrollWidth - innerWidth);
      assert.ok(await wider() <= 0, 'Explore');
      await page.goto(url(GUIDE), { waitUntil: 'load' });
      assert.ok(await wider() <= 0, 'guide');
      noErrors(page);
    });
  }
});
