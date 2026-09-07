# Matter Access Control

Who can reach a matter, who decides, and what the deployment guarantees.

A **matter** is a `projects` row — there is no separate `Matter` model
([ADR 0020](../adr/0020-governed-agentic-legal-matter-sessions.md) D3), so matter membership is
project membership. Everything below is enforced in one module,
[`api/app/authz/matters.py`](../../api/app/authz/matters.py); nothing else decides matter access.

> **Scope of the guarantee.** This is application-layer authorization, not a cryptographic
> boundary. Anyone with direct read access to the Postgres database — an operator, a DBA, a
> restored backup — reads everything regardless of what this document says. A compliance
> narrative that claims otherwise is overclaiming. What this layer gives you is a truthful,
> auditable answer to "who could reach this matter through the product, and when did that
> change."

---

## The model

Two things decide access: a per-matter **roster** (`project_members`) and a per-matter **ambient
grant** (`projects.share_scope`).

### Roles on the roster

| Role | Can |
|---|---|
| `lead` | Everything below, plus manage the roster, the share scope, the privileged flag, the inference-tier floor, and archiving. |
| `contributor` | Read the matter and add to it: edit standing context, attach files/skills/knowledge bases, start chats in it. |
| `reader` | Read the matter and everything in it. Change nothing. |
| `blocked` | **Nothing.** A negative grant — an ethical screen. |

`blocked` is a role value rather than a separate table on purpose: the composite primary key
`(project_id, user_id)` then guarantees that "is this person screened?" has exactly one answer — a
grant and a screen can never coexist — and one indexed query answers both halves of a conflicts
check.

### Share scope

| `share_scope` | Reach |
|---|---|
| `personal` | The owner and the explicit roster only. **The default.** |
| `members` | Identical reach to `personal`; marks a matter as *deliberately restricted* rather than never shared, so the UI can tell the two apart. |
| `org` | Every non-blocked user in the deployment gets **read**. Writing still requires an explicit roster row. |

`org` grants read and never write. Contributing to a matter always requires a roster row, so the
roster stays a truthful answer to *who worked this matter* — which is the question that matters for
privilege and for conflicts, months later, when nobody remembers.

---

## Resolution order

Evaluated top to bottom; the first rule that matches wins.

1. **A `blocked` roster row → no access.** Absolute.
2. **The caller owns the matter → `lead`.**
3. **An explicit roster row → its role.**
4. **`share_scope = 'org'` → `read`.**
5. **Otherwise → no access.**

Three properties of that order are load-bearing and should not be "optimised" later:

**A screen beats `is_admin`.** An ethical wall an operator-admin can walk through is not a wall,
and in a small firm the operator-admin is frequently also a practising lawyer. An admin who must
see a screened matter lifts the screen — an attributed, audited, permanent-in-the-log act — rather
than bypassing it silently. A test pins this
(`api/tests/test_matter_authz.py::test_screen_beats_is_admin`).

**There is no operator-admin bypass and no `auditor` branch at all.** Before the roster existed,
`is_admin` did *not* let anyone read another user's matter — the loaders were plain owner checks.
Adding such a branch here would be a widening of cross-user access introduced under cover of a
collaboration feature, and an unaudited one. The deployment-wide `auditor` role
(migration 0065) is unaffected and still reaches the citation-ledger and receipt surfaces exactly
as before. Three tests pin the absence of this capability, because absent capabilities are what
well-meaning patches reintroduce.

**Ownership short-circuits the roster.** A matter whose lead row was deleted by hand never becomes
unreachable by its own owner.

### Status codes

- **404** — no access at all, *and* for a matter that does not exist. The two are deliberately
  indistinguishable so an id probe learns nothing. A fired screen is a 404.
- **403** — the caller *can* read the matter but asked for more than their role allows. At that
  point 403 leaks nothing they could not already see, and a 404 would actively mislead the UI.

---

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `LQ_AI_MATTER_DEFAULT_SHARE_SCOPE` | `personal` | The `share_scope` applied to a new matter when the caller does not specify one. |

The default is `personal` — fail-restrictive, per
[ADR 0016](../adr/0016-transparency-and-governance-invariants.md) P4. A new matter reaches only its
owner until someone is added.

Set it to `org` when ambient visibility is the working assumption and an ethical screen is the
exception — the posture most small firms already run under in their practice-management system. It
never widens write access, and a `blocked` row still overrides it.

Sandbox matters (`is_sandbox`) are per-user scratch space and are pinned to `personal` by a database
CHECK constraint; they cannot be shared whatever this setting says.

> **This setting only affects matters created after it is set.** Changing it never retroactively
> widens an existing matter. Migration 0067's backfill deliberately leaves every pre-existing matter
> at `personal`.

