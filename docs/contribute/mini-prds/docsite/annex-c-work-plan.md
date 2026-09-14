# Annex C — Page trees, sizing, and claimable work

**Effort key** (as on the contribution board): **S** = under a day · **M** = a few days ·
**L** = more than a week. **Kind**: *curation* = an existing repo file becomes a page
(reorder, retitle, entry sentence, onward links, commit stamp); *new* = written from
nothing; *generated* = a build step over structured sources, near-zero cost per release
thereafter.

All numbers are **estimates for planning, not commitments** — a contributor claiming an
item is expected to re-size it. Nothing here is assigned to anyone. Review is by the
maintainer by default; because content stays in the repository (ADR 0028), CODEOWNERS
routing for security, compliance and skills paths applies as it does today.

---

## 1. Page trees per namespace

### `/` + `/start/` — entry hub and orientation · 6 pages · [all audiences · J1, J2]

| Page | Kind | Est. |
|---|---|---|
| Entry hub: definition, data boundary, goal cards, "not for" link | new | S |
| Is LQ.AI for you? *(J1 — considerations page with checkable disqualifiers)* | new | S |
| What it touches: prerequisites, hardware summary, data-boundary summary | new | S |
| Quickstart *(reordered; recovery inlined)* | curation | S |
| Choose your path *(routing by goal, permission to skip)* | new | S |
| Where end-user help lives *(the in-app Learn boundary, stated as policy)* | new | S |

### `/operate/` — run it · ~16 pages + extensible recipes · [OPS · J2, J6, J9, J11, J17, J19, J20, J22]

