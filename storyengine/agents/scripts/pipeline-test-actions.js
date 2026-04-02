const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';
const VIDEO_ID = 'f9749bd2-5045-42a5-b90e-ecd253bd7c20';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  const bugs = [];

  // ====== TEST 1: Pipeline page card navigation ======
  console.log('=== TEST 1: Pipeline page card navigation ===');
  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Check how cards are structured
  const cardStructure = await page.evaluate(() => {
    // Find elements containing video titles
    const allElements = document.querySelectorAll('*');
    const titleEls = [];
    for (const el of allElements) {
      if (el.textContent?.includes("America Can't Stop") && el.children.length < 3 && el.textContent.length < 100) {
        titleEls.push({
          tag: el.tagName,
          class: el.className?.substring(0, 80),
          parentTag: el.parentElement?.tagName,
          parentClass: el.parentElement?.className?.substring(0, 80),
          gpTag: el.parentElement?.parentElement?.tagName,
          gpClass: el.parentElement?.parentElement?.className?.substring(0, 80),
          hasOnClick: !!el.onclick || !!el.parentElement?.onclick,
          hasHref: el.getAttribute('href') || el.parentElement?.getAttribute('href'),
          role: el.getAttribute('role') || el.parentElement?.getAttribute('role')
        });
      }
    }
    return titleEls.slice(0, 3);
  });
  console.log('  Card structure:', JSON.stringify(cardStructure, null, 2));

  // Check if there are Next.js Link components (they render as <a>)
  const links = await page.evaluate(() => {
    const anchors = Array.from(document.querySelectorAll('a'));
    return anchors.map(a => ({ href: a.href, text: a.textContent?.substring(0, 60) }))
      .filter(a => a.href.includes('/pipeline/'));
  });
  console.log(`  Links to /pipeline/[id]: ${links.length}`);
  if (links.length > 0) {
    links.slice(0, 3).forEach(l => console.log(`    ${l.href} — "${l.text?.substring(0, 40)}"`));
  } else {
    console.log('  BUG: No clickable links to navigate from pipeline list to video detail!');
    bugs.push({
      id: 'BUG-PT-001',
      title: 'BUG: Pipeline page video cards are not clickable links',
      description: 'Pipeline page shows video cards but they are not wrapped in <a> or Next.js <Link> components. Users cannot click a video card to navigate to its detail page. Must type the URL manually.',
      severity: 'high'
    });
  }

  // ====== TEST 2: Video detail action buttons ======
  console.log('\n=== TEST 2: Video detail action buttons ===');
  await page.goto(`${BASE}/pipeline/${VIDEO_ID}`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Check "Run Next Step" button
  const runNextStep = page.locator('button:has-text("Run Next Step")');
  if (await runNextStep.count() > 0) {
    console.log('  "Run Next Step" button: FOUND');
    // Take before screenshot
    const main = page.locator('main');

    // Check what status badge shows
    const statusText = await page.evaluate(() => {
      const badges = document.querySelectorAll('[class*="badge"], [class*="status"], [class*="pill"]');
      return Array.from(badges).map(b => b.textContent?.trim()).filter(t => t && t.length < 30);
    });
    console.log(`  Status badges: ${JSON.stringify(statusText)}`);
  } else {
    console.log('  "Run Next Step" button: NOT FOUND');
  }

  // Check "Skip Stage" button
  const skipStage = page.locator('button:has-text("Skip Stage")');
  console.log(`  "Skip Stage" button: ${await skipStage.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);

  // ====== TEST 3: Autopilot toggle ======
  console.log('\n=== TEST 3: Autopilot page toggle ===');
  const autopilotErrors = [];
  page.removeAllListeners('console');
  page.on('console', msg => { if (msg.type() === 'error') autopilotErrors.push(msg.text()); });

  await page.goto(`${BASE}/autopilot`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Find toggle switch
  const toggles = await page.evaluate(() => {
    const inputs = document.querySelectorAll('input[type="checkbox"], [role="switch"], button[aria-checked]');
    return Array.from(inputs).map(i => ({
      tag: i.tagName,
      type: i.type,
      checked: i.checked || i.getAttribute('aria-checked'),
      label: i.labels?.[0]?.textContent || i.getAttribute('aria-label') || ''
    }));
  });
  console.log(`  Toggles found: ${toggles.length}`);
  toggles.forEach(t => console.log(`    ${t.tag} checked=${t.checked} label="${t.label}"`));

  const cleanErrors = autopilotErrors.filter(e => !e.includes('favicon') && !e.includes('Download the React DevTools'));
  if (cleanErrors.length > 0) {
    console.log(`  Autopilot errors: ${cleanErrors.length}`);
    cleanErrors.forEach(e => console.log(`    ${e.substring(0, 150)}`));
  }

  // ====== TEST 4: Competitors scrape button ======
  console.log('\n=== TEST 4: Competitors page scrape button ===');
  await page.goto(`${BASE}/competitors`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const scrapeBtn = page.locator('button:has-text("Scrape"), button:has-text("Refresh"), button:has-text("Scan")');
  const scrapeBtnCount = await scrapeBtn.count();
  console.log(`  Scrape/Refresh buttons: ${scrapeBtnCount}`);
  if (scrapeBtnCount > 0) {
    const btnTexts = [];
    for (let i = 0; i < Math.min(scrapeBtnCount, 5); i++) {
      btnTexts.push(await scrapeBtn.nth(i).textContent());
    }
    console.log(`  Button texts: ${JSON.stringify(btnTexts)}`);
  }

  // ====== TEST 5: Analytics YouTube Sync ======
  console.log('\n=== TEST 5: Analytics YouTube Sync button ===');
  await page.goto(`${BASE}/analytics`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const syncBtn = page.locator('button:has-text("Sync"), button:has-text("YouTube")');
  const syncBtnCount = await syncBtn.count();
  console.log(`  Sync buttons: ${syncBtnCount}`);
  if (syncBtnCount > 0) {
    for (let i = 0; i < Math.min(syncBtnCount, 3); i++) {
      console.log(`    "${await syncBtn.nth(i).textContent()}"`);
    }
  }

  // ====== TEST 6: Profile page edit ======
  console.log('\n=== TEST 6: Profile page edit ===');
  await page.goto(`${BASE}/profile`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const editBtn = page.locator('button:has-text("Edit")');
  console.log(`  Edit button: ${await editBtn.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);

  const profileMain = page.locator('main');
  if (await profileMain.count() > 0) {
    await profileMain.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-profile-detail.png` });
  }

  // Summary
  console.log('\n\n=== ACTION TEST SUMMARY ===');
  console.log(`Bugs found: ${bugs.length}`);
  bugs.forEach(b => console.log(`  ${b.id}: ${b.title}`));

  await browser.close();

  const fs = require('fs');
  fs.writeFileSync(`${SCREENSHOT_DIR}/action-results.json`, JSON.stringify({ bugs, tests: 6 }, null, 2));
})();
