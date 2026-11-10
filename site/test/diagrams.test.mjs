import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { DIAGRAM_COLORS, diagramMetadata, findDiagrams, portraitSource, diagramKey,
  replaceDiagrams, validateSvg, intrinsicSvg, diagramFigure } from '../scripts/lib/diagrams.mjs';
import { satteri } from '@astrojs/markdown-satteri';

const source = 'flowchart LR\naccTitle: A question and answer\naccDescr: A question reaches the gateway and an answer returns.\nA["Question"] --> B["Gateway"]';
const assets = {
  light: { landscape: '/_diagrams/light.svg', portrait: '/_diagrams/light-mobile.svg' },
  dark: { landscape: '/_diagrams/dark.svg', portrait: '/_diagrams/dark-mobile.svg' },
};

describe('canonical diagram definitions', () => {
  it('renders generated pictures and literal Mermaid braces through the classic MDX processor', async () => {
    const processor = await satteri().createMdxRenderer(
      { syntaxHighlight: false, gfm: true, smartypants: false },
      { srcDir: new URL('../src/', import.meta.url), optimize: false, sourcemap: false }
    );
    const figure = diagramFigure({ title: 'A branching flow', description: 'Keep the condition visible.', source: 'flowchart LR\nA{Condition} --> B' }, assets);
    const result = await processor.process(`## Diagram\n\n${figure}`, '/tmp/lq-diagram-regression.mdx', {});
    assert.match(result.code, /lq-diagram/);
    assert.match(result.code, /A\{Condition\}/);
  });
  it('keeps diagram text and boundary lines legible in both themes', () => {
    const luminance = (hex) => {
      const channels = hex.slice(1).match(/../g).map((channel) => parseInt(channel, 16) / 255)
        .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
      return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
    };
    const ratio = (a, b) => (Math.max(luminance(a), luminance(b)) + 0.05) /
      (Math.min(luminance(a), luminance(b)) + 0.05);
    for (const colors of Object.values(DIAGRAM_COLORS)) {
      assert.ok(ratio(colors.primaryTextColor, colors.primaryColor) >= 4.5);
      assert.ok(ratio(colors.titleColor, colors.clusterBkg) >= 4.5);
      assert.ok(ratio(colors.lineColor, colors.background) >= 3);
    }
  });
  it('requires a complete accessible description for a rendered diagram', () => {
    assert.equal(diagramMetadata('flowchart LR\nA --> B'), null);
    assert.throws(() => diagramMetadata('flowchart LR\naccTitle: Missing description'), /accDescr/);
    assert.equal(diagramMetadata(source).title, 'A question and answer');
    for (const directive of ['%%{init: {"securityLevel":"loose"}}%%', 'click A "https://example.com"', '---\nconfig: {}\n---']) {
      assert.throws(() => diagramMetadata(source + '\n' + directive), /directives/);
    }
  });

  it('does not render a Mermaid example nested inside a longer code fence', () => {
    const example = '````markdown\n```mermaid\n' + source + '\n```\n````';
    assert.deepEqual(findDiagrams(example), []);
    assert.equal(findDiagrams('~~~mermaid\n' + source + '\n~~~')[0].line, 1);
    assert.throws(() => findDiagrams('```mermaid\n' + source), /unclosed/);
  });

  it('changes layout direction without changing graph nodes or edge meaning', () => {
    const portrait = portraitSource(source + '\nsubgraph GROUP\ndirection LR\nend');
    assert.ok(portrait.startsWith('flowchart TB'));
    assert.match(portrait, /direction TB/);
    assert.match(portrait, /A\["Question"\] --> B\["Gateway"\]/);
    assert.notEqual(diagramKey(source, 'light', 'v1'), diagramKey(source, 'dark', 'v1'));
    assert.notEqual(diagramKey(source, 'light', 'v1'), diagramKey(source, 'light', 'v2'));
    const stacked = portraitSource(source + '\n%% portrait-stack: A B');
    assert.match(stacked, /A ~~~ B/);
    assert.match(stacked, /A\["Question"\] --> B\["Gateway"\]/);
    assert.throws(() => portraitSource(source + '\n%% portrait-stack: A Missing'), /declared nodes/);
  });

  it('retains boundary membership as labels when flattening a narrow-screen graph', () => {
    const source = 'flowchart LR\n%% portrait-flat\nsubgraph inside["Your environment"]\nA["Gateway"]\nend\nsubgraph outside["External endpoints, when enabled"]\nB["Cloud"]\nend\nA -->|Chat| B';
    const portrait = portraitSource(source);
    assert.ok(!portrait.includes('subgraph'));
    assert.match(portrait, /A\["`Your environment\nGateway`"\]/);
    assert.match(portrait, /B\["`External\nendpoints, when\nenabled\nCloud`"\]/);
    assert.match(portrait, /A -->\|Chat\| B/);
    assert.throws(() => portraitSource(source.replace('A["Gateway"]', 'A("Gateway")')), /rectangular/);
  });

  it('preserves source and qualifications while replacing only human diagram fences', async () => {
    const input = 'Required qualification.\n\n```mermaid\n' + source + '\n```\n\nKeep this limitation.';
    const output = await replaceDiagrams(input, async () => assets);
    assert.equal(output.count, 1);
    assert.match(output.markdown, /Required qualification/);
    assert.match(output.markdown, /Keep this limitation/);
    assert.match(output.markdown, /<figure class="lq-diagram"/);
    assert.match(output.markdown, /srcset="\/_diagrams\/light-mobile.svg"/);
    assert.match(output.markdown, /A\[&quot;Question&quot;\] --&gt; B\[&quot;Gateway&quot;\]/);
    assert.ok(input.includes(source), 'the canonical input was changed');
  });

  it('rejects active or remote SVG output while allowing local SVG references', () => {
    assert.equal(validateSvg('<svg viewBox="0 0 10 10"><path style="fill:url(#paint)"/></svg>'), '<svg viewBox="0 0 10 10"><path style="fill:url(#paint)"/></svg>');
    for (const element of ['<script/>', '<foreignObject/>', '<g onclick="x()"/>', '<image href="https://example.com/x"/>', '<image href="//example.com/x"/>', '<path style="fill:url(data:image/svg+xml,x)"/>']) {
      assert.throws(() => validateSvg(`<svg viewBox="0 0 10 10">${element}</svg>`), /active or remote/);
    }
  });

  it('gives the image an intrinsic size so compact diagrams are not enlarged or distorted', () => {
    const svg = intrinsicSvg('<svg width="100%" viewBox="-8 -8 400.2 600.4"><path/></svg>');
    assert.match(svg, /width="401" height="601"/);
    assert.ok(!svg.includes('width="100%"'));
    assert.throws(() => intrinsicSvg('<svg viewBox="0 0 0 20"/>'), /invalid diagram viewBox/);
  });
});
