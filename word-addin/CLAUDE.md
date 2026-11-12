# word-addin — configuration notes for coding agents

> Supplements the root [`/CLAUDE.md`](../CLAUDE.md) — read that first. This file
> covers `word-addin/`-specific tooling that isn't part of the repo-wide
> conventions: the generated OpenAPI client, and the state-layer shape it
> plugs into.

---

## The generated OpenAPI client

`word-addin/` generates a typed TypeScript client from the backend's live
OpenAPI spec via [`@hey-api/openapi-ts`](https://heyapi.dev/) — see
`openapi-ts.config.ts`. This exists because hand-mirroring 139+ backend
endpoints into `domain/types.ts` and hand-writing an `apiRequest<T>()` call
per endpoint doesn't scale; the generator does both from a single source of
truth.

### Regenerating

```sh
npm run openapi-ts
```

Requires the dev stack's `api` container to be running (`docker compose up
api` or the full stack) — the generator reads the spec from **the live
server**, not a committed file:

```ts
// openapi-ts.config.ts
input: `${process.env.LQ_AI_OPENAPI_URL ?? "http://localhost:8000"}/openapi.json`,
```

`LQ_AI_OPENAPI_URL` overrides the default for a non-standard dev api port,
mirroring `vite.config.ts`'s `LQ_AI_DEV_API_ORIGIN` pattern.

**Why the live server and not `docs/api/backend-openapi.generated.yaml`**
(the repo's own committed, drift-guarded export): that file is regenerated
on the `api` service's own release cadence, so it can lag behind
in-progress backend work during active development. The live endpoint is
always current. Trade-off: regenerating word-addin's client requires a
running `api` container, which the committed file wouldn't.

### Output — `src/generated/`

Gitignored (`.gitignore`) and excluded from lint (`.eslintrc.cjs`
`ignorePatterns`) — it's a build artifact, not reviewed or hand-edited.
Treat it exactly like `node_modules/`: if it's missing, run
`npm run openapi-ts`, don't try to reconstruct it by hand.

Structure:

| File | Contents |
|---|---|
| `sdk.gen.ts` | One function per operation, named after its `operationId` (e.g. `loginApiV1AuthLoginPost`, `sendMessageApiV1ChatsChatIdMessagesPost`). |
| `types.gen.ts` | Per-operation `<Name>Data` (request), `<Name>Responses` (success bodies by status code), `<Name>Errors` (error bodies by status code), plus every named schema. |
| `client.gen.ts` | The shared `client` singleton every `sdk.gen.ts` function uses by default. |
| `client/`, `core/` | Runtime primitives (`createClient`, request/response typing, SSE support — see below). Not meant to be imported directly except where noted. |

### Required runtime wiring (do this before calling any generated function)

The generated `client` singleton is **not** ready to use out of the box —
two things it doesn't do automatically, unlike `services/apiClient.ts`'s
`authenticatedFetch`:

1. **Base URL.** `client.gen.ts` hardcodes `baseUrl` to whatever
   `LQ_AI_OPENAPI_URL` was at generation time (`http://localhost:8000` by
   default) — that's a dev convenience baked into the codegen input, not a
   runtime value. Anything that calls a generated function needs
   `client.setConfig({ baseUrl: deploymentOrigin() })` to have run first.
   `src/taskpane/auth.ts` does this once at module load (it's the first
   consumer) — new consumers can rely on that having already run, since
   `client` is a single module-level singleton shared across the whole
   app; don't call `setConfig` again elsewhere.
2. **Bearer auth.** No interceptor attaches the access token automatically.
   Every authenticated call needs `headers: { Authorization: `Bearer
   ${token}` }` passed explicitly per call — see `taskpane/auth.ts`'s
   `logout()` for the pattern. There is currently no 401-refresh-retry
   equivalent to `authenticatedFetch`'s for generated-client calls; that's
   unbuilt, not just unused.

### Call shape

```ts
const { data, error, response } = await someOperationFn({
  body: {...},           // or path / query, per the operation's Data type
  headers: {...},
});
```

Non-throwing by default (`throwOnError` defaults `false`) — check
`error`/`data` rather than wrapping in try/catch. This also covers network
failures: the generated client's fetch call is internally wrapped, so a
rejected `fetch()` (offline, DNS failure, etc.) lands in `error` the same
way a 4xx/5xx response would, not as a thrown exception. `response` (the
raw `Response`) is available alongside `data`/`error` for status-code
branching (see `AuthContext.tsx`'s `login()` for the 401/423 branch
pattern). Pass `throwOnError: true` per-call if you want a rejected
promise instead.

