/**
 * Client for the document-grounded chat endpoint —
 * `POST /api/v1/word-addin/document-chat` — the Word add-in's only chat
 * client (the persisted-chat client was removed; see `store.ts`).
 * Response is structured (`content` + `citations`) via the backend's
 * forced `emit_answer` tool call — see `word_addin.py`'s
 * `EMIT_ANSWER_TOOL`.
 *
 * Stateless by design: no persisted chat/message history, no `chat_id`.
 * Every call re-enumerates the open document's paragraphs fresh via
 * `docxHelper` and sends the whole snapshot alongside the prompt — the
 * open document is the state, not a server-side conversation record.
 *
 * `apiRequest` (hand-rolled, `services/apiClient.ts`): no generated-
 * client type fidelity to lose since this endpoint isn't in the
 * generated client at all yet.
 */
import {
  composerDraftAtom,
  documentChatSendingAtom,
  documentChatTurnsAtom,
  selectedModelIdAtom,
  selectedSkillNamesAtom,
  store,
} from "@/store";
import { apiRequest } from "@/services/apiClient";
import type {
  DocumentChatCreate,
  DocumentChatParagraph,
  DocumentChatResponse,
  DocumentChatTurn,
} from "@/domain/documentChat";
import { docxHelper } from "@/commands/docxHelper";




/** Reads every paragraph out of the currently-open Word document via
 *  `docxHelper` and assigns each one the array-index `paragraphId` the
 *  `DocumentChatCreate`/citation contract expects (see
 *  `domain/documentChat.ts`) — always re-enumerated fresh, never
 *  cached, since edits between turns would desync a cached index. */
async function getDocumentParagraphs(): Promise<DocumentChatParagraph[]> {
  let paragraphs: DocumentChatParagraph[] = [];
  await docxHelper.getContextAndWordParagraphs((paras) => {
    paragraphs = paras.items.map((p, paragraphId) => ({ paragraphId, text: p.text }));
  });
  return paragraphs;
}

/** Composer-facing entry point for the Chat tab — reads
 *  `composerDraftAtom` for the prompt,
 *  `selectedSkillNamesAtom`/`selectedModelIdAtom` for this turn's picks,
 *  and appends both turns to `documentChatTurnsAtom`. No lazy
 *  chat-creation step since there's no persisted chat behind this
 *  endpoint — every turn just resends whatever skills/model are
 *  currently selected alongside a fresh document snapshot. */
export const documentChatClient = {
  async create(): Promise<void> {
    const prompt = store.get(composerDraftAtom).trim();
    if (!prompt) return;

    const skills = store.get(selectedSkillNamesAtom);
    const model = store.get(selectedModelIdAtom) ?? undefined;

    const userTurn: DocumentChatTurn = {
      id: `user-${crypto.randomUUID()}`,
      role: "user",
      content: prompt,
    };
    store.set(documentChatTurnsAtom, (prev) => [...prev, userTurn]);
    store.set(composerDraftAtom, "");
    store.set(documentChatSendingAtom, true);

    // On failure, the optimistic user turn is left in place — the
    // draft was already cleared, so removing it too would lose the
    // user's message with no trace.
    try {
      const paragraphs = await getDocumentParagraphs();
      const body: DocumentChatCreate = {
        userInstruction: toDocumentChatInstruction(prompt, paragraphs),
        model,
        stream: false,
        skills: skills.length > 0 ? skills : undefined,
      };
      const response = await apiRequest<DocumentChatResponse>("/word-addin/document-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const assistantTurn: DocumentChatTurn = {
        id: `assistant-${crypto.randomUUID()}`,
        role: "assistant",
        content: response.content,
        citations: response.citations,
      };
      store.set(documentChatTurnsAtom, (prev) => [...prev, assistantTurn]);
    } finally {
      store.set(documentChatSendingAtom, false);
    }
  },
};


function toDocumentChatInstruction(text: string, paragraphs: DocumentChatParagraph[]): string {
  const output = {
    input_schema: SCHEMAS.CHAT_INPUT,
    citations_schema: SCHEMAS.CITATIONS,
    output_schema: SCHEMAS.CHAT_OUTPUT,
    input: {
      paragraphs,
      instruction: text
    }
  }
  return JSON.stringify(output)
}


// Schema-first, instruction-last: `CHAT_INPUT`/`CITATION`/`CHAT_OUTPUT`
// establish the JSON's architecture before `input.instruction` (what the user
// actually typed) ever appears — a client-built, structured contract instead of
// the old backend-side a flattened text with a text marker.  The `CHAT_OUTPUT` 
// must mirror `word_addin.py`'s `EMIT_ANSWER_TOOL.function.parameters` exactly — 
// keep the two in sync by hand (the tool call is the actual enforcement mechanism; 
// this is reinforcing documentation sent in the prompt, not a second enforcement path).

let SCHEMAS = {
  CHAT_OUTPUT: {
    type: "object",
    description: "The shape you must return via the emit_answer tool call.",
    properties: {
      response: {
        type: "string",
        description: "Your answer, in Markdown, with citation:<n> links per citations_schema.",
      },
      citations: {
        type: "array",
        items: {
          type: "object",
          properties: {
            paragraph_id: {
              type: "integer",
              description: "0-based paragraphId this citation is grounded in.",
            },
            quote: { type: "string", description: "Verbatim quoted text from that paragraph." },
          },
          required: ["paragraph_id", "quote"],
        },
      },
    },
    required: ["response", "citations"],
  },
  CITATIONS: `Ground claims in the document by citing specific paragraphs. A citation is 
  {paragraph_id, quote}: paragraph_id is the paragraphId (see input_schema) the 
  claim is grounded in, and quote MUST be a verbatim substring of that 
  paragraph's text, not a paraphrase — the client locates and highlights that 
  exact substring in the live document, so an inexact quote fails silently. 
  You MUST return your answer via the emit_answer function call, never as 
  plain text. In the \`response\` field's Markdown, wrap the phrase supporting
  each citation in a link to \`citation:<n>\`, where <n> is that citation's 
  0-based index in the \`citations\` array — e.g. \"...allows [30 days' written 
  notice](citation:0)...\". The link text is the only visible signal of what's 
  being cited (no separate preview), so wrap a natural, meaningful phrase, not 
  a bare number or symbol.`,
  CHAT_INPUT: {
    type: "object",
    description: "Shape of this object's own `input` field.",
    properties: {
      paragraphs: {
        type: "array",
        description: "Every paragraph of the currently open Word document, in document order.",
        items: {
          type: "object",
          properties: {
            paragraphId: {
              type: "integer",
              description: "0-based index of this paragraph in the document.",
            },
            text: { type: "string", description: "The paragraph's full text." },
          },
          required: ["paragraphId", "text"],
        },
      },
      instruction: {
        type: "string",
        description: "The user's question or request about the document.",
      },
    },
    required: ["paragraphs", "instruction"],
  }
}
