# Help with compliance and procurement reviews

Help turn broad claims into specific questions, controls and supporting evidence.

## Useful ways to help

Review a questionnaire answer, identify the evidence needed for a requirement or document which responsibilities belong to the app and which belong to the team running it.

## Make the conclusion traceable

Explain how the evidence supports the answer. A setting, policy or code comment alone may not establish that a particular installation meets the requirement. The Procurement-Readiness Pack's `[OPERATOR-CONFIGURABLE]` marker is this project's own device for keeping that distinction visible — it flags an answer that depends on the operator's own configuration instead of asserting it holds for every deployment (see [`docs/procurement/README.md`](../procurement/README.md)).

## Specific projects to consider

The contribution briefs cover completing the procurement-readiness pack and mapping the design to NIST AI RMF. The OWASP language-model risk mapping is a useful joint task with an engineer. Start from the existing SIG Lite starter and the framework brief, identify missing evidence, and avoid describing planned controls as implemented.

### Details

- **[Procurement-Readiness Pack](mini-prds/procurement-readiness-pack.md)** — pre-filled SIG Lite and CAIQ Lite questionnaire responses, plus a cover letter explaining why a self-hosted open-source deployment is an unusual procurement. A starter SIG Lite response covering the privileged-matter-handling domain is already merged; the gap is the remaining ~15 SIG Lite domains, the full CAIQ Lite response, and the cover letter. Scoped as **M** effort with **High** foundation readiness — the contribution board's effort key reads M as a few days.
- **[NIST AI RMF 1.0 Profile mapping](mini-prds/nist-ai-rmf-profile.md)** — maps the project's design and operational practices against the NIST AI Risk Management Framework (AI 100-1) and its Generative AI Profile (AI 600-1), function by function: Govern, Map, Measure, Manage. This document does not exist yet in [`docs/compliance/`](../compliance/README.md), and federal and federal-adjacent procurement reviewers look for it specifically. Also scoped as **M** effort with **High** foundation readiness, but the mini-PRD sets its own expectation higher — roughly one to two focused weeks — so use that figure for this item rather than the board's generic one.
- **[OWASP LLM Top 10 mapping](mini-prds/owasp-llm-top10-mapping.md)** — scoped for a security-aware engineer, but its output (a risk-by-risk mapping of prompt injection, sensitive-information disclosure, and the rest of the OWASP LLM list against the project's actual mitigations) is a document your review process will also want. You bring the framework fluency; an engineer partner brings the code citations.

## Review and ownership

Claim the work through an issue and agree its scope with a maintainer. The procurement and compliance paths have counsel review requirements in addition to engineering review. Remove client information from examples before contributing; prior completion of your own questionnaire does not make it suitable to publish unchanged.

### Details

Open a GitHub issue titled with the mini-PRD's slug (for example, `procurement-readiness-pack`), comment that you would like to take it, and wait for a maintainer response — typically within a week. Each mini-PRD's own "Where to start" section is the working brief once you begin; see [the contribution board's](EASIEST-CONTRIBUTIONS.md) claim process for the rest.

[CODEOWNERS](../../.github/CODEOWNERS) routes both `docs/compliance/` and `docs/procurement/` to the project's counsel reviewers in addition to the maintainer team, because these documents affect what an operator can tell their own procurement or governance function. A pull request against either directory does not merge on maintainer approval alone.
