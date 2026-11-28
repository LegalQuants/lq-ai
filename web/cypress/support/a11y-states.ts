// Initial inventory from @SaifAlYounan, LegalQuants/lq-ai#437.
export const states = [
	{ id: 'login', path: '/lq-ai/login', ready: '[data-testid="lq-ai-login-submit"]' },
	{ id: 'dashboard', path: '/lq-ai', ready: '.lq-dashboard h1' },
	{ id: 'matters', path: '/lq-ai/matters', heading: 'Matters' },
	{ id: 'new-matter', path: '/lq-ai/matters', heading: 'Matters', dialog: true },
	{ id: 'knowledge', path: '/lq-ai/knowledge', ready: '[data-testid="lq-ai-knowledge-page"]' },
	{ id: 'skills', path: '/lq-ai/skills', ready: '[data-testid="lq-ai-user-skills"]' },
	{ id: 'appearance', path: '/lq-ai/settings/appearance', heading: 'Appearance' }
] as const;
export const viewports = [
	{ id: 'desktop', width: 1440, height: 900 },
	{ id: 'phone', width: 390, height: 844 }
] as const;
// The theme each variant pins and renders (ADR 0045 §3). Every variant saves
// its theme as LQ.AI's own choice, so none follows the runner's OS setting.
// The inventory keys are unchanged: the last segment used to name a saved
// Open WebUI preference that always rendered light, and now names the theme.
export const themes = ['light', 'dark'] as const;
export type A11yTheme = (typeof themes)[number];
export const stateIds = states.flatMap((s) =>
	viewports.flatMap((v) => themes.map((t) => `${s.id}/${v.id}/${t}`))
);
