import { defineConfig } from "vitest/config";

// Minimal unit-test setup for pure TypeScript modules (no DOM, no Next.js
// runtime needed). Added for Timeline Workbench chunk T1 — this frontend
// had no unit-test runner before (package.json's only "test" script was
// Playwright e2e, which needs a running server/browser and isn't suited to
// testing a pure function in isolation). Scoped to co-located *.test.ts
// files so it never picks up the Playwright specs under tests/.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
