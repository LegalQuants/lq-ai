/**
 * /api/v1/chats/{chat_id}/ledger — Citation Ledger read surface (P1-A3/B1).
 *
 * Returns the turn/chat ledger resolved to source identity + passage(s) read
 * + verification status + provenance, plus per-turn fiduciary-grade verdicts
 * (`gates`). Lazy-fetched per assistant message, like citations/sources.
 */
import { apiRequest } from './client';
import type { ChatLedger } from '../types';

/** GET /api/v1/chats/{chat_id}/ledger[?message_id=…] */
export async function getChatLedger(chatId: string, messageId?: string): Promise<ChatLedger> {
	const q = messageId ? `?message_id=${encodeURIComponent(messageId)}` : '';
	return apiRequest<ChatLedger>(`/chats/${encodeURIComponent(chatId)}/ledger${q}`);
}
