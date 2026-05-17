/**
 * /api/v1/chats/{chat_id}/messages/{message_id}/citations — M2 citations.
 *
 * Lazy-fetched after each assistant message renders. The endpoint returns
 * `MessageCitation` rows persisted by the M2 Citation Engine (M2-A2 through
 * M2-C1). M2-C2 consumes this surface to render the five citation states.
 *
 * A future refactor (DE-275) may embed citations directly in the
 * assistant-message envelope to avoid the second round-trip; until then the
 * lazy fetch is the canonical client path.
 */
import { apiRequest } from './client';
import type { Citation } from '../types';

/** GET /api/v1/chats/{chat_id}/messages/{message_id}/citations */
export async function getMessageCitations(
	chatId: string,
	messageId: string
): Promise<Citation[]> {
	return apiRequest<Citation[]>(
		`/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/citations`
	);
}
