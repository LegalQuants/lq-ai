/**
 * The sidebar cutover (interface-redesign P1.3c, ADR 0045 §6), checked in the
 * source: the LQ.AI layout always renders the sidebar chrome for a signed-in
 * person, the developer switch is gone everywhere, the old top bar, tab row,
 * trust chrome and top-bar bell are no longer mounted, and the layout's gates
 * are still the layout's.
 *
 * The layout renders nothing on the server (it waits for the sign-in gate),
 * so this reads its source; the chrome's behaviour is covered by the render
 * tests of each piece and by the Cypress specs.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const src = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const read = (rel: string) => readFileSync(join(src, rel), 'utf8');
const layout = read('routes/lq-ai/+layout.svelte');
const script = layout.slice(0, layout.indexOf('</script>'));
const markup = layout.slice(layout.indexOf('</script>'), layout.indexOf('<style>'));

function walk(dir: string): string[] {
	return readdirSync(dir).flatMap((f) => {
		const p = join(dir, f);
		if (statSync(p).isDirectory()) return f.startsWith('__') ? [] : walk(p);
		return /\.(svelte|ts)$/.test(f) ? [p] : [];
	});
}

describe('the LQ.AI layout after the cutover', () => {
	it('renders the sidebar chrome for every signed-in route outside sign-in', () => {
		expect(script).toMatch(
			/\$: sidebarChrome = !isAuthExempt\(pathname\) && !!\$auth\.access_token;/
		);
		// The three pieces of the chrome, each behind that one condition.
		const chrome =
			/\{#if sidebarChrome\}\s*<ShellSidebar[\s\S]*?<PageHeader \{pathname\} \/>\s*\{\/if\}/;
		expect(markup).toMatch(chrome);
		expect(markup).toMatch(/\{#if sidebarChrome\}\s*<RightSidebar \{pathname\} \/>\s*\{\/if\}/);
		expect(markup).toContain('automations={$autonomousChromeEnabled}');
		expect(markup).toContain('<ShellAttribution {sidebarChrome} />');
		expect(markup).toContain('<main id="lq-main">');
		expect(markup).toContain('<SessionTimeoutWarning />');
	});

	it('mounts none of the old chrome', () => {
		for (const gone of [
			'TopTabBar',
			'AmbientTrustChrome',
			'NotificationBell',
			'lq-topbar',
			'lq-tabbar',
			'settings/appearance'
		])
			expect(layout, gone).not.toContain(gone);
	});

	it('keeps every gate in the layout', () => {
		expect(script).toContain("goto('/lq-ai/login')");
		expect(script).toContain("goto('/lq-ai/change-password')");
		expect(script).toContain('user.must_change_password');
		expect(script).toContain("startTracker(() => goto('/lq-ai/login?reason=idle-timeout'))");
		expect(script).toContain('if (userId) void initPreferences();');
		expect(script).toMatch(
			/function isAuthExempt\(pathname: string\): boolean \{\s*return pathname === '\/lq-ai\/login' \|\| pathname === '\/lq-ai\/change-password';/
		);
	});
});

describe('the developer switch is gone', () => {
	it('is read nowhere under the LQ.AI folders', () => {
		const found: string[] = [];
		for (const file of [...walk(join(src, 'lib/lq-ai')), ...walk(join(src, 'routes/lq-ai'))]) {
			const text = readFileSync(file, 'utf8');
			for (const needle of ['lq-ai.shell', 'readShellSwitch', 'sidebarChromeOn', 'sidebarShell'])
				if (text.includes(needle)) found.push(`${relative(src, file)}: ${needle}`);
			if (/from '(\$lib\/lq-ai|\.\.?)\/shell'/.test(text))
				found.push(`${relative(src, file)}: shell import`);
		}
		expect(found).toEqual([]);
	});
});
