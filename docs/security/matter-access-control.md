# Matter access control and administration

This implementation adapts [Sergio's PR #536](https://github.com/LegalQuants/lq-ai/pull/536).
The membership table, sharing scopes, resolver and initial tests originate with
@sergiomaldo, credited as co-author of the replacement contribution.

## Content permissions

A matter is a `projects` row. The resolver evaluates explicit `blocked` first,
then ownership, explicit membership, organisation-wide read, and finally denial.
`personal` and `members` both restrict reads to the owner and explicit members;
`members` labels deliberate restriction. `org` allows ambient read only.
Contributors may edit matter content; leads also govern membership and settings.
Viewer and auditor accounts remain read-only even when assigned a stronger matter role.
Sandbox matters remain private and reject roster mutations and ownership transfer.

Admins and auditors do not receive automatic access to matter contents. Existing
auditor access to non-matter ledger/receipt surfaces remains; matter-linked reads
must satisfy matter access before either ownership or auditor shortcuts.
The controls are API-layer permissions, not cryptographic isolation from database
operators. They do not determine whether a legal screen is sufficient in a jurisdiction.

## Central policy administration

An unscreened administrator can enumerate administrative summaries, inspect the
roster, change memberships or sharing policy, and transfer ownership without
joining the matter. Summaries include name, owner, sharing scope and archived state;
they exclude context, documents, messages and attachment identifiers.
The administrator can explicitly grant themselves content access with a reason;
that is an audited permission change, not an automatic read bypass.

Any `blocked` administrator is excluded from the administrative list and cannot
manage that matter or lift their own screen. Another unscreened administrator
may lift it through the ordinary audited management operation. Deployment-level
recovery still requires an independent authorised account; this change adds no
silent break-glass bypass. Auditors cannot administer permissions.
This is not protection against a malicious infrastructure operator or misuse of
global account-provisioning/reset authority; independent administrator identities
and procedures remain operator responsibilities.

Administrative writes require a non-blank reason. Audit rows record the actor,
target, before/after values and reason in the same transaction as the change.
Deleting a `blocked` membership lifts the screen and can restore ambient `org`
read access; it is explicitly flagged in the audit log and confirmed by the UI.

## Ownership transfer and account erasure

Transfer chooses an active new owner and the former owner's resulting role,
including `blocked`. The new owner must not be screened and must not have a
conflicting active matter slug. The transaction changes ownership and the roster,
then transfers the old owner's chats, files and KBs whose direct project is this
matter. It does not rewrite stored `messages.directed_by_user_id` or attribution records.
HTTP messages and their assistant outputs record the authenticated director;
account erasure anonymizes that reference under the existing retention policy.
The recipient becomes custodian of those chats and may make future contributions.
Files and KBs also attached elsewhere require reconciliation first. Running
autonomous sessions must be halted first; schedules and watches are disabled.
Other members' independently owned work stays theirs. Saved skill work and
autonomous history retain their existing ownership; they are not silently reassigned.

Deletion preflights shared matters and data linked into retained matters.
Relational deletion and object-erasure requests commit together. A durable
`storage_deletion_queue` is drained after commit; failures remain for retry by the
daily deletion worker. A database rollback never removes object bytes.
The roster's inviter field becomes null on account erasure; historical invitations
remain in the audit trail. Object deletion is eventual, not an atomic database/S3 transaction.

## Runtime enforcement and limits

Screens follow files and KBs through both direct scope and attachment junctions,
including retrieval through another KB. Screen checks precede owner shortcuts for linked chats, files, KBs, receipts,
citation/source reads and saved skill files. Chat listings exclude denied matters.
Autonomous calls recheck current matter contribution access at the governance
checkpoint; orchestration rechecks during admission/effects and owner reads.
Run-in-chat intake, selected-source reads, retained answers and receipts retain
their matter checks. Admin/auditor run reads check the actual caller before
using the owner identity to load the result; role status alone grants no matter access.
Already-dispatched external calls cannot be recalled, and downloaded copies cannot
be retroactively revoked.

Personal ZIP export creation and URL issuance fail closed while the user has any
screened matters; an administrator must reconcile scope before exporting. URLs
already issued by object storage retain their original expiry; this release does
not claim retroactive revocation of those external URLs. All users' normal exports
continue when no screen exists.

## Operator verification

Use `/lq-ai/admin/matters` as an administrator not assigned to a private matter:
inspect the roster, add a reader with a reason, and confirm the matter content
endpoint still denies the administrator. Impose a screen on that administrator;
confirm their management access is denied and another administrator can lift it.
Transfer ownership with the former owner screened; confirm the new owner can see
the retained work and the former owner cannot. Repeat on desktop and phone in
light and dark schemes. Account-erasure tests use a throwaway database and mocked
object storage; never run migrations against a live development database.
