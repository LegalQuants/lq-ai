import { describe, it, expect } from 'vitest';

import { parseOAuthReturn, buildAuthorizeUrl } from '../chat/toolGate';

describe('parseOAuthReturn', () => {
	it('detects connected', () => {
		expect(parseOAuthReturn(new URLSearchParams('mcp_connected=1'))).toEqual({
			status: 'connected',
			server: null
		});
	});
	it('detects error with server', () => {
		expect(parseOAuthReturn(new URLSearchParams('mcp_error=1&server=files'))).toEqual({
			status: 'error',
			server: 'files'
		});
	});
	it('none when absent', () => {
		expect(parseOAuthReturn(new URLSearchParams('foo=bar'))).toEqual({
			status: 'none',
			server: null
		});
	});
});

describe('buildAuthorizeUrl', () => {
	it('appends return_url (no existing query)', () => {
		expect(
			buildAuthorizeUrl('/api/v1/mcp/oauth/files/authorize', 'https://app/lq-ai/chats?c=1')
		).toBe(
			'/api/v1/mcp/oauth/files/authorize?return_url=' +
				encodeURIComponent('https://app/lq-ai/chats?c=1')
		);
	});
	it('uses & when authorize_url already has a query', () => {
		expect(buildAuthorizeUrl('/x?a=1', 'https://app/c')).toBe(
			'/x?a=1&return_url=' + encodeURIComponent('https://app/c')
		);
	});
});
