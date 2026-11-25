/**
 * Route-prefix helpers for the LQ.AI shell.
 *
 * `isLQAIPath` is the one question the root wrapper (`src/routes/+layout.svelte`,
 * OpenWebUI's) asks about our routes: is this pathname one of ours? It used to
 * live in `light-theme.ts`, which made the wrapper depend on the theme module
 * for a path check. The interface redesign replaces the theme module (dark
 * mode); the OpenWebUI removal plan reuses the path check in the wrapper. Keeping
 * the check in its own module lets each change land without touching the other.
 */
export function isLQAIPath(pathname: string): boolean {
	return pathname === '/lq-ai' || pathname.startsWith('/lq-ai/');
}
