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
import {
	LQ_TONES,
	LQ_GAP_VAR,
	LQ_LEADING_VAR,
	LQ_TEXT_ELEMENTS,
	LQ_TEXT_SIZE_VAR,
	LQ_TEXT_TONE_VAR,
	LQ_TRACKING_VAR,
	LQ_TYPE_SCALE,
	lqColorShade
} from '../components/shared/types';

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

describe('semantic roles follow the ADR 0045 palette and keep the spacing', () => {
	it('exports only the agreed roles and maps their base shades to the ADR 0045 role tokens', () => {
		expect(LQ_TONES).toEqual(['accent', 'governance', 'info', 'warning', 'danger', 'neutral']);
		const values = [
			'var(--lq-accent, #111114)',
			'var(--lq-governance, #a34a00)',
			'var(--lq-info, #111114)',
			'var(--lq-warning, #111114)',
			'var(--lq-danger, #b42318)',
			'var(--lq-text-secondary, #4f5158)'
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

// Server render wraps output in hydration comments; drop them to see the element.
const markupOf = (html: string) => html.replace(/<!--[^>]*-->/g, '');

describe('text and titles carry the ADR 0045 type scale', () => {
	it('names every step of the scale and renders each one at its size', () => {
		expect(LQ_TYPE_SCALE).toEqual([
			'11',
			'12',
			'12.5',
			'13',
			'13.5',
			'14',
			'14.5',
			'16',
			'20',
			'24',
			'26',
			'32'
		]);
		for (const step of LQ_TYPE_SCALE) {
			expect(LQ_TEXT_SIZE_VAR[step]).toBe(`${step}px`);
			expect(render(LqText, { props: { size: step } }).body).toContain(`font-size: ${step}px`);
			expect(render(LqTitle, { props: { size: step } }).body).toContain(`font-size: ${step}px`);
		}
	});

	it('keeps the older named text sizes their callers use, on the scale', () => {
		expect(LQ_TEXT_SIZE_VAR).toMatchObject({
			xs: '12px',
			sm: '13px',
			md: '14px',
			lg: '16px',
			xl: '20px'
		});
		for (const value of Object.values(LQ_TEXT_SIZE_VAR))
			expect(LQ_TYPE_SCALE.map((step) => `${step}px`)).toContain(value);
	});

	it('draws the uppercase label style without a CSS class', () => {
		const html = render(LqText, {
			props: {
				as: 'span',
				size: '12',
				weight: 'semibold',
				tone: 'tertiary',
				transform: 'uppercase',
				tracking: 'wide'
			}
		}).body;
		expect(markupOf(html)).toMatch(/^<span[\s>]/);
		for (const declaration of [
			'font-size: 12px',
			'font-weight: 600',
			'color: var(--lq-text-tertiary, #65676f)',
			'letter-spacing: 0.06em',
			'text-transform: uppercase'
		])
			expect(html).toContain(declaration);
	});

	it('leaves line height and letter spacing to the page unless asked', () => {
		const plain = render(LqText, { props: {} }).body;
		expect(plain).not.toContain('line-height');
		expect(plain).not.toContain('letter-spacing');
		expect(render(LqText, { props: { leading: 'relaxed' } }).body).toContain('line-height: 1.6');
		expect(render(LqTitle, { props: { leading: 'tight' } }).body).toContain('line-height: 1.3');
		expect(LQ_LEADING_VAR).toEqual({ tight: '1.3', snug: '1.4', relaxed: '1.6' });
		expect(LQ_TRACKING_VAR).toEqual({ normal: 'normal', wide: '0.06em' });
	});

	it('renders as each text element the old classes were used on', () => {
		expect(LQ_TEXT_ELEMENTS).toEqual([
			'p',
			'span',
			'div',
			'label',
			'li',
			'th',
			'td',
			'a',
			'strong',
			'code',
			'legend',
			'article',
			'table'
		]);
		for (const element of LQ_TEXT_ELEMENTS)
			expect(markupOf(render(LqText, { props: { as: element } }).body)).toMatch(
				new RegExp(`^<${element}[\\s>]`)
			);
	});

	it('takes its heading level from order and its size from the scale', () => {
		const sizes = { 1: '32px', 2: '26px', 3: '20px', 4: '16px', 5: '14.5px', 6: '14px' };
		for (const [order, size] of Object.entries(sizes)) {
			const html = render(LqTitle, { props: { order: Number(order) as 1 } }).body;
			expect(markupOf(html)).toMatch(new RegExp(`^<h${order}[\\s>]`));
			expect(html).toContain(`font-size: ${size}`);
			expect(html).toContain('font-weight: 700');
		}
		const page = render(LqTitle, {
			props: { order: 1, size: '20', weight: 'semibold', tone: 'primary' }
		}).body;
		expect(markupOf(page)).toMatch(/^<h1[\s>]/);
		expect(page).toContain('font-size: 20px');
		expect(page).toContain('font-weight: 600');
		expect(page).toContain('color: var(--lq-text, #111114)');
	});
});
