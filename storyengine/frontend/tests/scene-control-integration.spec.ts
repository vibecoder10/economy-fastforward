import {readFileSync} from "node:fs";
import {resolve} from "node:path";
import {expect, test} from "@playwright/test";
import {adaptSceneControlSnapshot} from "../src/components/custom-film/scene-control-adapter";
import {
  getSceneControl,
  putSceneControlFilmLock,
  quoteSceneControlOperation,
  transitionSceneControlScene,
  type SceneControlApiSnapshot,
} from "../src/lib/scene-control-api";
import {isSceneControlFrontendEnabled} from "../src/lib/env";

const hash = (character: string) => character.repeat(64);
const shotIds = Array.from({length: 5}, (_, index) => `shot-${index + 1}`);
const durations = [72, 96, 72, 96, 96];
const keys = [
  "establish_relay_room",
  "signal_exchange",
  "silent_alarm_beat",
  "breaker_exchange",
  "breaker_payoff",
];
const lines = [
  [],
  [
    ["scene_control_character_mara", "The signal is inside.", "controlled; frames 78-118"],
    ["scene_control_character_elias", "Then it knows we're here.", "alarmed; frames 120-164"],
  ],
  [],
  [
    ["scene_control_character_mara", "Kill the transmitter.", "command; frames 246-286"],
    ["scene_control_character_elias", "Already did.", "calm; frames 288-332"],
  ],
  [],
] as const;

const apiShots = shotIds.map((shot_id, index) => ({
  shot_id,
  order_index: index,
  duration_frames: durations[index],
  shot_contract: {
    shot_key: keys[index],
    section_id: "section-1",
    duration_frames: durations[index],
    technique: (index === 1 || index === 3
      ? "poco_dialogue"
      : "cinematic_action") as "poco_dialogue" | "cinematic_action",
    performance_mode: (lines[index].length
      ? "dialogue"
      : "silent_action") as "dialogue" | "silent_action",
    narrative_purpose: `Narrative purpose ${index + 1}`,
    caused_by: index ? [`fact ${index}`] : [],
    progression_kinds: ["story" as const],
    story_value: `Story advances ${index + 1}`,
    opening_state: {
      story_facts: [`fact ${index}`],
      character_positions: {scene_control_character_mara: "console"},
      prop_states: {},
      emotional_state: {},
    },
    action_beats: [`visible action ${index + 1}`],
    closing_state: {
      story_facts: [`fact ${index + 1}`],
      character_positions: {scene_control_character_mara: "console"},
      prop_states: {},
      emotional_state: {},
    },
    transition_from_previous: index ? ("continuous" as const) : ("opening" as const),
    continuity_bridge: index ? `bridge ${index}` : null,
    environment_id: "scene_control_environment_relay_room",
    character_ids: [
      "scene_control_character_mara",
      "scene_control_character_elias",
    ],
    active_prop_ids: [],
    screen_direction: "Mara remains screen left",
    shot_size: "medium",
    camera_move: "restrained push",
    spoken_lines: lines[index].map(([speaker_id, text, delivery]) => ({
      speaker_id,
      kind: "dialogue" as const,
      text,
      language: "English",
      delivery,
      addressee_id: null,
    })),
    storyboard_composition: "Both characters hold established relay-room geography.",
    final_picture_intent: "Grounded nocturnal relay-room image with restrained contrast.",
    motion_intent: "Subtle character and practical-light motion only.",
    ambient_sound: "Relay room hum",
    score_intent: "Restrained pulse",
    sfx_cues: [],
    caption_mode: lines[index].length ? ("dialogue" as const) : ("none" as const),
  },
}));

