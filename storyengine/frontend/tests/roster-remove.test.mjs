import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const apiSource = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");
const panelSource = readFileSync(
  new URL("../src/components/production/RosterStagePanel.tsx", import.meta.url),
  "utf8",
);

test("the roster panel exposes a confirmed remove action for every machine card", () => {
  assert.match(apiSource, /export const removeRosterUnit/);
  assert.match(apiSource, /\/api\/pipeline\/roster-remove\/\$\{videoId\}/);
  assert.match(panelSource, /removeRosterUnit\(videoId, machine\)/);
  assert.match(panelSource, /Remove \$\{u\.machine\} from roster/);
  assert.match(panelSource, /Remove this machine from the roster\?/);
});
