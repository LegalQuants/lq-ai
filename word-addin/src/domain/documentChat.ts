/**
 * Pure domain logic for the document-grounded chat surface —
 * `POST /api/v1/word-addin/document-chat`. Rebuild of the DE-287 M3-B3
 * scaffolding removed earlier on this branch; see
 * `api/app/api/word_addin.py` for the stateless-by-design rationale —
 * the open Word document is the state, not a persisted chat history,
 * so this endpoint takes no `db` dependency and writes nothing to
 * `chats`/`messages`.
 *
 * Distinct from `domain/chat.ts`'s `Message`-based chat: no `chat_id`,
 * no persisted history — every call re-sends a fresh snapshot of the
 * open document's paragraphs (`DocumentChatCreate.paragraphs`)
 * alongside the prompt. `paragraphId` is the array index into
 * `context.document.body.paragraphs` at the moment of the call, not a
 * stable identifier across edits or later turns — re-enumerate and
 * re-send every turn.
 *
 * Response comes back via a forced `emit_answer` tool call server-side
 * (see `word_addin.py`'s `EMIT_ANSWER_TOOL`) — structured, provider-
 * enforced JSON, not prompt-based JSON framing. `citations[].paragraphId`
 * resolves back into `DocumentChatCreate.paragraphs`' same indexing;
 * `citations[].quote` is meant to be an exact substring of that
 * paragraph's text, resolvable via `docxHelper`'s `paragraph.search()`
 * for in-doc highlighting — not verified server-side (no persisted copy
 * of a live Word document to verify against).
 */
import type { ChatMessage } from "@/components/chat/MessageBubble";

export interface DocumentChatParagraph {
  paragraphId: number;
  text: string;
}

export interface DocumentChatCreate {
  userInstruction: string;
  model?: string;
  stream?: boolean;
  skills?: string[];
}

export interface DocumentChatCitation {
  paragraphId: number;
  quote: string;
}

/** Non-streaming response for `POST /word-addin/document-chat`. */
export interface DocumentChatResponse {
  content: string;
  citations: DocumentChatCitation[];
}

/** Local turn record the Chat tab keeps for document-chat — no
 *  persisted `Message` row behind this endpoint, so (unlike
 *  `domain/chat.ts`'s `ChatTurn`) this shape is invented here rather
 *  than mirrored from the backend. Lives only for the task pane's
 *  session. */
export interface DocumentChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: DocumentChatCitation[];
}

/** `DocumentChatTurn` → the UI's thinner `ChatMessage` — mirrors
 *  `domain/chat.ts`'s `toChatMessage` so both chat flavors render
 *  identically. */
export function toDocumentChatMessage(m: DocumentChatTurn): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    citations: m.citations,
  };
}

