---
title: Data, privacy and evidence
description: Where your information goes, who can access it, and what the app records — one page indexing every artifact a security, evaluator, or procurement review needs.
audience: [evaluator, operator, partner]
status: draft
sources:
  - docs/HONEST-STATE.md
  - docs/security/threat-model.md
  - docs/security/anonymization.md
  - docs/security/audit-logging.md
  - docs/security/releases/README.md
  - docs/security/dependencies.md
  - GOVERNANCE.md
  - SECURITY.md
  - docs/procurement/README.md
  - docs/compliance/README.md
  - docs/adr/0025-release-versioning-and-pipeline-ordering.md
sidebar:
  order: 1
---

Understand where your information goes, who can access it, and what the app records. You are here
because someone asked you to sign off on LQ.AI, or to hand it to someone who will. This page is the
index of every artifact that answer will need — what it covers, what it deliberately leaves to you,
and the file in the repository it is checked against. Every table row links to a page that curates
the underlying artifact rather than restating it, so what you read here and what the code does stay
the same document.

LQ.AI is self-hosted: there is no LegalQuants-operated service standing between your deployment
and this evidence. Every claim below traces to a file you can open in the same repository that
built the running system — see [Verify these claims yourself](../../trust/verify-these-claims.md) for the
commands.

## The artifacts

| Artifact | What it covers | What stays the operator's | Canonical file |
|---|---|---|---|
| [What information is sent outside LQ.AI?](../../trust/what-leaves-my-deployment.md) | Where chat and skill content goes, tier by tier, and what a miss looks like | Which inference tier you route each matter to | `docs/security/anonymization.md` |
| [Review the security risks](../../security/threat-model.md) | STRIDE-by-component threats and mitigations for the five production services | Your host, OS, IdP, and secret custody | `docs/security/threat-model.md` |
| [Replace identifying details before sending a request](../../security/anonymization.md) | What the pseudonymization layer catches, skips, and has (and has not) been measured against | Recognizer tuning for your own document conventions | `docs/security/anonymization.md` |
| [What the audit log records](../../security/audit-logging.md) | What is logged, what is not, retention, and the one-query evidence pattern | Tamper-evidence infrastructure, retention policy | `docs/security/audit-logging.md` |
| [Check the software you download](../../security/releases/README.md) | Signed images, SBOM, dependency-update cadence | Scanning the SBOM and applying patches | `docs/security/releases/README.md` |
| [Known limitations](../../HONEST-STATE.md) | Shipped / partial / scaffold / deferred, with a verification path for every row | None — this is the honest inventory | `docs/HONEST-STATE.md` |
| [How project decisions are made](../../../GOVERNANCE.md) | Who decides, how, and where the record lives | None | `GOVERNANCE.md` |
| [Keep the app running if circumstances change](../../trust/continuity.md) | What survives if the maintainers stop | Your own backups and exports | `LICENSE` |
| [Report a security problem](../../../SECURITY.md) | How to report a vulnerability, and how the project decides public vs. private handling | None | `SECURITY.md` |
| [Answer security and procurement questions](../../procurement/README.md) | A pre-filled SIG Lite starter for privileged-matter handling | The rest of your procurement process | `docs/procurement/sig-lite.md` |
| [Match requirements to controls and evidence](../../compliance/README.md) | Framework-alignment status (SOC 2, ISO, GDPR, HIPAA, FedRAMP) and what's still planned | Your own certification | `docs/compliance/README.md` |
| [Release history](../changelog/index.intro.md) | What each released version changed, and the upgrade class it carries | Deciding when to re-review | `docs/releases/` |
| [Check the claims yourself](../../trust/verify-these-claims.md) | Commands and files to check every claim on this page yourself | — | `README.md` |

Each canonical file is named as a repository path; every page's footer stamp links it at the
commit that page was checked against.

## The URL-stability commitment

Once a page under `/trust/` ships, its address does not change. You can cite a specific URL in a
security questionnaire, an insurer's file, or a signed-off procurement record, and it will still
resolve a year later — the page's content may be revised (the footer stamp on every page names the
commit it was last checked against), but the location does not move. If a URL you cited from this
tree stops resolving, that is a bug against this site, not an expected consequence of a release.

:::note[Professional duty]
An evaluator relying on this tree for a client engagement or an internal sign-off is entitled to
cite it by URL without re-verifying the address every time. That is the commitment the section
above makes explicit, and it is what lets you complete a security questionnaire from this page
without a meeting.
:::

## Next

- [Check the claims yourself](../../trust/verify-these-claims.md) — the commands and files behind every row above.
- [Known limitations](../../HONEST-STATE.md) — the honest inventory of what is shipped, partial, or deferred.
- [What information is sent outside LQ.AI?](../../trust/what-leaves-my-deployment.md) — start here if your first question is about data flow.
- [Versioning and upgrade classes](../../adr/0025-release-versioning-and-pipeline-ordering.md) — how to tell what changed between two named releases when a re-review comes round.
