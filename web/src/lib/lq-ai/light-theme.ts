/** LQ.AI has a single light palette; upstream theme preferences do not apply. */
export function isLQAIPath(pathname: string): boolean {
	return pathname === '/lq-ai' || pathname.startsWith('/lq-ai/');
}

export function applyLQAILightTheme(doc: Document): void {
	const root = doc.documentElement;
	root.classList.remove('dark', 'oled-dark', 'her');
	root.classList.add('light');
	root.style.colorScheme = 'light';
	// Remove OLED overrides left by a previous upstream route.
	for (const shade of [800, 850, 900, 950]) {
		root.style.removeProperty(`--color-gray-${shade}`);
	}
	doc.querySelector('meta[name="theme-color"]')?.setAttribute('content', '#ffffff');
}
