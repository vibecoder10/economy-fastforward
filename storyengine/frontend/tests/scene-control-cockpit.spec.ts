import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {expect, test} from "@playwright/test";
import {SCENE_CONTROL_SYNTHETIC_FIXTURE} from "../src/components/custom-film/scene-control-fixture";
import {
  currentScene,
  formatCents,
  nextSceneState,
  previousReviewState,
  transitionLabel,
  validateSceneControlSnapshot,
} from "../src/components/custom-film/scene-control-model";

test("synthetic cockpit fixture proves one progressive five-shot scene", () => {
  const snapshot = validateSceneControlSnapshot(
    SCENE_CONTROL_SYNTHETIC_FIXTURE,
  );
  const scene = currentScene(snapshot);

  expect(scene.number).toBe(1);
  expect(scene.target_duration_seconds).toBe(18);
  expect(scene.character_labels).toEqual(["Mara", "Elias"]);
  expect(scene.environment_label).toBe("Relay room");
  expect(snapshot.film_locks.map(({id}) => id)).toEqual([
    "story",
    "dialogue",
    "style",
    "cast",
    "environments",
    "techniques",
  ]);
  expect(scene.shots).toHaveLength(5);
  expect(scene.shots.map(({duration_seconds}) => duration_seconds)).toEqual([
    3, 4, 3, 4, 4,
  ]);
  expect(
    scene.shots.reduce((seconds, shot) => seconds + shot.duration_seconds, 0),
  ).toBe(18);
  expect(
    scene.shots.filter(({performance_mode}) => performance_mode === "silent_action"),
  ).toHaveLength(3);
  expect(
    new Set(
      scene.shots.flatMap(({dialogue}) =>
        dialogue.map(({speaker_id}) => speaker_id),
      ),
    ),
  ).toEqual(
    new Set([
      "scene_control_character_mara",
      "scene_control_character_elias",
    ]),
  );
  expect(scene.shots.map(({shot_key}) => shot_key)).toEqual([
    "establish_relay_room",
    "signal_exchange",
    "silent_alarm_beat",
    "breaker_exchange",
    "breaker_payoff",
  ]);
  expect(scene.shots.flatMap(({dialogue}) => dialogue.map(({text}) => text))).toEqual([
    "The signal is inside.",
    "Then it knows we're here.",
    "Kill the transmitter.",
    "Already did.",
  ]);
  expect(scene.shots.every(({advancement}) => advancement.length > 0)).toBe(true);
  expect(scene.transition_evidence_hashes.storyboard_approved).toMatch(
    /^[0-9a-f]{64}$/,
  );

  const lockedScene = snapshot.scenes[1];
  expect(lockedScene.rail_status).toBe("locked");
  expect(lockedScene.state).toBe("draft");
});

test("state helpers expose only the explicit next gate and prior review gate", () => {
  expect(nextSceneState("draft")).toBe("plan_approved");
  expect(nextSceneState("assembled")).toBe("accepted");
  expect(nextSceneState("accepted")).toBeNull();
  expect(previousReviewState("animation_approved")).toBe("imagery_approved");
  expect(transitionLabel("draft", "plan_approved")).toContain("no generation");
  expect(transitionLabel("audio_approved", "assembled")).toContain(
    "deterministic",
  );
});

test("quote is exact, unapproved, and has no broad authorization surface", () => {
  const quote = SCENE_CONTROL_SYNTHETIC_FIXTURE.next_operation!;
  expect(quote.approval_status).toBe("not_approved");
  expect(quote.max_repair_calls).toBe(0);
  expect(quote.unit_max_cents).toBe(5);
  expect(quote.exact_incremental_max_cents).toBe(25);
  expect(quote.prior_completed_cumulative_spend_cents).toBe(0);
  expect(quote.new_exact_cumulative_ceiling_cents).toBe(25);
  expect(formatCents(quote.new_exact_cumulative_ceiling_cents)).toBe("$0.25");
  expect(quote.explicitly_unapproved).toContain("Provider fallback");

  const typesSource = readFileSync(
    resolve(
      process.cwd(),
      "src/components/custom-film/scene-control-types.ts",
    ),
    "utf8",
  );
  const cockpitSource = readFileSync(
    resolve(
      process.cwd(),
      "src/components/custom-film/SceneControlCockpit.tsx",
    ),
    "utf8",
  );
  expect(typesSource).not.toContain("onAuthorizeOperation");
  expect(cockpitSource).not.toContain("Approve scene");
  expect(cockpitSource).not.toContain("autoplay");
  expect(cockpitSource).toContain("has no approval endpoint");
});

test("cockpit source preserves keyboard and disabled-state semantics", () => {
  const source = readFileSync(
    resolve(
      process.cwd(),
      "src/components/custom-film/SceneControlCockpit.tsx",
    ),
    "utf8",
  );
  expect(source).toContain('aria-label="Film scenes"');
  expect(source).toContain("aria-current=");
  expect(source).toContain("aria-pressed=");
  expect(source).toContain("aria-describedby=");
  expect(source).toContain("focus-visible:ring-2");
  expect(source).toContain("disabled:cursor-not-allowed");
});

test("invalid snapshots fail closed", () => {
  const duplicateCurrent = structuredClone(
    SCENE_CONTROL_SYNTHETIC_FIXTURE,
  );
  duplicateCurrent.scenes[1].rail_status = "current";
  expect(() => validateSceneControlSnapshot(duplicateCurrent)).toThrow(
    "exactly one current scene",
  );

  const missingCurrent = structuredClone(
    SCENE_CONTROL_SYNTHETIC_FIXTURE,
  );
  missingCurrent.current_scene_id = "not-a-scene";
  expect(() => validateSceneControlSnapshot(missingCurrent)).toThrow(
    "exactly one current scene",
  );
});
