# On-ramp for a practicing lawyer

If you are a practicing lawyer and you want your first contribution to be reading real output rather than writing code, start here.

## What to claim first

The single best first contribution is not a new skill — it is **certifying an existing one**. Each of the ten skills the acceptance-tests mini-PRD tracks ships with a `test-plan.md` describing the scenarios it should handle; what none of them yet has is the acceptance pass — running the skill against real (anonymized) documents and recording whether the output meets the structural expectations the test plan describes. The [acceptance-tests mini-PRD](mini-prds/skill-acceptance-tests.md) scopes this at roughly half a day per skill, ten skills tracked as ten separate pull requests, no coding required. It is on [the contribution board](EASIEST-CONTRIBUTIONS.md).

Authoring a new skill is the second path, and where it lands is decided by [ADR 0024](../adr/0024-jurisdiction-and-practice-area-expansion.md): a community work-product skill goes to `legalquants/lq-skills`, while `lq-ai`'s own `skills/` directory holds the curated first-party set. A change to an existing first-party skill — a new regime for DPA Checklist Review, say — stays here; a new domain skill is a `lq-skills` contribution. [`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md) catalogs the candidates — new domain skills (settlement-agreement review, employment offer letter review, HIPAA BAA review), additional jurisdictions for the DPA Checklist Review skill, and structural patterns like a defined-terms consistency check. Read at least two existing starter skills in your practice area before drafting; the [skill-authoring on-ramp](../skills/author-your-first-skill.md) walks through that in full.

If your practice diverges from a starter skill, forking is a supported outcome, not a failure — a fork can stay private to your deployment, come back as a named variant alongside the original (`msa-review-saas`, `msa-review-financial-services`), or come back as a PR against the original if it fixes a substantive issue.

## The five steps

Every skill carrying legal substance goes through claim → draft → attest → review → merge, documented in full in [`skills/CONTRIBUTING.md`](../../skills/CONTRIBUTING.md). **Claim** on a tracking issue first, so two contributors don't duplicate the same skill. **Draft** the `SKILL.md`, any reference files, and at least one worked example. **Attest** in your pull request description — see [the attestation bar](../../skills/CONTRIBUTING.md#3-attest) for what that certification covers and how it decays. **Review** by a practicing attorney and an engineer, in parallel, before merge.

## Where review happens

Everything under this repository's `skills/` — the folder as a whole, not only individual skill folders, and holding the curated first-party set per ADR 0024 — is routed by [CODEOWNERS](../../.github/CODEOWNERS) to both the maintainer team and the project's practicing-attorney reviewers. A skill pull request is not mergeable on maintainer approval alone; it needs the attorney reviewer's sign-off on the substance and an engineer's sign-off on the operational shape — frontmatter completeness, whether the workflow runs cleanly, whether the worked examples are actually worked.
