import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { ConfirmProvider } from "@/components/ui/confirm";
import { ToastProvider } from "@/components/ui/toast";
import { StaticDocuStageRail } from "./StaticDocuStageRail";
import type { TaskWatcherBridge } from "@/hooks/use-task-poller";

const video = {
  id: "video",
  status: "ready_to_render",
  render_mode: "static_docu",
  thumbnail_url: "https://example.test/thumb.jpg",
  research_payload: { unit_roster: ["HMS Argus"] },
};
const actions = {
  summary: { scenes: 1, voiced: 1 },
  actions: [],
};
const roster = {
  total: 1,
  ready: 1,
  units: [{ reference: { status: "verified" } }],
};
const assets = [{
  scene: 1,
  image_index: 1,
  image_url: "https://example.test/view.jpg",
  status: "done",
  generation_method: "static_docu",
  caption: null,
}];

function renderRail(running: boolean, taskType: string | null, failure: string | null = null, status = video.status): string {
  const watcher: TaskWatcherBridge = {
    running,
    failure,
    taskType,
    message: running ? "Working on it…" : null,
    viaAgent: null,
    markStarted: () => undefined,
    subscribe: () => () => undefined,
  };
  const rail = createElement(StaticDocuStageRail, {
    video: { ...video, status } as never,
    videoActions: actions as never,
    rosterDashboard: roster as never,
    assets: assets as never,
    activeStage: "video",
    onSelectStage: () => undefined,
    taskWatcher: watcher,
  });
  return renderToStaticMarkup(createElement(
    QueryClientProvider,
    { client: new QueryClient() },
    createElement(ToastProvider, null, createElement(ConfirmProvider, null, rail)),
  ));
}

function buttonTag(markup: string, testId: string): string {
  const match = markup.match(new RegExp(`<button[^>]*data-testid="${testId}"[^>]*>`));
  if (!match) throw new Error(`missing ${testId} button`);
  return match[0];
}

function isDisabled(tag: string): boolean {
  return /\sdisabled=""/.test(tag);
}

describe("StaticDocuStageRail persisted task controls", () => {
  it("restores a reloaded external autobuild as active and disables duplicates", () => {
    const markup = renderRail(true, "autobuild");
    expect(markup).toContain("Running All…");
    expect(markup).toContain("Run All is finishing the video…");
    expect(isDisabled(buttonTag(markup, "run-all"))).toBe(true);
    expect(isDisabled(buttonTag(markup, "stage-run-video"))).toBe(true);
    expect(markup).toContain("animate-spin");
  });

  it("restores controls when the persisted task is terminal or idle", () => {
    const markup = renderRail(false, null);
    expect(markup).not.toContain("Running All…");
    expect(isDisabled(buttonTag(markup, "run-all"))).toBe(false);
    expect(isDisabled(buttonTag(markup, "stage-run-video"))).toBe(false);
  });
});


it("restores the persisted failure on the static documentary rail after reload", () => {
  const html = renderRail(false, null, "Kie source search is temporarily unavailable. Completed research is saved.");
  expect(html).toContain("Kie source search is temporarily unavailable");
  expect(html).toContain("Run All stopped at");
});


it("labels a blocked incomplete script as Script rather than the next visual stage", () => {
  const html = renderRail(false, null, "Anthropic has reached its API usage limit.", "ready_for_scripting");
  expect(html).toMatch(/Run All stopped at Script/);
});
