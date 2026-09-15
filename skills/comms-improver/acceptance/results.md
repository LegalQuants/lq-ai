# Acceptance results - comms-improver v1.0.0

> Reviewing attorney: **Peter Scripps** (Senior Privacy Counsel; licensed in Arizona). The verdicts and notes below are his assessment.

## Run method

Skills are assembled and invoked exactly as the LQ.AI Inference Gateway does (ADR 0007), via direct provider API calls that mirror the gateway's adapters - no live gateway, no Organization Profile, thinking off (the gateway sends no thinking parameter for skill runs). System prompt = `# Skill: …` + SKILL.md body + `reference/*.md` + a `### Provided inputs` block, pinned by sha256.

| Model | Resolved id (captured at run time) | Parameters |
|---|---|---|
| claude-sonnet-4-6 | `claude-sonnet-4-6` | max_tokens 4096; temperature/top_p/thinking omitted; no tools |
| qwen2.5-7b | `qwen2.5:7b` | /api/chat; options.num_ctx 32768; num_predict/temperature/top_p omitted; no tools |

**Grading standard** (per `docs/acceptance-testing-framework.md`): structural (mechanical) + calibration (attorney judgment) + conservative-posture. n=1 per cell; grades reflect the single documented run.

## Summary

| Input × audience | Scenario | claude-sonnet-4-6 | qwen2.5-7b |
|---|---|---|---|
| Limitation of liability, for a layperson | Test-plan S1 - contract clause | CONCERN | FAIL |
| Workforce-analytics memo, for the CEO/CFO | Test-plan S2 - legal memo for executive (pairs with the layperson run for S6) | PASS | FAIL |
| Privacy-policy commitments, for the sales team | Test-plan S3 - regulatory language for sales | PASS | FAIL |
| FTC complaint passage, for an executive | Test-plan S4 - authority preservation | PASS | FAIL |
| Vicarious-liability holding (Meyer v. Holley), for a layperson | Test-plan S5 - technical legal terminology | PASS | FAIL |
| Workforce-analytics memo, for a layperson | Test-plan S6 - audience-comparison pair (same input as the executive run) | PASS | FAIL |
| Already-plain text (refusal 1) | Test-plan Refusal 1 - text does not need rewriting | PASS | CONCERN |
| “Best efforts” clause (refusal 2) | Test-plan Refusal 2 - simplification would alter legal effect | CONCERN | FAIL |

- **claude-sonnet-4-6: 6 PASS · 2 CONCERN · 0 FAIL**
- **qwen2.5-7b: 0 PASS · 1 CONCERN · 7 FAIL**

**No follow-up issue is filed.** This is a pre-launch acceptance pass - the skill is being tested, not triaged in production. On the frontier tier the skill passes (the two concerns are calibration notes, not defects); the local-tier failures are inference-capability signal across the model matrix, not comms-improver defects. Nothing here indicates a skill bug to track.


## Per-input results

### Limitation of liability, for a layperson  ·  Test-plan S1 - contract clause

**Issue.** Simplifying a limitation-of-liability clause for a customer with no legal background: does the rewrite keep the two distinct limits AND preserve the carveout that they do not apply to personal-injury / property-damage from equipment defects?

**Rule (verbatim from the governing docs):**
- “Rewritten text is meaningfully simpler (shorter sentences, fewer clauses, common-vocabulary words).” - `test-plan.md:32`
- “The rewrite does not change the legal effect (a "shall" doesn't become a "may"; an exception doesn't become a guarantee).” - `test-plan.md:34`
- “If the original clause has a defined term, the defined term is preserved (or explained in plain language without changing its scope).” - `test-plan.md:38`
- “If the original clause has carveouts or exceptions, all are preserved.” - `test-plan.md:39`

**claude-sonnet-4-6 - CONCERN**  
Output: [`outputs/01-clause-lol--layperson--claude-sonnet-4-6.md`](outputs/01-clause-lol--layperson--claude-sonnet-4-6.md)  
> The rewrite states an absolute cap ("we cannot owe you more than that, no matter what") and then immediately introduces the personal-injury/property-damage exceptions, which undercuts the cap just stated.
> 
> The cap phrasing "the specific equipment that caused the problem" is imprecise about limitations/recovery where an order contains multiple pieces of equipment and only one is at fault. It also blurs "services" vs. "equipment."

