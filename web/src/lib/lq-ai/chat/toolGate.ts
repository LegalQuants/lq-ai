/** Pure helpers for the chat tool-gate UI (PR6b). No Svelte, no network. */

export interface OAuthReturn {
	status: 'connected' | 'error' | 'none';
	server: string | null;
}

/** Parse the PR4d OAuth-callback return query (`?mcp_connected` / `?mcp_error&server=`). */
export function parseOAuthReturn(params: URLSearchParams): OAuthReturn {
	if (params.has('mcp_connected')) return { status: 'connected', server: params.get('server') };
	if (params.has('mcp_error')) return { status: 'error', server: params.get('server') };
	return { status: 'none', server: null };
}

/** Append `return_url` to an authorize URL, preserving any existing query. */
export function buildAuthorizeUrl(authorizeUrl: string, returnUrl: string): string {
	const sep = authorizeUrl.includes('?') ? '&' : '?';
	return `${authorizeUrl}${sep}return_url=${encodeURIComponent(returnUrl)}`;
}
