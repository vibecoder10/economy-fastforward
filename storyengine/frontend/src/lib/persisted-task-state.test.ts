import { describe, expect, it } from "vitest";

import { persistedTaskActivity } from "./persisted-task-state";

describe("persisted pipeline task presentation", () => {
  it("restores an active Run All final stage after the production page reloads", () => {
    expect(persistedTaskActivity("running", "autobuild", "ready_to_render")).toEqual({
      active: true,
      runAllActive: true,
      renderActive: true,
    });
    expect(persistedTaskActivity("pending", "autobuild", "rendering")).toEqual({
      active: true,
      runAllActive: true,
      renderActive: true,
    });
  });

  it("restores a directly started render without labeling it Run All", () => {
    expect(persistedTaskActivity("running", "render", "ready_to_render")).toEqual({
      active: true,
      runAllActive: false,
      renderActive: true,
    });
  });

  it("does not keep completed or failed work active", () => {
    expect(persistedTaskActivity("completed", "autobuild").active).toBe(false);
    expect(persistedTaskActivity("failed", "render").active).toBe(false);
    expect(persistedTaskActivity("idle", null).active).toBe(false);
  });
});
