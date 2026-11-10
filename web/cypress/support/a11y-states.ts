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
// These are saved upstream preferences, not supported LQ.AI render themes.
// Keep the inventory keys stable; both inputs must render the light-only UI.
export const savedThemePreferences = ['light', 'dark'] as const;
export const stateIds = states.flatMap((s) =>
	viewports.flatMap((v) => savedThemePreferences.map((t) => `${s.id}/${v.id}/${t}`))
);
