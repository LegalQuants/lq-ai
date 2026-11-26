# Common structural expectations - every comms-improver run

Applies to every input x audience x model cell, in addition to the input's own key.
Provenance convention: every criterion carries its source - `[src: <file>:<line> «verbatim»]`
(test-plan.md and SKILL.md live at `skills/comms-improver/` in the repo). Structural
section-presence traces to the skill's own output contract; calibration traces to the
test-plan. Machine-checked by `check_provenance.py`.

## Output structure (the skill's documented contract)

- Header block with Audience / Purpose / Length constraint / Tone [src: SKILL.md:133 «**Audience:** [from input]»]
- Section present: Rewritten text [src: SKILL.md:138 «## Rewritten text»]
- Section present: What was changed [src: SKILL.md:142 «## What was changed»]
- Section present: Terms simplified or preserved [src: SKILL.md:146 «## Terms simplified or preserved»]
- Section present: Preservation-of-meaning concerns [src: SKILL.md:150 «## Preservation-of-meaning concerns»]
- Section present: Suggested follow-ups [src: SKILL.md:154 «## Suggested follow-ups»]
- Output length proportional to input [src: SKILL.md:159 «The output should be proportional to the input.»]

## Cross-cutting calibration (reviewing attorney)

- Meaning preserved - reliance on the rewrite leads to the same operational decisions [src: test-plan.md:156 «the rewrite, if relied on instead of the original, would lead to the same operational decisions»]
- No invented content [src: test-plan.md:157 «The rewrite does not add factual claims, exceptions, or qualifications not in the original.»]
- No silently dropped substance [src: test-plan.md:158 «The rewrite does not silently drop substantive provisions in the name of simplification.»]
- Legal effect unchanged [src: test-plan.md:34 «The rewrite does not change the legal effect (a "shall" doesn't become a "may"; an exception doesn't become a guarantee).»]
- Audience calibration is real across paired runs [src: test-plan.md:159 «Different audiences produce visibly different rewrites.»]
- Citations preserved where authorities are operative [src: test-plan.md:160 «When `preserve_authority: true` or when authorities are operative, the citations are preserved.»]

## Known test-plan / skill-contract conflict (graded per the contract; filed upstream)

- The test-plan requires a "what this skill does not do" enumeration [src: test-plan.md:161 «"What this skill does not do" enumeration present.»] but the skill's output contract ends at Suggested follow-ups [src: SKILL.md:154 «## Suggested follow-ups»] and emits no such section. Outputs are NOT failed for omitting what the contract never asks the model to produce; the contradiction is flagged to maintainers as a follow-up issue.
