import { describe, expect, it } from 'vitest';
import { render } from 'svelte/server';

import LqButton from '../components/shared/LqButton.svelte';
import LqPill from '../components/shared/LqPill.svelte';
import LqSwitch from '../components/shared/LqSwitch.svelte';
import LqAlert from '../components/shared/LqAlert.svelte';
import LqGroup from '../components/shared/LqGroup.svelte';
import LqStack from '../components/shared/LqStack.svelte';
import LqText from '../components/shared/LqText.svelte';
import LqTitle from '../components/shared/LqTitle.svelte';
import LqCard from '../components/shared/LqCard.svelte';
import { LQ_TONES, LQ_GAP_VAR, LQ_TEXT_TONE_VAR, lqColorShade } from '../components/shared/types';

const attributes = {
	class: 'caller-class',
	'data-testid': 'forwarded',
	'aria-label': 'Accessible name'
};

describe('design primitive native attribute contract', () => {
	it('keeps button styling alongside caller attributes and native form/disabled behavior', () => {
		const html = render(LqButton, {
			props: {
				...attributes,
				tone: 'danger',
				variant: 'outline',
				type: 'submit',
				disabled: true,
				name: 'action',
				value: 'save',
				form: 'editor'
			}
		}).body;
		expect(html).toMatch(/<button[^>]*type="submit"/);
		expect(html).toContain('disabled');
		expect(html).toContain('name="action"');
		expect(html).toContain('value="save"');
		expect(html).toContain('form="editor"');
		expect(html).toContain('lq-btn-outline');
		expect(html).toContain('lq-tone-danger');
		for (const text of ['caller-class', 'data-testid="forwarded"', 'aria-label="Accessible name"'])
			expect(html).toContain(text);
	});

	it('forwards pill attributes to its outer span and keeps activation and removal as sibling buttons', () => {
		const html = render(LqPill, {
			props: { ...attributes, text: 'Skill', tone: 'info', onClick: () => {}, onRemove: () => {} }
		}).body;
		expect(html).toMatch(
			/<span[^>]*data-testid="forwarded"[^>]*class="[^"]*lq-pill[^"]*caller-class/
		);
		expect(html).toContain('aria-label="Accessible name"');
		expect(html).toContain('lq-pill-tone-info');
		expect(html.match(/<button\b/g)).toHaveLength(2);
		expect(html).toMatch(/<\/button>\s*(?:<!--.*?-->\s*)*<button/s);
		expect(html).toContain('aria-label="Remove Skill"');
		expect(render(LqPill, { props: { text: 'Static' } }).body).not.toContain('<button');
	});

	it('puts switch hooks and its accessible name on the actual switch control', () => {
		const html = render(LqSwitch, {
			props: { ...attributes, checked: true, disabled: true, tone: 'accent' }
		}).body;
		const button = html.match(/<button\b[^>]*>/)?.[0] ?? '';
		for (const text of [
			'role="switch"',
			'aria-checked="true"',
			'aria-label="Accessible name"',
			'data-testid="forwarded"',
			'lq-switch',
			'caller-class',
			'disabled'
		])
			expect(button).toContain(text);
	});

	it('allows a non-urgent status announcement without overriding it with alert', () => {
		const html = render(LqAlert, {
			props: { ...attributes, tone: 'warning', role: 'status' }
		}).body;
		expect(html).toContain('role="status"');
		expect(html).not.toContain('role="alert"');
		expect(html).toContain('lq-alert-tone-warning');
		expect(html).toContain('caller-class');
	});

	it.each([
		['group', () => render(LqGroup, { props: attributes }).body],
		['stack', () => render(LqStack, { props: attributes }).body],
		['text', () => render(LqText, { props: { ...attributes, as: 'label', for: 'field' } }).body],
		['title', () => render(LqTitle, { props: { ...attributes, order: 2 } }).body],
		['card', () => render(LqCard, { props: attributes }).body]
	])('preserves the same class and attribute contract on %s', (_name, markup) => {
		const html = markup();
		for (const text of ['caller-class', 'data-testid="forwarded"', 'aria-label="Accessible name"'])
			expect(html).toContain(text);
	});
});

describe('semantic roles preserve the existing palette and spacing', () => {
	it('exports only the agreed roles and maps their base shades to existing CSS families', () => {
		expect(LQ_TONES).toEqual(['accent', 'info', 'warning', 'danger', 'neutral']);
		const values = [
			'var(--lq-accent, #1f7a6b)',
			'var(--lq-tier, #355a82)',
			'var(--lq-warn, #a16e1f)',
			'var(--lq-error, #b54848)',
			'var(--lq-text-secondary, #4b5563)'
		];
		LQ_TONES.forEach((tone, index) => {
			expect(lqColorShade(tone, 5)).toBe(values[index]);
			expect(LQ_TEXT_TONE_VAR[tone]).toBe(values[index]);
			expect(render(LqButton, { props: { tone } }).body).toContain(`lq-tone-${tone}`);
		});
	});

	it('uses spacing fallbacks that match practice.css even outside the shell', () => {
		expect(LQ_GAP_VAR).toEqual({
			xs: 'var(--lq-space-1, 4px)',
			sm: 'var(--lq-space-2, 8px)',
			md: 'var(--lq-space-4, 16px)',
			lg: 'var(--lq-space-6, 24px)',
			xl: 'var(--lq-space-8, 32px)'
		});
		expect(render(LqStack, { props: { gap: 'md' } }).body).toContain(
			'gap: var(--lq-space-4, 16px)'
		);
		expect(render(LqGroup, { props: { gap: 12 } }).body).toContain('gap: 12px');
	});
});
