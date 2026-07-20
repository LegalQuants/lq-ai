import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@/services/skillClient", () => ({
  skillClient: { get: vi.fn().mockResolvedValue(undefined) },
}));
vi.mock("@/services/modelClient", () => ({
  modelClient: { get: vi.fn().mockResolvedValue(undefined) },
}));

import { skillClient } from "@/services/skillClient";
import { modelClient } from "@/services/modelClient";
import { initializeApp } from "@/services/bootstrap";

describe("initializeApp", () => {
  beforeEach(() => {
    vi.mocked(skillClient.get).mockClear();
    vi.mocked(modelClient.get).mockClear();
  });

  it("calls skillClient.get() and modelClient.get()", async () => {
    await initializeApp();

    expect(skillClient.get).toHaveBeenCalledTimes(1);
    expect(modelClient.get).toHaveBeenCalledTimes(1);
  });

  it("runs both in parallel, not sequentially", async () => {
    const order: string[] = [];
    vi.mocked(skillClient.get).mockImplementation(async () => {
      order.push("skills-start");
      await Promise.resolve();
      order.push("skills-end");
    });
    vi.mocked(modelClient.get).mockImplementation(async () => {
      order.push("models-start");
      await Promise.resolve();
      order.push("models-end");
    });

    await initializeApp();

    // Both starts happen before either end — proves Promise.all, not
    // sequential awaiting (which would produce skills-start, skills-end,
    // models-start, models-end).
    expect(order.slice(0, 2)).toEqual(expect.arrayContaining(["skills-start", "models-start"]));
  });
});
