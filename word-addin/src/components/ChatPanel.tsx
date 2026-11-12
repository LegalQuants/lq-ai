/**
 * ChatPanel — chat surface for the Word add-in's "Chat" tab.
 *
 * Scaffolded from the web app's ChatPanel.svelte
 * (web/src/lib/lq-ai/components/ChatPanel.svelte) — same header /
 * message-list / model-bar / skills-row / saved-prompts-row / composer /
 * ambient-footer shape, rebuilt with Mantine (canonical in the add-in;
 * see word-addin/src/taskpane/theme.ts for the sage/slate/amber theme
 * that mirrors the web app's Practice palette).
 *
 * Wired to the Jotai-backed service clients under `src/services/`
 * (`documentChatClient.ts`, `skillClient.ts`) for chat/message state +
 * skills. Sends against the stateless, document-grounded
 * `/word-addin/document-chat` surface (see `documentChatClient.ts`) —
 * the add-in's only chat client. No routed-provider/tier metadata on
 * document-chat turns yet (`DocumentChatResponse` doesn't carry it —
 * see `api/app/api/word_addin.py`), so `AmbientFooter` always shows its
 * fallback text for now rather than a real per-turn value. Still no
 * sidebar / attached-files panel / receipts drawer / KB attach modal —
 * those are the ChatSidebar / AttachedFilesPanel / ReceiptsDrawer /
 * AttachKBModal pieces of the web version, out of scope per DE-287.
 */
import React from "react";
import { useAtomValue } from "jotai";
import { Stack, Divider } from "@mantine/core";
import { MessageList } from "@/components/chat/MessageList";
import { SkillsRow } from "@/components/chat/SkillsRow";
import { SavedPromptsRow } from "@/components/chat/SavedPromptsRow";
import { Composer } from "@/components/chat/Composer";
import { AmbientFooter } from "@/components/chat/AmbientFooter";
import { documentChatUIMessagesAtom, selectedModelIdAtom } from "@/store";
import { ModelCombobox } from "@/components/ModelCombobox";
import { modelClient } from "@/services/modelClient";

export const ChatPanel: React.FC = () => {
  const chatMessages = useAtomValue(documentChatUIMessagesAtom);
  const selectedModelId = useAtomValue(selectedModelIdAtom);




  return (
    <Stack gap={0} h="100%" style={{ display: "flex" }} data-testid="lq-ai-chat-shell">
      <MessageList messages={chatMessages} />

      <Divider />

      <Stack gap="xs" p="sm" data-testid="lq-ai-composer">
        <ModelCombobox selectedId={selectedModelId} onSelect={modelClient.select} />
        <SkillsRow />
        {/* <SavedPromptsRow /> //Disabled for now  */}
        <Composer />
      </Stack>

      {/* <AmbientFooter provider="no provider" tier="default" /> */}
    </Stack>
  );
};
