/**
 * The Tabler icons the run components draw themselves, and nothing else.
 *
 * The run panel's render tests are an injection guard: no `<svg>` may appear in a page
 * built from untrusted text. Since S1-3b (ADR 0045 §5) the components draw a few Tabler
 * line icons of their own: RunLine's state marks, and the warning icon on four notes.
 * `withoutOwnIcons` removes exactly those, so the guard still fails on any other svg.
 *
 * An svg counts as one of ours only when all of these hold:
 *  - its class names one of the icons below (`tabler-icon tabler-icon-<name>`);
 *  - its attributes are Tabler's own, with Tabler's values: no event handler, no link;
 *  - it is hidden from assistive technology (`aria-hidden="true"`);
 *  - its body is exactly the body that Tabler icon renders, character for character.
 * A forged svg that borrows the class, an icon not on the list, or a real icon with an
 * extra attribute or a changed body is left in the markup, and the guard catches it.
 */
import { render } from 'svelte/server';
import {
	IconAlertTriangle,
	IconCheck,
	IconCircle,
	IconCircleDot,
	IconMinus,
	IconSquare
} from '@tabler/icons-svelte';

/** Every icon the run components may draw: RunLine's marks and the notes' warning icon. */
export const RUN_OWN_ICONS = {
	'alert-triangle': IconAlertTriangle,
	check: IconCheck,
	circle: IconCircle,
	'circle-dot': IconCircleDot,
	minus: IconMinus,
	square: IconSquare
} as const;

const withoutComments = (html: string) => html.replace(/<!--[^>]*-->/g, '');
const SVG = /<svg\b([^>]*)>([\s\S]*?)<\/svg>/g;
const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
const NUMBER = /^\d+(?:\.\d+)?$/;

/** Tabler's attributes and the values they may take; `class` and `aria-hidden` are checked apart. */
const TABLER_VALUES: Record<string, (value: string) => boolean> = {
	xmlns: (v) => v === 'http://www.w3.org/2000/svg',
	width: (v) => NUMBER.test(v),
	height: (v) => NUMBER.test(v),
	viewbox: (v) => v === '0 0 24 24',
	fill: (v) => v === 'none',
	stroke: (v) => v === 'currentColor',
	'stroke-width': (v) => NUMBER.test(v),
	'stroke-linecap': (v) => v === 'round',
	'stroke-linejoin': (v) => v === 'round'
};
const CLASS = /^tabler-icon tabler-icon-([a-z0-9-]+)(?:\s+[\w-]+)*\s*$/;

function bodyOf(component: unknown): string {
	const html = withoutComments(render(component as never, { props: {} as never }).body);
	const match = /<svg\b[^>]*>([\s\S]*?)<\/svg>/.exec(html);
	if (!match) throw new Error('a Tabler icon rendered no svg');
	return match[1];
}

const BODIES = new Map<string, string>(
	Object.entries(RUN_OWN_ICONS).map(([name, component]) => [name, bodyOf(component)])
);

/** Whether one `<svg …>…</svg>` is exactly one of the run components' own icons. */
export function isOwnIcon(svg: string): boolean {
	const match = /^<svg\b([^>]*)>([\s\S]*?)<\/svg>$/.exec(svg);
	if (!match) return false;
	let name: string | undefined;
	let hidden = false;
	for (const attribute of match[1].matchAll(ATTRIBUTE)) {
		const key = attribute[1].toLowerCase();
		const value = attribute[2] ?? attribute[3] ?? attribute[4] ?? '';
		if (key === 'class') {
			name = CLASS.exec(value)?.[1];
			if (!name) return false;
		} else if (key === 'aria-hidden') {
			if (value !== 'true') return false;
			hidden = true;
		} else if (!TABLER_VALUES[key]?.(value)) {
			return false;
		}
	}
	if (!name || !hidden || !BODIES.has(name)) return false;
	return withoutComments(match[2]) === BODIES.get(name);
}

/** The markup with the run components' own icons taken out; every other svg stays. */
export function withoutOwnIcons(html: string): string {
	return html.replace(SVG, (svg) => (isOwnIcon(svg) ? '' : svg));
}
