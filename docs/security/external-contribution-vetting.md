# Vetting external contributions — a maintainer security playbook

> **Audience:** anyone with merge rights on `lq-ai`. **Purpose:** how to adversarially review a pull request from a contributor you don't know before it touches `main`, so that LQ.AI never becomes a vector for embedding something in *other people's* self-hosted deployments.
>
> This is a **supply-chain** document. LQ.AI is self-hosted, bring-your-own-keys software that runs in the operator's environment, often holding privileged provider keys (the Inference Gateway, per [PRD §4](../PRD.md#4-the-lq-ai-inference-gateway)) and client legal data. A backdoor merged here doesn't compromise *us* — it compromises every operator who pulls the release. That asymmetry is why the bar for external contributions is high. Related: [SECURITY.md](../../SECURITY.md) (vuln disclosure), [docs/security/threat-model.md](threat-model.md), [docs/security/dependencies.md](dependencies.md), [CONTRIBUTING.md](../../CONTRIBUTING.md).

---

## 0. The one rule that prevents accidents

**A passing CI run is not a security review.** CI proves the code *runs* and passes lint/type/test gates. It says nothing about whether the code is *hostile*. Trivy and CodeQL catch known-bad patterns and CVEs; they do not catch a novel backdoor, a credential baked into a config, or a deployment recipe that quietly joins the operator to an attacker's network.

> **Never auto-merge or "self-merge on green" a PR from someone outside the maintainer/known-contributor circle.** Every external PR gets a human adversarial read first. Automated assistants (Claude Code et al.) must never merge an external PR — they may *review and report*, but the merge button is a human maintainer's, exercised only after the read below.

---

## 1. When this applies

Run the full playbook for any PR where **you do not already trust the author** (first-time contributor, unfamiliar fork) **AND** the change is in a sensitive class:

| Change class | Why it's sensitive |
|---|---|
| **Deployment / infra** (`deploy/**`, `docker-compose*.yml`, Dockerfiles, Helm) | Runs on the operator's host; can mount the Docker socket, run privileged, join networks, pull images, execute scripts. |
| **CI / workflows** (`.github/workflows/**`) | Runs in *our* trusted context with repo secrets; a malicious workflow can exfiltrate signing keys or poison releases. |
| **Dependencies** (`requirements*.txt`, `package.json`, lockfiles, `pyproject.toml`) | A new or bumped dependency is code you now ship. Typosquats, compromised versions, transitive pulls. |
| **The security boundary** (`gateway/**`) | Holds privileged provider keys; per [CODEOWNERS](../../.github/CODEOWNERS) already security-routed. |
| **Auth / authz / crypto / audit** | A subtle change here is a subtle privilege escalation or a silenced audit trail. |
| **Secrets handling** (`.env.example`, key management, anything reading env/keys) | Where a hardcoded credential or a phone-home endpoint hides. |

For a trivial docs/typo PR from an unknown author, a normal read suffices — but still skim for links/images that exfiltrate (tracking pixels, `curl` one-liners in a README).

---

## 2. The threat model — what you are actually looking for

You are not looking for bugs. You are looking for **intent to reach back out of the operator's environment, or to take more privilege than the change needs**. Concretely:

1. **Foreign control plane / network join** — anything that enrolls the operator's deployment into infrastructure the *contributor* controls: a baked-in VPN auth key, a custom coordination/login server, a mesh-network credential, a hardcoded callback URL.
2. **Phone-home / exfiltration** — outbound calls to non-operator endpoints: `curl … | bash`, telemetry to an unfamiliar host, a reverse proxy whose upstream is an external address, a "license check," an analytics beacon.
3. **Privilege escalation on the host** — Docker socket mounts (`/var/run/docker.sock` → root on the host), `privileged: true`, broad `cap_add`, `network_mode: host`, host-path volume mounts, `:latest`/unpinned images from untrusted registries.
4. **Credential capture** — config that logs/forwards secrets, a hardcoded key, a default that points the operator's secrets at the contributor.
5. **Exposure / weakening** — binding services to `0.0.0.0` by default, disabling auth, exposing an admin API (Caddy admin, Traefik dashboard, the gateway), turning off TLS verification, widening CORS to `*`.
6. **Scope creep as camouflage** — a "deployment recipe" PR that also edits app code, CI, or secrets handling. The out-of-scope hunk is where the payload hides.
7. **Supply-chain on dependencies** — a new package that's a typosquat, pinned to a yanked/compromised version, or pulls a large transitive surface for a trivial feature.

---

## 3. The adversarial read — a checklist

Pull the diff **read-only**. Do **not** check out the branch and run it, build its images, or execute its scripts during review. Read every line — a payload can sit in line 290 of a 374-line file.

```bash
gh pr view <N> --repo LegalQuants/lq-ai --json author,headRepositoryOwner,additions,deletions,changedFiles,files
gh pr diff <N> --repo LegalQuants/lq-ai           # read-only; do not execute anything from it
```

**Scope & shape**
- [ ] Who is the author? First-time / unfamiliar fork → full playbook.
- [ ] What files, and is every changed file *within the stated scope*? Flag any hunk touching app code, `.github/`, `gateway/`, auth, or secrets when the PR claims to be "just a deploy recipe."
- [ ] Deletions: does it remove or weaken an existing safeguard?

**Compose / Dockerfiles / infra**
- [ ] **Images**: official/known sources, or a random Docker Hub user? Pinned (ideally by `@sha256:` digest) or a floating/`:latest` tag?
- [ ] **Docker socket** mounted? (`/var/run/docker.sock`) → near-automatic reject.
- [ ] `privileged: true`, `cap_add`, `network_mode: host`, host-path volume mounts → justified by the feature, or excess privilege?
- [ ] `command:` / `entrypoint:` / healthchecks running scripts, `curl`, downloads?
- [ ] **Port bindings**: default to `127.0.0.1`, or exposed to `0.0.0.0`/the network without the operator opting in?
- [ ] Environment: any hardcoded secret, key, or token? Any var pointed at an external host?

