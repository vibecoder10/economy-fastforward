const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';
const VIDEO_ID = 'f9749bd2-5045-42a5-b90e-ecd253bd7c20';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const allResults = [];

  // Go directly to video detail page
  console.log(`--- Testing video detail: /pipeline/${VIDEO_ID} ---`);

  const pageErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') pageErrors.push(msg.text()); });

  await page.goto(`${BASE}/pipeline/${VIDEO_ID}`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const main = page.locator('main');
  if (await main.count() > 0) {
    await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-video-detail.png` });
  }

  // Log page title and check for 404/error
  const title = await page.title();
  const bodyText = await page.textContent('body').catch(() => '');
  console.log(`  Title: ${title}`);
  console.log(`  Body length: ${bodyText.length}`);
  console.log(`  Has "not found": ${bodyText.toLowerCase().includes('not found')}`);
  console.log(`  Has error text: ${bodyText.toLowerCase().includes('error')}`);

  const cleanErrors = pageErrors.filter(e =>
    !e.includes('favicon') && !e.includes('Download the React DevTools')
  );
  console.log(`  Console errors: ${cleanErrors.length}`);
  cleanErrors.slice(0, 5).forEach(e => console.log(`    ${e.substring(0, 150)}`));

  // Find all interactive elements (buttons, tabs)
  const interactiveElements = await page.evaluate(() => {
    const els = Array.from(document.querySelectorAll('button, [role="tab"], [role="tablist"] > *'));
    return els.map(el => ({
      text: el.textContent?.trim().substring(0, 50),
      tag: el.tagName,
      role: el.getAttribute('role'),
      class: el.className?.substring(0, 80)
    }));
  });
  console.log(`\n  Interactive elements (${interactiveElements.length}):`);
  interactiveElements.filter(e => e.text && e.text.length < 30).forEach(e => {
    console.log(`    [${e.tag}${e.role ? ' role=' + e.role : ''}] "${e.text}"`);
  });

  // Try to find tabs specifically
  const tabNames = ['Info', 'Script', 'Storyboard', 'Visuals', 'Thumbnail', 'Render', 'Performance'];

  for (const tabName of tabNames) {
    page.removeAllListeners('console');
    const tabErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') tabErrors.push(msg.text()); });

    // Try multiple approaches
    let clicked = false;
    for (const selector of [
      `text="${tabName}"`,
      `button:has-text("${tabName}")`,
      `[role="tab"]:has-text("${tabName}")`,
      `div:has-text("${tabName}") >> nth=0`
    ]) {
      try {
        const el = page.locator(selector);
        if (await el.count() > 0) {
          await el.first().click({ timeout: 3000 });
          clicked = true;
          break;
        }
      } catch(e) {}
    }

    if (clicked) {
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

      if (await main.count() > 0) {
        await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-tab-${tabName.toLowerCase()}.png` });
      }

      const realErrors = tabErrors.filter(e =>
        !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('hydration') && !e.includes('Download the React DevTools')
      );

      allResults.push({ tab: tabName, found: true, clicked: true, errors: realErrors.length, pass: realErrors.length === 0, errorMsgs: realErrors.slice(0, 3) });
      console.log(`\n  Tab ${tabName}: CLICKED, Errors: ${realErrors.length}, ${realErrors.length === 0 ? 'PASS' : 'FAIL'}`);
      if (realErrors.length > 0) realErrors.slice(0, 3).forEach(e => console.log(`    ERROR: ${e.substring(0, 150)}`));
    } else {
      allResults.push({ tab: tabName, found: false, clicked: false, errors: 0, pass: false, errorMsgs: ['Tab not found'] });
      console.log(`\n  Tab ${tabName}: NOT FOUND`);
    }
  }

  // Now test the pipeline page navigation - can we click into a video?
  console.log('\n--- Testing pipeline page navigation ---');
  page.removeAllListeners('console');
  const navErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') navErrors.push(msg.text()); });

  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Check for clickable elements that might navigate to video
  const clickableCount = await page.locator('[class*="cursor-pointer"]').count();
  console.log(`  Cursor-pointer elements: ${clickableCount}`);

  // Try clicking the first card-like element
  const firstCard = page.locator('[class*="cursor-pointer"]').first();
  if (await firstCard.count() > 0) {
    const beforeUrl = page.url();
    await firstCard.click();
    await page.waitForTimeout(2000);
    const afterUrl = page.url();
    console.log(`  Before: ${beforeUrl}`);
    console.log(`  After:  ${afterUrl}`);
    console.log(`  Navigated: ${beforeUrl !== afterUrl}`);

    if (afterUrl.includes('/pipeline/')) {
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
      if (await main.count() > 0) {
        await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-nav-to-video.png` });
      }
      console.log(`  Navigation to video detail: PASS`);
    }
  }

  // Summary
  console.log('\n\n=== TAB TEST SUMMARY ===');
  const passed = allResults.filter(r => r.pass).length;
  const failed = allResults.filter(r => !r.pass).length;
  console.log(`Total: ${allResults.length} | PASS: ${passed} | FAIL: ${failed}`);
  allResults.forEach(r => {
    console.log(`  [${r.pass ? 'PASS' : 'FAIL'}] ${r.tab} — found:${r.found}, errors:${r.errors}`);
  });

  await browser.close();

  const fs = require('fs');
  fs.writeFileSync(`${SCREENSHOT_DIR}/tab-results.json`, JSON.stringify(allResults, null, 2));
})();
