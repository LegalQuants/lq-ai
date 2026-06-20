/** Pure helpers for the chat tool-gate UI (PR6b). No Svelte, no network. */

import type {
	ToolConfirmationRequiredFrame,
	McpAuthorizationRequiredFrame
} from '../types';

/**
 * A paused tool-loop gate, keyed to the assistant message whose turn paused.
 * Shared across ChatPanel (owner), MessageList (pass-through), and MessageBubble
 * (renderer) so the shape stays identical at every layer.
 */
export type PendingGate =
	| { assistantId: string; kind: 'confirm'; frame: ToolConfirmationRequiredFrame }
	| { assistantId: string; kind: 'connect'; frame: McpAuthorizationRequiredFrame };

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
