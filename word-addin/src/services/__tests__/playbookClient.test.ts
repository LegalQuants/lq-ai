import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/generated/sdk.gen", () => ({
  listPlaybooksApiV1PlaybooksGet: vi.fn(),
  executePlaybookApiV1PlaybooksPlaybookIdExecutePost: vi.fn(),
  getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet: vi.fn(),
}));

vi.mock("@/actions", () => ({ actions: { showNotification: vi.fn() } }));

import {
  listPlaybooksApiV1PlaybooksGet,
  executePlaybookApiV1PlaybooksPlaybookIdExecutePost,
  getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet,
} from "@/generated/sdk.gen";
import { store, resetStoreForTests, playbooksAtom } from "@/store";
import { playbookClient } from "@/services/playbookClient";
import { actions } from "@/actions";
import type { Playbook, PlaybookExecution } from "@/generated/types.gen";

const PLAYBOOKS: Playbook[] = [
  {
    id: "pb-1",
    name: "MSA Review",
    contract_type: "msa",
    created_at: "2026-07-15T00:00:00Z",
    updated_at: "2026-07-15T00:00:00Z",
  },
];

const EXECUTION: PlaybookExecution = {
  id: "exec-1",
  playbook_id: "pb-1",
  target_document_id: "doc-1",
  status: "pending",
  created_at: "2026-07-15T00:00:00Z",
};

describe("playbookClient", () => {
  beforeEach(() => {
    resetStoreForTests();
    vi.mocked(listPlaybooksApiV1PlaybooksGet).mockReset();
    vi.mocked(executePlaybookApiV1PlaybooksPlaybookIdExecutePost).mockReset();
    vi.mocked(getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet).mockReset();
    vi.mocked(actions.showNotification).mockReset();
  });

  it("get() populates playbooksAtom on success", async () => {
    vi.mocked(listPlaybooksApiV1PlaybooksGet).mockResolvedValue({
      data: PLAYBOOKS,
      error: undefined,
    });

    await playbookClient.get();

    expect(store.get(playbooksAtom)).toEqual(PLAYBOOKS);
  });

  it("get() notifies instead of throwing on failure", async () => {
    vi.mocked(listPlaybooksApiV1PlaybooksGet).mockResolvedValue({
      data: undefined,
      error: {},
    });

    await playbookClient.get();

    expect(store.get(playbooksAtom)).toEqual([]);
    expect(actions.showNotification).toHaveBeenCalledWith("Error loading playbooks");
  });

  it("execute() returns the created execution to the caller", async () => {
    vi.mocked(executePlaybookApiV1PlaybooksPlaybookIdExecutePost).mockResolvedValue({
      data: EXECUTION,
      error: undefined,
    });

    const result = await playbookClient.execute("pb-1", "doc-1");

    expect(executePlaybookApiV1PlaybooksPlaybookIdExecutePost).toHaveBeenCalledWith({
      path: { playbook_id: "pb-1" },
      body: { target_document_id: "doc-1", project_id: undefined },
    });
    expect(result).toEqual(EXECUTION);
  });

  it("getExecution() returns the execution to the caller", async () => {
    vi.mocked(getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet).mockResolvedValue({
      data: EXECUTION,
      error: undefined,
    });

    const result = await playbookClient.getExecution("exec-1");

    expect(getPlaybookExecutionApiV1PlaybookExecutionsExecutionIdGet).toHaveBeenCalledWith({
      path: { execution_id: "exec-1" },
    });
    expect(result).toEqual(EXECUTION);
  });
});
