/**
 * Wire types for the Skills / Chats / Messages endpoints, mirrored from
 * the canonical definitions in `web/src/lib/lq-ai/types.ts` (the web
 * app's own copy of the backend's OpenAPI sketch shapes — see
 * `docs/api/backend-openapi.yaml`). word-addin has no shared package
 * with `web/`, so this is a deliberate mirror, not an import — keep it
 * in sync by field name, not by re-exporting.
 */

export type MessageRole = "user" | "assistant" | "system" | "tool";

export interface Message {
  id: string;
  chat_id: string;
  role: MessageRole;
  content: string;
  applied_skills?: string[];
  routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
  routed_provider?: string | null;
  routed_model?: string | null;
  created_at: string;
}

export interface Chat {
  id: string;
  title: string;
  owner_id: string;
  project_id?: string | null;
  created_at: string;
  updated_at: string;
  /** Empty/absent means the sticky toggle is off; a new chat never
   *  inherits it. See `MessageCreate.set_sticky`. */
  sticky_skills?: string[];
}

export interface SkillSummary {
  name: string;
  version: string;
  scope: "builtin" | "user" | "team";
  title: string;
  description?: string;
  tags?: string[];
  minimum_inference_tier?: 1 | 2 | 3 | 4 | 5;
}

export interface AttachedSkillRef {
  slug?: string;
  inline_body?: string;
  source?: string;
  inputs?: Record<string, unknown>;
}

export interface MessageCreate {
  content: string;
  model?: string;
  stream?: boolean;
  attached_skills?: AttachedSkillRef[];
  /** `true` makes this turn's applied skills sticky for the chat; `false`
   *  clears the set; omitted leaves it unchanged. See docstring above. */
  set_sticky?: boolean | null;
}

// ----- SSE message-stream frames -----

export interface MessageStartFrame {
  type: "start";
  lq_ai_message_id: string;
  chat_id: string;
}

export interface MessageDeltaFrame {
  type: "delta";
  delta: string;
  lq_ai_message_id: string;
  routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
  applied_skills?: string[];
}

export interface MessageCompleteFrame {
  type: "complete";
  lq_ai_message_id: string;
  message: Message;
  applied_skills?: string[];
  routed_inference_tier?: 1 | 2 | 3 | 4 | 5 | null;
  routed_provider?: string | null;
}

export interface MessageErrorFrame {
  type: "error";
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
}

export type MessageStreamEvent =
  MessageStartFrame | MessageDeltaFrame | MessageCompleteFrame | MessageErrorFrame;
