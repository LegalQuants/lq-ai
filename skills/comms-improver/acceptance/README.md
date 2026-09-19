# Acceptance pass - comms-improver v1.0.0

How to read this directory (structure per the
[skill-acceptance-tests mini-PRD](https://github.com/LegalQuants/lq-ai/blob/main/docs/contribute/mini-prds/skill-acceptance-tests.md)):

- `inputs/` - 7 samples: five real (SEC EDGAR exhibits, an FTC complaint, a U.S. Reports opinion, a
  published privacy policy, two de-identified own-practice advice memos) plus two short synthetic
  refusal inputs. Public-record sources keep their public party names; own-practice memos were
  de-identified at source and re-scanned before staging.
- `expected/` - the grading key per input. **Every criterion cites its source line** in
  `skills/comms-improver/test-plan.md` or `SKILL.md` (`[src: file:line «verbatim»]`), so each
  requirement is traceable rather than paraphrased. `00-common-structural.md` holds the shared checklist.
- `outputs/` - one file per input × audience × model, verbatim, with a metadata header. Naming:
  `<input>--<audience>--<model>.md` (an audience segment is added because comms-improver runs each
  sample at two audiences).
- `results.md` - the headline: summary grid, per-input verdicts + the reviewing attorney's notes,
  refusal table, and divergences.

## Coverage (input → test-plan scenario)

| Input | Scenario |
|---|---|
| 01-clause-lol | S1 contract clause |
| 03-memo-workforce (×2 audiences) | S2 legal memo + S6 audience-comparison |
| 05-privacy-policy | S3 regulatory language for sales |
| 06-authority | S4 authority preservation |
| 07-terms-of-art | S5 technical legal terminology |
| r1-already-clear | Refusal 1 |
| r2-best-efforts | Refusal 2 |

Seven inputs cover all six scenarios and both refusals (the mini-PRD asks for 3, prefers 5).

## Run record

- **Reviewing attorney:** Peter Scripps - Senior Privacy Counsel; licensed in Arizona.
- **Skill version tested:** 1.0.0 (`lq_ai.version` in `SKILL.md`).
- **Date of acceptance pass:** 2026-07-12.
- **Models:** `claude-sonnet-4-6` (the repo's pinned Sonnet tier) and `qwen2.5:7b` via local Ollama
  (the repo's local tier; the repo pins the `qwen3.5` family). Exact resolved ids in `results.md`.
- **Run method:** each skill invoked as the Inference Gateway assembles it (ADR 0007) via direct
  provider API calls mirroring the gateway's adapters - no live gateway, no Organization Profile,
  thinking off (the gateway sends no thinking parameter for skill runs).
- **Anonymization:** verified. No party names, identifying details, or client-confidential
  information in any input or output file; own-practice memos were de-identified at source and
  re-scanned; public-record inputs retain their public party names, which is appropriate.

## Attestation

> **Attestation.** I reviewed each recorded output. This record reflects my assessment of the skill's
> performance in these scenarios.
>
> *Signed: Peter Scripps, Senior Privacy Counsel (Arizona)* - 2026-07-12
