const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  console.log('=== Pipeline page card navigation deep dive ===');
  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Get ALL anchor tags on the page
  const allAnchors = await page.evaluate(() => {
    return Array.from(document.querySelectorAll('a')).map(a => ({
      href: a.href,
      text: a.textContent?.substring(0, 60),
      class: a.className?.substring(0, 80)
    }));
  });
  console.log(`  Total <a> tags on page: ${allAnchors.length}`);
  allAnchors.forEach(a => console.log(`    href="${a.href}" text="${a.text?.substring(0, 40)}" class="${a.class?.substring(0, 40)}"`));

  // Check which tab is active
  const activeTab = await page.evaluate(() => {
    const tabs = document.querySelectorAll('button, [role="tab"]');
    return Array.from(tabs).filter(t => {
      const cls = t.className || '';
      return cls.includes('active') || cls.includes('selected') || t.getAttribute('aria-selected') === 'true' ||
             cls.includes('border-b') || cls.includes('text-white');
    }).map(t => t.textContent?.trim());
  });
  console.log(`  Active tabs/buttons: ${JSON.stringify(activeTab)}`);

  // Get all tab buttons at top of pipeline page
  const tabButtons = await page.evaluate(() => {
    const tabs = document.querySelectorAll('button');
    return Array.from(tabs).filter(b => {
      const text = b.textContent?.trim() || '';
      return text.length < 30 && !text.includes('\n');
    }).map(b => ({ text: b.textContent?.trim(), class: b.className?.substring(0, 50) }));
  });
  console.log(`  Tab buttons: ${JSON.stringify(tabButtons.map(t => t.text))}`);

  // Check if there's a "Daily Ideas" or "Production" tab that shows video cards differently
  // Try clicking the first visible card area - use coordinates
  console.log('\n  Trying to click on a video card area...');

  // Find the first video title position
  const titlePosition = await page.evaluate(() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.textContent?.includes("America Can't Stop")) {
        const range = document.createRange();
        range.selectNode(walker.currentNode);
        const rect = range.getBoundingClientRect();
        return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2, text: walker.currentNode.textContent.substring(0, 50) };
      }
    }
    return null;
  });
  console.log(`  Title position: ${JSON.stringify(titlePosition)}`);

  if (titlePosition) {
    const beforeUrl = page.url();
    await page.mouse.click(titlePosition.x, titlePosition.y);
    await page.waitForTimeout(2000);
    const afterUrl = page.url();
    console.log(`  Clicked at (${titlePosition.x}, ${titlePosition.y})`);
    console.log(`  URL before: ${beforeUrl}`);
    console.log(`  URL after:  ${afterUrl}`);

    if (afterUrl !== beforeUrl) {
      console.log('  NAVIGATION WORKS via click!');
    } else {
      // Maybe it's a modal/drawer instead of navigation?
      const bodyAfter = await page.textContent('body');
      const hasDetail = bodyAfter.includes('Research') && bodyAfter.includes('Script') && bodyAfter.includes('Thumbnail');
      console.log(`  No URL change. Detail panel visible: ${hasDetail}`);

      // Try clicking the card area (might be the container div)
      if (titlePosition.y > 0) {
        // Click slightly above the title (card header)
        await page.mouse.click(titlePosition.x, titlePosition.y - 30);
        await page.waitForTimeout(2000);
        const afterUrl2 = page.url();
        console.log(`  After clicking card header: ${afterUrl2}`);
      }
    }
  }

  // Also test the "Daily Ideas" tab vs "In Production" vs "Completed"
  const tabsToCheck = ['Daily Ideas', 'In Production', 'Completed'];
  for (const tabText of tabsToCheck) {
    const tab = page.locator(`button:has-text("${tabText}")`);
    if (await tab.count() > 0) {
      console.log(`\n  Clicking "${tabText}" tab...`);
      await tab.first().click();
      await page.waitForTimeout(2000);

      // Check for links now
      const linksAfter = await page.evaluate(() => {
        return Array.from(document.querySelectorAll('a')).filter(a => a.href.includes('/pipeline/')).map(a => a.href);
      });
      console.log(`    Links to /pipeline/[id]: ${linksAfter.length}`);
      if (linksAfter.length > 0) linksAfter.slice(0, 3).forEach(l => console.log(`      ${l}`));

      // Screenshot this tab
      const main = page.locator('main');
      if (await main.count() > 0) {
        await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-pipeline-tab-${tabText.toLowerCase().replace(/\s/g, '-')}.png` });
      }
    }
  }

  await browser.close();
})();
