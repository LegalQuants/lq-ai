# ADR 0024 — Matter-scoped access control (`project_members` + `share_scope`)

**Status:** Accepted — implemented in migration 0067 and `api/app/authz/matters.py`.
**Date:** 2026-08-21
**Written after the implementation**, not before, which is a departure from this repo's usual
order. Recorded that way deliberately rather than back-dated: the shape was settled by building it
against a running deployment, and this document is the honest account of the decisions that
survived that.
**Relates to:** [ADR 0020](0020-governed-agentic-legal-matter-sessions.md) D3 (matter = project),
[ADR 0016](0016-transparency-and-governance-invariants.md) P4/P5/P6,
[ADR 0012](0012-db-backed-user-skills.md) (the `teams` model this mirrors),
[PRD §2.3](../PRD.md#23-data-isolation-model), [PRD §3.11](../PRD.md#311-projects-m1),
[PRD §5.2](../PRD.md#52-rbac).

## Context

PRD §3.11 lists `share_scope` in the Project data model and names
`POST /api/v1/projects/{id}/share`; §3.11's M1 status records share-with-group as **deferred**.
Nothing shipped. The consequence surfaced when the deployment-wide `auditor` role landed
(lq-ai #266), whose own design note states it plainly:

> We chose a global role, not a per-org/per-matter scope. Grounding found LQ.AI has **no org /
> membership / project-sharing primitive** today … A scoped auditor would have needed a new
> membership table — out of scope.

Every resource was single-`owner_id`, and the rule "the caller owns it" was a predicate
copy-pasted into nine `_load_visible_*` helpers across `api/app/api/`. There was no table capable
of expressing "attorney B may see matter X", and no way to create a second user at all.

The driving requirement: several lawyers working one matter, each identifiable. Identity is not
cosmetic here — work-product protection for AI prompts and outputs turns on *who directed the AI*,
so an unattributed action is a weaker artefact than an attributed one.

## Decision drivers

1. **Privilege attaches at the matter.** Conflicts screening and reasonable-efforts obligations are
   asked at matter granularity, so that is where the authorization boundary belongs.
2. **One governance path** (ADR 0016 P6). Nine copies of an access rule is nine places to forget
   one, and the forgotten one is a leak no test names.
3. **Fail restrictive** (ADR 0016 P4). A guard that fails open is a bug even when every happy-path
   test passes.
4. **The roster must be a stored fact, not a derived aggregate.** "Who could see this matter, and
   when did that change" has to be answerable from one indexed table, not reconstructed from N
   per-resource ACLs that drift independently.
5. **Don't quietly widen anything.** A collaboration feature is an easy place to smuggle in a new
   cross-user read capability.

## Decisions

### D1 — The matter is the unit of access; `project_members` is the roster

A membership table over `projects`, mirroring `team_members` (migration 0014) deliberately: same
composite PK, same CASCADE/RESTRICT split, same `added_by_user_id` forensic column. A reviewer who
knows the team surface knows this one, and a future `project_teams` join slots in without a second
vocabulary.

Rejected: a generalized per-resource ACL — it makes "who is on this matter" a drifting aggregate.
Rejected: using `teams` as the scope — a team is a set of *people* and is deployment-global;
screening someone off one matter by editing team membership would change their access to every
other matter that team touches, which is exactly the imputation the screen exists to prevent.

### D2 — Denial is a role value, and it is absolute

`role='blocked'` is an ethical screen. The composite PK then guarantees a grant and a screen can
never coexist, so "is this person screened?" has exactly one answer, and one indexed query answers
both halves of a conflicts check.

**It beats `is_admin`.** A wall an operator-admin can walk through is not a wall, and in a small
firm the operator-admin is frequently also a practising lawyer. The remedy for an admin who must
see the matter is to lift the screen — attributed, audited, permanent in the log — not to bypass
it. Deliberately no break-glass: break-glass is how walls get breached in practice.

### D3 — Ambient scope grants read, never write

`share_scope ∈ (personal, members, org)`. `org` gives every non-blocked user read. Contributing
always requires an explicit roster row, so the roster remains a truthful answer to *who worked this
matter*. The deployment default is `personal`; `org` is an operator choice.

### D4 — No operator-admin bypass and no `auditor` branch on matters

Before this table existed, `is_admin` did not let anyone read another user's matter. Adding such a
branch here would be a widening of cross-user access introduced under cover of a collaboration
feature — and unaudited, since matter reads are not logged. The `auditor` role keeps its existing
reach over the citation-ledger and receipt surfaces, which resolve access their own way.

Three tests pin the *absence* of this capability. Absent capabilities are what a well-meaning
patch reintroduces.

### D5 — Reads widen; writes do not

A chat pinned to a matter is readable by anyone who can read the matter — that is the point of
sharing one. Chat *writes* stay owner-only, including for a lead: two lawyers interleaving turns in
one thread would make `work_product_attribution` ambiguous about who directed which output, which
is precisely the record that has to stay unambiguous. A colleague acting on a shared matter starts
their own thread in it.

The unfiltered chat sidebar also stays personal, so a firm-wide-readable matter never floods a
colleague's chat list; ask for a matter you can read and you get every author's threads in it.

### D6 — 404 for no access, 403 only for insufficient access

No access and "no such matter" are indistinguishable, preserving the existence-safe posture the
matter surface already documented. 403 is reserved for a caller who demonstrably already knows the
matter exists because they can read it, and is asking for more than their role allows — at which
point 403 leaks nothing new and a 404 would mislead the UI.

### D7 — Backfill preserves the pre-migration answer exactly

Migration 0067 writes one `lead` row per existing project for its owner and leaves every existing
matter at `share_scope='personal'`. The resolver therefore returns exactly the pre-migration answer
for every pre-existing row; a deployment that upgrades and changes nothing sees no behaviour change.

## Consequences

- One module (`api/app/authz/matters.py`) is now the only place matter access is decided; the nine
  `_load_visible_*` helpers delegate to it and keep their call-site shape.
- `matter_access_map` exists so a listing costs one membership query rather than one per row; the
  ordering itself lives in a single `resolve_access` function that both the single-row and batch
  paths call, so they cannot drift.
- The GDPR hard-delete job can no longer erase a matter with other members on it — a correctness
  fix this ADR forced into view.
- Slug uniqueness now resolves against the matter's *owner*, not the caller: slugs are unique per
  owner, and a contributor renaming a shared matter must be checked against the owner's namespace.

## Follow-ups (deliberately not in this ADR)

- `audit_log.project_id`, so a per-matter access log becomes producible; read-event auditing is a
  separate and larger question (write amplification on a busy privileged matter).
- Optimistic concurrency on `projects.context_md` — three people editing standing context currently
  clobber each other silently.
- Matter ownership transfer, without which a matter can be shared with an identity but not moved to
  one.
- `project_teams` grants; making file and KB visibility follow the matter.
- Client-level screening (`projects.client_ref`), so a lateral hire can be screened from a *client*
  rather than matter by matter.

## Cross-references

- [`docs/security/matter-access-control.md`](../security/matter-access-control.md) — the operator-facing document, including the limits of the guarantee.
- [`docs/db-schema.md`](../db-schema.md) — `project_members`, `projects.share_scope`, the backfill.
