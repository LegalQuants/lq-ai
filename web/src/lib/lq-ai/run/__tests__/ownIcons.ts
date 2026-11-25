/**
 * Exact server-rendered SVGs owned by RunLine and the run warning notes.
 * The text-escaping tests remove only these known renderings before checking the page.
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

const SVG = /<svg\b[^>]*>[\s\S]*?<\/svg>/g;

// RunLine draws 12px state marks. The notes use LqToneIcon's default warning profile.
// Compare whole SVGs so the opening tag, classes and body must match together.
const ownMarkup = new Set<string>();
for (const [name, component] of Object.entries(RUN_OWN_ICONS)) {
	const props =
		name === 'alert-triangle'
			? { size: 14, stroke: 1.75, class: 'lq-tone-icon ', 'aria-hidden': true }
			: { size: 12, stroke: 2, 'aria-hidden': true };
	const icons = render(component, { props }).body.match(SVG);
	if (icons?.length !== 1) throw new Error(`Expected one Tabler SVG for ${name}`);
	ownMarkup.add(icons[0]);
	// The render-test reader also inspects markup with Svelte's SSR comments removed.
	ownMarkup.add(icons[0].replace(/<!--[^>]*-->/g, ''));
}

export function isOwnIcon(svg: string): boolean {
	return ownMarkup.has(svg);
}

/** The markup with the run components' own icons taken out; every other svg stays. */
export function withoutOwnIcons(html: string): string {
	return html.replace(SVG, (svg) => (isOwnIcon(svg) ? '' : svg));
}
