/** Extract the same compiled article used by the full page, never a saved corpus. */
import { load } from 'cheerio';

/**
 * Navigation pages (pathway hubs, All documentation) carry no `url` in the
 * manifest. The reader puts a page's URL in the address bar and in its
 * in-page links, so derive it from the route rather than write "undefined".
 */
export function readerPage(page, base) {
  return page.url ? page : { ...page, url: `${base}${page.route}/` };
}

export function readerPayload(html, page) {
  const dom = load(html);
  const article = dom('main .sl-markdown-content').first();
  if (!article.length) throw new Error(`${page.route}: no compiled documentation article`);
  // Expressive Code places its generated initializer beside the code block.
  // The preview supplies its own copy behavior; do not re-execute that module.
  article.find('script[type="module"][src]').each((_index, element) => {
    if (/\/_astro\/ec\.[\w-]+\.js$/.test(dom(element).attr('src'))) dom(element).remove();
  });
  if (article.find('script,iframe,object,embed,base,form,input,textarea,select').length) {
    throw new Error(`${page.route}: unsupported active content in guide preview`);
  }
  article.find('*').each((_index, element) => {
    if (Object.keys(element.attribs ?? {}).some((name) => /^on/i.test(name))) throw new Error(`${page.route}: inline event handler in guide preview`);
  });
  // Expressive Code's page initialization does not run on inserted content.
  // Retain its rendered code, supplying a reader-owned copy control instead.
  article.find('.expressive-code .copy').remove();
  article.find('pre').each((index, element) => {
    dom(element).attr('data-lq-code', String(index));
    dom(element).before(`<button type="button" class="lq-reader-copy" data-lq-copy="${index}">Copy code</button>`);
  });
  const anchors = {};
  article.find('[id]').each((_index, element) => {
    const id = dom(element).attr('id');
    anchors[id] = `lq-reader-content-${id}`;
    dom(element).attr('id', anchors[id]);
  });
  article.find('*').each((_index, element) => {
    for (const attribute of ['aria-labelledby', 'aria-describedby', 'aria-controls', 'for']) {
      const value = dom(element).attr(attribute);
      if (value) dom(element).attr(attribute, value.split(/\s+/).map((id) => anchors[id] ?? id).join(' '));
    }
    const href = dom(element).attr('href');
    if (href?.startsWith('#')) dom(element).attr('href', `${page.url}${href}`);
  });
  return {
    schemaVersion: 1, route: page.route, url: page.url, title: page.title,
    description: page.description, status: page.status, kind: page.contentKind ?? page.kind,
    checkedAgainst: { sha: page.sha, date: page.date }, sources: page.sources ?? [],
    html: article.html(), anchors,
    metadataHtml: dom('main .lq-page-title__meta').first().toString(),
    sourceHtml: dom('main .lq-stamp').last().toString(),
    styles: [...new Set(dom('link[rel="stylesheet"]').filter((_i, el) => dom(el).attr('media') !== 'print').map((_i, el) => dom(el).attr('href')).get())],
  };
}
