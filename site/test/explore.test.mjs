import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { detailsPage, guideDetails } from '../scripts/lib/guide-details.mjs';
import { exploreSearchHref, recallSearches, rememberSearches, searchFromHash, TourState } from '../src/lib/explore-state.mjs';

const page = { route:'start/example', url:'/start/example/', title:'A source example', status:'draft',
  contentKind:'how-to', description:'Try it on a fictional NDA.', audience:['operator'],
  sha:'abc123', date:'2026-10-06', sources:['docs/example.md'] };
const html = `<html><body><main>
<div class="lq-page-title__meta">Page status: draft</div>
<div class="sl-markdown-content"><div class="sl-heading-wrapper level-h2"><h2 id="boundary">Data boundary</h2><a class="sl-anchor-link" href="#boundary"><span class="sr-only">Section titled “Data boundary”</span></a></div>
<p>Cloud models can receive document content.</p><h3 id="detail">A detail</h3><h2 id="check">Check that it worked</h2></div>
</main></body></html>`;

describe('guide details for Explore’s sidebar', () => {
  it('lists the guide’s sections with the ids the page gives them, and its facts as text', () => {
    const details=guideDetails(html,page);
    assert.deepEqual(details.sections,[{id:'boundary',title:'Data boundary'},{id:'check',title:'Check that it worked'}]);
    assert.equal(details.kindLabel,'How-to');
    assert.equal(details.description,'Try it on a fictional NDA.');
    assert.deepEqual(details.audience,['operator']);
    assert.equal(details.checkedAgainst.href,'https://github.com/LegalQuants/lq-ai/commit/abc123');
    assert.deepEqual(details.sources,[{path:'docs/example.md',href:'https://github.com/LegalQuants/lq-ai/blob/abc123/docs/example.md'}]);
    assert.ok(!JSON.stringify(details).includes('<'),'no markup reaches the page');
  });
  it('gives navigation pages a real permalink, which the manifest leaves out', () => {
    for(const base of ['/','/lq-ai/']) {
      const hub=detailsPage({route:'pathways/install',title:'How to install',status:'draft',kind:'navigation',sources:[]},base);
      assert.equal(hub.url,`${base}pathways/install/`);
      assert.equal(guideDetails(html,hub).url,`${base}pathways/install/`);
      assert.equal(detailsPage(page,base),page,'a page with its own URL keeps it');
    }
  });
  it('lists no sources without the commit they were checked at', () => {
    const unstamped=guideDetails(html,{...page,sha:undefined});
    assert.equal(unstamped.checkedAgainst,null);
    assert.deepEqual(unstamped.sources,[]);
    assert.throws(()=>guideDetails('<main>No article.</main>',page),/no compiled/);
  });
});

describe('Explore navigation and continuity', () => {
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
  it('remembers this tab’s searches and the result to come back to, and nothing else', () => {
    const memory=recallSearches(rememberSearches({queries:['  docker ',' privacy'],selected:'trust/anonymization',turn:1,scroll:812.4}));
    assert.deepEqual(memory,{queries:['docker','privacy'],selected:'trust/anonymization',turn:1,scroll:812});
    const many=Array.from({length:30},(_,i)=>'q'+i);
    const kept=recallSearches(rememberSearches({queries:many,selected:'start',turn:25}));
    assert.deepEqual(kept.queries,many.slice(-20),'the newest twenty');
    assert.equal(kept.queries[kept.turn],'q25','the result stays with its own search');
    assert.equal(recallSearches(rememberSearches({queries:many,selected:'start',turn:3})).selected,null,'its search was dropped');
    assert.equal(recallSearches(rememberSearches({queries:['x'.repeat(1500)]})).queries[0].length,1000);
    for(const raw of ['','not json','null','[]','{"queries":"docker"}']) assert.equal(recallSearches(raw),null,raw);
    assert.deepEqual(recallSearches('{"queries":["ok"],"selected":42,"turn":0,"scroll":-5}'),{queries:['ok'],selected:null,turn:null,scroll:0});
    assert.deepEqual(recallSearches('{"queries":["ok"],"selected":"start","turn":4}'),{queries:['ok'],selected:null,turn:null,scroll:0});
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
