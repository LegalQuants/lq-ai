import { Anchor, Box, Group } from "@mantine/core";

type Props = {
  origin: string;
};
export const Footer: React.FC<Props> = ({ origin }) => {
  return (
    <Box className="lq-footer" component="footer">
      <Group justify="space-between">
        <Anchor
          href={`${origin}/lq-ai`}
          target="_blank"
          rel="noopener noreferrer"
          children="Open LQ.AI web app"
        />
        <Anchor
          href="https://github.com/LegalQuants/lq-ai/blob/main/docs/PRD.md#de-287--word-add-in-feature-surface-chat-skills-playbooks-tier-badge--deferred-to-m4--community-contribution"
          target="_blank"
          rel="noopener noreferrer"
          children="Contribute (DE-287)"
        />
      </Group>
    </Box>
  );
};
