# Sticky skills — backend contract & frontend integration

> **Audience:** anyone building or porting a frontend against the LQ.AI backend
> (the bundled OpenWebUI fork, the Donna shell, the Word add-in, or your own
> client). This documents the **opt-in "sticky skills"** feature: the API
> contract a client integrates against, the design invariants to preserve, and
> the reference implementation in `web/`.
>
> **Canonical implementation:** issue [#207](https://github.com/LegalQuants/lq-ai/issues/207)
> finding 4, landed as one squash commit on `main` — `git show 5ad9f9e` for the
> full diff (migration + backend + frontend + docs + tests).

## What it does

By default a skill is applied **per message**: the client sends the skill(s) on
each `POST /chats/{id}/messages` turn, and a turn with no `skills` runs none. The
sticky toggle lets a user mark a chat's skills **sticky** so they keep applying
to follow-up turns without the client re-sending them — useful for research /
review skills a user wants active for a whole conversation.

## Design invariants (preserve these — they are the transparency posture)

These are not stylistic; they keep the feature aligned with the governance
invariants in [ADR 0016](../adr/0016-transparency-and-governance-invariants.md):

1. **Off by default** (P4 fail-restrictive). A brand-new chat never inherits
   stickiness.
2. **Explicit user control** (P8). Stickiness changes *only* when the user
   flips the toggle — never as a silent side effect of a normal turn.
3. **Per-chat scope.** The state lives on the chat; a new chat starts off.
4. **Audit stays honest** (P3/P10). Every turn still records its own
   `applied_skills`; the sticky set simply feeds into each turn's effective
   skills. You can always see exactly which skills ran on which turn.

## Backend contract (what any client integrates against)

The state is one column — `chats.sticky_skills text[]` (empty = toggle off; the
array *is* the state). Two wire fields:

### Request — `POST /chats/{id}/messages` (`MessageCreate`)
| field | type | meaning |
|---|---|---|
| `set_sticky` | `boolean \| null` | `true` = snapshot **this turn's applied skills** as the chat's sticky set; `false` = clear the set; `null`/omitted = leave it unchanged |

Server behavior per turn (after the turn's skill list is assembled):

- `set_sticky == false` → clear the set; this turn applies only the explicitly
  sent skills.
- otherwise → **union** the persisted sticky set into this turn's effective
  skills (forwarded to the gateway *and* recorded on the user message);
  - if `set_sticky == true` → snapshot the full resulting set as the new sticky set.

Consequence to rely on: an explicit per-turn skill **unions for that turn only**
and does **not** mutate the sticky set. The toggle is the only thing that
changes the set.

### Response — `Chat` (`GET /chats/{id}`, list, etc.)
| field | type | meaning |
|---|---|---|
| `sticky_skills` | `string[]` | the chat's active sticky set; empty = toggle off. Read this on load to render the toggle state. |

## Reference frontend implementation (`web/`)

The composer in `web/src/lib/lq-ai/components/ChatPanel.svelte`:

- **Types** (`web/src/lib/lq-ai/types.ts`): `Chat.sticky_skills?: string[]`,
  `MessageCreate.set_sticky?: boolean | null`.
- **State:** `stickyEnabled` (mirrors `chat.sticky_skills.length > 0`),
  `stickyDirty` (set true when the user flips the toggle), and an
  **id-tracked reactive** that re-syncs `stickyEnabled` from the chat *only when
  the chat id changes* — so it never clobbers an in-progress toggle within a
  chat, and opening a new chat resets to off.
- **UI:** a `role="switch"` "Keep skills on" button in the composer toolbar.
- **Send rule (critical):** include `set_sticky` in the request **only when
  `stickyDirty`** is set (`stickyDirty ? stickyEnabled : undefined`), then clear
  `stickyDirty` on a successful send. Sending it on every turn would re-snapshot
  the set each turn and break the "union for that turn, set unchanged" invariant.

## Porting checklist (custom / sibling frontends)

1. Add the column to the chats table (LQ.AI migration `0056`); expose
   `sticky_skills` on your chat read model and `set_sticky` on your message-create
   model — **match your own schema/migration conventions** (revision numbers and
   file paths will differ from LQ.AI's).
2. In the send handler, implement the union + snapshot/clear logic above against
   the chat row you already load.
3. In your composer, add the toggle with the state model and the send rule above.
4. Keep the four invariants. In particular: default off, send `set_sticky` only
   on a real toggle change, and keep per-turn `applied_skills` recording intact.

## Verification (replicate against your stack)

LQ.AI's tests (`api/tests/test_chats_skills_forwarding.py`) cover: snapshot on
toggle-on, carry-into-follow-up, explicit-skill-unions-with-set-unchanged,
toggle-off-clears, and GET exposes the set. Run them against a throwaway Postgres
(the api conftest auto-migrates). Frontend: `svelte-check` clean.

## Related / not included

- The per-message skill plumbing this builds on: `lq_ai_skills` /
  `attached_skills` forwarding (see `MessageCreate` in
  [`docs/api/backend-openapi.yaml`](../api/backend-openapi.yaml)).
- Out of scope here: the chat tool-call cap default ([DE-357](../PRD.md#9-deferred-enhancements-and-identified-future-work) / [#212](https://github.com/LegalQuants/lq-ai/issues/212)).
