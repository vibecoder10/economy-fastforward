import { test, expect, Page } from "@playwright/test";

// Acceptance spec for PRD `storyengine/prds/onboarding-ux-audit-2026-04-17.md`.
// Each test maps to a numbered acceptance criterion in the "Acceptance Criteria
// (Test Plan)" section of that PRD.
//
// All backend routes are intercepted here so these tests run without a live
// backend (and deterministically regardless of backend state).

async function stubBackend(page: Page, opts: { onboardingStatus?: "ok" | "fail"; saveChannel?: "ok" | "fail" } = {}) {
  const { onboardingStatus = "ok", saveChannel = "ok" } = opts;

  await page.route("**/api/dashboard/onboarding/status", async (route) => {
    if (onboardingStatus === "fail") {
      await route.fulfill({ status: 500, body: "boom" });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        completed: false,
        display_name: "Test User",
        steps: {
          channel_configured: false,
          api_keys: { configured: 0, required: 3 },
          style_generated: false,
        },
      }),
    });
  });

  await page.route("**/api/auth/youtube/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ connected: false, channel_name: null }),
    });
  });

  await page.route("**/api/channel-profile", async (route) => {
    if (saveChannel === "fail") {
      // Simulate an unreachable backend — the same shape fetchApi produces
      // when the origin is down.
      await route.abort("failed");
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
}

test.describe("Onboarding UX — PRD acceptance criteria", () => {
  test("AC-1: shows network-health banner when onboarding-status load fails", async ({ page }) => {
    await stubBackend(page, { onboardingStatus: "fail" });
    await page.goto("/onboarding");

    // Wait for the initial load to complete — the banner renders once the catch block fires.
    const banner = page.getByTestId("onboarding-network-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/couldn.?t load your progress/i);

    // Step 1 should still render below the banner so the user can continue
    // typing (data just won't persist until reconnect).
    await expect(page.getByRole("heading", { name: "Your Channel" })).toBeVisible();
  });

  test("AC-2: Step 1 Channel Name placeholder is NOT 'Economy FastForward'", async ({ page }) => {
    await stubBackend(page);
    await page.goto("/onboarding");

    const channelInput = page.getByRole("textbox", { name: /channel name/i });
    const placeholder = await channelInput.getAttribute("placeholder");

    expect(placeholder, "placeholder leaks Ryan's channel name").not.toMatch(/economy\s*fast\s*forward/i);
  });

  test("AC-3: Niche and Audience labels carry '(optional)' affordance", async ({ page }) => {
    await stubBackend(page);
    await page.goto("/onboarding");

    await expect(page.getByText(/what topics will you cover\?.*optional/i)).toBeVisible();
    await expect(page.getByText(/who are you making videos for\?.*optional/i)).toBeVisible();
  });

  test("AC-4: Continue button looks and behaves disabled when Channel Name is empty", async ({ page }) => {
    await stubBackend(page);
    await page.goto("/onboarding");

    const continueBtn = page.getByRole("button", { name: "Continue" });
    await expect(continueBtn).toBeDisabled();
    await expect(continueBtn).toHaveAttribute("aria-disabled", "true");

    // Computed opacity should be <= 0.4 (the PRD target) — opacity-40 class wins
    // over filled-variant inline background.
    const opacity = await continueBtn.evaluate((el) =>
      parseFloat(getComputedStyle(el).opacity),
    );
    expect(opacity).toBeLessThanOrEqual(0.4 + 0.01);

    // Cursor should visibly communicate not-allowed.
    const cursor = await continueBtn.evaluate(
      (el) => getComputedStyle(el).cursor,
    );
    expect(cursor).toBe("not-allowed");
  });

  test("AC-5: Step 1 submit-failure error is human-readable, not raw fetch text", async ({ page }) => {
    await stubBackend(page, { saveChannel: "fail" });
    await page.goto("/onboarding");

    // Fill the minimum required field so Continue is enabled.
    await page.getByRole("textbox", { name: /channel name/i }).fill("Test Channel");

    // Click Continue — the stub will cause updateChannelProfile to throw.
    await page.getByRole("button", { name: "Continue" }).click();

    // An error appears in the form.
    const errorText = await page
      .locator("p")
      .filter({ hasText: /couldn.?t|connection|please try again|session|limit|snag|doing that a lot/i })
      .first()
      .textContent();
    expect(errorText, "friendly error copy should render").toBeTruthy();

    // Raw dev strings must NOT leak to the user.
    await expect(page.getByText("Failed to fetch")).toHaveCount(0);
    await expect(page.getByText(/^API error \d/)).toHaveCount(0);
    await expect(page.getByText(/NetworkError/)).toHaveCount(0);
  });

  test("AC-6: /icon-192.svg is served with a 2xx status", async ({ page }) => {
    const resp = await page.request.get("/icon-192.svg");
    expect(resp.status(), `icon fetch status=${resp.status()}`).toBeGreaterThanOrEqual(200);
    expect(resp.status()).toBeLessThan(300);
  });

  test("AC-W1: fresh user (no welcome-seen flag) sees the welcome screen with display name", async ({ page }) => {
    await stubBackend(page);
    // No localStorage seed — page starts with a clean slate.
    await page.goto("/onboarding");

    await expect(page.getByRole("heading", { name: /Hey\s+Test/ })).toBeVisible();
    await expect(page.getByText(/5 quick steps/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Let.?s go/i })).toBeVisible();
    await expect(page.getByText(/takes about 15 minutes/i)).toBeVisible();
  });

  test("AC-W2: clicking Let's go dismisses welcome, lands on Step 1, and persists the flag", async ({ page }) => {
    await stubBackend(page);
    await page.goto("/onboarding");

    await page.getByRole("button", { name: /Let.?s go/i }).click();

    await expect(page.getByRole("heading", { name: "Your Channel" })).toBeVisible();

    const flag = await page.evaluate(() =>
      window.localStorage.getItem("onboarding_welcome_seen"),
    );
    expect(flag).toBe("1");
  });

  test("AC-W3: returning user with welcome-seen flag skips welcome and lands on Step 1 directly", async ({ page }) => {
    await stubBackend(page);

    // Seed localStorage before the app mounts. We need a context reload after
    // seeding because localStorage is per-origin and set via addInitScript
    // applies to subsequent navigations.
    await page.addInitScript(() => {
      window.localStorage.setItem("onboarding_welcome_seen", "1");
    });

    await page.goto("/onboarding");

    await expect(page.getByRole("heading", { name: "Your Channel" })).toBeVisible();
    // Welcome heading must not render.
    await expect(page.getByRole("heading", { name: /Hey\s+/ })).toHaveCount(0);
  });
});
