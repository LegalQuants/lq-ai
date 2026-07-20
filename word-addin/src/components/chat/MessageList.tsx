/**
 * MessageList — scrollable message stack, scaffolded from the web app's
 * MessageList.svelte (web/src/lib/lq-ai/components/MessageList.svelte).
 * Auto-scroll-to-bottom and streaming state are dropped for this static
 * scaffold — see MessageBubble.tsx's docstring.
 */
import React from "react";
import { ScrollArea, Text, Center } from "@mantine/core";
import { MessageBubble, type ChatMessage } from "@/components/chat/MessageBubble";

type MessageListProps = {
  messages: ChatMessage[];
};

export const MessageList: React.FC<MessageListProps> = ({ messages }) => {
  if (messages.length === 0) {
    return (
      <Center style={{ flex: 1 }}>
        <Text size="sm" c="dimmed" fs="italic" p="lg">
          No messages yet. Optionally attach a skill and send a message.
        </Text>
      </Center>
    );
  }

  return (
    <ScrollArea style={{ flex: 1 }} px="sm" py="sm" data-testid="lq-ai-message-list">
      {messages.map((m) => (
        <MessageBubble key={m.id} message={m} />
      ))}
    </ScrollArea>
  );
};
