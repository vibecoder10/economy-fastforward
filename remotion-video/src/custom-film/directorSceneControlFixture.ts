import {
  DIRECTOR_REMOTION_PROPS_VERSION,
  withDirectorPropsHash,
} from "./directorSchema";
import controlManifest from "./scene-control-proof-control-manifest.json";

const MARA_ID = "scene_control_character_mara";
const ELIAS_ID = "scene_control_character_elias";
const ENVIRONMENT_ID = "scene_control_environment_relay_room";

const continuity = (
  openingState: string,
  closingState: string,
  progression: string,
) => ({
  character_ids: [MARA_ID, ELIAS_ID],
  environment_id: ENVIRONMENT_ID,
  opening_state: openingState,
  closing_state: closingState,
  progression,
});

const source = (key: string, localPath: string, digest: string) => ({
  source_key: key,
  local_path: localPath,
  source_sha256: digest,
});

const words = (
  values: string[],
  fromFrame: number,
  toFrame: number,
) => {
  const width = toFrame - fromFrame;
  return values.map((text, index) => ({
    text,
    from_frame: fromFrame + Math.floor((width * index) / values.length),
    to_frame:
      index === values.length - 1
        ? toFrame
        : fromFrame + Math.floor((width * (index + 1)) / values.length),
  }));
};

const ambient = (shot: number, start: number, end: number) => ({
  layer_id: `ambient:relay-room:${shot}`,
  kind: "ambient" as const,
  source: source(
    "audio:relay-room-ambience",
    "motion-audio/music-bed.wav",
    "63570c59f6fc499c5d3cd991372e66bfeb85b316fe9c3058ac1d54fd10b073ea",
  ),
  start_frame: start,
  end_frame: end,
  gain_db: -28,
  loop: true,
});

