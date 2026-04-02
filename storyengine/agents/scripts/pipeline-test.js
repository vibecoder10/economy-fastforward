const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';

const PAGES = [
  { name: 'dashboard', path: '/' },
  { name: 'pipeline', path: '/pipeline' },
  { name: 'autopilot', path: '/autopilot' },
  { name: 'competitors', path: '/competitors' },
  { name: 'analytics', path: '/analytics' },
  { name: 'profile', path: '/profile' },
  { name: 'settings', path: '/settings' },
  { name: 'settings-keys', path: '/settings/keys' },
];

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  const results = [];

  for (const pg of PAGES) {
    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    try {
      console.log(`\n--- Testing ${pg.name} (${pg.path}) ---`);
      const response = await page.goto(`${BASE}${pg.path}`, { timeout: 15000 });
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

      const status = response ? response.status() : 'no response';
      const bodyText = await page.textContent('body').catch(() => '');
      const hasContent = bodyText && bodyText.length > 100;

      // Try to screenshot main content area
      const main = page.locator('main');
      if (await main.count() > 0) {
        await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-${pg.name}.png` });
      } else {
        await page.screenshot({ path: `${SCREENSHOT_DIR}/pt-${pg.name}.png` });
      }

      // Filter out noise errors
      const realErrors = errors.filter(e =>
        !e.includes('favicon') &&
        !e.includes('Failed to load resource') &&
        !e.includes('hydration') &&
        !e.includes('Download the React DevTools')
      );

      const result = {
        page: pg.name,
        path: pg.path,
        status,
        hasContent,
        consoleErrors: realErrors.length,
        errors: realErrors.slice(0, 3),
        pass: status === 200 && hasContent && realErrors.length === 0
      };

      results.push(result);
      console.log(`  Status: ${status}, Content: ${hasContent}, Errors: ${realErrors.length}, PASS: ${result.pass}`);
      if (realErrors.length > 0) {
        realErrors.slice(0, 3).forEach(e => console.log(`  ERROR: ${e.substring(0, 150)}`));
      }
    } catch (err) {
      results.push({ page: pg.name, path: pg.path, status: 'TIMEOUT', hasContent: false, consoleErrors: 0, errors: [err.message], pass: false });
      console.log(`  FAILED: ${err.message.substring(0, 100)}`);
    }

    // Remove console listener for next page
    page.removeAllListeners('console');
  }

  // Now test a video detail page
  console.log('\n--- Finding a video to test detail page ---');
  const errors2 = [];
  page.on('console', msg => { if (msg.type() === 'error') errors2.push(msg.text()); });

  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Find and click a video link
  const videoLinks = page.locator('a[href^="/pipeline/"]');
  const linkCount = await videoLinks.count();
  console.log(`  Found ${linkCount} video links on pipeline page`);

  let videoId = null;
  if (linkCount > 0) {
    const href = await videoLinks.first().getAttribute('href');
    videoId = href.replace('/pipeline/', '');
    console.log(`  Testing video: ${videoId}`);

    await videoLinks.first().click();
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

    const main = page.locator('main');
    if (await main.count() > 0) {
      await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-video-detail.png` });
    }

    const realErrors = errors2.filter(e =>
      !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('hydration') && !e.includes('Download the React DevTools')
    );

    results.push({
      page: 'video-detail',
      path: `/pipeline/${videoId}`,
      status: 200,
      hasContent: true,
      consoleErrors: realErrors.length,
      errors: realErrors.slice(0, 3),
      pass: realErrors.length === 0
    });
    console.log(`  Video detail - Errors: ${realErrors.length}, PASS: ${realErrors.length === 0}`);

    // Test each tab on the video detail page
    const tabs = ['Script', 'Storyboard', 'Visuals', 'Thumbnail', 'Render', 'Performance'];
    for (const tabName of tabs) {
      page.removeAllListeners('console');
      const tabErrors = [];
      page.on('console', msg => { if (msg.type() === 'error') tabErrors.push(msg.text()); });

      const tab = page.locator(`button, [role="tab"], a`).filter({ hasText: new RegExp(`^${tabName}$`, 'i') });
      if (await tab.count() > 0) {
        await tab.first().click();
        await page.waitForTimeout(2000);
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

        const main2 = page.locator('main');
        if (await main2.count() > 0) {
          await main2.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-tab-${tabName.toLowerCase()}.png` });
        }

        const tabRealErrors = tabErrors.filter(e =>
          !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('hydration') && !e.includes('Download the React DevTools')
        );

        results.push({
          page: `tab-${tabName.toLowerCase()}`,
          path: `${tabName} tab`,
          status: 200,
          hasContent: true,
          consoleErrors: tabRealErrors.length,
          errors: tabRealErrors.slice(0, 3),
          pass: tabRealErrors.length === 0
        });
        console.log(`  Tab ${tabName}: Errors: ${tabRealErrors.length}, PASS: ${tabRealErrors.length === 0}`);
        if (tabRealErrors.length > 0) {
          tabRealErrors.slice(0, 3).forEach(e => console.log(`    ERROR: ${e.substring(0, 150)}`));
        }
      } else {
        console.log(`  Tab ${tabName}: NOT FOUND`);
        results.push({ page: `tab-${tabName.toLowerCase()}`, path: `${tabName} tab`, status: 'NOT_FOUND', hasContent: false, consoleErrors: 0, errors: ['Tab button not found'], pass: false });
      }
    }
  }

  // Summary
  console.log('\n\n=== PIPELINE TEST SUMMARY ===');
  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass).length;
  console.log(`Total: ${results.length} | PASS: ${passed} | FAIL: ${failed}`);
  console.log('');
  results.forEach(r => {
    const icon = r.pass ? 'PASS' : 'FAIL';
    console.log(`  [${icon}] ${r.page} (${r.path}) — status:${r.status}, content:${r.hasContent}, errors:${r.consoleErrors}`);
    if (!r.pass && r.errors.length > 0) {
      r.errors.forEach(e => console.log(`         ${e.substring(0, 120)}`));
    }
  });

  await browser.close();

  // Write results JSON
  const fs = require('fs');
  fs.writeFileSync(`${SCREENSHOT_DIR}/test-results.json`, JSON.stringify(results, null, 2));
  console.log(`\nResults written to ${SCREENSHOT_DIR}/test-results.json`);
})();
