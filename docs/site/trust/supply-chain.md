---
title: Supply chain
description: How to verify that a specific LQ.AI release's images are authentic, what the SBOM tells you, and dependency-update cadence — plus one claim this page corrects rather than repeats.
audience: [evaluator, operator]
status: draft
sources:
  - docs/security/releases/README.md
  - docs/security/dependencies.md
  - docs/security/cryptography.md
  - docs/BUILD-AND-RELEASE.md
  - README.md
  - .github/workflows/release.yml
sidebar:
  order: 6
---

Every LQ.AI release publishes container images with a cosign signature and an attached SBOM
attestation — not an assertion that the release was scanned before shipping, but artifacts you
verify yourself against the exact commit the image was built from. This page starts with the release-verification reference,
then corrects one claim this project makes elsewhere about itself: it says its releases carry SLSA
build provenance, and — as of the commit this page was checked against — the release workflow does
not produce that attestation.

<!-- include: docs/security/releases/README.md -->

## What "SLSA Level 3" does not currently mean here

README.md's badge row and `docs/security/README.md` both describe LQ.AI releases as carrying SLSA
Level 3 build provenance. Reading [`.github/workflows/release.yml`](../../../.github/workflows/release.yml)
against that claim: the workflow's `sign` job runs `cosign sign` (keyless image signing) and
`cosign attest --type spdxjson` (the SBOM attestation) — both real, both verifiable with the
commands above. It does **not** call `actions/attest-build-provenance` or any equivalent step; the
`attestations: write` permission is granted with a comment referencing that action, but the action
is never invoked. There is consequently no SLSA provenance attestation to verify today, and the
"Verify the SLSA build provenance" instructions in the included section above will not find one
against a current release. Treat the cosign image signature and the SBOM attestation as what you
can verify today; do not rely on the SLSA badge until this gap closes. This is reported as a
canonical-file problem rather than corrected here, since fixing the workflow is outside this page's
scope.

## Dependency management and cryptography

<!-- include: docs/security/dependencies.md -->

Provider API keys, session tokens, and the master key that wraps them each use a documented
primitive with a stated key-lifecycle and rotation procedure — see
[`docs/security/cryptography.md`](../../security/cryptography.md) for the full table (algorithm,
library, and the exact file and line each one is minted or verified at) and its "Known limitations"
section, which names the trade-offs made (HS256 over RS256, Fernet over AEAD-GCM, no HSM/KMS
integration) rather than leaving them undiscovered.

Release mechanics — which version bump a given change requires, and the gate that checks it —
follow [ADR 0025](../../adr/0025-release-versioning-and-pipeline-ordering.md), summarized on
[`docs/BUILD-AND-RELEASE.md`](../../BUILD-AND-RELEASE.md): `api`, `gateway`, `web`, and `proxy`
share one release version, a `version-consistency` CI job fails a tag push if the components
disagree with each other or with a required minor bump, and every `vX.Y.Z` tag maps to one exact
commit those images were built from. The desktop launcher's code-signing identity is a separate,
single-point-of-failure concern — see [Continuity](continuity.md).

## Next

- [Continuity](continuity.md) — the release-signing bottleneck this page's ADR 0025 reference names.
- [Published gaps](published-gaps.md) — where the SLSA-provenance gap sits in the full honest inventory.
- [Verify these claims yourself](verify-these-claims.md) — the commands from this page, gathered in one place.