export const DIRECTOR_SCENE_CONTROL_PROOF_PROPS = withDirectorPropsHash({
  schema_version: DIRECTOR_REMOTION_PROPS_VERSION,
  identity: {
    director_contract_hash: controlManifest.director_contract.sha256,
    storyboard_gate_hash: controlManifest.storyboard_gate.sha256,
    picture_gate_hash: controlManifest.picture_gate.sha256,
    visual_gate_hash: controlManifest.visual_gate.sha256,
    admission_hash: controlManifest.admission.sha256,
  },
  video: {
    fps: 24,
    width: 1920,
    height: 1080,
    total_frames: 432,
  },
  shots: [
    {
      shot_id: "scene_control_shot_1",
      shot_key: "establish_relay_room",
      section_id: "scene_control_scene_1",
      order_index: 0,
      start_frame: 0,
      end_frame: 71,
      duration_frames: 72,
      technique: "cinematic_action",
      performance_mode: "silent_action",
      caption_mode: "none",
      transition_from_previous: "opening",
      transition_duration_frames: 0,
      continuity: continuity(
        "Mara stands left of the relay console; Elias watches from the breaker wall.",
        "Mara reaches the console and inserts the amber key while Elias holds position.",
        "Establishes both recurring characters, the relay-room geography, and the key that starts the conflict.",
      ),
      clip: source(
        "clip:scene-control-shot-1",
        "director-scene-proof/shot-1-establish-key.mp4",
        "4df8f1541ff38340a7abe7eec418e1fd4f70c30cf8e1fe8b9e0aee8d50ae9aae",
      ),
      spoken_lines: [],
      sound_layers: [
        ambient(1, 0, 72),
        {
          layer_id: "sfx:key-click",
          kind: "sfx",
          source: source(
            "audio:key-click",
            "motion-audio/data-click.wav",
            "a613caf2f4991325ca47af5cbe2d0870629112040f8c5b290b29a00d1863e883",
          ),
          start_frame: 40,
          end_frame: 46,
          gain_db: -8,
          loop: false,
        },
      ],
    },
    {
      shot_id: "scene_control_shot_2",
      shot_key: "signal_exchange",
      section_id: "scene_control_scene_1",
      order_index: 1,
      start_frame: 72,
      end_frame: 167,
      duration_frames: 96,
      technique: "poco_dialogue",
      performance_mode: "dialogue",
      caption_mode: "dialogue",
      transition_from_previous: "location_cut",
      transition_duration_frames: 12,
      continuity: continuity(
        "The amber key is seated and the relay line glows turquoise between Mara and Elias.",
        "Mara identifies the signal as internal; Elias realizes the intruder can detect them.",
        "Turns the unexplained signal into an immediate threat with shared character knowledge.",
      ),
      clip: source(
        "clip:scene-control-shot-2",
        "director-scene-proof/shot-2-signal-exchange.mp4",
        "ead7d4cd0bd172523b29f365a82bd5853e97d584884430adf328d92b365fd63b",
      ),
      spoken_lines: [
        {
          line_index: 0,
          speaker_id: MARA_ID,
          kind: "dialogue",
          text: "The signal is inside.",
          source: source(
            "voice:mara:signal",
            "director-scene-proof/mara-signal.wav",
            "6570e6da74f37c5ec47a26b3b2905810c7176d006810d480da425a8f2ab0a75d",
          ),
          start_frame: 78,
          end_frame: 118,
          measured_words: words(
            ["The ", "signal ", "is ", "inside."],
            78,
            118,
          ),
        },
        {
          line_index: 1,
          speaker_id: ELIAS_ID,
          kind: "dialogue",
          text: "Then it knows we're here.",
          source: source(
            "voice:elias:knows",
            "director-scene-proof/elias-knows.wav",
            "242833726029e266d3dda769451698663872ec04f04d1db48f08d8a3773115cc",
          ),
          start_frame: 120,
          end_frame: 164,
          measured_words: words(
            ["Then ", "it ", "knows ", "we're ", "here."],
            120,
            164,
          ),
        },
      ],
      sound_layers: [ambient(2, 72, 168)],
    },
    {
      shot_id: "scene_control_shot_3",
      shot_key: "silent_alarm_beat",
      section_id: "scene_control_scene_1",
      order_index: 2,
      start_frame: 168,
      end_frame: 239,
      duration_frames: 72,
      technique: "cinematic_action",
      performance_mode: "silent_action",
      caption_mode: "none",
      transition_from_previous: "continuous",
      transition_duration_frames: 0,
      continuity: continuity(
        "Mara and Elias face the live turquoise relay line.",
        "The line expands red across the console and both characters recoil toward the center.",
        "Uses an intentional dialogue-free reaction beat to make the threat visible before the decision.",
      ),
      clip: source(
        "clip:scene-control-shot-3",
        "director-scene-proof/shot-3-silent-alarm.mp4",
        "d5dba881d128a8e8e4f5a6a0a7b8b66c57f8173bfa9b975586ca4a89f0cb385c",
      ),
      spoken_lines: [],
      sound_layers: [
        ambient(3, 168, 240),
        {
          layer_id: "sfx:signal-pulse",
          kind: "sfx",
          source: source(
            "audio:signal-pulse",
            "motion-audio/signal-pulse.wav",
            "69d66a6e55ba6f32888b6c392cd84e7ad77e9d73627c67dc63e329fa4118055d",
          ),
          start_frame: 174,
          end_frame: 222,
          gain_db: -11,
          loop: false,
        },
        {
          layer_id: "sfx:silence-drop",
          kind: "sfx",
          source: source(
            "audio:silence-drop",
            "motion-audio/silence-drop.wav",
            "632ffe13ce979298edcd436902b080cc06933e81fd06ffadba14b635ecf432d4",
          ),
          start_frame: 216,
          end_frame: 240,
          gain_db: -7,
          loop: false,
        },
      ],
    },
    {
      shot_id: "scene_control_shot_4",
      shot_key: "breaker_exchange",
      section_id: "scene_control_scene_1",
      order_index: 3,
      start_frame: 240,
      end_frame: 335,
      duration_frames: 96,
      technique: "poco_dialogue",
      performance_mode: "dialogue",
      caption_mode: "dialogue",
      transition_from_previous: "continuous",
      transition_duration_frames: 0,
      continuity: continuity(
        "The red relay line is active; Elias is nearest the breaker wall.",
        "Mara orders the transmitter killed as Elias reaches the breaker and reveals he anticipated her.",
        "Converts discovery into a decisive coordinated action while preserving screen direction.",
      ),
      clip: source(
        "clip:scene-control-shot-4",
        "director-scene-proof/shot-4-breaker-exchange.mp4",
        "794ee4f51c02ed06d8ebfd3d7ecd62e6bcbf6e18f86e7670fc9171b146301db7",
      ),
      spoken_lines: [
        {
          line_index: 0,
          speaker_id: MARA_ID,
          kind: "dialogue",
          text: "Kill the transmitter.",
          source: source(
            "voice:mara:kill",
            "director-scene-proof/mara-kill.wav",
            "9048b56f5343977cc6f5b436b2d552a884dfae8bcf9e51108ce9f76076120b5a",
          ),
          start_frame: 246,
          end_frame: 286,
          measured_words: words(
            ["Kill ", "the ", "transmitter."],
            246,
            286,
          ),
        },
        {
          line_index: 1,
          speaker_id: ELIAS_ID,
          kind: "dialogue",
          text: "Already did.",
          source: source(
            "voice:elias:did",
            "director-scene-proof/elias-did.wav",
            "7c10b4f96eda1a48f50d2f15b4abeeda315df8e000072217c1e62669d2d65dd4",
          ),
          start_frame: 288,
          end_frame: 332,
          measured_words: words(["Already ", "did."], 288, 332),
        },
      ],
      sound_layers: [ambient(4, 240, 336)],
    },
    {
      shot_id: "scene_control_shot_5",
      shot_key: "breaker_payoff",
      section_id: "scene_control_scene_1",
      order_index: 4,
      start_frame: 336,
      end_frame: 431,
      duration_frames: 96,
      technique: "cinematic_action",
      performance_mode: "silent_action",
      caption_mode: "none",
      transition_from_previous: "time_cut",
      transition_duration_frames: 12,
      continuity: continuity(
        "Elias has reached the breaker; Mara remains beside the overloaded console.",
        "Elias throws the breaker, the relay collapses, and the console releases a paper trace to Mara.",
        "Pays off the key and breaker setup, resolves the immediate threat, and creates the evidence that drives the next scene.",
      ),
      clip: source(
        "clip:scene-control-shot-5",
        "director-scene-proof/shot-5-breaker-payoff.mp4",
        "833b577b606338719849e6e578456fdafaed461280c81ba26cfe9807b50740fd",
      ),
      spoken_lines: [],
      sound_layers: [
        ambient(5, 336, 432),
        {
          layer_id: "score:relay-resolution",
          kind: "score",
          source: source(
            "audio:relay-resolution",
            "motion-audio/music-bed.wav",
            "63570c59f6fc499c5d3cd991372e66bfeb85b316fe9c3058ac1d54fd10b073ea",
          ),
          start_frame: 336,
          end_frame: 432,
          gain_db: -22,
          loop: true,
        },
        {
          layer_id: "sfx:breaker-click",
          kind: "sfx",
          source: source(
            "audio:breaker-click",
            "motion-audio/data-click.wav",
            "a613caf2f4991325ca47af5cbe2d0870629112040f8c5b290b29a00d1863e883",
          ),
          start_frame: 368,
          end_frame: 374,
          gain_db: -6,
          loop: false,
        },
      ],
    },
  ],
});

export const DIRECTOR_SCENE_CONTROL_LOCKS = {
  character_ids: [MARA_ID, ELIAS_ID],
  environment_id: ENVIRONMENT_ID,
} as const;
