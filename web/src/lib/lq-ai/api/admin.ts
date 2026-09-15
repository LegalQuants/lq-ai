/**
 * Admin API — gateway alias CRUD (D0.5).
 *
 * The backend's /api/v1/admin surface gates these on `is_admin`. Non-admin
 * users get 403 ``forbidden``; the route guard in /lq-ai/admin/* turns that
 * into a redirect to /lq-ai with a flash error.
 */
import { apiRequest } from './client';
import type {
	UsageResponse,
	UsageQuery,
	AdminUserListResponse,
	AdminUserListQuery,
	AdminUserRow
} from '../types';

export interface AliasFallback {
	provider: string;
	model: string;
}

export interface Alias {
	name: string;
	provider: string;
	model: string;
	fallback: AliasFallback[];
	/** Tier 1-5 for the alias's primary target — populated on the
	 *  single-alias GET; absent on the list endpoint. */
	primary_inference_tier?: 1 | 2 | 3 | 4 | 5;
}

export interface AliasListResponse {
	object: 'list';
	data: Alias[];
}

export interface AliasCreateBody {
	name: string;
	provider: string;
	model: string;
	fallback?: AliasFallback[];
}

export interface AliasUpdateBody {
	provider: string;
	model: string;
	fallback?: AliasFallback[];
}

export async function listAliases(): Promise<AliasListResponse> {
	return apiRequest<AliasListResponse>('/admin/aliases');
}

export async function getAlias(name: string): Promise<Alias> {
	return apiRequest<Alias>(`/admin/aliases/${encodeURIComponent(name)}`);
}

export async function createAlias(body: AliasCreateBody): Promise<Alias> {
	return apiRequest<Alias>('/admin/aliases', { method: 'POST', body });
}

export async function updateAlias(name: string, body: AliasUpdateBody): Promise<Alias> {
	return apiRequest<Alias>(`/admin/aliases/${encodeURIComponent(name)}`, {
		method: 'PATCH',
		body
	});
}

export async function deleteAlias(name: string): Promise<void> {
	return apiRequest<void>(`/admin/aliases/${encodeURIComponent(name)}`, {
		method: 'DELETE'
	});
}

/**
 * Sanitized gateway config payload (D0.5). Used by the admin UI to
 * populate the provider dropdown when creating/editing aliases.
 *
 * Only the fields the editor consumes are typed; the gateway emits a
 * full ``GatewayConfig.model_dump`` so unknown fields ride along
 * unmodeled.
 */
export interface AdminConfigSnapshot {
	providers: Array<{
		name: string;
		type: string;
		tier: number;
		enabled?: boolean;
		models?: string[];
	}>;
	model_aliases: Record<string, unknown>;
	[k: string]: unknown;
}

export async function getAdminConfig(): Promise<AdminConfigSnapshot> {
	return apiRequest<AdminConfigSnapshot>('/admin/config');
}

/**
 * Provider-key (BYOK) management — runtime keys the gateway encrypts at rest
 * (ADR 0011) and hot-applies with no restart. Proxied by the backend at
 * /api/v1/admin/provider-keys (admin-gated). No full key is ever returned; the
 * status carries only the last 4 characters of a resolvable key.
 *
 * The set endpoint returns 400 ``failed_precondition`` when the gateway has no
 * LQ_AI_GATEWAY_MASTER_KEY (runtime storage disabled), 404 for an unknown
 * provider; revoke returns 409 for an env-sourced key (owned by the operator's
 * .env, not the runtime store). Callers surface these to the admin.
 */
export interface ProviderKeyStatus {
	provider: string;
	type: string;
	configured: boolean;
	/** Last 4 chars of a resolvable key, else null. Never a full key. */
	last4: string | null;
	/** Where the key comes from: encrypted runtime store, the env/.env, or none. */
	source: 'runtime' | 'env' | null;
}

export interface ProviderKeyListResponse {
	provider_keys: ProviderKeyStatus[];
}

export async function listProviderKeys(): Promise<ProviderKeyListResponse> {
	return apiRequest<ProviderKeyListResponse>('/admin/provider-keys');
}

/** Set or replace a provider's runtime key (POST replaces in place). */
export async function setProviderKey(provider: string, apiKey: string): Promise<ProviderKeyStatus> {
	return apiRequest<ProviderKeyStatus>('/admin/provider-keys', {
		method: 'POST',
		body: { provider, api_key: apiKey }
	});
}

