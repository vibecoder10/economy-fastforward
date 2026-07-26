import {
  DIRECTOR_REMOTION_PROPS_VERSION,
  withDirectorPropsHash,
} from "./directorSchema";

const hash = (character: string): string => character.repeat(64);

export const DIRECTOR_FILM_DEFAULT_PROPS = withDirectorPropsHash({
  schema_version: DIRECTOR_REMOTION_PROPS_VERSION,
  identity: {
    director_contract_hash: hash("1"),
    storyboard_gate_hash: hash("2"),
    picture_gate_hash: hash("3"),
    visual_gate_hash: hash("4"),
    admission_hash: hash("5"),
  },
  video: {
    fps: 24,
    width: 1920,
    height: 1080,
    total_frames: 72,
  },
  shots: [
    {
      shot_id: "proof-shot-1",
      shot_key: "corridor_run",
      section_id: "proof-section-1",
      order_index: 0,
      start_frame: 0,
      end_frame: 23,
      duration_frames: 24,
      technique: "cinematic_action",
      performance_mode: "silent_action",
      caption_mode: "none",
      transition_from_previous: "opening",
      transition_duration_frames: 0,
      clip: {
        source_key: "clip:proof-shot-1",
        local_path: "director-proof/shot-1.mp4",
        source_sha256: hash("6"),
      },
      spoken_lines: [],
      sound_layers: [
        {
          layer_id: "ambient:proof-shot-1",
          kind: "ambient",
          source: {
            source_key: "audio:ambient-proof",
            local_path: "motion-audio/music-bed.wav",
            source_sha256: hash("7"),
          },
          start_frame: 0,
          end_frame: 24,
          gain_db: -20,
          loop: true,
        },
      ],
    },
    {
      shot_id: "proof-shot-2",
      shot_key: "proof_exchange",
      section_id: "proof-section-2",
      order_index: 1,
      start_frame: 24,
      end_frame: 71,
      duration_frames: 48,
      technique: "poco_dialogue",
      performance_mode: "dialogue",
      caption_mode: "dialogue",
      transition_from_previous: "location_cut",
      transition_duration_frames: 6,
      clip: {
        source_key: "clip:proof-shot-2",
        local_path: "director-proof/shot-2.mp4",
        source_sha256: hash("8"),
      },
      spoken_lines: [
        {
          line_index: 0,
          speaker_id: "hero",
          kind: "dialogue",
          text: "You found it.",
          source: {
            source_key: "voice:proof-shot-2:1",
            local_path: "motion-audio/transition-envelope.wav",
            source_sha256: hash("9"),
          },
          start_frame: 24,
          end_frame: 42,
          measured_words: [
            {text: "You ", from_frame: 24, to_frame: 30},
            {text: "found ", from_frame: 30, to_frame: 36},
            {text: "it.", from_frame: 36, to_frame: 42},
          ],
        },
        {
          line_index: 1,
          speaker_id: "guide",
          kind: "dialogue",
          text: "Now we show them.",
          source: {
            source_key: "voice:proof-shot-2:2",
            local_path: "motion-audio/transition-envelope.wav",
            source_sha256: hash("a"),
          },
          start_frame: 42,
          end_frame: 66,
          measured_words: [
            {text: "Now ", from_frame: 42, to_frame: 48},
            {text: "we ", from_frame: 48, to_frame: 54},
            {text: "show ", from_frame: 54, to_frame: 60},
            {text: "them.", from_frame: 60, to_frame: 66},
          ],
        },
      ],
      sound_layers: [
        {
          layer_id: "score:proof-shot-2",
          kind: "score",
          source: {
            source_key: "audio:score-proof",
            local_path: "motion-audio/music-bed.wav",
            source_sha256: hash("b"),
          },
          start_frame: 24,
          end_frame: 72,
          gain_db: -24,
          loop: true,
        },
      ],
    },
  ],
});
