const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const results = [];

  // Go to pipeline page and find video links
  console.log('--- Finding video links on /pipeline ---');
  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Get all links and find ones that go to video details
  const allLinks = await page.locator('a').all();
  const videoHrefs = [];
  for (const link of allLinks) {
    const href = await link.getAttribute('href').catch(() => null);
    if (href && href.match(/\/pipeline\/[a-f0-9-]+/)) {
      videoHrefs.push(href);
    }
  }
  console.log(`  Found ${videoHrefs.length} video detail links`);

  // If no links found, try clicking a card directly
  if (videoHrefs.length === 0) {
    // Look for clickable cards
    const cards = page.locator('[class*="card"], [class*="Card"], [role="link"], [data-video-id]');
    const cardCount = await cards.count();
    console.log(`  Found ${cardCount} card-like elements`);

    // Try to find any link on the page
    const allHrefs = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('/pipeline/'));
    });
    console.log(`  All pipeline hrefs: ${JSON.stringify(allHrefs.slice(0, 5))}`);

    // Try clicking the first video card
    const clickableCards = page.locator('article, [class*="cursor-pointer"]').first();
    if (await clickableCards.count() > 0) {
      console.log('  Clicking first clickable card...');
      await clickableCards.click();
      await page.waitForTimeout(2000);
      const url = page.url();
      console.log(`  Navigated to: ${url}`);
      if (url.includes('/pipeline/')) {
        videoHrefs.push(url.replace(BASE, ''));
      }
    }
  }

  // If we still have no video hrefs, try the API directly
  if (videoHrefs.length === 0) {
    console.log('  Trying API to find video IDs...');
    const apiResp = await page.evaluate(async () => {
      try {
        const resp = await fetch('/api/videos?limit=3');
        const data = await resp.json();
        return data;
      } catch(e) {
        return { error: e.message };
      }
    });
    console.log(`  API response: ${JSON.stringify(apiResp).substring(0, 300)}`);

    if (Array.isArray(apiResp) && apiResp.length > 0) {
      videoHrefs.push(`/pipeline/${apiResp[0].id}`);
    } else if (apiResp && apiResp.videos && apiResp.videos.length > 0) {
      videoHrefs.push(`/pipeline/${apiResp.videos[0].id}`);
    }
  }

  if (videoHrefs.length === 0) {
    console.log('  NO VIDEOS FOUND - cannot test detail page');
    await browser.close();
    return;
  }

  // Test the first video detail page
  const videoPath = videoHrefs[0];
  console.log(`\n--- Testing video detail: ${videoPath} ---`);

  const detailErrors = [];
  page.removeAllListeners('console');
  page.on('console', msg => { if (msg.type() === 'error') detailErrors.push(msg.text()); });

  await page.goto(`${BASE}${videoPath}`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const main = page.locator('main');
  if (await main.count() > 0) {
    await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-video-detail.png` });
  } else {
    await page.screenshot({ path: `${SCREENSHOT_DIR}/pt-video-detail.png` });
  }

  const bodyText = await page.textContent('body').catch(() => '');
  console.log(`  Page loaded. Body length: ${bodyText.length}`);
  console.log(`  Console errors: ${detailErrors.filter(e => !e.includes('favicon') && !e.includes('Download the React DevTools')).length}`);

  // Find all tab buttons
  const tabButtons = await page.evaluate(() => {
    const buttons = Array.from(document.querySelectorAll('button, [role="tab"]'));
    return buttons.map(b => ({ text: b.textContent?.trim(), tagName: b.tagName })).filter(b => b.text && b.text.length < 30);
  });
  console.log(`  Tab-like buttons found: ${JSON.stringify(tabButtons.map(t => t.text))}`);

  // Test each tab
  const tabNames = ['Info', 'Script', 'Storyboard', 'Visuals', 'Thumbnail', 'Render', 'Performance'];

  for (const tabName of tabNames) {
    page.removeAllListeners('console');
    const tabErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') tabErrors.push(msg.text()); });

    // Try multiple selectors for the tab
    let tab = page.locator(`button:has-text("${tabName}")`);
    if (await tab.count() === 0) {
      tab = page.locator(`[role="tab"]:has-text("${tabName}")`);
    }
    if (await tab.count() === 0) {
      tab = page.getByText(tabName, { exact: true });
    }

    const count = await tab.count();
    if (count > 0) {
      await tab.first().click();
      await page.waitForTimeout(2000);
      await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

      if (await main.count() > 0) {
        await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-tab-${tabName.toLowerCase()}.png` });
      }

      const realErrors = tabErrors.filter(e =>
        !e.includes('favicon') && !e.includes('Failed to load resource') && !e.includes('hydration') && !e.includes('Download the React DevTools')
      );

      const pass = realErrors.length === 0;
      results.push({ tab: tabName, found: true, errors: realErrors.length, pass, errorMessages: realErrors.slice(0, 3) });
      console.log(`  Tab ${tabName}: FOUND, Errors: ${realErrors.length}, ${pass ? 'PASS' : 'FAIL'}`);
      if (realErrors.length > 0) {
        realErrors.slice(0, 3).forEach(e => console.log(`    ERROR: ${e.substring(0, 150)}`));
      }
    } else {
      results.push({ tab: tabName, found: false, errors: 0, pass: false, errorMessages: ['Tab not found'] });
      console.log(`  Tab ${tabName}: NOT FOUND`);
    }
  }

  // Summary
  console.log('\n=== VIDEO DETAIL TAB SUMMARY ===');
  const passed = results.filter(r => r.pass).length;
  const failed = results.filter(r => !r.pass).length;
  console.log(`Total: ${results.length} | PASS: ${passed} | FAIL: ${failed}`);
  results.forEach(r => {
    const icon = r.pass ? 'PASS' : 'FAIL';
    console.log(`  [${icon}] ${r.tab} — found:${r.found}, errors:${r.errors}`);
    if (r.errorMessages.length > 0 && !r.pass) {
      r.errorMessages.forEach(e => console.log(`         ${e.substring(0, 120)}`));
    }
  });

  await browser.close();

  const fs = require('fs');
  fs.writeFileSync(`${SCREENSHOT_DIR}/tab-results.json`, JSON.stringify(results, null, 2));
})();
