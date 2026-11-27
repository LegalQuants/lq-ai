/**
 * /api/v1/users/me/preferences — server-synced personalization toggles.
 *
 * GET returns the account's preferences. PATCH sends only the changed fields.
 */
import { apiRequest } from './client';
import type { Preferences, PreferencesUpdate } from '../types';

export async function getPreferences(signal?: AbortSignal): Promise<Preferences> {
	return apiRequest<Preferences>('/users/me/preferences', { signal });
}

export async function patchPreferences(
	patch: PreferencesUpdate,
	signal?: AbortSignal
): Promise<Preferences> {
	return apiRequest<Preferences>('/users/me/preferences', { method: 'PATCH', body: patch, signal });
}
