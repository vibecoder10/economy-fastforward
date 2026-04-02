const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';
const VIDEO_ID = 'f9749bd2-5045-42a5-b90e-ecd253bd7c20';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  // ====== TEST: Settings/Keys page ======
  console.log('=== Settings/Keys page ===');
  const keysErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') keysErrors.push(msg.text()); });

  await page.goto(`${BASE}/settings/keys`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const main = page.locator('main');
  if (await main.count() > 0) {
    await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-settings-keys.png` });
  }

  const cleanKeysErrors = keysErrors.filter(e => !e.includes('favicon') && !e.includes('DevTools'));
  console.log(`  Console errors: ${cleanKeysErrors.length}`);
  cleanKeysErrors.forEach(e => console.log(`    ${e.substring(0, 150)}`));

  // ====== TEST: Video detail - Visuals tab with images ======
  console.log('\n=== Video detail - Visuals tab deep check ===');
  page.removeAllListeners('console');
  const visualErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') visualErrors.push(msg.text()); });

  await page.goto(`${BASE}/pipeline/${VIDEO_ID}`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Click Storyboard & Visuals tab
  const visualsTab = page.locator('button:has-text("Storyboard & Visuals")');
  if (await visualsTab.count() > 0) {
    await visualsTab.first().click();
    await page.waitForTimeout(2000);
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});

    // Check for image elements
    const imageInfo = await page.evaluate(() => {
      const imgs = document.querySelectorAll('img');
      return {
        total: imgs.length,
        withSrc: Array.from(imgs).filter(i => i.src && !i.src.includes('data:') && !i.src.includes('favicon')).length,
        brokenCount: Array.from(imgs).filter(i => i.naturalWidth === 0 && i.complete).length,
        samples: Array.from(imgs).slice(0, 5).map(i => ({
          src: i.src?.substring(0, 80),
          alt: i.alt?.substring(0, 30),
          width: i.naturalWidth,
          height: i.naturalHeight,
          loaded: i.complete && i.naturalWidth > 0
        }))
      };
    });
    console.log(`  Images on page: ${imageInfo.total} (with src: ${imageInfo.withSrc}, broken: ${imageInfo.brokenCount})`);
    imageInfo.samples.forEach(s => console.log(`    ${s.loaded ? 'OK' : 'BROKEN'} ${s.width}x${s.height} src="${s.src}"`));

    // Check for buttons
    const buttons = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('button')).filter(b => {
        const t = b.textContent?.trim() || '';
        return t.includes('Generate') || t.includes('Regen') || t.includes('Variant') || t.includes('Approve');
      }).map(b => ({ text: b.textContent?.trim().substring(0, 40), disabled: b.disabled }));
    });
    console.log(`  Action buttons: ${JSON.stringify(buttons)}`);
  }

  const cleanVisualErrors = visualErrors.filter(e => !e.includes('favicon') && !e.includes('DevTools') && !e.includes('Failed to load resource'));
  console.log(`  Console errors: ${cleanVisualErrors.length}`);

  // ====== TEST: Thumbnail tab deep check ======
  console.log('\n=== Video detail - Thumbnail tab deep check ===');
  page.removeAllListeners('console');
  const thumbErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') thumbErrors.push(msg.text()); });

  const thumbTab = page.locator('button:has-text("Thumbnail")');
  if (await thumbTab.count() > 0) {
    await thumbTab.first().click();
    await page.waitForTimeout(2000);

    if (await main.count() > 0) {
      await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-thumb-detail.png` });
    }

    // Check for generate button
    const genBtn = page.locator('button:has-text("Generate Thumbnail")');
    const regenBtn = page.locator('button:has-text("Regenerate")');
    console.log(`  "Generate Thumbnail" button: ${await genBtn.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);
    console.log(`  "Regenerate" button: ${await regenBtn.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);

    // Check for prompt textarea
    const textarea = page.locator('textarea');
    const textareaCount = await textarea.count();
    console.log(`  Textareas (prompt editor): ${textareaCount}`);
  }

  // ====== TEST: Render tab deep check ======
  console.log('\n=== Video detail - Render tab deep check ===');
  const renderTab = page.locator('button:has-text("Render")');
  if (await renderTab.count() > 0) {
    await renderTab.first().click();
    await page.waitForTimeout(2000);

    if (await main.count() > 0) {
      await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-render-detail.png` });
    }

    const renderBtn = page.locator('button:has-text("Render Now")');
    console.log(`  "Render Now" button: ${await renderBtn.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);
  }

  // ====== TEST: Research tab buttons ======
  console.log('\n=== Video detail - Research tab actions ===');
  const researchTab = page.locator('button:has-text("Research")');
  if (await researchTab.count() > 0) {
    await researchTab.first().click();
    await page.waitForTimeout(2000);

    const approveBtn = page.locator('button:has-text("Approve Research")');
    const regenResearch = page.locator('button:has-text("Regenerate Research")');
    const requestChanges = page.locator('button:has-text("Request Changes")');
    console.log(`  "Approve Research": ${await approveBtn.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);
    console.log(`  "Regenerate Research": ${await regenResearch.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);
    console.log(`  "Request Changes": ${await requestChanges.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);

    // Check for expandable sections (Framework Analysis, Counter Arguments, Sources)
    const expandSections = ['Framework Analysis', 'Counter Arguments', 'Sources'];
    for (const section of expandSections) {
      const el = page.locator(`button:has-text("${section}")`);
      console.log(`  "${section}" section: ${await el.count() > 0 ? 'FOUND' : 'NOT FOUND'}`);
    }
  }

  // ====== TEST: Dashboard activity feed ======
  console.log('\n=== Dashboard activity feed ===');
  page.removeAllListeners('console');
  const dashErrors = [];
  page.on('console', msg => { if (msg.type() === 'error') dashErrors.push(msg.text()); });

  await page.goto(`${BASE}/`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  const activityItems = await page.evaluate(() => {
    const items = document.querySelectorAll('[class*="activity"], [class*="feed"], li, [class*="event"]');
    return Array.from(items).filter(i => i.textContent && i.textContent.length > 20 && i.textContent.length < 200)
      .slice(0, 5).map(i => i.textContent?.trim().substring(0, 80));
  });
  console.log(`  Activity items: ${activityItems.length}`);
  activityItems.forEach(a => console.log(`    ${a}`));

  const cleanDashErrors = dashErrors.filter(e => !e.includes('favicon') && !e.includes('DevTools'));
  console.log(`  Console errors: ${cleanDashErrors.length}`);

  await browser.close();
  console.log('\n=== FINAL TESTS COMPLETE ===');
})();