**qwen2.5-7b - FAIL**  
Output: [`outputs/01-clause-lol--layperson--qwen2.5-7b.md`](outputs/01-clause-lol--layperson--qwen2.5-7b.md)  
> It failed to simplify the damages taxonomy (extraordinary, punitive, etc. remain listed verbatim). It justifies retaining the legal jargon on the ground that the terms carry distinct meanings - accurate in the abstract, but contradicts the exact purpose of a 'make this plain language' skill.

### Workforce-analytics memo, for the CEO/CFO  ·  Test-plan S2 - legal memo for executive (pairs with the layperson run for S6)

**Issue.** Compressing a conditional-approval advice memo into an executive decision briefing: does the rewrite lead with the bottom line and preserve every load-bearing condition without softening the prohibition?

**Rule (verbatim from the governing docs):**
- “The rewrite leads with the recommendation or the conclusion.” - `test-plan.md:53`
- “The rewrite preserves the analysis's substantive conclusions; it does not assert different conclusions.” - `test-plan.md:56`
- “If the original memo has caveats, the rewrite preserves the caveats (or surfaces them in a "Caveats" section).” - `test-plan.md:60`

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/03-memo-workforce--executive--claude-sonnet-4-6.md`](outputs/03-memo-workforce--executive--claude-sonnet-4-6.md)  
> _(no note)_

**qwen2.5-7b - FAIL**  
Output: [`outputs/03-memo-workforce--executive--qwen2.5-7b.md`](outputs/03-memo-workforce--executive--qwen2.5-7b.md)  
> Opening fails to signal **conditional** approval, risking later surprise. Excluded signals described as 'off limits' rather than 'not collected.' It provides no reason for US-only scope or potential need for further review in case of international expansion. Tone in general invites further questions ('we'll stick to...').

### Privacy-policy commitments, for the sales team  ·  Test-plan S3 - regulatory language for sales

**Issue.** Rewriting privacy-policy commitments for the sales team: does it keep the promises specific in BOTH directions - not inventing permissions, and not overstating into 'we never share'?

**Rule (verbatim from the governing docs):**
- “The rewrite is operationally usable by the sales team.” - `test-plan.md:71`
- “The rewrite does not invent permissions or restrictions not in the original.” - `test-plan.md:72`
- “Caveats and escalation triggers are preserved.” - `test-plan.md:73`

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/05-privacy-policy--sales--claude-sonnet-4-6.md`](outputs/05-privacy-policy--sales--claude-sonnet-4-6.md)  
> Uses emoji (checkmark / cross / escalation glyphs), which may be appropriate for this sales-facing format.

**qwen2.5-7b - FAIL**  
Output: [`outputs/05-privacy-policy--sales--qwen2.5-7b.md`](outputs/05-privacy-policy--sales--qwen2.5-7b.md)  
> Significant omissions. The do-not-sell/share/transfer promise is only superficially preserved, and the no-third-party-marketing rule is weakened to a "we generally don't share for marketing" formulation where the source states it flatly. Retention periods are absent entirely, as are the required-by-law disclosure/retention exceptions. The guidance is also circular - effectively telling the sales team the practices "are in the policy."

### FTC complaint passage, for an executive  ·  Test-plan S4 - authority preservation

**Issue.** Rewriting an FTC complaint passage for an executive: do ALL five citations survive verbatim, and do the allegations stay allegations rather than becoming established facts?

**Rule (verbatim from the governing docs):**
- “Citations are preserved exactly.” - `test-plan.md:88`
- “The rewrite does not invent or alter authorities.” - `test-plan.md:89`
- “The reasoning chain that connects the authority to the conclusion is preserved.” - `test-plan.md:90`
- “If the original has multiple authorities, all are preserved.” - `test-plan.md:93`

