import { store, playbooksAtom } from "@/store";
import { actions } from "@/actions";
import {
  listPlaybooksApiV1PlaybooksGet,
  executePlaybookApiV1PlaybooksPlaybookIdExecutePost,
  getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet,
} from "@/generated/sdk.gen";
import type { PlaybookExecution } from "@/generated/types.gen";

/**
 * Playbook network calls (`/api/v1/playbooks*`) — scoped to **running**
 * existing playbooks against the open document, not authoring them.
 * Playbook create/update/delete stays a web-app concern; this client
 * doesn't wrap `createPlaybookApiV1PlaybooksPost` etc.
 *
 * Stubbed ahead of the Playbooks tab's real UI (DE-287 M3-B5 — currently
 * placeholder text in `App.tsx`) so the network layer exists once that
 * work starts, same rationale as `skillClient.ts`'s `userSkillClient`.
 * Not self-invoked at module load — nothing renders `playbooksAtom` yet.
 *
 * `execute()`'s request body (`PlaybookExecutionCreate`) requires a
 * `target_document_id` referencing an already-ingested `Document` row —
 * the Word add-in's open document isn't ingested anywhere. This client
 * sends the contract as declared; resolving what `target_document_id`
 * should be for a live, un-ingested Word document is backend-design work
 * for whoever picks up M3-B5, not something this client can paper over.
 *
 * `execute()`'s 202 response (`PlaybookExecution`) is properly typed by
 * the generated client. DE-287 M3-B5 describes **per-position SSE
 * streaming progress** for a running execution — not implemented here;
 * this lands as a plain non-streaming call. See ../../CLAUDE.md's
 * streaming section for the `createSseClient` wiring this would need,
 * and verify against the live spec whether this endpoint even declares
 * an SSE content type before assuming it's a drop-in swap.
 */
export const playbookClient = {
  /** `GET /api/v1/playbooks`. */
  async get(): Promise<void> {
    const { data, error } = await listPlaybooksApiV1PlaybooksGet();
    if (error || !data) {
      actions.showNotification("Error loading playbooks");
      return;
    }
    store.set(playbooksAtom, data);
  },

  /** `POST /api/v1/playbooks/{playbook_id}/execute` — `202 Accepted`,
   *  returns the created (queued/running) execution. Not stored — the
   *  caller drives whatever progress UI it needs from the returned
   *  execution id via `getExecution()`/polling, not a global atom. */
  async execute(
    playbookId: string,
    targetDocumentId: string,
    projectId?: string | null
  ): Promise<PlaybookExecution | undefined> {
    const { data, error } = await executePlaybookApiV1PlaybooksPlaybookIdExecutePost({
      path: { playbook_id: playbookId },
      body: { target_document_id: targetDocumentId, project_id: projectId },
    });
    if (error || !data) {
      actions.showNotification("Error starting playbook execution");
      return undefined;
    }
    return data;
  },

  /** `GET /api/v1/playbook-executions/{execution_id}` — single on-demand
   *  lookup, returned directly rather than stored (see `skillClient.ts`'s
   *  `getOne()` docstring / ../../CLAUDE.md's "an atom is for persistent,
   *  cross-component data" rule — a global "current execution" atom
   *  would race the moment two executions were polled concurrently). */
  async getExecution(executionId: string): Promise<PlaybookExecution | undefined> {
    const { data, error } = await getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet({
      path: { execution_id: executionId },
    });
    if (error || !data) {
      actions.showNotification("Error loading playbook execution");
      return undefined;
    }
    return data;
  },
};
