---
title: Audit & evidence
description: What LQ.AI logs, what it deliberately does not, retention, and the queries that turn the audit log into evidence for a client, an insurer, or a regulator.
audience: [evaluator, operator]
status: draft
sources:
  - docs/security/audit-logging.md
  - docs/db-schema.md
sidebar:
  order: 5
---

Every state-changing action in LQ.AI writes one row to the `audit_log` table, in the same database
transaction as the change itself — there is no audit-row-without-state-change and no
state-change-without-audit-row failure mode. This page is the operational reference for what that
buys you, and the two paragraphs after the include below turn it into the specific evidence pattern
a matter or an insurer's inquiry actually needs.

<!-- include: docs/security/audit-logging.md -->

## Matter-scoped evidence for a specific model call or citation

The pattern above answers "what happened to a given user or privileged resource." A narrower
question — "what did the assistant read and verify for this specific matter" — is answered by two
tables that were not part of the M1 audit log: `citation_ledger_entry`, indexed on `project_id`
(one row per turn per source the assistant actually read, referencing exactly one of a KB-document
citation, a case-law citation, or a tool-retrieved source, and holding no content of its own — a
metadata index only); and `inference_routing_log`, which records the provider, model, and routed
tier for every inference call and carries a `chat_id`.

```sql
-- Every source the assistant read and verified for one matter
SELECT chat_id, message_id, source_kind, verification_status, confidence, provider, retrieved_at
FROM citation_ledger_entry
WHERE project_id = '<matter-uuid>'
ORDER BY created_at;

-- Every model call made inside that matter's chats
SELECT r.timestamp, r.routed_provider, r.routed_model, r.routed_inference_tier, r.anonymization_applied
FROM inference_routing_log r
JOIN chats c ON c.id = r.chat_id
WHERE c.project_id = '<matter-uuid>'
ORDER BY r.timestamp;
```

Neither query returns the content of what was read or said — `citation_ledger_entry` is metadata
only, and `inference_routing_log` never carries message bodies — but together they produce a
matter-scoped record of every model call and every citation verification an insurer's inquiry, a
malpractice review, or an internal audit would ask for, without reconstructing it by hand.

:::caution[Silent failure]
Append-only is enforced by the application, not by the database: no api code path issues `UPDATE`
or `DELETE` against `audit_log`, but Postgres does not reject one, and chained-hash tamper
detection is not in M1. A row altered directly in the database leaves no signal. If your
evidentiary posture needs tamper-evidence, the source names two operator-side options: a trigger
that rejects updates and deletes, or logical replication to a write-once destination.
:::

:::note[Professional duty]
This is the structural answer to a question a closed-source SaaS product cannot give you: you can
evidence, to your client or your regulator, every occasion on which their material was sent to a
model provider, on which tier, and whether it was pseudonymized first — not as an assertion, but as
a query you run yourself against your own database.
:::

## Next

- [Anonymization](anonymization.md) — what `anonymization_applied` in the audit trail actually reflects.
- [What leaves my deployment](what-leaves-my-deployment.md) — the tier boundary these logs record.
- [Verify these claims yourself](verify-these-claims.md) — where the audit-log schema itself lives.
