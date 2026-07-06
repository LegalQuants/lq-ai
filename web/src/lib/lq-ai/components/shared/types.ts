/**
 * Shared prop vocabulary for the `lq` design-system primitives.
 *
 * Single source of truth: each option list is a `const` array, and every
 * primitive's prop type is derived from it (`(typeof X)[number]`) rather than
 * a hand-typed string-literal union. Adding an option here — and only here —
 * updates every primitive's types and editor autocomplete at once.
 */

export const LQ_VARIANTS = ['filled', 'outline', 'subtle', 'ghost'] as const;
export type LqVariant = (typeof LQ_VARIANTS)[number];

export const LQ_TONES = ['sage', 'slate', 'amber', 'red', 'neutral'] as const;
export type LqTone = (typeof LQ_TONES)[number];

export const LQ_SIZES = ["xs", "sm", "md", "lg"] as const;
export type LqSize = (typeof LQ_SIZES)[number];

// justify-content / align-items vocabularies for LqGroup/LqStack. These were
// plain `string` props until now — the one inconsistency in this file's
// "every prop is a derived union, not a bare string" rule. Kept to the
// values these two components actually support (flex containers), not the
// full CSS justify-content/align-items keyword set.
export const LQ_JUSTIFY = [
	'flex-start',
	'center',
	'flex-end',
	'space-between',
	'space-around',
	'space-evenly'
] as const;
export type LqJustify = (typeof LQ_JUSTIFY)[number];

export const LQ_ALIGN = ['flex-start', 'center', 'flex-end', 'stretch', 'baseline'] as const;
export type LqAlign = (typeof LQ_ALIGN)[number];

// Mantine-style spacing scale, mapped onto this project's `--lq-space-*`
// tokens (see styles/practice.css) so layout primitives (Group, Stack, ...)
// share the same gap vocabulary as everything else.
export const LQ_GAPS = ['xs', 'sm', 'md', 'lg', 'xl'] as const;
export type LqGap = (typeof LQ_GAPS)[number];

export const LQ_GAP_VAR: Record<LqGap, string> = {
	xs: 'var(--lq-space-1, 2px)',
	sm: 'var(--lq-space-2, 4px)',
	md: 'var(--lq-space-4, 8px)',
	lg: 'var(--lq-space-6, 16px)',
	xl: 'var(--lq-space-8, 24px)'
};

// Mantine-style elevation scale. Not backed by a practice.css token today
// (there's no --lq-shadow-* set yet) — values are plain box-shadow strings
// here, one place to promote them to CSS custom properties later without
// touching any component that consumes LqShadow.
export const LQ_SHADOWS = ['xs', 'sm', 'md', 'lg', 'xl'] as const;
export type LqShadow = (typeof LQ_SHADOWS)[number];

export const LQ_SHADOW_VAR: Record<LqShadow, string> = {
	xs: '0 1px 2px rgba(0, 0, 0, 0.05)',
	sm: '0 1px 3px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.06)',
	md: '0 4px 6px rgba(0, 0, 0, 0.08), 0 2px 4px rgba(0, 0, 0, 0.06)',
	lg: '0 10px 15px rgba(0, 0, 0, 0.1), 0 4px 6px rgba(0, 0, 0, 0.05)',
	xl: '0 20px 25px rgba(0, 0, 0, 0.12), 0 8px 10px rgba(0, 0, 0, 0.06)'
};

// Text weight scale — named steps (rather than raw fw numbers, like
// Mantine's Text `fw`) to match this file's semantic-name convention.
export const LQ_WEIGHTS = ['normal', 'medium', 'semibold', 'bold'] as const;
export type LqWeight = (typeof LQ_WEIGHTS)[number];

export const LQ_WEIGHT_VAR: Record<LqWeight, string> = {
	normal: '400',
	medium: '500',
	semibold: '600',
	bold: '700'
};

// Text-specific size scale. Deliberately separate from LqSize (Button's
// sm/md/lg) — Text needs an xs/xl step Button has no CSS for.
export const LQ_TEXT_SIZES = ['xs', 'sm', 'md', 'lg', 'xl'] as const;
export type LqTextSize = (typeof LQ_TEXT_SIZES)[number];

export const LQ_TEXT_SIZE_VAR: Record<LqTextSize, string> = {
	xs: '12px',
	sm: '13px',
	md: '14px',
	lg: '16px',
	xl: '18px'
};

// Text color: the text-hierarchy trio from practice.css (primary/secondary/
// tertiary) plus the five semantic tones already used for emphasis/status
// elsewhere (TrustPill, LqButton) — one color vocabulary for text everywhere.
export const LQ_TEXT_TONES = ['primary', 'secondary', 'tertiary', ...LQ_TONES] as const;
export type LqTextTone = (typeof LQ_TEXT_TONES)[number];

export const LQ_TEXT_TONE_VAR: Record<LqTextTone, string> = {
	primary: 'var(--lq-text, #1a1a1a)',
	secondary: 'var(--lq-text-secondary, #4b5563)',
	tertiary: 'var(--lq-text-tertiary, #9ca3af)',
	sage: 'var(--lq-accent, #1f7a6b)',
	slate: 'var(--lq-tier, #355a82)',
	amber: 'var(--lq-warn, #a16e1f)',
	red: 'var(--lq-error, #b54848)',
	neutral: 'var(--lq-text-secondary, #4b5563)'
};

// --- Color + shade ---------------------------------------------------------
//
// `tone` (above) is the pre-bundled look every primitive has used so far:
// pick "sage" and you get its soft background + base text + border all at
// once. `LqColor` + `LqShade` is the lower-level primitive underneath that:
// one hue (currently the same five as LqTone — there's no hue outside that
// set yet) at a specific step on a 0–9 ramp, Mantine-style. Most components
// should keep using `tone`; reach for `color`+`shade` only when the bundled
// look doesn't fit (a component needing just the shade-2 background without
// the shade-6 border, say).
//
// Shades are computed via CSS color-mix() from each color's single base
// --lq-* var rather than 50 hand-authored hex values — repaint the five base
// vars in practice.css and every shade of every color follows.
export type LqColor = LqTone;

export const LQ_SHADES = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9] as const;
export type LqShade = (typeof LQ_SHADES)[number];

const LQ_COLOR_BASE_VAR: Record<LqColor, string> = {
	sage: 'var(--lq-accent, #1f7a6b)',
	slate: 'var(--lq-tier, #355a82)',
	amber: 'var(--lq-warn, #a16e1f)',
	red: 'var(--lq-error, #b54848)',
	neutral: 'var(--lq-text-secondary, #4b5563)'
};

/**
 * Shade 5 is the color's base value, unmixed. Shades 0–4 blend toward white
 * (0 = lightest, ~90% white). Shades 6–9 blend toward black (9 = darkest,
 * ~60% black). Chosen to mirror Mantine's "5/6 sit near the base color"
 * convention without hand-tuning ten stops per color.
 */
export function lqColorShade(color: LqColor, shade: LqShade): string {
	const base = LQ_COLOR_BASE_VAR[color];
	if (shade === 5) return base;
	if (shade < 5) {
		const whitePercent = (5 - shade) * 18;
		return `color-mix(in oklab, ${base} ${100 - whitePercent}%, white)`;
	}
	const blackPercent = (shade - 5) * 15;
	return `color-mix(in oklab, ${base} ${100 - blackPercent}%, black)`;
}
