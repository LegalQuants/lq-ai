/**
 * /api/v1/chats/{chat_id}/messages/{message_id}/sources — external-source provenance (PR6c).
 *
 * Lazy-fetched after each assistant message renders when the message was
 * produced by a governed tool loop that consulted external case-law sources.
 * The endpoint returns `ToolSource` rows persisted by the PR6c backend
 * (Tasks 1–4). Tasks 6–7 consume this surface to render the source-pill
 * and expandable source panel.
 */
import { apiRequest } from './client';
import type { ToolSource } from '../types';

/** GET /api/v1/chats/{chat_id}/messages/{message_id}/sources */
export async function getMessageSources(
	chatId: string,
	messageId: string
): Promise<ToolSource[]> {
	return apiRequest<ToolSource[]>(
		`/chats/${encodeURIComponent(chatId)}/messages/${encodeURIComponent(messageId)}/sources`
	);
}
