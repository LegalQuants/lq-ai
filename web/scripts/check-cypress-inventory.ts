import { checkSpecInventory, SPEC_TRACKS, EXCLUDED_SPECS } from '../cypress/spec-tracks.ts';

checkSpecInventory();
console.log(
	JSON.stringify(
		{
			deterministic: SPEC_TRACKS.deterministic,
			llm: SPEC_TRACKS.llm,
			excluded: EXCLUDED_SPECS
		},
		null,
		2
	)
);