---

## What an operator should know

**Provisioning.** `POST /api/v1/admin/users` creates a user with a generated one-time password and
`must_change_password=true`, so the new user is forced through `/auth/change-password` on first
login. The plaintext is returned once in the response body and is never persisted, logged, or
written to the audit row. `POST /api/v1/admin/users/{id}/reset-password` re-issues one and revokes
the target's live refresh sessions.

**The people-picker.** `GET /api/v1/users/directory` returns id, email, and display name for every
non-deleted user, to any signed-in caller. This exists because the roster endpoints take a
`user_id`, and a matter lead who is *not* an operator-admin cannot reach `GET /admin/users` to find
one. A deployment is a single organisation ([PRD §2.3](../PRD.md#23-data-isolation-model)), so who
else works here is not a secret; *what they can do* still is, and role, admin flag, MFA state and
password state all stay behind the admin surface.

**Access tokens are stateless.** Revoking a roster row takes effect on the next request, because
authorization is resolved per request and never cached across requests — a screen erected at 14:03
bites at 14:03. But an *access token* remains valid until it expires
(`JWT_ACCESS_TOKEN_TTL_SECONDS`, default 900s). Deployments that raise that TTL widen the window in
which a just-removed user's in-flight token still authenticates them; the roster check still runs,
so they lose matter access immediately either way.

**Deleting a user.** The GDPR hard-delete job refuses to delete a matter that has roster members
other than the owner, and names the blocked matter ids in the worker log. Erasure covers the user's
own data, not a shared matter file that colleagues are working in. Resolve it by transferring
ownership first — see *Known limitations*.

---

## Auditing

Every roster change writes an `audit_log` row in the same transaction as the change itself
(ADR 0016 P5 — no state change without its audit row):

| Action | Recorded |
|---|---|
| `matter.member_added` | target user id + email, role granted |
| `matter.member_role_updated` | before/after role — this is how a screen's erection is recorded |
| `matter.member_removed` | role held at removal, and `lifted_screen: true` when the removed row was a screen |

Removing a `blocked` row is the one deletion here that *widens* access, which is why it is flagged
rather than logged as an ordinary removal.

### Known gap

`audit_log` has no `project_id` column, so these rows are queryable by `resource_id` but there is
no stable foreign key to the matter, and the historical `privilege_basis` string carries the
matter's *name* — which is mutable. **A per-matter access log is therefore not yet producible**, and
read events are not logged at all. If your compliance posture depends on answering "who accessed
this matter", treat that as an open item rather than a solved one.

---

## Known limitations

- **No matter ownership transfer.** A matter can be shared with another identity but not moved to
  one. The owner is permanently `lead` and cannot be demoted or removed from the roster.
- **No per-file or per-chat permissions inside a matter.** Access is uniform across the matter's
  contents. This is deliberate — privilege attaches at the matter, and per-resource drift inside a
  matter is unauditable — but it means you cannot share a matter while withholding one document in
  it.
- **File and knowledge-base *ownership* is still per-user.** A colleague reaching a shared matter
  reads its attached knowledge bases through the matter, but the standalone file and KB surfaces
  remain owner-scoped.
- **Chats in a shared matter are readable by every member but writable only by their author** —
  including by a lead. Two lawyers interleaving turns in one thread would make
  `work_product_attribution` ambiguous about who directed which output, which is precisely the
  record that has to stay unambiguous. A colleague acting on a shared matter starts their own
  thread in it.
- **No team-scope grants yet.** `teams` exists and is wired only to skill sharing; a
  `project_teams` join slots into step 3 of the resolution order when wanted.
- **No cross-deployment / external-counsel boundary.** See
  [DE-023](../PRD.md#de-023--external-counsel-collaboration-boundary). External counsel is a user in
  this deployment with a scoped roster row.
- **Screens are visible to everyone who can read the matter.** The roster shows screened people to
  any member. In a small firm that transparency is usually correct; in a larger one, knowing *that*
  a colleague is screened off a matter may itself be sensitive.

---

## Cross-references

- [`docs/db-schema.md` § `project_members`](../db-schema.md) — table definition, constraints, backfill.
- [ADR 0024 — Matter-scoped access control](../adr/0024-matter-scoped-access-control.md) — why this shape.
- [ADR 0020](../adr/0020-governed-agentic-legal-matter-sessions.md) D3 — matter = project.
- [ADR 0016](../adr/0016-transparency-and-governance-invariants.md) P4, P5, P6 — fail-restrictive, atomic audit, one governance path.
- [`docs/security/audit-logging.md`](audit-logging.md) — what the audit log holds and how to query it.
