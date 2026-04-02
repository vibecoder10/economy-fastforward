const { chromium } = require('playwright');

const BASE = 'http://localhost:3001';
const SCREENSHOT_DIR = 'storyengine/agents/screenshots';

(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();

  // ====== BUG INVESTIGATION 1: Pipeline card navigation ======
  console.log('=== INVESTIGATE: Pipeline card clickability ===');

  const networkRequests = [];
  page.on('request', req => {
    if (req.url().includes('/api/')) networkRequests.push(req.url());
  });

  await page.goto(`${BASE}/pipeline`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Get the full HTML of the first card to understand structure
  const cardHtml = await page.evaluate(() => {
    // Find elements that contain video titles
    const h3s = document.querySelectorAll('h3, h2, [class*="title"]');
    for (const h of h3s) {
      if (h.textContent?.includes("America")) {
        // Walk up to find the card container
        let el = h;
        for (let i = 0; i < 5; i++) {
          el = el.parentElement;
          if (!el) break;
        }
        if (el) {
          return {
            outerHTML: el.outerHTML.substring(0, 500),
            tagName: el.tagName,
            hasOnClick: el.hasAttribute('onclick'),
            role: el.getAttribute('role'),
            tabIndex: el.getAttribute('tabindex'),
            // Check for Next.js router events via data attributes
            dataAttrs: Array.from(el.attributes).filter(a => a.name.startsWith('data-')).map(a => `${a.name}=${a.value}`)
          };
        }
      }
    }
    return null;
  });
  console.log('  Card structure:', JSON.stringify(cardHtml, null, 2));

  // Check if clicking a card title navigates
  const titleEl = page.locator('h3:has-text("America"), h2:has-text("America"), p:has-text("America Can")').first();
  if (await titleEl.count() > 0) {
    const beforeUrl = page.url();
    console.log('  Clicking title text...');
    await titleEl.click();
    await page.waitForTimeout(2000);
    const afterUrl = page.url();
    console.log(`  Before: ${beforeUrl}`);
    console.log(`  After:  ${afterUrl}`);
    if (beforeUrl === afterUrl) {
      console.log('  CONFIRMED BUG: Clicking video title does NOT navigate to detail page');
    } else {
      console.log('  Navigation works via click (React onClick handler, not <a> tag)');
    }
  }

  // ====== BUG INVESTIGATION 2: Profile loading ======
  console.log('\n=== INVESTIGATE: Profile loading issue ===');

  const profileErrors = [];
  const profileRequests = [];
  page.removeAllListeners('console');
  page.removeAllListeners('request');

  page.on('console', msg => {
    if (msg.type() === 'error') profileErrors.push(msg.text());
  });
  page.on('requestfailed', req => {
    profileRequests.push({ url: req.url(), failure: req.failure()?.errorText });
  });
  page.on('response', resp => {
    if (resp.url().includes('/api/profile')) {
      profileRequests.push({ url: resp.url(), status: resp.status() });
    }
  });

  await page.goto(`${BASE}/profile`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Wait extra time for profile to load
  await page.waitForTimeout(3000);

  console.log('  Profile API requests:', JSON.stringify(profileRequests));
  console.log('  Console errors:', profileErrors.filter(e => !e.includes('favicon') && !e.includes('DevTools')).length);
  profileErrors.filter(e => !e.includes('favicon') && !e.includes('DevTools')).forEach(e =>
    console.log(`    ${e.substring(0, 200)}`)
  );

  // Check if "Loading profile..." still shows
  const loadingText = await page.locator('text="Loading profile"').count();
  console.log(`  "Loading profile..." still visible: ${loadingText > 0}`);

  // Check what the profile API returns
  const profileApiCheck = await page.evaluate(async () => {
    try {
      const resp = await fetch('/api/profile', {
        headers: { 'Authorization': 'Bearer dev-token' }
      });
      return { status: resp.status, body: await resp.text().then(t => t.substring(0, 300)) };
    } catch(e) {
      return { error: e.message };
    }
  });
  console.log('  Profile API from browser:', JSON.stringify(profileApiCheck));

  // Screenshot the profile page after waiting
  const main = page.locator('main');
  if (await main.count() > 0) {
    await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-profile-after-wait.png` });
  }

  // ====== BUG INVESTIGATION 3: Autopilot toggle ======
  console.log('\n=== INVESTIGATE: Autopilot toggle ===');

  await page.goto(`${BASE}/autopilot`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Find all buttons and check for toggle-like ones
  const toggleButtons = await page.evaluate(() => {
    const buttons = document.querySelectorAll('button');
    return Array.from(buttons)
      .filter(b => {
        const text = b.textContent?.toLowerCase() || '';
        return text.includes('on') || text.includes('off') || text.includes('toggle') ||
               text.includes('enable') || text.includes('disable');
      })
      .map(b => ({
        text: b.textContent?.trim(),
        class: b.className?.substring(0, 100),
        ariaChecked: b.getAttribute('aria-checked'),
        disabled: b.disabled
      }));
  });
  console.log('  Toggle-like buttons:', JSON.stringify(toggleButtons));

  // ====== INVESTIGATE: Dashboard content ======
  console.log('\n=== INVESTIGATE: Dashboard content ===');
  await page.goto(`${BASE}/`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  // Check stat cards
  const stats = await page.evaluate(() => {
    const cards = document.querySelectorAll('[class*="stat"], [class*="card"], [class*="metric"]');
    return Array.from(cards).slice(0, 10).map(c => c.textContent?.trim().substring(0, 80));
  });
  console.log('  Dashboard stat elements:', stats.length);
  stats.forEach(s => console.log(`    ${s}`));

  // ====== INVESTIGATE: Settings page ======
  console.log('\n=== INVESTIGATE: Settings page ===');
  await page.goto(`${BASE}/settings`, { timeout: 15000 });
  await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});

  if (await main.count() > 0) {
    await main.first().screenshot({ path: `${SCREENSHOT_DIR}/pt-settings-detail.png` });
  }

  const settingsContent = await page.evaluate(() => {
    const forms = document.querySelectorAll('form, input, select, textarea');
    return Array.from(forms).slice(0, 10).map(f => ({
      tag: f.tagName,
      type: f.type || '',
      name: f.name || '',
      placeholder: f.placeholder || '',
      value: f.value?.substring(0, 30) || ''
    }));
  });
  console.log('  Form elements:', JSON.stringify(settingsContent));

  await browser.close();
  console.log('\n=== DEEP INVESTIGATION COMPLETE ===');
})();
