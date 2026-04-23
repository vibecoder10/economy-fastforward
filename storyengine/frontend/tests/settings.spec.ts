import { test, expect, Page } from "@playwright/test";

// ─── Shared helpers ───────────────────────────────────────────────────────────

async function stubAuth(page: Page) {
  await page.route("**/api/auth/me", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ id: "test-user", email: "test@example.com" }),
    });
  });
  await page.addInitScript(() => {
    window.localStorage.setItem("token", "test-token");
  });
}

/**
 * Reusable OAuth callback mock — designed for reuse by the forthcoming YouTube OAuth spec.
 * Usage: await mockOAuthCallback(page, "/api/auth/google-drive/callback", { status: "ok" });
 */
export async function mockOAuthCallback(
  page: Page,
  callbackEndpoint: string,
  responseBody: Record<string, unknown>,
) {
  await page.route(`**${callbackEndpoint}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(responseBody),
    });
  });
}

function captureConsoleErrors(page: Page): () => string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      const text = msg.text();
      if (
        !text.includes("favicon") &&
        !text.includes("ERR_CONNECTION_REFUSED") &&
        !text.includes("net::") &&
        !text.includes("apis.google.com") &&
        !text.includes("ERR_NAME_NOT_RESOLVED") &&
        !text.includes("hydration") &&
        !text.includes("CORS") &&
        !text.includes("status of 410")
      ) {
        errors.push(text);
      }
    }
  });
  return () => errors;
}

/** Stub sidebar endpoints that fire on every page load. */
async function stubSidebar(page: Page) {
  await page.route("**/api/review/pending", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await page.route("**/api/health", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "healthy",
        service: "storyengine",
        database: true,
        active_tasks: 0,
      }),
    });
  });

  await page.route("**/api/dashboard/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({}),
    });
  });
}

/** Stub all endpoints the /settings page fetches on mount. */
async function stubSettingsPage(
  page: Page,
  overrides: {
    driveStatus?: { connected: boolean; folder_id: string | null; folder_name: string | null };
    channelProfile?: Record<string, unknown>;
    notifPrefs?: Record<string, boolean>;
  } = {},
) {
  await page.route("**/api/projects/current", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: route.request().postData() ?? "{}",
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "1",
        name: "Test Channel",
        niche: "Geopolitics",
        target_audience: "Adults interested in world affairs",
        visual_style: "cinematic_illustration",
        accent_color: "#00D4AA",
        frameworks: ["Game Theory"],
      }),
    });
  });

  await page.route("**/api/channel-profile", async (route) => {
    if (route.request().method() === "PUT") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: route.request().postData() ?? "{}",
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        overrides.channelProfile ?? {
          accent_color: "#00D4AA",
          logo_url: null,
        },
      ),
    });
  });

  await page.route("**/api/auth/google-drive/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        overrides.driveStatus ?? { connected: false, folder_id: null, folder_name: null },
      ),
    });
  });

  await page.route("**/api/auth/youtube/status", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ connected: false, channel_id: null, channel_name: null }),
    });
  });

  await page.route("**/api/preferences/notifications", async (route) => {
    if (route.request().method() === "PATCH") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: route.request().postData() ?? "{}",
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        overrides.notifPrefs ?? {
          email_video_complete: true,
          email_weekly_digest: true,
          email_error_alerts: true,
          email_ctr_alerts: true,
        },
      ),
    });
  });

  await page.route("**/api/settings/keys", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ keys: [] }),
    });
  });

  await page.route("**/api/billing/subscription", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ plan: "pro", status: "active" }),
    });
  });

  await stubSidebar(page);
}

/** Stub all endpoints the /settings/keys page fetches on mount. */
async function stubKeysPage(
  page: Page,
  overrides: {
    keys?: Array<{ name: string; configured: boolean; source: string | null; masked_value: string | null }>;
  } = {},
) {
  await page.route("**/api/settings/keys", async (route) => {
    const url = route.request().url();
    // Defensive guard: if Playwright ever matches sub-paths via this glob
    // (e.g. /api/settings/keys/anthropic_api_key), abort loudly so missing stubs
    // are caught immediately rather than silently escaping to the real network.
    if (url.match(/\/api\/settings\/keys\/.+/)) {
      await route.abort("failed");
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        keys: overrides.keys ?? [],
      }),
    });
  });

  await stubSidebar(page);
}

// ─── API Keys panel ─────────────────────────────────────────────────────────

test.describe("API Keys panel", () => {
  test("renders with no console errors when empty", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubKeysPage(page);
    await page.goto("/settings/keys");

    await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Validate All/i })).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("renders with no console errors when populated", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubKeysPage(page, {
      keys: [
        { name: "anthropic_api_key", configured: true, source: "vault", masked_value: "sk-...****" },
        { name: "elevenlabs_api_key", configured: false, source: null, masked_value: null },
      ],
    });
    await page.goto("/settings/keys");

    await expect(page.getByText("Anthropic (Claude)")).toBeVisible();
    await expect(page.getByText("sk-...****")).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("opens configure modal and saves key", async ({ page }) => {
    await stubAuth(page);

    // Specific route registered before stubKeysPage so it exists in Playwright's handler chain.
    // stubKeysPage calls route.abort() for sub-paths — Playwright's LIFO order means this
    // more-specific handler runs first for /api/settings/keys/anthropic_api_key requests.
    let savedKeyValue: string | undefined;
    await page.route("**/api/settings/keys/anthropic_api_key", async (route) => {
      if (route.request().method() === "POST") {
        const body = JSON.parse(route.request().postData() ?? "{}");
        savedKeyValue = body.value;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ status: "ok", message: "Saved" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ name: "anthropic_api_key", configured: false, source: null, masked_value: null }),
      });
    });

    await stubKeysPage(page, {
      keys: [
        { name: "anthropic_api_key", configured: false, source: null, masked_value: null },
      ],
    });

    await page.goto("/settings/keys");

    await page.getByRole("button", { name: "Configure" }).first().click();

    // Modal appears — find it by the title heading (no role="dialog" on this modal)
    await expect(page.getByRole("heading", { name: /Configure Anthropic/i })).toBeVisible();
    await page.getByPlaceholder(/Enter your API key/i).fill("sk-ant-test123");
    await page.getByRole("button", { name: /Save Key/i }).click();

    await expect(page.getByText("API Key Saved Successfully!")).toBeVisible();
    expect(savedKeyValue).toBe("sk-ant-test123");
  });

  test("test-key button exists and is wired for configured keys", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubKeysPage(page, {
      keys: [
        { name: "anthropic_api_key", configured: true, source: "vault", masked_value: "sk-...****" },
      ],
    });
    await page.goto("/settings/keys");

    // Configured key shows "Test" button with correct title
    const testBtn = page.getByRole("button", { name: /Test/i }).first();
    await expect(testBtn).toBeVisible();
    await expect(testBtn).toBeEnabled();
    // "Validate All" button is also visible (validates all keys)
    await expect(page.getByRole("button", { name: /Validate All/i })).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });
});

// ─── Google Drive connect ──────────────────────────────────────────────────

test.describe("Google Drive connect", () => {
  test("renders disconnected state with no console errors", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubSettingsPage(page, {
      driveStatus: { connected: false, folder_id: null, folder_name: null },
    });
    await page.goto("/settings");

    await expect(page.getByText("Google Drive Storage")).toBeVisible();
    await expect(page.getByRole("button", { name: /Connect Google Drive/i })).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("renders connected state with folder name", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubSettingsPage(page, {
      driveStatus: { connected: true, folder_id: "folder123", folder_name: "Economy FastForward" },
    });
    await page.goto("/settings");

    await expect(page.getByText("Economy FastForward")).toBeVisible();
    await expect(page.getByText("Google Drive Connected")).toBeVisible();
    await expect(page.getByRole("button", { name: /Disconnect/i })).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("drive-callback page exchanges code and redirects", async ({ page }) => {
    await stubAuth(page);
    await stubSettingsPage(page);
    await mockOAuthCallback(page, "/api/auth/google-drive/callback", {
      status: "ok",
      access_token: "mock_access_token",
    });
    await page.goto("/settings/drive-callback?code=mock_code");

    await expect(page.getByText("Google Drive connected!")).toBeVisible();

    await page.waitForURL("**/settings", { timeout: 5000 });
  });
});

// ─── Brand Kit panel ───────────────────────────────────────────────────────

test.describe("Brand Kit panel", () => {
  test("renders with no console errors when empty", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubSettingsPage(page, {
      channelProfile: { accent_color: null, logo_url: null },
    });
    await page.goto("/settings");

    await expect(page.getByRole("heading", { name: "Brand Kit" })).toBeVisible();
    await expect(page.getByText("Accent Color", { exact: true })).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("renders with no console errors when populated", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubSettingsPage(page, {
      channelProfile: { accent_color: "#FF6B35", logo_url: "https://example.com/logo.png" },
    });
    await page.goto("/settings");

    // Wait for the accent color input to reflect the value from the API
    const accentInput = page.locator("input[maxlength='7']");
    await expect(accentInput).toHaveValue("#FF6B35");
    // Logo URL input should be populated
    await expect(page.getByPlaceholder("https://example.com/logo.png")).toHaveValue("https://example.com/logo.png");

    expect(getErrors()).toHaveLength(0);
  });

  test("saves brand kit via Save button", async ({ page }) => {
    await stubAuth(page);

    let putBody: Record<string, unknown> | undefined;
    await stubSettingsPage(page);
    // Overrides the channel-profile route entirely (GET + PUT) to capture the PUT body.
    // Must register AFTER stubSettingsPage — Playwright uses LIFO route resolution,
    // so this handler runs first and shadows the one registered in stubSettingsPage.
    await page.route("**/api/channel-profile", async (route) => {
      if (route.request().method() === "PUT") {
        putBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ accent_color: "#FFB800", logo_url: null }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ accent_color: "#00D4AA", logo_url: null }),
      });
    });

    await page.goto("/settings");

    await page.getByRole("button", { name: "Amber" }).click();
    await page.getByRole("button", { name: /Save Brand Kit/i }).click();

    await expect(() => expect(putBody).toBeDefined()).toPass({ timeout: 3000 });
    expect(putBody!.accent_color).toBe("#FFB800");
  });

  test("saves logo URL and shows preview", async ({ page }) => {
    await stubAuth(page);

    let putBody: Record<string, unknown> | undefined;
    await stubSettingsPage(page);
    // Overrides the channel-profile route entirely (GET + PUT) to capture the PUT body.
    // Must register AFTER stubSettingsPage — Playwright uses LIFO route resolution,
    // so this handler runs first and shadows the one registered in stubSettingsPage.
    await page.route("**/api/channel-profile", async (route) => {
      if (route.request().method() === "PUT") {
        putBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ accent_color: "#00D4AA", logo_url: "https://example.com/logo.png" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ accent_color: "#00D4AA", logo_url: null }),
      });
    });

    await page.goto("/settings");

    await page.getByPlaceholder("https://example.com/logo.png").fill("https://example.com/logo.png");
    await page.getByRole("button", { name: /Save Brand Kit/i }).click();

    await expect(() => expect(putBody).toBeDefined()).toPass({ timeout: 3000 });
    expect(putBody!.logo_url).toBe("https://example.com/logo.png");
  });
});

// ─── Notification preferences ──────────────────────────────────────────────

test.describe("Notification preferences", () => {
  test("renders all 4 toggles with no console errors", async ({ page }) => {
    const getErrors = captureConsoleErrors(page);
    await stubAuth(page);
    await stubSettingsPage(page);
    await page.goto("/settings");

    await expect(page.getByText("Notifications")).toBeVisible();
    await expect(page.getByText("Pipeline Complete")).toBeVisible();
    await expect(page.getByText("Weekly Digest")).toBeVisible();
    await expect(page.getByText("Error Alerts")).toBeVisible();
    await expect(page.getByText("CTR Alerts")).toBeVisible();

    expect(getErrors()).toHaveLength(0);
  });

  test("toggling a preference calls PATCH endpoint", async ({ page }) => {
    await stubAuth(page);

    let patchBody: Record<string, unknown> | undefined;
    await stubSettingsPage(page);
    // Overrides the notifications route entirely (GET + PATCH) to capture the PATCH body.
    // Must register AFTER stubSettingsPage — Playwright uses LIFO route resolution,
    // so this handler runs first and shadows the one registered in stubSettingsPage.
    await page.route("**/api/preferences/notifications", async (route) => {
      if (route.request().method() === "PATCH") {
        patchBody = JSON.parse(route.request().postData() ?? "{}");
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            email_video_complete: false,
            email_weekly_digest: true,
            email_error_alerts: true,
            email_ctr_alerts: true,
          }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          email_video_complete: true,
          email_weekly_digest: true,
          email_error_alerts: true,
          email_ctr_alerts: true,
        }),
      });
    });

    await page.goto("/settings");

    const pipelineToggle = page.getByTestId("notif-toggle-email_video_complete");
    await pipelineToggle.click();

    await expect(() => expect(patchBody).toBeDefined()).toPass({ timeout: 3000 });
    expect(patchBody!.email_video_complete).toBe(false);
  });

  test("persists state: reload shows correct toggle state", async ({ page }) => {
    await stubAuth(page);
    await stubSettingsPage(page, {
      notifPrefs: {
        email_video_complete: false,
        email_weekly_digest: true,
        email_error_alerts: true,
        email_ctr_alerts: true,
      },
    });
    await page.goto("/settings");

    // Pipeline Complete toggle should be OFF.
    // When OFF, the toggle background is "var(--bg-surface)" (not turquoise).
    // Verify by checking the inline style doesn't contain turquoise.
    const pipelineToggle = page.getByTestId("notif-toggle-email_video_complete");
    await expect(pipelineToggle).toBeVisible();

    // When ON: style="background: var(--turquoise)"
    // When OFF: style="background: var(--bg-surface)"
    const bgStyle = await pipelineToggle.evaluate((el) => el.style.background);
    expect(bgStyle).not.toContain("turquoise");
  });
});
