/**
 * SkillsRow — collapsed header for the skill picker, scaffolded from the
 * web app's SkillPicker.svelte (web/src/lib/lq-ai/components/SkillPicker.svelte).
 * Wired to `skillsAtom`/`selectedSkillNamesAtom` (see src/services/skillClient.ts).
 * Per-skill frontmatter input forms (SkillInputForm.svelte's analog)
 * aren't ported — no skill in the built-in set requires them for a
 * first pass, and it's additive later, not a rewrite.
 */
import React, { useMemo, useState } from "react";
import { useAtomValue } from "jotai";
import {
  Group,
  Text,
  Popover,
  TextInput,
  Stack,
  Checkbox,
  ScrollArea,
  Pill,
  UnstyledButton,
} from "@mantine/core";
import { skillsAtom, selectedSkillNamesAtom } from "@/store";
import { skillClient } from "@/services/skillClient";

export const SkillsRow: React.FC = () => {
  const [opened, setOpened] = useState(false);
  const [search, setSearch] = useState("");

  const skills = useAtomValue(skillsAtom);
  const selectedNames = useAtomValue(selectedSkillNamesAtom);
  const selectedSkills = useMemo(
    () => skills.filter((s) => selectedNames.includes(s.name)),
    [skills, selectedNames]
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return skills;
    return skills.filter(
      (s) => s.name.toLowerCase().includes(q) || s.title.toLowerCase().includes(q)
    );
  }, [skills, search]);

  return (
    <Group gap={4} wrap="wrap" align="center">
      <Popover shadow="md" opened={opened} onChange={setOpened} withinPortal={false}>
        <Popover.Target>
          <UnstyledButton
            c="sage"
            fw={600}
            fz="sm"
            onClick={() => setOpened((v) => !v)}
            data-testid="lq-ai-skill-picker-toggle"
          >
            + Skill
          </UnstyledButton>
        </Popover.Target>

        <Popover.Dropdown>
          <Stack gap="xs" w={220}>
            <TextInput
              placeholder="Search skills…"
              size="xs"
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              autoFocus
            />
            {filtered.length === 0 && (
              <Text size="xs" c="dimmed" fs="italic">
                {search ? `No skills match "${search}".` : "No skills available."}
              </Text>
            )}
            <ScrollArea.Autosize mah={160}>
              <Stack gap={4}>
                {filtered.map((skill) => (
                  <Checkbox
                    key={skill.name}
                    size="xs"
                    label={skill.title}
                    checked={selectedNames.includes(skill.name)}
                    onChange={() => skillClient.toggleSelected(skill.name)}
                  />
                ))}
              </Stack>
            </ScrollArea.Autosize>
          </Stack>
        </Popover.Dropdown>
      </Popover>

      <Pill.Group style={{flex: 1}}>
        {selectedSkills.map((skill) => (
          <Pill
            key={skill.name}
            withRemoveButton
            onRemove={() => skillClient.toggleSelected(skill.name)}
            size="sm"
          >
            {skill.title}
          </Pill>
        ))}
      </Pill.Group>
    </Group>
  );
};
