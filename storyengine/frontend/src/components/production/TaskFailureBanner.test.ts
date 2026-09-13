import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";
import { TaskFailureBanner } from "./TaskFailureBanner";

function render(failure: string | null, running = false) {
  return renderToStaticMarkup(createElement(QueryClientProvider, { client: new QueryClient() },
    createElement(TaskFailureBanner, { videoId: "video", taskWatcher: {
      running, failure, message: null, viaAgent: null, taskType: null,
      markStarted: () => undefined, subscribe: () => () => undefined,
    } }),
  ));
}

describe("persisted task failures", () => {
  it("shows the provider blocker on a cold load without a running transition", () => {
    const html = render("Tavily is out of credits. Completed research is saved.");
    expect(html).toContain("Tavily is out of credits");
    expect(html).toContain("Completed research is saved");
  });
  it("hides the old error while a new run is active or no failure is saved", () => {
    expect(render("old failure", true)).toBe("");
    expect(render(null)).toBe("");
  });
});