const apiSnapshot: SceneControlApiSnapshot = {
  control_version: 1,
  video_id: "video-1",
  director_contract_id: "director-1",
  director_contract_hash: hash("a"),
  film_locks: {
    lock_version: 1,
    complete: true,
    missing: [],
    film_lock_set_hash: hash("f"),
    locks: [
      "story",
      "dialogue",
      "style",
      "cast",
      "environments",
      "techniques",
    ].map((lock_kind, index) => ({
      lock_kind: lock_kind as
        | "story"
        | "dialogue"
        | "style"
        | "cast"
        | "environments"
        | "techniques",
      revision: 1,
      payload: {summary: `${lock_kind} locked`},
      content_hash: String(index + 1).repeat(64),
      approval_hash: hash("b"),
      synthetic: true,
      approved_at: "2026-07-26T00:00:00Z",
    })),
  },
  current_scene_id: "scene-1",
  scenes: [
    {
      scene_id: "scene-1",
      scene_number: 1,
      revision: 1,
      revision_hash: hash("c"),
      film_lock_set_hash: hash("f"),
      artifact_hashes: {storyboard: hash("d")},
      state: "plan_approved",
      accepted_revision_hash: null,
      access: "current",
      synthetic: true,
      shots: apiShots,
      artifact_manifest: {
        version: 1,
        synthetic: true,
        shots: apiShots.map((shot, index) => ({
          shot_id: shot.shot_id,
          kind: "video",
          url: `/scene-control-proof/shot-${index + 1}-proof.mp4`,
          start_frame: durations
            .slice(0, index)
            .reduce((sum, duration) => sum + duration, 0),
          end_frame:
            durations
              .slice(0, index + 1)
              .reduce((sum, duration) => sum + duration, 0) - 1,
          sha256: "a".repeat(64),
        })),
        assembly: {
          kind: "video",
          url: "/scene-control-proof/director-scene-control-proof.mp4",
          duration_frames: 432,
          sha256: "b".repeat(64),
        },
      },
      scene_contract: {
        scene_number: 1,
        purpose: "Contain the relay threat.",
        target_duration_frames: 432,
        story_time: "Night 1",
        opening_state: "Relay live",
        state_change: "Trace recovered",
        character_ids: [
          "scene_control_character_mara",
          "scene_control_character_elias",
        ],
        environment_id: "scene_control_environment_relay_room",
        active_prop_ids: [],
        continuity_in: "Relay live",
        continuity_out: "Paper trace recovered",
        dialogue_turns: [],
        silent_action_beats: [],
        shot_ids: shotIds,
      },
    },
    {
      scene_id: "scene-2",
      scene_number: 2,
      revision: 1,
      revision_hash: hash("e"),
      film_lock_set_hash: hash("f"),
      artifact_hashes: {},
      state: "draft",
      accepted_revision_hash: null,
      access: "locked",
      synthetic: true,
      shots: [
        {
          ...apiShots[0],
          shot_id: "scene-2-shot",
          order_index: 5,
          duration_frames: 576,
          shot_contract: {
            ...apiShots[0].shot_contract,
            shot_key: "read_trace",
            duration_frames: 576,
          },
        },
      ],
      artifact_manifest: {},
      scene_contract: {
        scene_number: 2,
        purpose: "Read the trace.",
        target_duration_frames: 576,
        story_time: "Immediately after",
        opening_state: "Trace recovered",
        state_change: "Source identified",
        character_ids: ["scene_control_character_mara"],
        environment_id: "scene_control_environment_relay_room",
        active_prop_ids: [],
        continuity_in: "Paper trace recovered",
        continuity_out: "Source identified",
        dialogue_turns: [],
        silent_action_beats: [],
        shot_ids: ["scene-2-shot"],
      },
    },
  ],
};