/** Revoke a provider's runtime key (retires its live adapter). 204 on success. */
export async function revokeProviderKey(provider: string): Promise<void> {
	return apiRequest<void>(`/admin/provider-keys/${encodeURIComponent(provider)}`, {
		method: 'DELETE'
	});
}

/**
 * Research-source (authority provider) management — the four fiduciary-grade
 * authority sources (CourtListener, GovInfo, EDGAR, EUR-Lex) the gateway can
 * cite from. Proxied by the backend at /api/v1/admin/tool-providers
 * (admin-gated). Secrets are write-only: no key is ever returned, only
 * `has_key` (a bool). EDGAR/EUR-Lex are keyless (`key_required: false`) and
 * just need an enable/disable toggle; CourtListener/GovInfo need a key.
 *
 * Set returns 400 ``failed_precondition`` when the gateway has no runtime key
 * storage (no master key), 404 for an unregistered source type, 409 when the
 * source is configured via the environment (gateway.yaml), not the runtime
 * store.
 */
export interface ToolProviderStatus {
	type: string;
	enabled: boolean;
	name: string | null;
	/** Whether a runtime/env key is present. Never the key itself. */
	has_key: boolean;
	/** Whether this source needs an API key (CourtListener/GovInfo) or is keyless (EDGAR/EUR-Lex). */
	key_required: boolean;
	egress_tier: number | null;
}

export interface ToolProviderListResponse {
	tool_providers: ToolProviderStatus[];
}

export async function listToolProviders(): Promise<ToolProviderListResponse> {
	return apiRequest<ToolProviderListResponse>('/admin/tool-providers');
}

/** Enable a source, optionally with a key. */
export async function setToolProvider(type: string, apiKey?: string): Promise<ToolProviderStatus> {
	const body: Record<string, unknown> = { type };
	if (apiKey) body.api_key = apiKey;
	return apiRequest<ToolProviderStatus>('/admin/tool-providers', { method: 'POST', body });
}

/** Rotate a source's key. */
export async function patchToolProvider(type: string, apiKey: string): Promise<ToolProviderStatus> {
	return apiRequest<ToolProviderStatus>(`/admin/tool-providers/${encodeURIComponent(type)}`, {
		method: 'PATCH',
		body: { api_key: apiKey }
	});
}

/** Disable a source (removes the entry + retires the live adapter). 204 on success. */
export async function deleteToolProvider(type: string): Promise<void> {
	return apiRequest<void>(`/admin/tool-providers/${encodeURIComponent(type)}`, {
		method: 'DELETE'
	});
}

/**
 * GET /api/v1/admin/usage — aggregated turn counts for trust + cost visibility.
 *
 * Admin-only; callers must handle `LQAIApiError` with status 403 (non-admin
 * users) by showing a graceful "admins only" message rather than an error.
 */
export async function getUsage(query: UsageQuery = {}): Promise<UsageResponse> {
	const params = new URLSearchParams();
	for (const [k, v] of Object.entries(query)) {
		if (v !== undefined && v !== null && v !== '') params.append(k, String(v));
	}
	const qs = params.toString();
	return apiRequest<UsageResponse>(`/admin/usage${qs ? '?' + qs : ''}`);
}

/**
 * GET /api/v1/admin/users — list platform users with optional role/email filters.
 *
 * Admin-only. Callers must handle LQAIApiError status 403.
 */
export async function listUsers(query: AdminUserListQuery = {}): Promise<AdminUserListResponse> {
	const params = new URLSearchParams();
	for (const [k, v] of Object.entries(query)) {
		if (v !== undefined && v !== null && v !== '') params.append(k, String(v));
	}
	const qs = params.toString();
	return apiRequest<AdminUserListResponse>(`/admin/users${qs ? '?' + qs : ''}`);
}

/**
 * PATCH /api/v1/admin/users/{user_id}/role — update a user's platform role.
 *
 * Returns 409 with code "last_admin" when demoting the last admin account.
 */
export async function patchUserRole(
	userId: string,
	role: 'admin' | 'member' | 'viewer'
): Promise<AdminUserRow> {
	return apiRequest<AdminUserRow>(`/admin/users/${encodeURIComponent(userId)}/role`, {
		method: 'PATCH',
		body: { role }
	});
}
