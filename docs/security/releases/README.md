# Release Verification

> **Scope:** how operators verify that a specific LQ.AI release's container images, SBOM, and SLSA provenance are authentic — i.e., that they were built by the LegalQuants release workflow and not tampered with in transit.

LQ.AI uses [sigstore keyless signing](https://docs.sigstore.dev/) (cosign + Fulcio + Rekor) and [SLSA build provenance](https://slsa.dev/spec/v1.0/) attestations.

## Quick verify (single image)

```bash
cosign verify \
  --certificate-identity-regexp "https://github.com/legalquants/lq-ai" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/legalquants/lq-ai-api:v0.1.0
```

A successful run prints the signing certificate's issuer, subject (the workflow OIDC identity), and Rekor transparency-log entry. Failure prints a diagnostic explaining whether the signature is missing, the cert doesn't match, or the cert's identity doesn't match the regexp.

## Verify all three images in a release

```bash
TAG=v0.1.0
for service in api gateway web; do
  echo "=== ${service} ==="
  cosign verify \
    --certificate-identity-regexp "https://github.com/legalquants/lq-ai" \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    "ghcr.io/legalquants/lq-ai-${service}:${TAG}"
done
```

## Verify the SBOM attestation

The SBOM is bound to the image digest as a cosign attestation of type `spdxjson`:

```bash
cosign verify-attestation \
  --type spdxjson \
  --certificate-identity-regexp "https://github.com/legalquants/lq-ai" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/legalquants/lq-ai-api:v0.1.0 | jq -r '.payload' | base64 -d | jq '.predicate' > api.spdx.json

# Then scan the SBOM with your preferred tool
grype sbom:./api.spdx.json
```

## Verify the SLSA build provenance

SLSA provenance is attached via GitHub's attestations service by `actions/attest-build-provenance`, which runs in `.github/workflows/build-image.yml`. That is a reusable workflow that `release.yml` calls once per service. Verify with the `gh` CLI, pinning the builder:

```bash
gh attestation verify \
  oci://ghcr.io/legalquants/lq-ai-api:<tag> \
  --owner legalquants \
  --signer-workflow LegalQuants/lq-ai/.github/workflows/build-image.yml
```

A successful run prints the signer workflow (`build-image.yml`), the calling workflow (`release.yml`), the trigger event (tag push), and the input commit SHA. Together these show the image was built from that exact source by that exact workflow.

**SLSA level, and which releases it covers.** The `--signer-workflow` pin is what makes this SLSA v1.0 **Build Level 3**. The provenance is signed by an isolated reusable workflow that the calling workflow cannot tamper with ([GitHub's guidance](https://docs.github.com/en/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-and-reusable-workflows-to-achieve-slsa-v1-build-level-3)). Releases up to and including **v0.7.1** also carry a provenance attestation, but it was generated inside `release.yml`'s own jobs, so it is signed by `release.yml` and is Build Level 2. For those tags, drop `--signer-workflow` (or pin `--signer-workflow LegalQuants/lq-ai/.github/workflows/release.yml`). Build Level 3 applies from the first release after v0.7.1.

## What the verification proves

- **Image authenticity:** the signature was produced by a process holding a short-lived Fulcio cert bound to the LegalQuants workflow OIDC identity. An attacker who obtained access to the registry but not to the workflow's OIDC identity cannot produce a valid signature.
- **Image provenance:** the SLSA attestation pins the image to a specific commit SHA + workflow + builder (the isolated `build-image.yml` reusable workflow, for releases after v0.7.1). An attacker who modified the source after the fact cannot reproduce the attestation without re-running the workflow (which would produce a new, distinct attestation with a new timestamp).
- **Dependency snapshot:** the SBOM lists every dependency at build time. An attacker who substituted a dependency post-build cannot match the SBOM hash.

## What the verification does NOT prove

- The image is **free of vulnerabilities**. Verification proves authenticity, not safety. Operators run SCA tools against the SBOM independently — see [docs/security/dependencies.md](../dependencies.md).
- The release **was a deliberate choice by LegalQuants maintainers**. A compromised maintainer with the ability to push a tag could produce a valid release. This is the trust assumption shared by all OSS — see [SECURITY.md](../../../SECURITY.md) for the disclosure process if you suspect a compromised release.

## Operator-key signing (forks)

If you fork LQ.AI and prefer operator-controlled key signing (e.g., for air-gapped deployments where short-lived OIDC certs aren't available), replace the keyless flow in `.github/workflows/release.yml` step "Sign container image (keyless)" with:

```yaml
      - name: Sign container image (operator key)
        env:
          COSIGN_PRIVATE_KEY: ${{ secrets.COSIGN_PRIVATE_KEY }}
          COSIGN_PASSWORD: ${{ secrets.COSIGN_PASSWORD }}
        run: |
          cosign sign --yes --key env://COSIGN_PRIVATE_KEY \
            ghcr.io/your-org/lq-ai-${{ matrix.service }}:${{ steps.tag.outputs.tag }}
```

Then operators verify with:

```bash
cosign verify --key cosign.pub ghcr.io/your-org/lq-ai-api:v0.1.0
```

This trades keyless's ergonomic advantages for an operator-managed key lifecycle. For most public OSS deployments, keyless is the right default.

## Cross-references

- [docs/security/README.md](../README.md) — security-doc index.
- [docs/security/dependencies.md](../dependencies.md) — vulnerability monitoring.
- [.github/workflows/release.yml](../../../.github/workflows/release.yml) — the release workflow that produces these artifacts.