test("adapter preserves the canonical synthetic proof and sequential lock", () => {
  const adapted = adaptSceneControlSnapshot(apiSnapshot);
  expect(adapted).not.toBeNull();
  expect(adapted!.current_scene_id).toBe("scene-1");
  expect(adapted!.film_locks_approved).toBe(true);
  expect(adapted!.film_locks.every(({reviewable}) => reviewable)).toBe(true);
  expect(adapted!.scenes[0].target_duration_seconds).toBe(18);
  expect(adapted!.scenes[0].shots.map(({id}) => id)).toEqual(shotIds);
  expect(adapted!.scenes[0].shots.map(({duration_seconds}) => duration_seconds)).toEqual([
    3, 4, 3, 4, 4,
  ]);
  expect(
    adapted!.scenes[0].shots.flatMap(({dialogue}) =>
      dialogue.map(({text}) => text),
    ),
  ).toEqual([
    "The signal is inside.",
    "Then it knows we're here.",
    "Kill the transmitter.",
    "Already did.",
  ]);
  expect(adapted!.scenes[0].transition_evidence_hashes.plan_approved).toBe(
    hash("c"),
  );
  expect(
    adapted!.scenes[0].transition_evidence_hashes.storyboard_approved,
  ).toBe(hash("d"));
  expect(adapted!.scenes[1].rail_status).toBe("locked");
  expect(adapted!.scenes[0].shots[0].preview).toMatchObject({
    url: "/scene-control-proof/shot-1-proof.mp4",
    start_frame: 0,
    end_frame: 71,
  });
  expect(adapted!.scenes[0].assembly_preview).toMatchObject({
    url: "/scene-control-proof/director-scene-control-proof.mp4",
    duration_frames: 432,
    current_for_acceptance: false,
  });
});

test("assembly proof is current only at an exact assembled or accepted gate", () => {
  const staleDraft = structuredClone(apiSnapshot);
  staleDraft.scenes[0].state = "draft";
  staleDraft.scenes[0].artifact_hashes = {};
  expect(
    adaptSceneControlSnapshot(staleDraft)!.scenes[0].assembly_preview
      ?.current_for_acceptance,
  ).toBe(false);

  const staleRejected = structuredClone(apiSnapshot);
  staleRejected.scenes[0].state = "audio_approved";
  staleRejected.scenes[0].artifact_hashes = {};
  expect(
    adaptSceneControlSnapshot(staleRejected)!.scenes[0].assembly_preview
      ?.current_for_acceptance,
  ).toBe(false);

  const currentAssembled = structuredClone(apiSnapshot);
  currentAssembled.scenes[0].state = "assembled";
  if (!("assembly" in currentAssembled.scenes[0].artifact_manifest)) {
    throw new Error("test fixture assembly is missing");
  }
  currentAssembled.scenes[0].artifact_hashes.assembly =
    currentAssembled.scenes[0].artifact_manifest.assembly.sha256;
  expect(
    adaptSceneControlSnapshot(currentAssembled)!.scenes[0].assembly_preview
      ?.current_for_acceptance,
  ).toBe(true);

  currentAssembled.scenes[0].artifact_hashes.assembly = "c".repeat(64);
  expect(
    adaptSceneControlSnapshot(currentAssembled)!.scenes[0].assembly_preview
      ?.current_for_acceptance,
  ).toBe(false);
});

test("adapter renders exact non-synthetic shot contracts without placeholders", () => {
  const source = structuredClone(apiSnapshot);
  source.scenes = [structuredClone(source.scenes[0])];
  source.scenes[0].synthetic = false;
  source.scenes[0].shots = [structuredClone(apiShots[1])];
  source.scenes[0].scene_contract.shot_ids = [shotIds[1]];
  source.scenes[0].scene_contract.target_duration_frames = 96;
  source.scenes[0].artifact_manifest = {};
  const adapted = adaptSceneControlSnapshot(source)!;
  const shot = adapted.scenes[0].shots[0];

  expect(shot.shot_key).toBe("signal_exchange");
  expect(shot.duration_seconds).toBe(4);
  expect(shot.narrative_function).toBe("Narrative purpose 2");
  expect(shot.advancement).toBe("Story advances 2");
  expect(shot.opening_state).toContain("fact 1");
  expect(shot.closing_state).toContain("fact 2");
  expect(shot.character_action).toBe("visible action 2");
  expect(shot.camera_action).toContain("restrained push");
  expect(shot.transition).toBe("Continuous");
  expect(shot.continuity_inputs).toContain("bridge 1");
  expect(shot.continuity_outputs).toEqual(["fact 2"]);
  expect(shot.performance_mode).toBe("dialogue");
  expect(shot.dialogue[0]).toMatchObject({
    speaker_label: "Mara",
    text: "The signal is inside.",
    performance_intent: "controlled",
    start_seconds: 3.25,
    timing_label: "frames 78–118",
  });
});