**VPN / networking / proxy recipes** (the #134 class)
- [ ] Any **auth key / pre-auth token** committed or defaulted (Tailscale `TS_AUTHKEY`, WireGuard keys, etc.)? → reject; the operator must supply their own.
- [ ] A **custom control/login server** (`--login-server`, a headscale URL, a non-standard coordination endpoint)? → reject.
- [ ] Public exposure where private was claimed (`tailscale funnel` vs `serve`; `0.0.0.0`; an open inbound port)?
- [ ] Proxy upstreams: all **internal** service names, or does one point at an external/attacker host?
- [ ] Admin planes exposed (Caddy `admin`, Traefik dashboard, the **gateway**)?

**Dependencies**
- [ ] Every added/bumped package: real, correctly spelled, actively maintained, at a known-good version? Cross-check against [docs/security/dependencies.md](dependencies.md). Justified by the feature (per CONTRIBUTING's "don't add libraries without justification")?

**README / .env.example / scripts**
- [ ] Any instruction to run `curl … | bash`, add the contributor's node/tailnet, or use a specific key/endpoint?
- [ ] `.env.example`: all secrets empty placeholders? Any default pointing somewhere external?

**Verify what you reviewed is what you'd merge**
- [ ] The `gh` diff matches the branch; before merging, `git fetch` the head and re-read the exact commit. Beware a force-push between review and merge — re-read if the head SHA moved.

---

## 4. Disposition

- **Safe to merge** — scope contained, no item above tripped, design takes *no more privilege than the feature needs*, defaults are private/secure. Merge is still a deliberate human action; note in the PR that a security review was done.
- **Needs changes** — non-blocking hygiene (unpinned image, duplicated config, stale comment) or a fixable exposure. Request changes; merge after.
- **Reject / escalate** — any §2 vector that isn't an obvious mistake. If it looks deliberate, do **not** engage the contributor with specifics that teach them to hide it better; decline, and if it appears to be an attempted supply-chain attack, treat it under [SECURITY.md](../../SECURITY.md).

**Two things only a human decides** (no checklist clears them): **contributor trust** (a clean diff from an unknown author is still an unknown author — weigh history, account age, the nature of the change) and **residual supply-chain hygiene** (e.g. whether to require digest-pinning). When in doubt, ask for changes or hold; the cost of waiting is days, the cost of a merged backdoor is every operator.

---

## 5. Worked example — PR #134, "added caddy with tailscale deployment"

A first-time external contributor (an unfamiliar fork) opened a PR adding a Caddy + Tailscale reverse-proxy recipe: 4 new files under `deploy/caddy-tailscale/` (`Caddyfile`, `docker-compose.proxy.yml`, `README.md`, `.env.example`), 647 additions, **0 deletions**. Deploy + networking infra from an unknown author → full playbook. Here is exactly what we checked and found:

**Scope** — contained to a new directory; nothing touched app code, `gateway/`, `.github/workflows/`, auth, or secrets handling; zero deletions. Merging it changes **no existing code path** — it's purely opt-in.

**The decisive structural finding** — *there is no Tailscale container at all.* The recipe does **not** run Tailscale in Docker; it relies on the **host's already-installed, operator-authenticated** Tailscale and asks the operator to run one standard, documented command themselves (`tailscale serve`). That single design choice removes the entire "join every operator to my network" class of attack — there is no credential or control plane the contributor could inject.

**Checklist results:**

| Check | Finding |
|---|---|
| Baked-in Tailscale auth key | None — no `TS_AUTHKEY` anywhere; host owns the identity |
| Custom `--login-server` / coordination server | None — standard Tailscale only |
| `tailscale funnel` (public exposure) | Not used — `tailscale serve` = tailnet-private; README states "no public DNS, no inbound ports" |
| Image source | `caddy:2-alpine` — official library image (not a random user's) |
| Docker socket / privileged / host network / host mounts | None — only named volumes `caddy-data` / `caddy-config` |
| `command`/`entrypoint`/script execution, phone-home | None — no scripts, no external endpoints |
| Reverse-proxy upstreams | Internal only (`api:8000`, `web:8080`) — no external host |
| Caddy admin API / gateway exposure | Not exposed — only `:80` mapped; `auto_https off`; gateway stays on `127.0.0.1` (per PRD §4) |
| Default network exposure | Loopback (`127.0.0.1`) by default |
| Hardcoded secrets in `.env.example` | None — all secrets are empty placeholders; all binds default to `127.0.0.1` |

**Disposition: safe on the merits → "needs (minor) changes," then merge.** No §2 vector present; the design takes no more privilege than the feature needs. Non-blocking cleanup requested: (1) the recipe's `.env.example` is a 374-line near-duplicate of the root `.env.example` and will drift — slim it to the Caddy-specific delta plus a pointer; (2) a stale compose comment (`/api/v1/*` vs the actual `/lq-ai-api/v1/*` route). Residual human-judgment items left to the maintainer: contributor trust (first-time author) and whether to digest-pin the image.

The point of this example is not Caddy or Tailscale specifically — it's the *shape* of the read: scope it, find the one structural fact that collapses the threat (here, "no TS container/credential"), then walk the checklist to confirm nothing reaches back out of the operator's environment or grabs excess privilege, and separate the code findings from the human-trust call.

---

*Maintained alongside [SECURITY.md](../../SECURITY.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md). If you vet a contribution that surfaces a pattern this playbook doesn't cover, add it.*