### Type fidelity varies by endpoint — verify before trusting `unknown`

The generated response type is only as good as the backend handler's
declared `response_model`. Endpoints that serialize/forward a payload
without one come back typed as `200: unknown` (confirmed for
`GET /skills` and `GET /models`, likely others) — for those, the
hand-authored `docs/api/backend-openapi.yaml` sketch is the more reliable
schema reference (per the root CLAUDE.md's decision-routing table, item
2), and this codebase's own hand-rolled `domain/types.ts`/`domain/models.ts`
mirrors remain the practical source of truth until the backend adds a
proper response model.

### Streaming (SSE) — not auto-wired, read before using

`core/serverSentEvents.gen.ts` exports a real, generic SSE reader,
`createSseClient<TData>()` (frame parsing, `Last-Event-ID`, retry/backoff,
abort support) — but **no generated function uses it**. The live
`/openapi.json` doesn't declare the `text/event-stream` content type for
`POST /chats/{chat_id}/messages` (FastAPI can't statically introspect a
handler that dynamically branches between a JSON and a streaming
response the way the hand-authored sketch documents it), so that
operation generated as a plain non-SSE `.post()` call with an untyped
response.

To use `createSseClient` for an actual stream:
- Import it directly — `@/generated/core/serverSentEvents.gen` — it's not
  re-exported from `sdk.gen.ts`/`index.ts`.
- Type its generic against this codebase's own hand-written frame union
  (`domain/chat.ts`'s `MessageStreamEvent` / `domain/documentChat.ts`'s
  `DocumentChatStreamEvent`), since the generated types don't have them
  for this endpoint.
- Build the request by hand (URL, method, JSON body, bearer header) — same
  manual-wiring caveats as above.
- **Explicitly set `sseMaxRetryAttempts: 0`** (or otherwise disable the
  default retry/backoff) for chat-completion-style streams. A retry opens
  a *new* generation request, not a resumed one — the default
  reconnect-on-failure behavior is correct for a long-lived event feed and
  actively wrong here (a transient network blip mid-stream would silently
  fire a second, duplicate generation).

### Migration status

Only `src/taskpane/auth.ts` (`runRefresh`, `logout`) and
`src/auth/AuthContext.tsx` (`login`) call the generated client so far.
Everything else — `services/skillClient.ts`, `services/documentChatClient.ts`,
and any future service — still uses the hand-rolled `services/apiClient.ts`
(`apiRequest`/`apiStreamRequest` against `authenticatedFetch`) and
hand-mirrored `domain/types.ts` types. Migrating one of those is a matter
of repeating the auth migration's pattern (base URL already configured
globally by `taskpane/auth.ts`; just add the bearer header per call) —
nothing else here should change to do it.

---

## Project structure & working conventions

These are the maintainer's standing preferences for how this app is
organized — read them before adding a new file, not just when touching the
generated client. The OpenAPI-client guidance above has to fit inside
these, not the other way around.

### Imports

- **Use the `@/` alias for anything outside the current file's own
  directory.** `@/store`, `@/domain/types`, `@/services/skillClient`, not
  `../../store` or `../types`. A relative import is only acceptable for a
  sibling in the same directory (e.g. `./ModelBar` from another file in
  `components/chat/`) — anything that walks up a directory (`../`) should
  be an `@/`-rooted import instead. This is enforced editor-side too: the
  repo-root `.vscode/settings.json` sets
  `typescript.preferences.importModuleSpecifier: "non-relative"` so
  auto-import suggestions default to `@/` already.

### State layer

- **All Jotai atoms live in `src/store.ts`.** Hard rule, no exceptions —
  not even for a service that switches to the generated client. Every
  other file imports atoms from `@/store`; nothing defines its own.

  The reason isn't just tidiness: with every atom declared in one module,
  typing `from "@/store"` anywhere in the app gives full IntelliSense/
  autocomplete over the complete set of available atoms — you can
  discover what state exists by autocompleting the import, instead of
  having to already know which of a dozen scattered files defines the
  atom you want. Splitting atoms across service files trades that away
  for a marginal locality benefit that isn't worth it here.