test("adapter fails closed when canonical production shots are missing or drift", () => {
  const missing = structuredClone(apiSnapshot);
  missing.scenes[0].shots = [];
  expect(() => adaptSceneControlSnapshot(missing)).toThrow();

  const durationDrift = structuredClone(apiSnapshot);
  durationDrift.scenes[0].shots[0].duration_frames += 1;
  expect(() => adaptSceneControlSnapshot(durationDrift)).toThrow();

  const externalMedia = structuredClone(apiSnapshot);
  if ("assembly" in externalMedia.scenes[0].artifact_manifest) {
    externalMedia.scenes[0].artifact_manifest.assembly.url =
      "https://example.com/proof.mp4";
  }
  expect(() => adaptSceneControlSnapshot(externalMedia)).toThrow(
    "artifact manifest is malformed or unsafe",
  );

  const frameDrift = structuredClone(apiSnapshot);
  if ("shots" in frameDrift.scenes[0].artifact_manifest) {
    frameDrift.scenes[0].artifact_manifest.shots[1].start_frame += 1;
  }
  expect(() => adaptSceneControlSnapshot(frameDrift)).toThrow(
    "artifact manifest is malformed or unsafe",
  );
});

test("missing film locks remain editable and establishable", () => {
  const source = structuredClone(apiSnapshot);
  source.film_locks.complete = false;
  source.film_locks.missing = ["techniques"];
  source.film_locks.locks = source.film_locks.locks.filter(
    ({lock_kind}) => lock_kind !== "techniques",
  );
  const adapted = adaptSceneControlSnapshot(source)!;
  const missing = adapted.film_locks.find(({id}) => id === "techniques")!;

  expect(missing.status).toBe("draft");
  expect(missing.reviewable).toBe(true);
  expect(missing.payload).toEqual({});
  expect(missing.summary).toContain("Establish");

  const cockpitSource = readFileSync(
    resolve(
      process.cwd(),
      "src/components/custom-film/SceneControlCockpit.tsx",
    ),
    "utf8",
  );
  expect(cockpitSource).toContain("Establish missing lock");
  expect(cockpitSource).toContain("Edit canonical payload");
  expect(cockpitSource).toContain("Enter valid JSON");
  expect(cockpitSource).toContain("No media or provider generation starts");
});

test("API client sends exact revision, evidence, and quote bodies", async () => {
  const calls: Array<{url: string; init?: RequestInit}> = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = (async (input, init) => {
    calls.push({url: String(input), init});
    const body = String(input).endsWith("/operations/quote")
      ? {
          quote_version: 1,
          video_id: "video-1",
          scene_id: "scene-1",
          scene_number: 1,
          shot_ids: shotIds,
          scene_revision_hash: hash("c"),
          operation_type: "storyboard_images",
          provider_operation: "storyboard_image",
          deterministic: false,
          initial_calls: 5,
          max_repair_calls: 0,
          unit_max_cents: 5,
          exact_incremental_max_cents: 25,
          prior_completed_cumulative_spend_cents: 0,
          new_exact_cumulative_ceiling_cents: 25,
          included_media: [],
          explicitly_unapproved: ["provider work"],
          approval_status: "not_approved",
          approval_card_hash: hash("q"),
        }
      : String(input).endsWith("/transition")
        ? {
            scene_id: "scene-1",
            scene_number: 1,
            state: "plan_approved",
            revision_hash: hash("c"),
            event_hash: hash("x"),
            next_scene_unlocked: false,
          }
        : apiSnapshot;
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: {"Content-Type": "application/json"},
    });
  }) as typeof fetch;

  try {
    await getSceneControl("video-1");
    await putSceneControlFilmLock("video-1", "techniques", {
      allowed: ["cinematic_action"],
    });
    await transitionSceneControlScene("video-1", "scene-1", {
      expected_revision_hash: hash("c"),
      target_state: "plan_approved",
      evidence_hash: hash("z"),
    });
    await quoteSceneControlOperation("video-1", "scene-1", {
      expected_revision_hash: hash("c"),
      operation_type: "storyboard_images",
    });
  } finally {
    globalThis.fetch = originalFetch;
  }

  expect(calls[0].url).toContain(
    "/api/custom-film/video-1/scene-control",
  );
  expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe(
    "Bearer dev-token",
  );
  expect(JSON.parse(String(calls[1].init?.body))).toEqual({
    payload: {allowed: ["cinematic_action"]},
  });
  expect(calls[1].url).toContain("/film-locks/techniques");
  expect(JSON.parse(String(calls[2].init?.body))).toEqual({
    expected_revision_hash: hash("c"),
    target_state: "plan_approved",
    evidence_hash: hash("z"),
  });
  expect(JSON.parse(String(calls[3].init?.body))).toEqual({
    expected_revision_hash: hash("c"),
    operation_type: "storyboard_images",
  });
  expect(calls.map(({url}) => url).join("\n")).not.toContain("approve");
  expect(calls.map(({url}) => url).join("\n")).not.toContain("generate");
});

