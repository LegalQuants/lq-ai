/**
 * ADR 0045 §1 and §5 (S1-3b): icons are Tabler line icons, info and warning are neutral
 * ink with a distinct icon, and a privileged matter carries a lock in the governance
 * colour. Rendered to HTML in node (`svelte/server`), as the other component tests are.
 */
import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { render } from 'svelte/server';

import LqToneIcon, { LQ_TONE_ICON_NAME } from '../components/shared/LqToneIcon.svelte';
import LqAlert from '../components/shared/LqAlert.svelte';
import MatterCard from '../components/MatterCard.svelte';
import ShellSidebar from '../components/ShellSidebar.svelte';
import { createSidebarLists } from '../sidebarLists';
import type { Project } from '../types';
import type { User } from '../tabs';

const svgWith = (name: string, ...attrs: string[]) =>
	new RegExp(`<svg(?=[^>]*tabler-icon-${name}\\b)${attrs.map((a) => `(?=[^>]*${a})`).join('')}`);

describe('LqToneIcon: one icon per note and caution', () => {
	it('draws a triangle for a caution and a circle for a note, hidden by default', () => {
		expect(LQ_TONE_ICON_NAME).toEqual({ warning: 'alert-triangle', info: 'info-circle' });
		for (const tone of ['warning', 'info'] as const) {
			const html = render(LqToneIcon, { props: { tone } }).body;
			expect(html).toMatch(svgWith(LQ_TONE_ICON_NAME[tone], 'aria-hidden="true"'));
			expect(html).not.toContain('role="img"');
		}
	});

	it('names itself when it stands alone', () => {
		const html = render(LqToneIcon, { props: { tone: 'warning', label: 'Caution' } }).body;
		expect(html).toMatch(svgWith('alert-triangle', 'role="img"', 'aria-label="Caution"'));
		expect(html).not.toContain('aria-hidden');
	});
});

describe('LqAlert carries its tone icon for info and warning only', () => {
	const alert = (tone: string) =>
		render(LqAlert, { props: { tone: tone as never, role: 'status' } }).body;

	it('warning and info draw their icon, hidden from assistive technology', () => {
		expect(alert('warning')).toMatch(svgWith('alert-triangle', 'aria-hidden="true"'));
		expect(alert('info')).toMatch(svgWith('info-circle', 'aria-hidden="true"'));
	});

	it('neutral and danger draw none (danger keeps its colour)', () => {
		expect(alert('neutral')).not.toContain('tabler-icon-');
		expect(alert('danger')).not.toContain('tabler-icon-');
	});
});

describe('a privileged matter carries a lock', () => {
	const matter = {
		id: 'm1',
		name: 'Larkspur',
		slug: 'larkspur',
		description: null,
		minimum_inference_tier: null,
		archived_at: null,
		updated_at: '2026-01-01T00:00:00Z'
	};

	it('on the matter card, as a hidden icon inside the pill named "Privileged"', () => {
		const html = render(MatterCard, { props: { matter: { ...matter, privileged: true } } as never })
			.body;
		const pill = html.match(/<button[^>]*aria-label="Privileged"[^>]*>[\s\S]*?<\/button>/);
		expect(pill).not.toBeNull();
		expect(pill![0]).toMatch(svgWith('lock', 'aria-hidden="true"'));
		const plain = render(MatterCard, { props: { matter: { ...matter, privileged: false } } as never })
			.body;
		expect(plain).not.toContain('tabler-icon-lock');
	});

	it('in the sidebar, after the matter name, named "Privileged"', () => {
		const member: User = {
			id: 'u1',
			email: 'm@x',
			is_admin: false,
			must_change_password: false,
			role: 'member'
		};
		const project = (id: string, name: string, privileged: boolean): Project => ({
			id,
			name,
			slug: id,
			owner_id: 'u1',
			privileged,
			created_at: '2026-11-01T00:00:00Z',
			updated_at: '2026-11-05T00:00:00Z'
		});
		const lists = createSidebarLists({
			listProjects: async () => {
				throw new Error('SSR tests must not fetch');
			},
			listChats: async () => {
				throw new Error('SSR tests must not fetch');
			}
		});
		lists.seed({
			projects: [project('m1', 'Larkspur', true), project('m2', 'Kestrel', false)],
			chats: [],
			loadedAt: 1
		});
		const html = render(ShellSidebar, { props: { user: member, pathname: '/lq-ai', lists } }).body;
		const row = (id: string) => {
			const m = html.match(new RegExp(`<a[^>]*data-sidebar-matter="${id}"[^>]*>[\\s\\S]*?</a>`));
			expect(m, id).not.toBeNull();
			return m![0];
		};
		expect(row('m1')).toMatch(
			svgWith('lock', 'lq-sidebar-privileged', 'role="img"', 'aria-label="Privileged"')
		);
		expect(row('m2')).not.toContain('tabler-icon-lock');
	});
});

describe('no emoji as icons in the LQ.AI shell', () => {
	// Left until a later step or a ruling: the tab row until S1-8 removes it, the run
	// panel's state marks (its render tests forbid any <svg>), and the fallback beside a
	// skill's own emoji icon (skill data).
	const ALLOWED = new Set([
		'lib/lq-ai/tabs.ts',
		'lib/lq-ai/components/run/RunLine.svelte',
		'lib/lq-ai/components/AttachedSkillPill.svelte',
		'lib/lq-ai/components/SlashPopover.svelte'
	]);
	const src = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
	const walk = (dir: string): string[] =>
		readdirSync(dir).flatMap((f) => {
			const p = join(dir, f);
			if (statSync(p).isDirectory()) return f.startsWith('__') ? [] : walk(p);
			return /\.(svelte|ts)$/.test(f) ? [p] : [];
		});

	it('finds none outside the allowed files', () => {
		const found: string[] = [];
		for (const file of [...walk(join(src, 'lib/lq-ai')), ...walk(join(src, 'routes/lq-ai'))]) {
			const rel = relative(src, file);
			if (ALLOWED.has(rel)) continue;
			readFileSync(file, 'utf8')
				.split('\n')
				.forEach((line, i) => {
					const t = line.trim();
					if (/^(\*|\/\/|\/\*|<!--)/.test(t)) return;
					// Arrows (the external-link mark, prose arrows) and the CSS disclosure
					// triangles are typography, not icons, and are left as text.
					const glyphs = line.replace(/[\u2190-\u21ff\u25b6\u25bc]/g, '');
					if (/\p{Extended_Pictographic}/u.test(glyphs)) found.push(`${rel}:${i + 1}`);
				});
		}
		expect(found).toEqual([]);
	});
});