*Reviewing-attorney judgment call:* One live question: the source hedges the 2010 predicate as 'alleged violations of Section 5(a)'; Claude's rewrite hardened it to «since it was found to have violated *Section 5(a) of the FTC Act*». A 2010 consent order does exist. Your call: allegation-to-finding upgrade (CONCERN) or acceptable shorthand (PASS)?

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/06-authority--executive--claude-sonnet-4-6.md`](outputs/06-authority--executive--claude-sonnet-4-6.md)  
> Allegations are correctly preserved as allegations.

**qwen2.5-7b - FAIL**  
Output: [`outputs/06-authority--executive--qwen2.5-7b.md`](outputs/06-authority--executive--qwen2.5-7b.md)  
> Scenario is unclear as presented in the narrative, jumping from 'there was a 2010 order' to 'there was a case' without establishing the main subject matter being described. Allegations also read as established.

### Vicarious-liability holding (Meyer v. Holley), for a layperson  ·  Test-plan S5 - technical legal terminology

**Issue.** Rewriting a Supreme Court passage on vicarious liability for a layperson: are the terms of art handled right (preserved-with-explanation or an operational equivalent, never silently dropped), and does the holding survive with precision?

**Rule (verbatim from the governing docs):**
- “The skill does not silently drop technical terms or replace them with imprecise equivalents.” - `test-plan.md:105`
- “If the term is operationally significant, the term is preserved with explanation.” - `test-plan.md:107`
- “The rewrite does not lose precision in service of simplification.” - `test-plan.md:110`
- “The rewrite flags terms it cannot fully capture in plain language.” - `test-plan.md:111`
- “Pass criteria: Reviewing attorney confirms precision is preserved.” - `test-plan.md:113`

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/07-terms-of-art--layperson--claude-sonnet-4-6.md`](outputs/07-terms-of-art--layperson--claude-sonnet-4-6.md)  
> Naming "respondeat superior" is unnecessary here - the focus is the holding - and the omission is not "silent," since the explanation conveys the underlying principle.

**qwen2.5-7b - FAIL**  
Output: [`outputs/07-terms-of-art--layperson--qwen2.5-7b.md`](outputs/07-terms-of-art--layperson--qwen2.5-7b.md)  
> Unhelpfully structured. Explaining the Supreme Court merely 'disagrees' with a lower court understates that the ruling binds lower courts (important for a lay audience). Omitting 'respondeat superior' is acceptable, though 'principal' introduces vocab that makes it read like a textbook. The phrase about 'not just the owner or manager' suggests misleadingly that both the company and the managers are responsible, rather than only the company.

### Workforce-analytics memo, for a layperson  ·  Test-plan S6 - audience-comparison pair (same input as the executive run)

**Issue.** Same memo, lay audience: do the two audience runs differ in tone/depth/vocabulary while carrying the SAME substance, rather than diverging in what they actually say?

