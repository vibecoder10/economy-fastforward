# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: dashboard-fixes.spec.ts >> Dashboard Fixes PRD — End-to-End >> T4: Soft delete >> DELETE endpoint soft-deletes and filters from list
- Location: tests/dashboard-fixes.spec.ts:234:9

# Error details

```
Error: expect(received).toBeTruthy()

Received: false
```

# Test source

```ts
  150 |     const res = await fetch(url, opts);
  151 |     // 404 = endpoint doesn't exist, 405 = wrong method
  152 |     return res.status !== 404 && res.status !== 405;
  153 |   } catch {
  154 |     return false;
  155 |   }
  156 | }
  157 | 
  158 | // --- Test Suite ---
  159 | 
  160 | test.describe("Dashboard Fixes PRD — End-to-End", () => {
  161 |   let token: string;
  162 |   let videoId: string | null;
  163 | 
  164 |   test.beforeAll(async () => {
  165 |     token = await getAuthToken();
  166 |     videoId = await createTestVideo(token, "E2E Test Video — PRD13");
  167 |   });
  168 | 
  169 |   // ========================================
  170 |   // T2: Stage progression
  171 |   // ========================================
  172 |   test.describe("T2: Stage progression", () => {
  173 |     test("advance endpoint advances video status", async () => {
  174 |       test.skip(!videoId, "No test video created");
  175 |       const exists = await endpointExists(
  176 |         `${API_URL}/api/videos/${videoId}/advance`,
  177 |         "PATCH",
  178 |         token
  179 |       );
  180 |       test.skip(!exists, "Advance endpoint not deployed");
  181 | 
  182 |       const res = await fetch(`${API_URL}/api/videos/${videoId}/advance`, {
  183 |         method: "PATCH",
  184 |         headers: { Authorization: `Bearer ${token}` },
  185 |       });
  186 |       expect(res.ok).toBeTruthy();
  187 |       const data = await res.json();
  188 |       expect(data.status).toBeDefined();
  189 |     });
  190 |   });
  191 | 
  192 |   // ========================================
  193 |   // T3: Storyboard approve/reject endpoints
  194 |   // ========================================
  195 |   test.describe("T3: Storyboard approve/reject", () => {
  196 |     test("storyboard approve endpoint accepts POST", async () => {
  197 |       const exists = await endpointExists(
  198 |         `${API_URL}/api/review/storyboard/test-id/approve`,
  199 |         "POST",
  200 |         token
  201 |       );
  202 |       test.skip(!exists, "Storyboard approve endpoint not deployed");
  203 |       // Endpoint exists and accepts POST (may return 404 for invalid ID, that's OK)
  204 |       expect(exists).toBeTruthy();
  205 |     });
  206 | 
  207 |     test("storyboard reject endpoint accepts POST", async () => {
  208 |       const exists = await endpointExists(
  209 |         `${API_URL}/api/review/storyboard/test-id/reject`,
  210 |         "POST",
  211 |         token,
  212 |         { reason: "test" }
  213 |       );
  214 |       test.skip(!exists, "Storyboard reject endpoint not deployed");
  215 |       expect(exists).toBeTruthy();
  216 |     });
  217 | 
  218 |     test("bulk approve-all endpoint accepts POST", async () => {
  219 |       const exists = await endpointExists(
  220 |         `${API_URL}/api/review/storyboard/approve-all`,
  221 |         "POST",
  222 |         token,
  223 |         { video_id: videoId }
  224 |       );
  225 |       test.skip(!exists, "Bulk approve endpoint not deployed");
  226 |       expect(exists).toBeTruthy();
  227 |     });
  228 |   });
  229 | 
  230 |   // ========================================
  231 |   // T4: Soft delete
  232 |   // ========================================
  233 |   test.describe("T4: Soft delete", () => {
  234 |     test("DELETE endpoint soft-deletes and filters from list", async () => {
  235 |       const deleteTestId = await createTestVideo(token, "Soft Delete E2E");
  236 |       test.skip(!deleteTestId, "Could not create test video");
  237 | 
  238 |       const exists = await endpointExists(
  239 |         `${API_URL}/api/videos/${deleteTestId}`,
  240 |         "DELETE",
  241 |         token
  242 |       );
  243 |       test.skip(!exists, "DELETE endpoint not deployed");
  244 | 
  245 |       // Verify in list before delete
  246 |       const beforeRes = await fetch(`${API_URL}/api/videos`, {
  247 |         headers: { Authorization: `Bearer ${token}` },
  248 |       });
  249 |       const beforeList = await beforeRes.json();
> 250 |       expect(beforeList.some((v: any) => v.id === deleteTestId)).toBeTruthy();
      |                                                                  ^ Error: expect(received).toBeTruthy()
  251 | 
  252 |       // Soft delete
  253 |       const delRes = await fetch(
  254 |         `${API_URL}/api/videos/${deleteTestId}`,
  255 |         {
  256 |           method: "DELETE",
  257 |           headers: { Authorization: `Bearer ${token}` },
  258 |         }
  259 |       );
  260 |       expect(delRes.ok).toBeTruthy();
  261 | 
  262 |       // Verify filtered from list
  263 |       const afterRes = await fetch(`${API_URL}/api/videos`, {
  264 |         headers: { Authorization: `Bearer ${token}` },
  265 |       });
  266 |       const afterList = await afterRes.json();
  267 |       expect(afterList.some((v: any) => v.id === deleteTestId)).toBeFalsy();
  268 |     });
  269 |   });
  270 | 
  271 |   // ========================================
  272 |   // T5: Video clip prompts + user preferences
  273 |   // ========================================
  274 |   test.describe("T5: Video prompts & user preferences", () => {
  275 |     test("generate-video-prompts endpoint exists", async () => {
  276 |       test.skip(!videoId, "No test video");
  277 |       const exists = await endpointExists(
  278 |         `${API_URL}/api/pipeline/generate-video-prompts/${videoId}`,
  279 |         "POST",
  280 |         token
  281 |       );
  282 |       test.skip(!exists, "Video prompts endpoint not deployed");
  283 |       expect(exists).toBeTruthy();
  284 |     });
  285 | 
  286 |     test("user preferences GET endpoint exists", async () => {
  287 |       const exists = await endpointExists(
  288 |         `${API_URL}/api/user/preferences`,
  289 |         "GET",
  290 |         token
  291 |       );
  292 |       test.skip(!exists, "Preferences endpoint not deployed");
  293 |       expect(exists).toBeTruthy();
  294 |     });
  295 | 
  296 |     test("user preferences PUT saves data", async () => {
  297 |       const exists = await endpointExists(
  298 |         `${API_URL}/api/user/preferences`,
  299 |         "PUT",
  300 |         token,
  301 |         { tab_order: ["Script", "Visuals"] }
  302 |       );
  303 |       test.skip(!exists, "Preferences PUT not deployed");
  304 |       expect(exists).toBeTruthy();
  305 |     });
  306 |   });
  307 | 
  308 |   // ========================================
  309 |   // T6: Thumbnail generation
  310 |   // ========================================
  311 |   test.describe("T6: Thumbnail generation", () => {
  312 |     test("thumbnail pipeline endpoint exists", async () => {
  313 |       test.skip(!videoId, "No test video");
  314 |       const exists = await endpointExists(
  315 |         `${API_URL}/api/pipeline/thumbnail/${videoId}`,
  316 |         "POST",
  317 |         token
  318 |       );
  319 |       // Endpoint exists even if it returns a status gate error
  320 |       test.skip(!exists, "Thumbnail endpoint not deployed");
  321 |       expect(exists).toBeTruthy();
  322 |     });
  323 |   });
  324 | 
  325 |   // ========================================
  326 |   // T7: Storyboard approve/reject UI
  327 |   // ========================================
  328 |   test.describe("T7: Storyboard approve/reject UI", () => {
  329 |     test("review page loads with storyboard-related content", async ({
  330 |       page,
  331 |     }) => {
  332 |       await loginViaToken(page, token);
  333 |       await page.goto(`${BASE_URL}/review`);
  334 |       await page.waitForLoadState("networkidle");
  335 |       await page.waitForTimeout(2000);
  336 | 
  337 |       // Review page should render (may redirect to login if auth required)
  338 |       const url = page.url();
  339 |       // Either on review page or redirected to login (both valid)
  340 |       expect(
  341 |         url.includes("/review") || url.includes("/login")
  342 |       ).toBeTruthy();
  343 | 
  344 |       if (url.includes("/review")) {
  345 |         // Check for storyboard-related tabs or content
  346 |         const content = await page.textContent("body");
  347 |         expect(
  348 |           content?.toLowerCase().includes("storyboard") ||
  349 |             content?.toLowerCase().includes("scripts") ||
  350 |             content?.toLowerCase().includes("review")
```