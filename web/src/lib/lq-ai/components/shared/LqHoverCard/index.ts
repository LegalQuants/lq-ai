import Root from './Root.svelte';
import Target from './Target.svelte';
import Dropdown from './Dropdown.svelte';

// Same namespacing technique bits-ui uses for `Button.Root` elsewhere in this
// codebase: attach the parts as static properties on the Root component
// itself, so `<LqHoverCard>` is the Root and `<LqHoverCard.Target>` /
// `<LqHoverCard.Dropdown>` are the same objects imported above.
//
// `Object.assign(Root, { Target, Dropdown })` looks equivalent but confuses
// svelte2tsx's prop-type inference into merging Root's and Dropdown's props
// into one type — the explicit cast + direct assignment below avoids that.
const LqHoverCard = Root as typeof Root & { Target: typeof Target; Dropdown: typeof Dropdown };
LqHoverCard.Target = Target;
LqHoverCard.Dropdown = Dropdown;

export default LqHoverCard;
