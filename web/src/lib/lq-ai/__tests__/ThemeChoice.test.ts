/**
 * The two controls that show and change the theme (ADR 0045 §2): the cards in
 * Account settings › Appearance and the row at the foot of the left sidebar.
 * Rendered to HTML in node (`svelte/server`), as the other component tests are.
 */
import { afterEach, describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { render } from 'svelte/server';

import ShellSidebar from '../components/ShellSidebar.svelte';
import ThemeChoiceCards from '../components/ThemeChoiceCards.svelte';
import { defaultPreferences, preferences } from '../stores/preferences';
import { themeChoice } from '../stores/theme';
import { LQAI_THEME_CHOICES, LQAI_THEME_LABEL, type LQAIThemeChoice } from '../theme';
import type { User } from '../tabs';

const member: User = {
	id: 'm',
	email: 'm@x',
	is_admin: false,
	must_change_password: false,
	role: 'member'
};

afterEach(() => {
	themeChoice.set('system');
	preferences.set({ ...defaultPreferences });
});

describe('the theme cards in Appearance', () => {
	const cards = (choice: LQAIThemeChoice) => {
		themeChoice.set(choice);
		return render(ThemeChoiceCards).body;
	};
	const radio = (body: string, choice: string) => {
		const tag = body.match(new RegExp(`<input\\b[^>]*value="${choice}"[^>]*>`));
		expect(tag, `radio ${choice}`).not.toBeNull();
		return tag![0];
	};

	it('offers Light, Dark and Match system as one named group of radios', () => {
		const body = cards('system');
		expect(body).toMatch(/role="radiogroup"[^>]*aria-labelledby="lq-theme-title"/);
		expect(body).toMatch(
			/<h3[^>]*id="lq-theme-title"[^>]*>(?:<!--.*?-->)*Theme(?:<!--.*?-->)*<\/h3>/
		);
		expect(body).toContain('aria-describedby="lq-theme-hint"');
		const values = [...body.matchAll(/<input\b[^>]*type="radio"[^>]*>/g)].map(
			(m) => m[0].match(/value="([^"]+)"/)![1]
		);
		expect(values).toEqual([...LQAI_THEME_CHOICES]);
		for (const choice of LQAI_THEME_CHOICES) {
			expect(radio(body, choice)).toContain('name="lq-theme"');
			expect(body).toMatch(
				new RegExp(`>(?:<!--.*?-->)*${LQAI_THEME_LABEL[choice]}(?:<!--.*?-->)*</span>`)
			);
		}
	});

	it.each([...LQAI_THEME_CHOICES])(
		'checks and outlines the %s card when it is the choice',
		(on) => {
			const body = cards(on);
			for (const choice of LQAI_THEME_CHOICES) {
				expect(/\schecked/.test(radio(body, choice)), `${choice} checked`).toBe(choice === on);
				const card = body.match(
					new RegExp(`<label\\b[^>]*data-testid="lq-theme-card-${choice}"[^>]*>`)
				)![0];
				expect(card.includes('lq-theme-card-on'), `${choice} outlined`).toBe(choice === on);
			}
		}
	);

	it('hides each preview from assistive technology', () => {
		const previews = [
			...cards('light').matchAll(/<span\b[^>]*class="[^"]*lq-theme-preview [^>]*>/g)
		];
		expect(previews).toHaveLength(3);
		for (const preview of previews) expect(preview[0]).toContain('aria-hidden="true"');
	});

	it('draws the previews from the fixed preview tokens, never the theme’s own', () => {
		const source = readFileSync(
			new URL('../components/ThemeChoiceCards.svelte', import.meta.url),
			'utf8'
		);
		const style = source.slice(source.indexOf('<style>'));
		const previewRules = [...style.matchAll(/\.lq-theme-preview[\w-]*[^{]*\{([^}]*)\}/g)]
			.map((m) => m[1])
			.join('\n');
		expect(previewRules).toContain('var(--lq-preview-light-canvas)');
		expect(previewRules).toContain('var(--lq-preview-dark-canvas)');
		// The frame around a preview is the page's border; nothing else in it follows the theme.
		const themed = [...previewRules.matchAll(/var\((--lq-[\w-]+)\)/g)]
			.map((m) => m[1])
			.filter((name) => !name.startsWith('--lq-preview-') && !name.startsWith('--lq-radius-'));
		expect([...new Set(themed)]).toEqual(['--lq-border']);
	});
});

describe('the theme row at the foot of the sidebar', () => {
	const sidebar = (choice: LQAIThemeChoice) => {
		themeChoice.set(choice);
		return render(ShellSidebar, { props: { user: member, pathname: '/lq-ai' } }).body;
	};
	const row = (body: string) => {
		const tag = body.match(/<button\b[^>]*data-testid="lq-shell-theme"[^>]*>[\s\S]*?<\/button>/);
		expect(tag, 'theme row').not.toBeNull();
		return tag![0];
	};

	it.each([
		['light', 'sun', 'Dark'],
		['dark', 'moon', 'Match system'],
		['system', 'device-desktop', 'Light']
	] as const)(
		'names the %s choice, draws its icon and says what a press does',
		(on, icon, next) => {
			const tag = row(sidebar(on));
			const label = `Theme: ${LQAI_THEME_LABEL[on]}`;
			expect(tag).toContain(`>${label}</span>`);
			// The accessible name starts with the visible text.
			expect(tag).toContain(`aria-label="${label}. Switch to ${next}."`);
			expect(tag).toContain(`data-theme-choice="${on}"`);
			expect(tag).toMatch(
				new RegExp(`<svg(?=[^>]*tabler-icon-${icon}\\b)(?=[^>]*aria-hidden="true")`)
			);
			expect(tag).toContain('type="button"');
		}
	);

	it('sits in the foot, after Account settings and inside the navigation', () => {
		const body = sidebar('system');
		const foot = body.slice(body.indexOf('data-section="foot"'));
		expect(foot.indexOf('data-nav-id="account"')).toBeGreaterThan(-1);
		expect(foot.indexOf('data-nav-id="account"')).toBeLessThan(foot.indexOf('lq-shell-theme'));
		expect(foot.indexOf('lq-shell-theme')).toBeLessThan(foot.indexOf('</nav>'));
	});

	it('is not a navigation row', () => {
		expect(row(sidebar('system'))).not.toContain('data-nav-id');
	});
});