test("mounted page refetches canonical state and has no provider authority", () => {
  const source = readFileSync(
    resolve(process.cwd(), "src/app/scene-control/[videoId]/page.tsx"),
    "utf8",
  );
  expect(source).toContain('queryKey: ["scene-control", videoId]');
  expect(source).toContain("await query.refetch()");
  expect(source).toContain("error.status === 409");
  expect(source).toContain("expected_revision_hash");
  expect(source).toContain("evidence_hash");
  expect(source).toContain("Create draft scene — no generation");
  expect(source).toContain("No provider work was approved or started");
  expect(source).toContain("Scene Control read model rejected");
  expect(source).toContain(
    "incomplete shot data cannot be mistaken for production truth",
  );
  expect(source).not.toContain("authorizeScene");
  expect(source).not.toContain("/approve");
  expect(source).not.toContain("/generate");
});

test("production page exposes discoverable Custom Film Scene Control navigation", () => {
  expect(isSceneControlFrontendEnabled(undefined)).toBe(false);
  expect(isSceneControlFrontendEnabled("false")).toBe(false);
  expect(isSceneControlFrontendEnabled("true")).toBe(true);
  const source = readFileSync(
    resolve(process.cwd(), "src/app/pipeline/[videoId]/page.tsx"),
    "utf8",
  );
  expect(source).toContain("video.custom_film_plan_id");
  expect(source).toContain("`/scene-control/${encodeURIComponent(videoId)}`");
  expect(source).toContain("Scene Control");
  expect(source).toContain(
    "Open deterministic scene-by-scene planning and review controls",
  );
  expect(source).toContain(
    "CUSTOM_FILM_SCENE_CONTROL_ENABLED && video.custom_film_plan_id",
  );

  const envSource = readFileSync(
    resolve(process.cwd(), "src/lib/env.ts"),
    "utf8",
  );
  expect(envSource).toContain('value === "true"');
  expect(envSource).not.toContain(
    'CUSTOM_FILM_SCENE_CONTROL_ENV !== "false"',
  );
});

test("proof UI requires controls, provenance, and never autoplays", () => {
  const source = readFileSync(
    resolve(
      process.cwd(),
      "src/components/custom-film/SceneControlCockpit.tsx",
    ),
    "utf8",
  );
  expect(source).toContain("<video");
  expect(source).toContain("controls");
  expect(source).toContain('preload="metadata"');
  expect(source).toContain("Frame evidence");
  expect(source).toContain("Assembly provenance · SHA-256");
  expect(source).toContain("before accepting the scene");
  expect(source).toContain("Synthetic comparison proof");
  expect(source).toContain(
    "not approved for the current gate",
  );
  expect(source).toContain(
    "not an approved artifact for the current gate",
  );
  expect(source).not.toContain("autoPlay");
  expect(source).not.toContain("autoplay");
});
