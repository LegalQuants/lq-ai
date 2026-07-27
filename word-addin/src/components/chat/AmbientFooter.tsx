/**
 * AmbientFooter — bottom-of-chat reassurance bar, ported from the web
 * app's AmbientFooter.svelte (web/src/lib/lq-ai/components/AmbientFooter.svelte).
 * Renders the routed provider + tier for the latest assistant message.
 */
import React from "react";
import { Box } from "@mantine/core";
import { TrustPill } from "@/components/chat/TrustPill";

type AmbientFooterProps = {
  provider: string;
  tier: string;
};

export const AmbientFooter: React.FC<AmbientFooterProps> = ({ provider, tier }) => (
  <Box
    py={6}
    px="sm"
    style={{ borderTop: "1px solid var(--mantine-color-gray-3)" }}
    aria-label="Chat status"
  >
    <TrustPill variant="provider" label={`● ${provider} · ${tier}`} />
  </Box>
);
