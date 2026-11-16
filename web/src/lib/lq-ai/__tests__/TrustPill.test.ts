import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';
import TrustPill, { toneClassFor, labelFor, markFor } from '../components/TrustPill.svelte';

describe('TrustPill helpers', () => {
  it('maps secure variant to sage tone by default', () => {
    expect(toneClassFor('secure', undefined)).toBe('lq-pill-tone-sage');
  });

  it('maps tier variant to slate tone by default', () => {
    expect(toneClassFor('tier', undefined)).toBe('lq-pill-tone-slate');
  });

  it('honors explicit override tone', () => {
    expect(toneClassFor('tier', 'amber')).toBe('lq-pill-tone-amber');
    expect(toneClassFor('secure', 'red')).toBe('lq-pill-tone-red');
  });

  it('falls back to neutral for unknown variants', () => {
    // @ts-expect-error testing runtime fallback
    expect(toneClassFor('mystery', undefined)).toBe('lq-pill-tone-neutral');
  });

  it('labelFor shows no glyph in dot mode (ADR 0045 §5: no glyphs as icons)', () => {
    expect(labelFor('self-hosted', 'dot')).toBe('');
    expect(labelFor('self-hosted', 'label')).toBe('self-hosted');
  });

  it('markFor: the lock and the warning icon win over the dot', () => {
    expect(markFor('secure', 'slate', { lock: true })).toBe('lock');
    expect(markFor('warn', undefined)).toBe('warning');
    expect(markFor('audit', 'amber', { dot: true })).toBe('warning');
    expect(markFor('secure', undefined, { dot: true })).toBe('dot');
    expect(markFor('secure', undefined, { display: 'dot' })).toBe('dot');
    expect(markFor('tier', undefined)).toBeNull();
    expect(markFor('error', undefined)).toBeNull();
  });
});

describe('TrustPill marks render as Tabler icons (SSR)', () => {
  const pill = (props: Record<string, unknown>) => render(TrustPill, { props: props as never }).body;

  it('a warn pill carries the warning icon, hidden, and keeps its accessible name', () => {
    const html = pill({ variant: 'warn', label: 'Archived' });
    expect(html).toContain('aria-label="Archived"');
    expect(html).toMatch(/<svg(?=[^>]*tabler-icon-alert-triangle)(?=[^>]*aria-hidden="true")/);
    expect(html.replace(/<!--[^>]*-->/g, '')).toMatch(/>\s*Archived\s*</);
  });

  it('a privileged pill draws the lock, not the dot, and is still named "Privileged"', () => {
    const html = pill({ variant: 'secure', tone: 'slate', lock: true, label: 'Privileged' });
    expect(html).toContain('aria-label="Privileged"');
    expect(html).toMatch(/<svg(?=[^>]*tabler-icon-lock)(?=[^>]*aria-hidden="true")/);
    expect(html).toContain('lq-pill-locked');
  });

  it('a status dot replaces the "● " callers used to put in the label', () => {
    const html = pill({ variant: 'secure', dot: true, label: 'self-hosted' });
    expect(html).toContain('aria-label="self-hosted"');
    expect(html).toMatch(/<span class="lq-pill-mark[^"]*" aria-hidden="true">/);
    expect(html).not.toContain('●');
  });

  it('a plain pill has no mark and no svg', () => {
    const html = pill({ variant: 'provider', label: 'ollama-local' });
    expect(html).not.toContain('<svg');
    expect(html).not.toContain('lq-pill-mark');
  });

  it('dot display keeps the name but shows no text glyph', () => {
    const html = pill({ variant: 'secure', display: 'dot', label: 'self-hosted' });
    expect(html).toContain('aria-label="self-hosted"');
    expect(html).not.toContain('●');
    expect(html).toContain('lq-pill-mark');
  });
});