- **An atom is for persistent, cross-component data — not every network
  result.** Before adding one to `store.ts`, ask whether more than one
  component actually needs to read it reactively. If only the caller of
  a single function needs the result, return it and hold it in that
  component's own `useState`, not a global atom.

  Data that's fetched once and needed broadly — the skills catalog
  (`skillsAtom`), the model list (`modelsAtom`) — belongs in the store:
  it's loaded at startup and genuinely read from multiple places
  (`SkillsRow`, `ModelBar`, `selectedSkillsAtom`'s derivation, composer
  send logic). A single on-demand lookup — "fetch this one skill's
  detail," "search skills for this query" — does not: it's the result of
  one call, consumed by whichever component made it. `skillClient.ts`'s
  `getOne()`/`contents()`/`inputs()`/`autocomplete()` all return their
  result directly rather than writing it to an atom, for exactly this
  reason — a global "last-fetched skill detail" atom would silently
  race the moment two components looked up two different skills at
  around the same time, with no error, just a stale/wrong read for one
  of them. That's the concrete failure mode this rule prevents, not a
  hypothetical.

- **All cross-cutting UI actions live in `src/actions.ts`.** Things that
  aren't owned by one specific domain/service — `setComposerDraft`,
  `toggleSticky`, `showNotification` — live in the single `actions`
  object there, for the same IntelliSense-from-one-import reason as
  `store.ts`. This is distinct from **domain-specific** actions, which
  stay on their owning service client (`skillClient.toggleSelected()`,
  `documentChatClient.create()`) rather than moving to `actions.ts` — see
  "Services" below.

- **`@/domain`** — hand-rolled types and functions. Pure: no atoms, no
  fetch, nothing that touches the store or the network. Wire-type mirrors
  (`domain/types.ts`), pure mappers/parsers (`domain/chat.ts`'s
  `toChatMessage`/`consumeMessageStream`), grouping/selection logic
  (`domain/models.ts`). Testable in isolation for exactly that reason —
  see the `domain/__tests__/` files.

- **`@/services`** *(working on this — still settling)* — logically
  grouped services, each configured as a store-like object for the same
  autocomplete-on-import reason `store.ts`/`actions.ts` exist: type
  `skillClient.` or `documentChatClient.` and see everything that service
  can do, instead of having to know the standalone function names by
  memory. Each service exports an object with only the members that
  apply — `{get, create, update, delete}` — for calls that also touch
  local Jotai state, plus separate standalone functions for one-shot
  startup fetches self-invoked at module load (e.g. `skillClient.ts`'s
  `loadSkills()`). See `skillClient.ts`/`documentChatClient.ts` for the
  current pattern.

  **Preferred implementation going forward: use the generated
  `openapi-ts` functions** (`@/generated/sdk.gen`) inside each service
  rather than hand-writing `apiRequest`/`apiStreamRequest` calls — see
  "The generated OpenAPI client" above for the wiring caveats (base URL,
  bearer auth) that come with doing that. Only `taskpane/auth.ts` and
  `AuthContext.tsx` do this so far; the rest of `services/` still predates
  the generated client and hasn't been migrated yet (see "Migration
  status" above) — that's the direction to take a service in when you
  touch it next, not a reason to keep writing new hand-rolled calls.

- The generated client's output lives in neither tier — it's a third,
  generated layer (`src/generated/`) that `services/` files call into, the
  same way they'd call `services/apiClient.ts`'s hand-written `apiRequest`.

### Components

- **Mantine for everything.** No ad-hoc styled `<div>` trees where a
  Mantine primitive exists. Don't extract a component for something used
  exactly once unless it genuinely crosses multiple boundaries and bundles
  real integrated functionality (state + behavior, not just markup) — a
  one-off wrapper around a single Mantine component that only exists to
  avoid repeating a few props is not that.

  **Known current violation, not yet cleaned up**: this rule isn't fully
  followed in the existing tree yet. Don't treat existing code as the
  precedent to copy; treat this rule as the target to write new code
  against, and fix instances as you touch them rather than as a dedicated
  sweep.

- **File placement — three tiers**:
  ```
  components/            raw, shared components — usable from any feature
  components/{feature}/  components bespoke to one feature (e.g. components/chat/)
  taskpane/{page}.tsx     higher-order pages/feature abstractions built from the above
  ```
  `components/` is for genuinely reusable primitives/pieces. A component
  that only makes sense within one feature belongs in
  `components/{feature}/` (e.g. `components/chat/ModelBar.tsx`,
  `components/chat/Composer.tsx`), not at the top level. `taskpane/`
  is for the higher-order pages that compose feature components together
  — there's effectively one page today, so this tier isn't heavily
  exercised yet, but the placement rule still applies as the app grows
  past a single view.

  **Known current inconsistency**: `components/App.tsx` (the whole app
  shell) and `components/ChatPanel.tsx`/`components/ModelSelectInput.tsx`
  (chat-feature-specific) currently sit at the top level of `components/`
  rather than in `taskpane/` or `components/chat/` respectively. Not an
  active problem given the app's current single-page shape, but don't use
  their placement as precedent when adding new files — follow the three-tier
  rule above instead.
