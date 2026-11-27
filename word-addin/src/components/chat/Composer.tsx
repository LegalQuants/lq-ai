/**
 * Composer — message textarea + action row, scaffolded from the web
 * app's ChatPanel.svelte composer markup
 * (web/src/lib/lq-ai/components/ChatPanel.svelte, lines ~1071-1146).
 *
 * Wired to `composerDraftAtom` (src/store.ts) and
 * `documentChatSendingAtom`/`documentChatClient.create()` (see
 * src/services/documentChatClient.ts) — sends against the stateless,
 * document-grounded `/word-addin/document-chat` surface, the add-in's
 * only chat client (the persisted-chat client was removed — document
 * state lives in the open Word document, not a server-side conversation
 * record). Enhance Prompt (✨), Receipts (📜), and slash-invocation stay
 * inert — out of scope, not implied by the skills/chat state-layer ask.
 */
import React, { useState } from "react";
import { useAtom, useAtomValue } from "jotai";
import { Textarea, Group, Button } from "@mantine/core";
import { composerDraftAtom, documentChatSendingAtom } from "@/store";
import { documentChatClient } from "@/services/documentChatClient";
import { actions } from "@/actions";

export const Composer: React.FC = () => {
  const [value, setValue] = useAtom(composerDraftAtom);
  const streaming = useAtomValue(documentChatSendingAtom);

  async function handleSend(): Promise<void> {
    try {
      await documentChatClient.create();
    } catch (e) {
      actions.showErrorNotification("Failed to send message", false)
    }
  }

  return (
    <Group gap={2} align="flex-end" wrap="nowrap">
      <Textarea
        placeholder="Type a message…"
        autosize
        minRows={3}
        value={value}
        onChange={(e) => setValue(e.currentTarget.value)}
        disabled={!!streaming}
        data-testid="lq-ai-composer-input"
        style={{ flex: 1 }}
      />

      <Button
        color="sage"
        disabled={!value.trim() || !!streaming}
        loading={!!streaming}
        onClick={handleSend}
        data-testid="lq-ai-send-btn"
        style={{ flexShrink: 0 }}
      >
        Send
      </Button>
    </Group>
  );
};
