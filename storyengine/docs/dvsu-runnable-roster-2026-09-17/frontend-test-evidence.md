# Frontend runnable-roster evidence

2026-09-17 local, mocked-API verification. No provider endpoint, database, or production route was contacted.

`npx playwright test tests/dvsu-runnable-roster.spec.ts --project=chromium` passed 2/2 using the installed Google Chrome channel. The factual fixture renders 20 roster cards: two cached factual previews and 18 unready research cards. It proves the 18 per-card Run Script controls and Run All are enabled, the summary is `0/20` production and `2/20` previews, the preparable path completes a mocked durable preview job with matching request identity, the hard-blocked path creates no second preview POST, Run All confirms then makes exactly one mocked script POST, and card buttons disable while that POST is pending. The nonfactual fixture remains held by its saved research gate.

`npm run test:unit -- src/components/production/ScriptVoiceTab.factual.test.ts` passed 7/7. `npx tsc --noEmit` passed. `npm run build` completed successfully with Next.js webpack.

Final 2026-09-17 review verification: after the passed-preview subtitle correction, the same rendered Chrome suite passed 2/2 again. It includes the passed-preview subtitle and absence-of-stale-review-error assertions. `npx tsc --noEmit` and `npm run build` passed again. Generated `next-env.d.ts` and Playwright result files were restored after verification.
