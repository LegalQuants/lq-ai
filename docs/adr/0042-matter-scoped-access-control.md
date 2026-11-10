# ADR 0042 — Matter access and central policy administration

**Status:** Proposed — maintainer-authorised replacement implementation for PR #536;
code and security review remain required before merge.
**Date:** 2026-10-13
**Credit:** @sergiomaldo's PR #536 supplies the membership, sharing and resolver foundation;
Sergio is credited as co-author of the replacement contribution.

## Context

PRD §3.11 promises sharing matter context; ADR 0020 D3 maps matters to projects.
PR #536 provides project membership and explicit denial but ties policy management
to matter-lead content authority. The maintainer requested independent central
control while retaining deliberate content access and enforceable screens.

## Decisions

1. The matter roster contains `lead`, `contributor`, `reader`, or `blocked` for
   each person; explicit denial precedes every content grant.
2. Administrator or auditor status alone grants no matter content access.
3. Unscreened administrators can enumerate limited management metadata, manage
   membership and sharing, and transfer custody without receiving a content role.
   Administrative control-path writes require a non-blank reason and atomic audit.
4. A screened administrator cannot manage that matter or lift their own screen.
   Another unscreened administrator must make the explicit audited change.
5. Ownership transfer selects the former owner's resulting role and transfers
   the old owner's directly scoped chats, files and KBs atomically. Historical
   authorship is retained; the new custodian controls future chat contributions.
   Shared attachments, active autonomous work and slug collisions must be resolved first.
6. Sandbox matters reject roster mutations and custody transfer.
7. Account erasure preflights shared data and queues object removal in the same
   transaction as relational deletion. Physical erasure occurs after commit and
   is retried durably; rollback cannot delete retained object bytes.
8. Content-bearing ledger, receipt and source reads require matter access even
   for owners or auditors. Autonomous governance checkpoints recheck current access.

## Consequences and bounds

Policy administrators and content readers are separate powers, supported by the
existing administrator role in the first implementation. More granular delegated
security roles require a future explicit decision. No implicit emergency bypass
is introduced; independent administrator availability remains an operator duty.

Screens are application-layer controls. They do not recall downloaded copies,
previously issued object-store URLs or already dispatched external requests.
Export creation and URL issuance refuse while screens require scope reconciliation.
Saved skill work and autonomous history retain their separate ownership rather
than being silently reassigned on transfer. The operator guide records these limits.

## Alternatives considered

- Implicit administrator content access: would silently widen confidentiality exposure.
- Lead-only management: would leave the organisation dependent on an individual custodian.
- A full delegated policy-role system now: a larger change than the authorised first version.
- Status quo: retains owner-only matters and leaves sharing unimplemented.

## References

- [PRD §3.11](../PRD.md#311-projects-m1)
- [ADR 0020 D3](0020-governed-agentic-legal-matter-sessions.md#d3--plain-language-matter-intake-matter--project)
- [PR #536](https://github.com/LegalQuants/lq-ai/pull/536)
- [Matter access operator guide](../security/matter-access-control.md)