**Rule (verbatim from the governing docs):**
- “The two rewrites differ in tone, depth, and emphasis appropriate to their audiences.” - `test-plan.md:122`
- “Both preserve the same substantive meaning.” - `test-plan.md:123`
- “Neither omits information the other includes (audience-driven emphasis differs; substance does not).” - `test-plan.md:124`

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/03-memo-workforce--layperson--claude-sonnet-4-6.md`](outputs/03-memo-workforce--layperson--claude-sonnet-4-6.md)  
> A good, audience-appropriate explanation; the substance is well captured for the register change.

**qwen2.5-7b - FAIL**  
Output: [`outputs/03-memo-workforce--layperson--qwen2.5-7b.md`](outputs/03-memo-workforce--layperson--qwen2.5-7b.md)  
> Framing suggests decision isn't yet made: 'we want to use tools.' And audience addressed is inconsistent. It drifts between addressing employees who may work on implementation: 'we might need to update our privacy notice' and has awkward phrasing: 'protect legal requirements.'
> 
> And 'our rules are different in other countries' wrongly implies the company's own rules rather than the law drive the decision. It omits the granular exclusions as well.

### Already-plain text (refusal 1)  ·  Test-plan Refusal 1 - text does not need rewriting

**Issue.** Given text that is already plain: does the skill recognize it needs no rewrite - saying so explicitly or light-editing with a note - rather than fabricating complexity?

**Rule (verbatim from the governing docs):**
- “Skill notes that the text doesn't need rewriting (or doesn't have legal content amenable to legal-jargon simplification).” - `test-plan.md:139`
- “Skill optionally proceeds with light edits and a note.” - `test-plan.md:140`
- “Pass criteria: Skill avoids producing low-quality rewrites of text that doesn't need rewriting.” - `test-plan.md:142`

**claude-sonnet-4-6 - PASS**  
Output: [`outputs/r1-already-clear--layperson--claude-sonnet-4-6.md`](outputs/r1-already-clear--layperson--claude-sonnet-4-6.md)  
> _(no note)_

**qwen2.5-7b - CONCERN**  
Output: [`outputs/r1-already-clear--layperson--qwen2.5-7b.md`](outputs/r1-already-clear--layperson--qwen2.5-7b.md)  
> No explicit acknowledgment that the text needed no changes.

### “Best efforts” clause (refusal 2)  ·  Test-plan Refusal 2 - simplification would alter legal effect

**Issue.** Given a 'best efforts' clause: does the skill flag that simplifying the phrase would alter the legal standard - and preserve or restore the term - rather than silently downgrading it?

**Rule (verbatim from the governing docs):**
- “Skill explicitly flags that simplification would alter legal effect.” - `test-plan.md:149`
- “Skill either preserves the original term with explanation, or refuses to simplify the specific phrase.” - `test-plan.md:150`
- “Pass criteria: Skill distinguishes preservation of meaning from simplification of vocabulary.” - `test-plan.md:152`

**claude-sonnet-4-6 - CONCERN**  
Output: [`outputs/r2-best-efforts--layperson--claude-sonnet-4-6.md`](outputs/r2-best-efforts--layperson--claude-sonnet-4-6.md)  
> Not certain 'best efforts' needs to be surfaced verbatim in a simplified version. It carries more meaning than 'do your best,' which is why it's a term of art. But the skill is supposed to explain the terms of art in an approachable way. And the answer here avoided a silent downgrade by explaining the significance of the principle involved.

**qwen2.5-7b - FAIL**  
Output: [`outputs/r2-best-efforts--layperson--qwen2.5-7b.md`](outputs/r2-best-efforts--layperson--qwen2.5-7b.md)  
> The alteration risk is not explicitly surfaced.

## Refusal scenarios

| Input | claude-sonnet-4-6 | qwen2.5-7b |
|---|---|---|
| Refusal 1 - already clear | PASS | CONCERN |
| Refusal 2 - best-efforts trap | CONCERN | FAIL |

## Claude-observed methodology notes

These are engineering/methodology observations recorded by the assistant (Claude) that ran the pass - how the runs were produced and where they diverge from the test-plan's assumptions. They are **not** part of the reviewing attorney's assessment or attestation.

- **Output naming** carries an audience segment (`<input>--<audience>--<model>.md`) because the comms-improver test-plan runs each sample at two audiences; the mini-PRD's example naming shows `<input>-<model>.md`.
- **Local-tier context window (product finding).** The gateway's Ollama adapter sets no `num_ctx`, so at Ollama's ~2-4k default this skill's ~7-8k-token prompt is silently truncated. Runs here set `num_ctx=32768`; noted for maintainers.
- **No `preserve_authority` input.** The comms test-plan Scenario 4 assumes a `preserve_authority` input the skill does not declare; the authority-preservation run used `preserve_specific_terms`.
- **Test-plan / skill-contract conflict.** The test-plan's cross-cutting checks require a "what this skill does not do" enumeration in output, but the skill's SKILL.md output contract emits no such section; outputs were not failed for omitting it.
- **Models.** The mini-PRD requires two distinct models (one cloud, one local). Claude ran on the repo's pinned `claude-sonnet-4-6`; the local tier ran `qwen2.5:7b` via Ollama - a representative lightweight local model. The repo's example gateway config pins the newer `qwen3.5` family (released 2026-02), not yet packaged as an Ollama library tag; a future pass can use it. Both are gateway-supported providers.
- **Terms-of-art cell scope.** The Meyer v. Holley (Scenario 5) grading key covers terms-of-art handling and precision only; case-citation preservation is Scenario 4's requirement (the FTC cell) and is not applied here. Every grading criterion carries its `test-plan.md` line reference in the `expected/` key.

