# Upstream request — make `skill_inputs` reach the model for non-templated skills

**To:** lq-ai backend session · **From:** Donna · **Date:** 2026-05-29 · **Pin observed:** `438198c`

## Summary

`MessageCreate.skill_inputs` is accepted, anonymized, and forwarded to the gateway as `lq_ai_skill_inputs`, but the collected values **never reach the model for any current built-in skill**. The gateway assembler only substitutes `{{placeholder}}` tokens in a skill body and silently drops any bound input the body doesn't reference. None of the 14 built-in skills use `{{}}` placeholders, so a UI that collects a skill's declared inputs (jurisdiction, perspective, audience, …) produces values that vanish. This blocks Donna from shipping a skill-input form with real payoff.

## Evidence (verified live at `438198c`)

- `gateway/app/skills/assembler.py` → `interpolate(template, bindings)` substitutes only `{{name}}`; its docstring notes "surplus inputs the body never references are tolerated" — i.e. dropped. `assemble_skill_prompt` calls `_render_skill(skill, inputs=bindings)` which interpolates `content_md` and reference files, nothing more.
- `grep -rl '{{' skills/*/SKILL.md` → no matches. No built-in body is templated.
- Repro: attach `comms-improver` (declares required `text` + `audience`) and POST a message with `skill_inputs: {"comms-improver": {"text": "...", "audience": "a 10-year-old"}}`. The model replies "I don't see any text to rewrite" — the bound inputs were dropped. A user-skill whose body contains `{{topic}}`/`{{style}}` *does* interpolate correctly, confirming the mechanism works only for templated bodies.
- `extract_required_inputs` re-parses frontmatter for required-input names, but missing required inputs are **not enforced** for built-ins in practice: posting `contract-qa` with no `skill_inputs` returns `200` (the model asks conversationally) rather than raising `SkillInputMissing`.

## Proposed fix

**Option A (recommended) — append unreferenced bound inputs as a labelled context block.**
After interpolation in `_render_skill` / `assemble_skill_prompt`, for each skill take the bound inputs that were *not* consumed by a `{{placeholder}}` and append them to the assembled skill prompt as a short labelled block, e.g.:

```
### Provided inputs for {skill_name}
- {input_name}: {value}
```

This makes every skill — templated or not — benefit from collected inputs, with no corpus edits. Backward compatible (skills that template their bodies are unaffected; the block only carries the leftovers). Smallest blast radius.

**Option B — template the built-in corpus.**
Add `{{}}` placeholders to each built-in `SKILL.md` body matching its declared inputs. Higher-fidelity prompts but touches every skill file and must stay in sync with the frontmatter `inputs` block.

A combination is reasonable: ship Option A as the safety net now, adopt Option B opportunistically per skill.

## Suggested test

In `gateway/tests/test_inference_skill_assembly.py` (or sibling): assemble a **non-templated** skill with bound inputs and assert the assembled prompt contains the input name and value (Option A), so collected inputs are provably visible to the model without requiring `{{placeholders}}`.

## Relay / pin-bump workflow

Per `donna-phase-status` memory: relay this to the lq-ai session; when merged, report the SHA so Donna bumps the submodule pin, runs `npm run gen:api`, rebuilds, verifies live, and logs the bump in `docs/decisions/lq-ai-pin.md`. Then build the deferred Donna composer skill-input form against the now-meaningful contract.
