/**
 * SavedPromptsRow — collapsed header for the saved-prompts panel,
 * scaffolded from the web app's SavedPromptsPanel.svelte
 * (web/src/lib/lq-ai/components/SavedPromptsPanel.svelte). Static
 * scaffold: "+ New" / "Show" don't do anything yet — the list, quick
 * insert, and promote-to-skill flow land when `savedPromptsApi` is wired
 * up on the add-in side.
 */
import React from "react";
import { Group, Text, Button } from "@mantine/core";

export const SavedPromptsRow: React.FC = () => (
  <Group justify="space-between">
    <Text fw={600} size="sm">
      Saved prompts
    </Text>
    <Group gap={6}>
      <Button variant="light" color="sage" size="xs">
        + New
      </Button>
      <Button variant="default" size="xs">
        Show
      </Button>
    </Group>
  </Group>
);
