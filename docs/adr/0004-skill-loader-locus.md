# ADR 0004 — Skill loader lives in the backend (`api/`), not the gateway

**Status:** Accepted (2026-05-08); extended by [ADR 0012 — DB-backed user skills](0012-db-backed-user-skills.md) (2026-05-10) for the user/team-scope shadow layer
**Decision-makers:** Kevin Keller (initial maintainer)
**Affected components:** `api/`, `gateway/` (downstream — C2 reads skill content from `api/`)
**Related:** [`docs/M1-IMPLEMENTATION-ORDER.md` Task C1](../M1-IMPLEMENTATION-ORDER.md), [PRD §3 capability specs](../PRD.md#3-capability-specifications), [PRD §7.1 skills as canonical artifact](../PRD.md#71-skills-as-the-canonical-artifact-of-value), [skill-authoring guide](../skill-authoring-guide.md), [ADR 0012 — DB-backed user skills](0012-db-backed-user-skills.md) (the user-scope extension)

---

## Context

Task C1 says: *"On gateway startup, load all skills from `skills/` filesystem directory. Parse frontmatter, validate schema, register in memory. Reload on SIGHUP. Expose `GET /api/v1/skills` and `GET /api/v1/skills/{name}`."*

The wording mixes two surfaces:

1. **Gateway-side use.** Skills shape inference — `SKILL.md` body becomes part of the system prompt during prompt assembly (Task C2). That happens on the gateway side of the boundary because the gateway is what actually dispatches the inference call. Reading skills from disk near where they're consumed minimizes round-trips.
2. **Backend-side surface.** `GET /api/v1/skills` and `GET /api/v1/skills/{name}` are paths under `/api/v1`, which is the backend FastAPI service ([backend-openapi.yaml](../api/backend-openapi.yaml)). Per [ADR 0002 — Backend-owned auth](0002-backend-owned-auth.md), the backend is the single user-facing API surface; everything authenticated and queryable by users goes through it. The user-facing skill listing is therefore a backend concern, not a gateway concern.

The implementation question is whether the **filesystem walk + parse + registry** also lives in the backend, in the gateway, or in both. Three options:

- **Option A — Loader lives in `api/` only.** The backend owns the registry. The OpenAPI sketch maps directly to a real handler that reads from the in-memory registry. C2 (prompt assembly, gateway-side) requests skill content from `api/` over HTTP — same boundary every other gateway↔backend interaction crosses today (see ADR 0003 for the wider statement of the project's anti-shared-code stance).
- **Option B — Loader lives in `gateway/` only.** The gateway owns the registry. The backend's `/api/v1/skills` endpoints proxy to a gateway admin endpoint (e.g., `GET /admin/v1/skills` per the existing admin surface in [gateway-openapi.yaml](../api/gateway-openapi.yaml) §A3). Two HTTP hops to get skill metadata; the cross-subsystem cache is the gateway's registry.
- **Option C — Loader lives in both.** Each subsystem walks `skills/` independently. Simpler to reason about per subsystem; doubles the cost of any change to the schema (two parsers to keep in sync); contradicts the project's "one canonical source per concern" posture.

The constraints that rule Options B and C in or out:

- **Subsystem isolation.** Per [`CLAUDE.md`](../../CLAUDE.md), the two services are self-contained and talk over HTTP. Either one can own the loader; the question is which gives the cleanest boundary.
- **OpenAPI conformance.** The path `/api/v1/skills` is registered on the backend in `docs/api/backend-openapi.yaml`. It cannot move to the gateway without rewriting the sketch and breaking the existing 501 stubs the web client and Word add-in (M3) are coded against.
- **Storage isolation (later milestones).** Beyond M1, skill content moves to a database table (per PRD §7.1 — user-scope and team-scope forks). The backend already owns the database; the gateway does not write user content. That progression argues for the backend owning the registry from the start.
- **Mode 2 (air-gap).** In an air-gapped deployment the backend and gateway are typically in the same network namespace, so the gateway-→-backend hop for skill content during C2 is cheap. In Mode 1 (gateway routes to a hosted provider), the gateway is also typically co-located with the backend; the hop is ~1ms intra-cluster.
- **First-run footprint.** B5's `GatewayClient` already exists in `api/`. The reverse — a backend-aware HTTP client in the gateway — does not. Adding one to satisfy "the gateway owns skills" introduces a new dependency direction (gateway calls backend) the system doesn't have yet, and we don't want to invent that direction for a single use case.

## Decision

**Adopt Option A. The filesystem loader and registry live in the backend (`api/app/skills/`).** The C2 prompt-assembly path (gateway-side) will request skill content from the backend over HTTP at the boundary the system already uses for everything else.

Concretely:

- **`api/app/skills/`** — new package containing:
  - `loader.py` — walks the configured skills directory, parses each `SKILL.md`'s frontmatter, validates against the Pydantic schema, returns a `SkillRegistry` instance.
  - `registry.py` — in-memory `SkillRegistry` with atomic-swap reload semantics.
  - `schema.py` — Pydantic models for the frontmatter (the `lq_ai:` namespace) plus the wire shapes returned to the user (matching `SkillSummary` and `Skill` in `docs/api/backend-openapi.yaml`).
- **`api/app/api/skills.py`** — replaces the 501 stub with real handlers backed by `SkillRegistry`.
- **`api/app/main.py`** — lifespan handler builds the registry on startup and installs a SIGHUP handler that triggers a re-walk and atomic swap. *(Amended 2026-06-07: the registry install is now a shared bootstrap, `api/app/skills/bootstrap.py`, called by both the api lifespan and the arq worker's `on_startup` — a dual-process install; the SIGHUP reload remains api-only.)*
- **C2 (prompt assembly, gateway-side)** — when implemented, the gateway calls `GET /api/v1/skills/{name}` on the backend (using the gateway's existing `httpx` machinery and the same `X-LQ-AI-Gateway-Key` shared secret in the reverse direction). C2 is out of scope for C1; C1 only delivers the loader + registry + user-facing endpoints.
- **`SKILLS_DIR` configuration.** New backend setting (default: `<repo-root>/skills`, overridable to support test fixtures and operator-side overlays). The gateway has its own `gateway.yaml`; skill loading does not need to be threaded through the gateway's configuration.
- **`skills/` directory remains the canonical filesystem location.** The repo continues to ship the 10 starter skills in `skills/`. The backend's `SKILLS_DIR` defaults to that directory; tests use a fixture directory with synthetic skills (no legal substance — skill content is the human-attestation pipeline's domain, not an agent's).

## Consequences

### Positive

- **OpenAPI conformance.** `GET /api/v1/skills` and `/api/v1/skills/{name}` map directly to real handlers; no proxying.
- **One canonical source.** The backend owns user-facing skill metadata; future user/team-scope forks naturally extend the same registry against the backend's database.
- **Reuses an existing direction.** The gateway-→-backend hop in C2 uses the same `httpx` + shared-secret pattern the backend-→-gateway already uses; no new client class on the gateway side.
- **Test affordance.** The fixture-skills pattern (synthetic skills under `api/tests/fixtures/skills/`) is straightforward — the loader takes a path argument and tests pass a different one.

### Negative

- **One extra HTTP hop in C2.** When the gateway assembles a prompt with skills attached, it fetches each skill's content from the backend rather than reading from a local registry. Round-trip cost is ~1ms intra-cluster; not material against an inference-latency budget measured in seconds.
- **Reload coordination is backend-only.** SIGHUP reload runs on the backend process; the gateway's view of skills is whatever the backend last surfaced. If the gateway caches skill content in C2 (for performance), it must invalidate on a signal of its own — but the simplest gateway-side path is not to cache and to fetch fresh per inference call. C2 will document and decide.

### Neutral

- The progression to a DB-backed skill table at user/team scope (deferred enhancement) lands in the backend, where the database lives. No locus change; just adding a backing store behind the same registry interface.

## Notes on alternatives

- **Option B (gateway-only) reconsidered.** This is genuinely tempting because skills *are* about inference, and inference *is* the gateway's domain. But the user-facing API is also a real concern, and forcing user requests through a backend-→-gateway proxy when the data is structured documents the backend already knows how to serve is the more painful path. The hop in C2 (gateway-→-backend) is preferable to the hop in user-facing browsing (browser-→-backend-→-gateway), which would require auth-translating across the boundary on every skill list call.
- **Option C (both) reconsidered.** Two parsers to keep in sync, two registries to coordinate, two SIGHUP handlers — and skills are not large enough to need two caches.

## Decision is local to C1+C2

If the operational reality of C2's gateway-→-backend hop turns out to be hot enough that the gateway needs its own cache, the loader can be replicated to the gateway as a read-only mirror of the backend's registry without breaking this ADR — the contract (registry behind an HTTP API, filesystem as the canonical source) stays the same. We will surface that as a deferred enhancement when (and if) C2's profiling shows it matters.
