# Contribution scope and upstream provenance

Pull requests to [LegalQuants/lq-ai](https://github.com/LegalQuants/lq-ai) are submissions to
**LQ.AI**, maintained by LegalQuants. LQ.AI's contribution process requires a DCO sign-off
on every commit and no separate LQ.AI CLA. See the
[root contribution guide](../../CONTRIBUTING.md#sign-off-developer-certificate-of-origin).
This describes LQ.AI's submission process; it does not settle the scope or legal effect of
the Open WebUI CLA retained in this checkout.

## LQ.AI work and inherited material

LQ.AI's policy is to accept original contributions under the root
[Apache License 2.0](../../LICENSE). Existing third-party material retains its applicable
terms and notices. Copying, adapting, or modifying that material requires checking its
provenance and terms, rather than assuming the root licence replaces them.

The `web/` component is an Open WebUI fork containing both inherited material and
downstream LQ.AI changes. Neither a location under `web/` nor an LQ.AI-specific directory
name establishes the provenance or applicable terms of every file. Review the actual
files, their notices, and their history, including any sources they reuse.

## File-specific submission terms for #749

For the focused renderer fix in [issue #749](https://github.com/LegalQuants/lq-ai/issues/749),
LQ.AI accepts the contributor's original changes to
`web/src/lib/lq-ai/components/LedgerEntryRow.svelte` and newly authored component regression
tests under the root Apache License 2.0, with DCO sign-off on every commit. LQ.AI does not
request agreement to the Open WebUI CLA as a condition of accepting this bounded patch,
or request that the contributor make a separate grant to Open WebUI Inc.

This scope covers displaying the existing authority reference, preserving other source
identities, wrapping long references, and tests using synthetic ledger entries. It does
not cover copying or adapting Open WebUI implementation or tests, changing the inherited
shell, or submitting the patch to Open WebUI. If the patch needs any of those changes,
raise the provenance and submission terms with a maintainer before expanding its scope.

This confirms LQ.AI's acceptance terms for this contribution. It does not amend inherited
licences, waive third-party rights, or provide a binding interpretation of Open WebUI's
CLA on behalf of Open WebUI Inc.

### Provenance checked for this scope

Checked at LQ.AI commit
[`ec13799bd`](https://github.com/LegalQuants/lq-ai/commit/ec13799bdd73da96b9815af32bb3281126571d1b).
The history supports treating this patch as work on LQ.AI's citation-ledger feature:

- `LedgerEntryRow.svelte` was added in
  [PR #228, `07f32162f`](https://github.com/LegalQuants/lq-ai/commit/07f32162f7aee9c97724a4549a59b75a9483c850).
  Its only subsequent modification at the checked base is the treatment display in
  [PR #234, `f5f32ccb5`](https://github.com/LegalQuants/lq-ai/commit/f5f32ccb5c3613ad4da2cac40c2f872853ceca89).
  Both changes occurred in LQ.AI after the Open WebUI import.
- The chip styles explicitly reuse LQ.AI's `M2Citations.svelte`, added in
  [PR #42, `8a1b3fc32`](https://github.com/LegalQuants/lq-ai/commit/8a1b3fc3281a8d905f2b0eff3f62600d0e623d9f).
  The row directly imports LQ.AI's types, `ledger-state.ts`, and `treatment-display.ts`;
  it does not directly import an Open WebUI component. The ledger types and state helper
  were added in #228; the treatment helper was added in #234.
- Existing related tests are
  [`citations/__tests__/ledger-state.test.ts`](../../web/src/lib/lq-ai/citations/__tests__/ledger-state.test.ts)
  and [`api/__tests__/ledger.test.ts`](../../web/src/lib/lq-ai/api/__tests__/ledger.test.ts),
  both added in #228, and
  [`__tests__/treatment-display.test.ts`](../../web/src/lib/lq-ai/__tests__/treatment-display.test.ts),
  added in #234. They test helpers and the API client; they are not row-rendering tests.
  No dedicated `LedgerEntryRow` rendering test exists at the checked base. The #749
  component tests are new work to be reviewed when submitted, not tests whose authorship
  has already been verified.
- An exact-text screen of the row, `M2Citations`, the two imported ledger helpers, and
  the three related test files found no runs of five consecutive nonblank lines shared
  with Open WebUI's tagged v0.9.2 or v0.11.0 frontend source. The upstream tag hashes were
  verified against its public repository. This supports the history review but cannot
  detect every adaptation or prove independent authorship of every line.

The root contribution guide at #228 already specified Apache 2.0 submissions and DCO
sign-off rather than a CLA. This file-specific statement makes LQ.AI's requested terms
explicit; it is not a declaration that all files under `web/src/lib/lq-ai/` share the
same provenance or licence.

## Why the Open WebUI documents are retained

These documents were brought in by the Open WebUI v0.9.2
[vendor import, `333fe6549`](https://github.com/LegalQuants/lq-ai/commit/333fe65495a2eb56eb20da52c72206d61469dc61)
and remain unchanged from that import:

- [Open WebUI licence](../../web/LICENSE): identifies Open WebUI Inc., refers to its CLA,
  and preserves earlier licence terms by reference to the history.
- [Open WebUI CLA](../../web/CONTRIBUTOR_LICENSE_AGREEMENT): contains the wording
  "this repository" and names Open WebUI Inc. as the recipient of its grant.
- [Multi-licence notice](../../web/LICENSE_NOTICE) and
  [licence history](../../web/LICENSE_HISTORY): describe the inherited MIT, BSD 3-Clause,
  and Open WebUI licence periods.

They document the upstream material's provenance and terms. They are not LQ.AI-authored
contribution instructions. Retaining them does not mean that LQ.AI asks for a separate
CLA, and LQ.AI's DCO policy does not amend, waive, or override upstream rights or terms.
This note does not reinterpret the CLA's "this repository" wording as a binding exclusion
of downstream submissions.

## When the scope is unclear

For the bounded #749 patch, use the file-specific submission terms above. The effect of
the inherited CLA on other downstream submissions, especially changes involving inherited
or mixed-origin material, may need clarification beyond this guide.

Before submitting a patch where the applicable terms remain unclear:

1. Ask an LQ.AI maintainer on the relevant
   [issue](https://github.com/LegalQuants/lq-ai/issues) or PR. For #749, use that issue's
   existing discussion.
2. Include the exact paths, relevant commits, notices, and any copied or adapted sources.
   Ask which submission terms LQ.AI expects for those changes and what remains unresolved
   about the upstream documents.
3. Wait for a recorded clarification before submitting the affected contribution.
   Maintainers should seek upstream or legal clarification where needed; a DCO sign-off
   alone does not resolve the ambiguity. Maintainer roles and the route for project scope
   decisions are in [GOVERNANCE.md](../../GOVERNANCE.md#how-decisions-are-made).
