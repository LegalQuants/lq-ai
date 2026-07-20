/**
 * MessageBubble — single chat turn, scaffolded from the web app's
 * MessageBubble.svelte (web/src/lib/lq-ai/components/MessageBubble.svelte).
 *
 * M3 scope note: this is a static scaffold (no streaming, no tool-gate
 * card, no refusal-kind branch, no ledger wiring). Those land when
 * in-Word chat moves off DE-287's deferred status. The bubble styling
 * and the assistant pill row (tier · applied skills · capture-as-skill
 * affordance) mirror the web version.
 *
 * Content renders via `MarkdownContent` — `citation:<n>` links (document-
 * chat's `EMIT_ANSWER_TOOL` convention) become clickable inline Anchors
 * that scroll/highlight the source paragraph in the live document; any
 * other link renders normally. Regular persisted-chat messages have no
 * `citations`, so `MarkdownContent` just renders plain markdown for them.
 */
import React from "react";
import { Box, Group, Paper, ActionIcon } from "@mantine/core";
import { ProvenancePill, type ProvenanceKind } from "@/components/chat/ProvenancePill";
import { TrustPill } from "@/components/chat/TrustPill";
import { MarkdownContent } from "@/components/chat/MarkdownContent";
import type { DocumentChatCitation } from "@/domain/documentChat";
import { IconEditFilled } from "@tabler/icons-react";

export type ChatMessagePill = {
  kind: ProvenanceKind;
  summary: string;
  tierMismatch?: boolean;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  /** e.g. "Tier 4" — rendered as a slate TrustPill, same as TierBadge.svelte. */
  tierLabel?: string;
  /** e.g. "Fiduciary-grade" — rendered as a sage TrustPill, same as the
   *  citation-ledger gate badge (web/src/lib/lq-ai/citations/ledger-state.ts). */
  gateLabel?: string;
  pills?: ChatMessagePill[];
  captureable?: boolean;
  /** Document-chat only (`toDocumentChatMessage`) — undefined for
   *  persisted-chat messages, which have no in-doc citations to link. */
  citations?: DocumentChatCitation[];
};

type MessageBubbleProps = {
  message: ChatMessage;
};

export const MessageBubble: React.FC<MessageBubbleProps> = ({ message }) => {
  const isUser = message.role === "user";
  const hasPillRow =
    !isUser &&
    (message.tierLabel ||
      message.gateLabel ||
      (message.pills && message.pills.length > 0) ||
      message.captureable);

  return (
    <Box
      mb="sm"
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: isUser ? "flex-end" : "flex-start",
      }}
      data-testid={`lq-ai-message-${message.id}`}
    >
      <Paper
        p="xs"
        radius="lg"
        withBorder={!isUser}
        style={{
          maxWidth: "93%",
          background: isUser ? "var(--mantine-color-sage-9)" : "var(--mantine-color-gray-1)",
          color: isUser ? "white" : "var(--mantine-color-text)",
        }}
      >
        <Box fz="md" data-testid="lq-ai-message-content">
          <MarkdownContent content={message.content} citations={message.citations} />
        </Box>
      </Paper>

      {hasPillRow && (
        <Group gap={4} mt={4} wrap="wrap">
          {message.tierLabel && <TrustPill variant="tier" label={message.tierLabel} />}
          {message.gateLabel && <TrustPill variant="audit" tone="sage" label={message.gateLabel} />}
          {message.pills?.map((p, i) => (
            <ProvenancePill
              key={i}
              kind={p.kind}
              summary={p.summary}
              tierMismatch={p.tierMismatch}
            />
          ))}
          {message.captureable && (
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              aria-label="Capture as a skill"
              title="Capture as a skill"
              children={<IconEditFilled />}
            />
          )}
        </Group>
      )}
    </Box>
  );
};
