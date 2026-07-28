import { test, expect, Page } from "@playwright/test";

// Regression spec for the "build offer card never appears" bug (live prod,
// 2026-07-27/28) — root cause: DirectorHome's entry box (rendered at `/` or
// `/chat`) hands off a brand-new video to the Director surface by setting
// local context state AND calling `router.push('/chat/<id>')`
// (DirectorContext.tsx `setSelectedVideoId`). That real Next.js navigation
// unmounts the ChatCore instance that just fired the seed `/api/chat` turn —
// almost always before the response lands — and the REPLACEMENT instance
// used to call `getChatConversation` immediately, racing (and usually
// losing) against the backend still finishing that very turn. The fix
// (DirectorContext.tsx `pendingInitialTurn`, ChatCore.tsx's `turn()` return
// value + the two new effects) survives that navigation by handing the
// turn's result through DirectorContext instead of local component state.
//
// This test reproduces the race deterministically by delaying the stubbed
// `/api/chat` response past the point the client-side navigation completes,
// then asserts the response still renders WITHOUT a manual reload — and
// that exactly one `/api/chat` POST was made (no double-send).

const VIDEO_ID = "vid-race-1";
const CHAT_DELAY_MS = 4000; // comfortably longer than a client-side route swap

async function stubBackend(page: Page) {
  // Lenient catch-all first (Playwright matches the MOST RECENTLY
  // registered route first, so specific handlers below still win) — keeps
  // this test from having to enumerate every endpoint the authenticated
  // shell / sidebar / canvas / rail touch on mount; those panels are each
  // independently error-boundaried on the real Director surface, so a
  // generic `{}` for anything unrelated to this test's assertions is safe.
  await page.route("**/api/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "{}" })
  );

  await page.route("**/api/auth/me", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "u1", email: "test@example.com", display_name: "Test", plan: "pro" }),
    })
  );

  await page.route("**/api/workspaces", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ is_operator: false, workspaces: [] }) })
  );

  await page.route("**/api/billing/subscription", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ plan: "pro", status: "active", trial_active: true, trial_days_remaining: 5 }),
    })
  );

  // DirectorHome's own page-load queries (recent videos, production styles,
  // custom-film recipes, suggested models) — real shapes, empty is fine.
  await page.route("**/api/videos", (route) => {
    if (route.request().method() === "POST") return route.fallback();
    return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
  });
  await page.route("**/api/production-styles", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ styles: [] }) })
  );
  await page.route("**/api/custom-film/recipes", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ recipes: [] }) })
  );
  await page.route("**/api/chat/suggested-models", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ videos: [] }) })
  );
  await page.route("**/api/style-descriptions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ descriptions: [] }) })
  );

  // createVideo() — the free, instant DB insert PromptEntrySection.send() fires.
  await page.route("**/api/videos", (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: VIDEO_ID,
        video_title: "a dragon movie",
        status: "idea_logged",
        thumbnail_url: null,
        accent_color: "#00E4B8",
        total_cost: 0,
        views: 0,
        ctr: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }),
    });
  });

  await page.route(`**/api/videos/${VIDEO_ID}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: VIDEO_ID,
        video_title: "a dragon movie",
        status: "idea_logged",
        thumbnail_url: null,
        accent_color: "#00E4B8",
        total_cost: 0,
        views: 0,
        ctr: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        pipeline_stages: null,
        production_style_snapshot: null,
        custom_film_plan: null,
      }),
    })
  );

  await page.route(`**/api/pipeline/actions/${VIDEO_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ actions: [] }) })
  );
  await page.route(`**/api/videos/${VIDEO_ID}/ledger`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ total_cost: 0, entries: [], by_stage: {} }) })
  );
  await page.route("**/api/production-guide/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ stages: [], next_step: { action: "run", stage: "research" } }),
    })
  );
  await page.route("**/api/pipeline/stream**", (route) =>
    route.fulfill({ status: 200, contentType: "text/event-stream", body: ": connected\n\n" })
  );

  // RightRail's Media panel filters these as arrays (assets/script scenes) —
  // the generic `{}` catch-all above crashes it (`.filter is not a
  // function`), which trips a ROOT-level Next.js error boundary (not one of
  // DirectorSurface's per-panel ones) and blanks the whole page. Unrelated
  // to this test's assertions, but it has to not crash for them to be
  // reachable at all.
  await page.route(`**/api/videos/${VIDEO_ID}/assets`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route(`**/api/videos/${VIDEO_ID}/script`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route(`**/api/pipeline/actions/${VIDEO_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ actions: [] }) })
  );
  await page.route(`**/api/videos/${VIDEO_ID}/ledger`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ total_cost: 0, entries: [], by_stage: {} }) })
  );

  // No prior conversation for this video — the seed turn is the first ever.
  await page.route(`**/api/chat/conversation?video_id=${VIDEO_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ conversation_id: null, messages: [], phase: "created" }) })
  );
}

test.describe("Director seed-turn navigation race", () => {
  test("the build-offer card renders after the seed turn even when its response lands AFTER the /chat/<id> navigation completes, with exactly one POST", async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem("token", "test-token");
    });
    await stubBackend(page);

    let chatPostCount = 0;
    let capturedExplicitVerb: string | undefined;
    await page.route("**/api/chat", async (route) => {
      if (route.request().method() !== "POST") return route.fallback();
      chatPostCount += 1;
      const body = route.request().postDataJSON() as { explicit_verb?: string };
      capturedExplicitVerb = body.explicit_verb;
      // Deliberately resolve AFTER the client-side navigation to
      // /chat/<id> has had time to complete — this is what reproduces the
      // race: on the pre-fix code, the ChatCore instance that fired this
      // request is unmounted by then, and its response is discarded.
      await new Promise((r) => setTimeout(r, CHAT_DELAY_MS));
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          conversation_id: "conv-1",
          assistant_text: "Ready when you are — I'll build the video (~$1.50).",
          cards: [
            {
              id: "confirm_action",
              label: "Build the video",
              type: "single",
              options: [
                { value: "yes", label: "Do it · ~$1.50" },
                { value: "no", label: "Cancel" },
              ],
            },
          ],
          plan: null,
          ready_to_create: false,
          video_id: null,
          phase: "asking",
        }),
      });
    });

    await page.goto("/");
    const box = page.getByPlaceholder(/Describe the video you want/i);
    await expect(box).toBeVisible();
    await box.fill("a dragon movie");
    await box.press("Enter");

    // The video-scoped URL should land almost immediately (the create call
    // is free/instant) — well before the delayed /api/chat resolves. This
    // proves the "video id lives in the URL" requirement survives the fix.
    await expect(page).toHaveURL(new RegExp(`/chat/${VIDEO_ID}$`), { timeout: 10_000 });

    // Right after the navigation, the card must NOT be there yet (the
    // backend hasn't answered) — this pins down that we're really
    // exercising the race, not some other, already-resolved path.
    await expect(page.getByText("Do it · ~$1.50")).toHaveCount(0);

    // The actual assertion: once the delayed response lands, the card
    // renders on its own — no reload, no user action.
    await expect(page.getByText("Do it · ~$1.50")).toBeVisible({ timeout: CHAT_DELAY_MS + 10_000 });
    await expect(page.getByText(/I'll build the video/)).toBeVisible();

    // No double-send: exactly one POST /api/chat for this whole flow.
    expect(chatPostCount).toBe(1);
    // The front door's own contract: explicit_verb="build" must reach the
    // backend so the co-pilot never has to guess the verb from free text.
    expect(capturedExplicitVerb).toBe("build");
  });
});
