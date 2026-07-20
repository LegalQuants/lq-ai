import { useEffectAsync } from "@/hooks/useEffectAsync";
import { Combobox, Loader, Pill, PillsInput, useCombobox } from "@mantine/core";
import { useDebouncedValue } from "@mantine/hooks";
import React from "react";

//! This is just scaffolding. Maybe could make it more concrete by adding
//! a value array, include a partial function, etc.  


type Props = {
  //onSelect: (docketId:string) => void;
  onSelect: (docketId: string, title: string) => void;
  disabled?: boolean;
  value?: string;
};

export const indigoPill = {
  root: {
    background: "var(--mantine-color-indigo-7)",
  },
};


export const PillAutocomplete: React.FC<Props> = ({ onSelect, value }) => {
  let [text, setText] = React.useState<string>("");
  let [debouncedText] = useDebouncedValue(text, 400);
  let [partials, setPartials] = React.useState<{ id: string; title: string }[]>([]);
  const [loading, setLoading] = React.useState(false);

  const combobox = useCombobox({
    onDropdownClose: () => combobox.resetSelectedOption(),
  });

  useEffectAsync(async () => {
    if (debouncedText && text.trim().length > 1) {
      //This is for searching. You would set loading, get the Partials, 
    }
  }, [debouncedText]);

  let options = partials.map((m) => (
    <Combobox.Option value={m.id} key={m.id} c="dark">
      {m.id} {m.title}
    </Combobox.Option>
  ));

  const pill = value ? (
    <Pill
      withRemoveButton
      onRemove={() => onSelect("", "")}
      styles={indigoPill}
      c="white"
      children={value}
    />
  ) : null;

  options = options.length > 25 ? options.slice(0, 24) : options;
  const createLabel = text.trim();
  const canCreate = createLabel.length > 4 && options.length === 0;

  let handleSubmit = (id: string) => {
    if (id === "$create") {
      if (createLabel.length === 0) return;
      onSelect(createLabel, "");
      setText("");
      combobox.closeDropdown();
      return;
    }

    setText("");
    combobox.closeDropdown();
    let selected = partials.find((i) => i.id === id);
    if (selected) onSelect(selected.id, selected.title);
  };

  return (
    <Combobox
      onOptionSubmit={handleSubmit}
      withinPortal={false}
      store={combobox}
      disabled={value !== undefined}
      shadow="md"
    >
      <Combobox.DropdownTarget>
        <PillsInput
          onClick={() => combobox.openDropdown()}
          rightSection={loading ? <Loader size={18} /> : null}
        >
          <Pill.Group>
            {pill}

            <Combobox.EventsTarget>
              <PillsInput.Field
                onFocus={() => combobox.openDropdown()}
                onBlur={() => combobox.closeDropdown()}
                value={text}
                placeholder={!value ? "Search " : ""}
                onChange={(event) => {
                  combobox.updateSelectedOptionIndex();
                  setText(event.currentTarget.value);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Backspace" && text.length === 0) {
                    event.preventDefault();
                    setText("");
                  }
                }}
              />
            </Combobox.EventsTarget>
          </Pill.Group>
        </PillsInput>
      </Combobox.DropdownTarget>

      <Combobox.Dropdown hidden={!canCreate && options.length === 0}>
        <Combobox.Options>{options}</Combobox.Options>

        {canCreate && <Combobox.Option value="$create">+ Create {createLabel}</Combobox.Option>}
      </Combobox.Dropdown>
    </Combobox>
  );
};