| Page | Kind | Est. |
|---|---|---|
| Hub | new | S |
| Install: macOS desktop | curation | S |
| Install: Docker Compose | curation | S |
| Install: Helm / Kubernetes *(chart currently has no prose at all)* | new | S–M |
| Reverse proxy + TLS | curation | S |
| Air-gapped / local-only + **egress inventory** *(publish what the air-gap CI measures)* | curation + generated | S–M |
| Hardware sizing: named reference configurations | new | S–M |
| Architecture explainer | curation | S |
| Logs & monitoring | curation | S |
| Backup & restore *(no benchmarked hobbyist site has this; regulated sites treat it as the floor)* | new | M |
| Upgrade guide *(per-version notes come from `/changelog/`)* | new | M |
| Rotate a leaked provider key *(runbook: revoke, blast radius, audit query)* | new | S |
| Symptom index: "something is wrong" *(triage branches: install / upgrade / silent-degrade)* | new | S–M |
| Move machines / uninstall cleanly | new | S |
| Troubleshooting & FAQ | new | S–M |
| Headless boot: what runs without the web UI, labelled unsupported, no compatibility promised *(ADR 0031 — the site's only page on building against LQ.AI; J17)* | new | S |
| **`recipes/`** — supported-shapes index + topology recipes in the house format | new + extensible | index S; each recipe S |

### `/trust/` — trust centre · ~13 pages · [EVAL, PRODUCT · J3, J4, J14, J16] · **URL-stability commitment**

| Page | Kind | Est. |
|---|---|---|
| Trust-centre index *(the single missing artifact — this page is the deliverable)* | new | S |
| What leaves my deployment *(J3; ends in a decision)* | new | M — **waits on #439** (open question 1) |
| Threat model | curation | S |
| Anonymization: what it does and does not do | curation | S |
| Audit & evidence *(incl. the one-query privileged-evidence pattern)* | curation | S |
| Supply chain: SBOM, provenance, signed releases | curation | S |
| Published gaps *(HONEST-STATE, surfaced proudly)* | curation | S |
| Governance & maintainership *(links the public decisions log as a first-class artifact)* | curation | S |
| Continuity: if we stop maintaining this *(named risks, named mitigations)* | new | S |
| Security disclosure policy *(+ the public-vs-private exploitability test, J24)* | curation + new | S |
| Pre-filled questionnaires *(links open items honestly)* | curation | S |
| Compliance framework mappings index *(scope statements per artifact — what it covers, what remains the operator's)* | curation | S |
| Verify these claims yourself | new | S |

### `/skills/` — skills & playbooks · ~10 pages + generated indexes · [AUTHOR, PRODUCT · J7, J18, J23]

| Page | Kind | Est. |
|---|---|---|
| Hub | new | S |
| What a skill is | curation | S |
| Author your first skill | new | S–M |
| Your prompt files are already skill-shaped *(J7's entry point)* | new | S |
| Test your skill before sharing *(coordinate with the skill-acceptance-tests mini-PRD)* | new | S–M |
| Personal / team-shared / upstream — and which upstream *(two-repo routing per ADR 0024)* | curation | S |
| The attestation bar *(what it is, what it covers, how it decays)* | curation | S |
| Playbooks | curation | S |
| **Skill catalogue** *(columns: skill · practice area · jurisdiction · contributor · attested-by · tier; covers first-party and community repos or scopes explicitly)* | generated | M |
| **`coverage/`** — jurisdiction × practice-area index *(per-page: attested skills, sources/MCP connectors, scope notes from canon, gaps, contribution route)* | generated | M |

### Not in the tree: `/build/`

ADR 0031 (headless / API-only use: acknowledged, not supported) keeps building against
LQ.AI out of scope. Its one page is the headless-boot page in `/operate/`. No API
reference, frontend or fork guide, gateway drop-in page, streaming guide, or cookbook is
planned. Revisit when ADR 0031's triggers fire.

### `/deliver/` — deliver to a client · ~8 pages · [PRODUCT · J8, J12, J13]

Until the parent PRD's open question 4 is settled, only the branding page ships.

| Page | Kind | Est. |
|---|---|---|
| Hub | new | S |
| **Branding & licensing obligations** *(ships independently — parent spawned item 1)* | new | M |
| Theming mechanics *(extract the CSS-variable spec from the archived design doc first)* | curation | S |
| Deliver a branded deployment, end-to-end *(stitched guide across operate/skills/trust)* | new | M |
| Multi-deployment operations | new | M |
| Production-readiness matrix *(supported / operator-provided / not-yet, per row)* | new | S–M |
| What you may and may not claim | curation | S |
| Fork-based multi-tenant SaaS: unsupported-but-legal | new | S |
| Hand-off pack for the client's security team *(indexes into `/trust/`)* | curation | S |

### `/contribute/` · ~9 pages · [CONTRIB · J5, J23, J24]

| Page | Kind | Est. |
|---|---|---|
| Index: the two tracks *(engineering vs legal substance)* | curation | S |
| The live board *(build-time read of the existing board file — never forked)* | generated | S–M |
| On-ramps: lawyer / compliance professional / engineer | new | 3 × S |
| Coding-agent onboarding | curation | S |
| Dev environment guide *(api + gateway + web — the one genuine content gap)* | new | M |
| Contributing is a credential *(the membership route, stated)* | new | S |
| Code of conduct | curation | S |

### `/reference/` — generated · [OPS, AUTHOR]

| Artifact | Source | Est. (one-time) |
|---|---|---|
| Configuration reference *(env + gateway.yaml + mcp.yaml)* | Pydantic config models | M |
| Error vocabulary | specs + code | S |
| Skill frontmatter schema | loader schema | S |
| Playbook position schema | playbook docs/schema | S |
| ADR index *(renders real statuses — which will surface the stale ones)* | `docs/adr/` | S |
| Release versioning statement | ADR 0025 | S |

### `/changelog/` · [OPS, EVAL · J6, J11, J14]

One page per release, generated from GitHub Releases at build time: upgrade class (patch =
upgrade blind / minor = read first, per ADR 0025), operator-action list, migration status,
image tags, link to full notes. Requires a small structured block per release rather than
prose parsing. Coverage depends on the release-notes backfill (parent spawned item 4);
until it lands, the page states the gap.

### Machine surface · [J5, J20]

`/llms.txt`, `.md` served per page URL, and a downloadable full-text bundle (which is J20's
offline artifact for free). Build steps, specified before the first page is written.

---

## 2. Claimable work items

Twenty-two items. Each is claimable by one contributor, sized independently, and carries
its acceptance test (the journey failed-whens from Annex B plus the Annex A gates).
**Profiles are roles, not people.** Items marked ⛔ wait on an open question, not on
effort.

| # | Item | Size | Profile | Acceptance / notes |
|---|---|---|---|---|
| C1 | Site scaffold: Astro/Starlight, theme, CI build to Pages | M–L | frontend engineer | builds green; a11y + link gates wired |
| C2 | Content transform: frontmatter injection, link rewriting, commit stamps, archaeology exclusion rules | M | engineer | every page stamped; zero orphans; no hard-coded `/lq-ai/` base anywhere in output |
| C3 | Machine surface: llms.txt, .md routes, offline bundle | S–M | engineer | J5, J20 tests |
| C4 | Entry hub + `/start/` set | M | technical writer | J1, J2 tests; J1 needs a second reader |
| C5 | Install spine curation (macOS, Compose, TLS, air-gap) | M | DevOps | J2 test |
| C6 | Helm deployment page | S–M | DevOps | chart deployable from the page alone |
| C7 | Hardware sizing + reference configurations | S–M | DevOps | J19 test |
| C8 | Backup & restore | M | DevOps | J6 test (restore actually performed) |
| C9 | Upgrade guide + symptom index + key-rotation runbook | M | DevOps | J9, J11 tests |
| C10 | Recipes catalogue: index, house format, first two recipes | M | DevOps | J22 test; each further recipe is its own S item |
| C11 | Egress inventory page from air-gap CI output | S–M | engineer | J20 test |
| C12 | Trust-centre index + curation set | M | compliance / security professional | J4 test |
| C13 | ⛔ Data-flow page ("what leaves my deployment") | M | compliance + engineer | J3 test; waits on #439 |
| C14 | Continuity + verify-yourself + disclosure-test pages | S–M | compliance professional | R-G shape; J24 test |
| C15 | Skills authoring set | M | practising lawyer | J7 test |
| C16 | Skill-testing page | S–M | lawyer + engineer | coordinates with skill-acceptance-tests mini-PRD |
| C17 | Skill catalogue generator + frontmatter/position schema references | M | engineer | catalogue axes render; schemas tabulated |
| C18 | Coverage index generator (jurisdiction × practice area) | M | engineer, lawyer review | J23 test; scope notes from canon on every page |
| C19 | Contribute set + live-board wiring + dev-env guide | M–L | technical writer + engineer | agent orients from one fetch (J5) |
| C20 | Headless boot page (unsupported; ADR 0031) | S | engineer | J17 test |
| C21 | Deliver set (theming, stitched guide, multi-deploy, readiness matrix, claims, SaaS page, hand-off) | L (splittable ×2) | DevOps + licence-comfortable lawyer | J8, J12, J13 tests; licensing page ships first and independently; the rest waits on open question 4 |
| C22 | Reference + changelog generators | M | engineer | config, schemas, ADR index; changelog states the backfill gap honestly |

**Sequencing constraints, not assignments:** C1–C3 precede everything (the infrastructure
is a prerequisite, and the machine surface is cheap only if specified first). C13 waits on
#439. The branding page inside C21 does not wait for anything — it ships as its own item
per the parent PRD.

---

## 3. Totals

| Phase | Sections | Narrative pages (curation / new) | Rough single-contributor equivalent |
|---|---|---|---|
| **P0 launch** | `/` + `/start/` + install spine + `/trust/` (less the data-flow page) + machine surface + J11/J20/J22 minimums | ~26 (≈15 / ≈11) | ~5–6 weeks |
| **P1 launch-with** | rest of `/operate/` (incl. the headless page), `/skills/`, `/contribute/`, and the data-flow page when #439 closes | ~25 (≈11 / ≈14) | ~3.5 weeks |
| **P2 fast-follow** | `/deliver/` (the branding page ships independently) | ~9 (≈3 / ≈6) | ~2 weeks |
| **Infrastructure** | scaffold, transform, machine surface, generators | — | ~2 weeks |
| **Total** | | **~60 + generated** | **~13 weeks-equivalent** |

Three honest framings:

1. **"Launch" is ~26 pages, more than half curation.** The single-contributor-weeks number
   is the wrong way to read this — the point of the item structure is that the same work
   is 22 claimable items across five profiles.
2. **The expensive half is the unwritten half, and it is the fast-follow half.** P0 is
   mostly curation; P2 is mostly new writing. The cost curve supports the priority order.
3. **Two items wait on something other than effort** — the data-flow page (#439) and
   changelog coverage (the release-notes backfill). The PRD names them so no contributor
   discovers a wall mid-item.
