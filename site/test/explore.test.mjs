import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { readerPayload } from '../scripts/lib/reader-assets.mjs';
import { exploreSearchHref, guideLocation, ReadingState, searchFromHash, TourState } from '../src/lib/explore-state.mjs';

const page = { route:'start/example', url:'/start/example/', title:'A source example', status:'draft',
  kind:'how-to', sha:'abc123', date:'2026-10-06', sources:['docs/example.md'] };
const html = `<html><head><link rel="stylesheet" href="/_astro/theme.css"></head><body><main>
<div class="lq-page-title__meta">Page status: draft</div>
<div class="sl-markdown-content"><h2 id="boundary">Data boundary</h2><a href="#boundary">This section</a>
<aside aria-labelledby="boundary">Cloud models can receive document content.</aside>
<figure class="lq-diagram"><picture><source media="(max-width: 600px)" srcset="/_diagrams/mobile.svg"><img src="/_diagrams/desktop.svg" alt="Local and cloud are alternative routes"></picture></figure>
<img src="/product/choose-skill.jpg" alt="Fictional NDA, ready status"><details><summary>Example limitations</summary>AI output requires review.</details>
<div class="expressive-code"><pre><code><div class="ec-line">first line</div><div class="ec-line">&lt;script&gt; is a code example</div></code></pre><div class="copy"><button>Old control</button></div></div>
<script type="module" src="/_astro/ec.fixture.js"></script></div>
<div class="lq-stamp">Checked against abc123 · docs/example.md</div></main></body></html>`;

describe('current guide previews', () => {
  it('retains diagrams, images, caveats, status, sources, code, and meaningful anchors', () => {
    const payload=readerPayload(html,page);
    for(const text of ['Cloud models can receive document content.','AI output requires review.','/_diagrams/mobile.svg','/_diagrams/desktop.svg','/product/choose-skill.jpg','&lt;script&gt;','first line']) assert.ok(payload.html.includes(text),text);
    assert.equal(payload.anchors.boundary,'lq-reader-content-boundary');
    assert.match(payload.html,/aria-labelledby="lq-reader-content-boundary"/);
    assert.match(payload.html,/href="\/start\/example\/#boundary"/);
    assert.match(payload.metadataHtml,/Page status: draft/);
    assert.match(payload.sourceHtml,/docs\/example.md/);
    assert.equal(payload.status,'draft');
    assert.deepEqual(payload.styles,['/_astro/theme.css']);
    assert.ok(!payload.html.includes('Old control'));
    assert.match(payload.html,/data-lq-copy="0"/);
    assert.ok(!payload.html.includes('<script'));
  });
  it('refuses unsupported interactive content rather than silently deleting instructions', () => {
    for(const content of ['<script>alert(1)</script>','<form>Required action</form>','<iframe src="https://example.com"></iframe>','<a onclick="alert(1)">A link</a>']) assert.throws(()=>readerPayload(html.replace('<h2',content+'<h2'),page),/active content|event handler/);
    assert.throws(()=>readerPayload('<main>No article.</main>',page),/no compiled/);
  });
});

describe('Explore navigation and continuity', () => {
  it('uses real permalinks and anchors under both bases, rejecting foreign and inherited routes', () => {
    for(const base of ['/','/lq-ai/']) {
      const pages={'start/example':{url:`${base}start/example/`}};
      const options={base,origin:'https://docs.example',pages};
      assert.deepEqual(guideLocation(`${base}start/example/#data%20boundary`,options),{route:'start/example',anchor:'data boundary',url:`${base}start/example/#data%20boundary`});
      for(const href of ['https://other.example/start/example/','javascript:alert(1)',`${base}toString/`,`${base}missing/`,`${base}start/example/#%bad`]) assert.equal(guideLocation(href,options),null);
    }
  });
  it('hands a search to Explore in the fragment only, and reads it back intact', () => {
    for(const base of ['/','/lq-ai/']) {
      const href=exploreSearchHref(base,'  install with docker & keys #1  ');
      assert.equal(href,`${base}#q=install%20with%20docker%20%26%20keys%20%231`);
      const url=new URL(href,'https://docs.example');
      assert.equal(url.search,'','the query never reaches the server');
      assert.equal(searchFromHash(url.hash),'install with docker & keys #1');
      assert.equal(exploreSearchHref(base,'   '),base);
    }
    assert.equal(searchFromHash(new URL(exploreSearchHref('/','x'.repeat(1500)),'https://docs.example').hash).length,1000);
    for(const hash of ['','#','#q=','#q=%20%20','#boundary','#q=%bad','#question=privacy']) assert.equal(searchFromHash(hash),null);
  });
  it('restores each guide’s own scroll, expanded sections, and list filter', () => {
    const state=new ReadingState();
    const expanded=[true,false];
    state.save('all',{scroll:400,expanded,filter:'NDA'});
    state.save('start/example',{scroll:100,expanded:[false],filter:''});
    expanded[0]=false;
    assert.deepEqual(state.restore('all'),{scroll:400,expanded:[true,false],filter:'NDA'});
    assert.deepEqual(state.restore('start/example'),{scroll:100,expanded:[false],filter:''});
    assert.deepEqual(state.restore('unvisited'),{scroll:0,expanded:[],filter:''});
  });
  it('plays only after opt-in, resumes from the paused step, and replays after completion', () => {
    const state=new TourState(3);
    assert.equal(state.next(),null);
    state.play(); assert.equal(state.next(),0);
    state.pause(); assert.equal(state.next(),null);
    state.play(); assert.equal(state.next(),1); assert.equal(state.next(),2);
    assert.equal(state.playing,false);
    state.play(); assert.equal(state.next(),0);
  });
});
