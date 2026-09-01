import assert from "node:assert/strict";
import test from "node:test";
import {
  resolveStaticDocuStage,
  staticDocuRunAllPreflight,
  staticDocuPictureTitle,
} from "../src/lib/static-docu-navigation.ts";

test("Voice remains selected on the shared Script and Voice page", () => {
  assert.equal(resolveStaticDocuStage("script-voice", "voice"), "voice");
  assert.equal(resolveStaticDocuStage("script-voice", "script"), "script");
  assert.equal(resolveStaticDocuStage("pictures", "voice"), "pictures");
});

test("a missing picture uses the locked roster name, never narration text", () => {
  assert.equal(
    staticDocuPictureTitle(null, { name: "Essex class", designation: "CV-9 through CV-47" }, 9),
    "CV-9 through CV-47 Essex class",
  );
  assert.equal(staticDocuPictureTitle(null, null, 9), "Scene 9");
  assert.equal(
    staticDocuPictureTitle("Generated Essex view", { name: "Essex class" }, 9),
    "Generated Essex view",
  );
});

test("Run All can start a brand-new video before a roster exists", () => {
  assert.deepEqual(staticDocuRunAllPreflight(0, 0), {
    allowed: true,
    note: "Research will discover and verify the roster automatically.",
  });
  assert.equal(staticDocuRunAllPreflight(24, 20).allowed, true);
});
