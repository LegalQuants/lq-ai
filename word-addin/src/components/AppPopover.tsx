import { ActionIcon, Popover, Stack } from "@mantine/core";
import { IconSettings } from "@tabler/icons-react";


type Props = {
  i?: any;
}
export let AppPopover:React.FC<Props> = () => {
  return (
    <Popover shadow="md">
      <Popover.Target>
        <ActionIcon children={<IconSettings />} />
      </Popover.Target>

      <Popover.Dropdown>
        <Stack gap="sm">
          
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}