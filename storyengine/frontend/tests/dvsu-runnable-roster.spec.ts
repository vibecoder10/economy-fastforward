import { expect, test, type Page } from "@playwright/test";

const VIDEO_ID = "dvsu-runnable-roster";
const SUBJECT = "Every US Submarine Class Ever Built";
const roster = Array.from({ length: 20 }, (_, index) => `SS-${index + 1} Test Submarine ${index + 1}`);

test.use({ channel: "chrome" });

function preview(machine: string, scene: number) {
  return {
    machine,
    scene,
    paragraph: `${machine} ${Array(88).fill("fixture").join(" ")}`,
    passed: true,
    factual_passed: true,
    compiler_version: 2,
    editorial_review_version: 1,
    editorial_review: {
      version: 1, passed: true, issues: [], checks: Object.fromEntries(
        ["design_intent", "actual_use", "consequence", "gap_or_supported_substitute", "verdict", "spoken_style"].map((key) => [key, true]),
      ),
    },
    machine_script_contract: "factual_100_v1",
    review_context_version: 6,
    subject_context: SUBJECT,
    source_fingerprint: `fixture-${scene}`,
  };
}

async function stubPipeline(page: Page, factual = true) {
  const payload = {
    machine_script_contract: factual ? "factual_100_v1" : "legacy_anton",
    unit_roster: roster.map((designation) => ({ designation })),
    unit_research_hold_validation: { passed: false, units: [] },
    unit_research_cards: roster.map((machine, index) => ({
      machine_name: machine,
      readiness: index < 2
        ? { passed: true, warnings: [] }
        : { passed: false, warnings: ["Sources need preparation"] },
    })),
    machine_script_previews: factual ? {
      [roster[0]]: preview(roster[0], 1),
      [roster[1]]: preview(roster[1], 2),
    } : {},
  };
  const video = {
    id: VIDEO_ID,
    video_title: SUBJECT,
    status: "ready_for_scripting",
    render_mode: "static_docu",
    research_payload: payload,
    script_validation: {},
    pipeline_stages: null,
    created_at: "2026-09-17T00:00:00Z",
  };

  await page.route("**/api/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  await page.route("**/api/auth/me", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ id: "operator", email: "operator@example.test", display_name: "Operator", plan: "pro" }) }));
  await page.route("**/api/workspaces", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ is_operator: false, workspaces: [] }) }));
  await page.route("**/api/billing/subscription", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ plan: "pro", status: "active", trial_active: false }) }));
  await page.route(`**/api/videos/${VIDEO_ID}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(video) }));
  await page.route(`**/api/videos/${VIDEO_ID}/assets`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/videos/${VIDEO_ID}/script`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
  await page.route(`**/api/pipeline/task/${VIDEO_ID}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "idle" }) }));
  await page.route(`**/api/pipeline/roster-dashboard/${VIDEO_ID}`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "ready", ready: 0, total: 20, units: [] }) }));
  await page.route("**/api/pipeline/stream**", (route) => route.fulfill({ status: 200, contentType: "text/event-stream", body: ": connected\n\n" }));
}

test("factual roster renders runnable cards, labels previews separately, and hard preflight makes no paid POST", async ({ page }) => {
  await stubPipeline(page);
  let readinessPosts = 0;
  let paidPosts = 0;
  await page.route(`**/api/pipeline/machine-script-preview-readiness/${VIDEO_ID}`, (route) => {
    readinessPosts += 1;
    const machine = (route.request().postDataJSON() as { machine?: string }).machine;
    const hardBlocked = machine === roster[19];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      status: hardBlocked ? "blocked" : "preparation_needed", ready: false, preparable: !hardBlocked, video_id: VIDEO_ID,
      machine, summary: hardBlocked ? "Evidence is unavailable" : "Evidence needs preparation", warnings: [hardBlocked ? "Evidence is unavailable" : "Evidence needs preparation"],
    }) });
  });
  await page.route(`**/api/pipeline/machine-script-preview-jobs/${VIDEO_ID}`, (route) => {
    paidPosts += 1;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "accepted" }) });
  });
  let jobPolls = 0;
  await page.route(`**/api/pipeline/machine-script-preview-jobs/${VIDEO_ID}/**`, (route) => {
    jobPolls += 1;
    const requestId = route.request().url().split("/").pop();
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
      id: requestId, status: "completed", result: { status: "completed", preview: preview(roster[2], 3) },
    }) });
  });
  let scriptPosts = 0;
  let releaseScriptPost!: () => void;
  await page.route(`**/api/pipeline/script/${VIDEO_ID}`, async (route) => {
    scriptPosts += 1;
    await new Promise<void>((resolve) => { releaseScriptPost = resolve; });
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "accepted" }) });
  });

  await page.goto(`/pipeline/${VIDEO_ID}`);
  await expect(page.getByText("0/20 production scenes passed current factual review; 2/20 script previews passed.")).toBeVisible();
  await expect(page.getByText("Script preview passed")).toHaveCount(2);
  await expect(page.getByText("Reviewed preview saved. Run All adds it to the production script.")).toHaveCount(2);
  await expect(page.getByText("Current factual review did not pass.", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Research check needed")).toHaveCount(18);
  await expect(page.getByRole("button", { name: "Run All Script Cards" })).toBeEnabled();
  const runCards = page.getByRole("button", { name: "Run Script", exact: true });
  await expect(runCards).toHaveCount(18);
  for (let index = 0; index < 18; index += 1) await expect(runCards.nth(index)).toBeEnabled();

  await runCards.first().click();
  await expect(page.getByTestId("confirm-modal-message")).toContainText("prepares any missing source-backed research");
  await page.getByTestId("confirm-modal-confirm").click();
  expect(readinessPosts).toBe(1);
  await expect.poll(() => paidPosts).toBe(1);
  await expect.poll(() => jobPolls).toBe(1);
  await expect(page.getByText(`${roster[2]} preview generated. Production script unchanged.`)).toBeVisible();
  await expect(page.getByText("Preview failed:")).toHaveCount(0);

  await runCards.last().click();
  await expect(page.getByText("Preview blocked: Evidence is unavailable. Production script unchanged.")).toBeVisible();
  expect(readinessPosts).toBe(2);
  expect(paidPosts).toBe(1);

  await page.getByRole("button", { name: "Run All Script Cards" }).click();
  await expect(page.getByTestId("confirm-modal-message")).toContainText("18 cards need research preparation before writing.");
  await page.getByTestId("confirm-modal-confirm").click();
  await expect.poll(() => scriptPosts).toBe(1);
  await expect(runCards.first()).toBeDisabled();
  releaseScriptPost();
});

test("nonfactual roster remains held by its saved research gate", async ({ page }) => {
  await stubPipeline(page, false);
  await page.goto(`/pipeline/${VIDEO_ID}`);
  await expect(page.getByRole("button", { name: "Run All Script Cards" })).toBeHidden();
  await expect(page.getByText("Machine research is incomplete: 2/20 verified cards finished.")).toBeVisible();
});
