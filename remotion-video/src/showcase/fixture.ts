import {canonicalJson, sha256Hex} from "../custom-film/canonical";
import type {CustomFilmRemotionProps} from "../custom-film/schema";

const hash = (character: string) => character.repeat(64);
const sectionSpecs = [
  {id: "showcase-opening", role: "opening", start: 0, duration: 1080, source: "synthetic:opening:visual", audio: "synthetic:opening:audio"},
  {id: "showcase-evidence", role: "evidence", start: 1080, duration: 2520, source: "synthetic:evidence:visual", audio: "synthetic:evidence:audio"},
  {id: "showcase-witness", role: "case_study", start: 3600, duration: 2160, source: "synthetic:witness:visual", audio: "synthetic:witness:audio"},
  {id: "showcase-explanation", role: "explanation", start: 5760, duration: 1440, source: "synthetic:explanation:visual", audio: "synthetic:explanation:audio"},
] as const;

const body = {
  schema_version: "custom-film-remotion-props-v1" as const,
  identity: {
    assembly_version: "custom-film-assembly-v2",
    assembly_manifest_hash: hash("a"),
    tenant_id: "synthetic-local-tenant",
    video_id: "storyengine-custom-film-showcase",
    plan_id: "storyengine-five-minute-showcase-plan-v1",
    plan_hash: hash("5"),
    quote_inputs_hash: hash("6"),
    approval_hash: hash("7"),
    runtime_hash: hash("8"),
    runtime_job_id: `custom-film-runtime:${hash("8")}`,
    max_spend: 15,
    render_engine: "remotion" as const,
  },
  video: {
    fps: 24,
    width: 1920,
    height: 1080,
    total_duration_seconds: 300,
    total_frames: 7200,
  },
  transition_accounting: {
    type: "dip_to_black_non_overlap",
    duration_source: "fixed_12_frames_inside_section",
    overlap_frames_total: 0 as const,
    duration_lives_inside_assigned_sections: true as const,
  },
  sections: sectionSpecs.map((spec, index) => ({
    section_id: spec.id,
    order_index: index,
    role: spec.role,
    render_mode: index === 3 ? "static_explainer" : "synthetic_showcase",
    visual_profile: spec.role,
    dialogue_audio: index === 2 ? "bilingual_dialogue" : "voice_over",
    scene_ids: [`${spec.id}:scene`],
    start_frame: spec.start,
    duration_frames: spec.duration,
    transition_in: {
      type: index === 0 ? "none" : "fade_from_black",
      duration_frames: index === 0 ? 0 : 12,
      overlap_frames: 0 as const,
      accounting: "inside_section" as const,
      audio: index === 0 ? "none" : "fade_in",
    },
    transition_out: {
      type: index === 3 ? "none" : "dip_to_black",
      duration_frames: index === 3 ? 0 : 12,
      overlap_frames: 0 as const,
      accounting: "inside_section" as const,
      audio: index === 3 ? "none" : "fade_out",
    },
    assets: [{
      asset_id: `${spec.id}:asset`,
      source_key: spec.source,
      source_sha256: hash(String(index + 1)),
      provenance_hash: hash(String(index + 2)),
      caption_hash: hash(String(index + 3)),
      caption_card: {title: spec.role, fixture: "local synthetic"},
      actual_duration_ms: null,
      assigned_duration_ms: spec.duration * 1000 / 24,
      start_frame: 0,
      duration_frames: spec.duration,
      timing_transform: {
        mode: "static_hold" as const,
        source_duration_ms: null,
        output_duration_ms: spec.duration * 1000 / 24,
      },
      camera: {mode: "deterministic_remotion_frames"},
    }],
    audio: {
      mode: index === 2 ? "bilingual_dialogue" : "voice_over",
      sources: [{
        source_key: spec.audio,
        source_sha256: hash(String(index + 4)),
        source_duration_ms: spec.duration * 1000 / 24,
      }],
      timing_transform: {
        mode: "none" as const,
        source_duration_ms: spec.duration * 1000 / 24,
        output_duration_ms: spec.duration * 1000 / 24,
        atempo_chain: [],
        caption_scale: 1,
      },
      gain_db: 0,
    },
    captions: [{
      scene_id: `${spec.id}:scene`,
      text: index === 2 ? "Mara: Si puedes oírme. / Mara, if you can hear me." : `StoryEngine showcase: ${spec.role}`,
      language: index === 2 ? {mode: "bilingual", languages: ["es", "en"]} : {mode: "narration", languages: ["en"]},
      section_start_ms: 0,
      section_end_ms: spec.duration * 1000 / 24,
      start_frame: spec.start,
      end_frame: spec.start + spec.duration,
    }],
  })),
};

export const STORYENGINE_SHOWCASE_DEFAULT_PROPS: CustomFilmRemotionProps = {
  ...body,
  props_hash: sha256Hex(canonicalJson(body)),
};

export const STAGED_PROOF_SOURCE_KEYS = {
  image: "approved:staged:image:opening",
  video: "approved:staged:video:opening",
  audio: "approved:staged:audio:opening",
} as const;

const stagedBody: any = structuredClone(body);
stagedBody.identity.video_id = "storyengine-custom-film-showcase-staged-proof";
stagedBody.identity.assembly_manifest_hash = hash("b");
stagedBody.sections[0].assets = [
  {
    ...stagedBody.sections[0].assets[0],
    asset_id: "showcase-opening:staged-image",
    source_key: STAGED_PROOF_SOURCE_KEYS.image,
    source_sha256: "6678be4d336ddaa0cdbf8df41ef2fc04f2a3e754425d0c9fa78f4515d65bf055",
    provenance_hash: hash("c"),
    caption_hash: hash("d"),
    assigned_duration_ms: 2500,
    start_frame: 0,
    duration_frames: 60,
    timing_transform: {
      mode: "static_hold",
      source_duration_ms: null,
      output_duration_ms: 2500,
    },
  },
  {
    ...stagedBody.sections[0].assets[0],
    asset_id: "showcase-opening:staged-video",
    source_key: STAGED_PROOF_SOURCE_KEYS.video,
    source_sha256: "9fcfa7b28174c01b13d0f28c13e5a7d4b17497e52614438b116067a1980c2098",
    provenance_hash: hash("f"),
    caption_hash: hash("a"),
    actual_duration_ms: 2000,
    assigned_duration_ms: 42500,
    start_frame: 60,
    duration_frames: 1020,
    timing_transform: {
      mode: "repeat_then_trim",
      source_duration_ms: 2000,
      output_duration_ms: 42500,
      repeat_count: 22,
      final_repeat_duration_ms: 500,
    },
  },
];
stagedBody.sections[0].audio.sources = [{
  source_key: STAGED_PROOF_SOURCE_KEYS.audio,
  source_sha256: "69d66a6e55ba6f32888b6c392cd84e7ad77e9d73627c67dc63e329fa4118055d",
  source_duration_ms: 45000,
}];
stagedBody.sections[0].captions[0].text = "STAGED CAPTION · APPROVED LOCAL SOURCE";

export const STORYENGINE_SHOWCASE_STAGED_PROOF_PROPS: CustomFilmRemotionProps = {
  ...stagedBody,
  props_hash: sha256Hex(canonicalJson(stagedBody)),
};

const sourceClipBody: any = structuredClone(stagedBody);
sourceClipBody.identity.video_id = "storyengine-custom-film-showcase-source-clip-proof";
sourceClipBody.identity.assembly_manifest_hash = hash("e");
sourceClipBody.sections[0].assets = [{
  ...sourceClipBody.sections[0].assets[1],
  asset_id: "showcase-opening:source-clip-video",
  assigned_duration_ms: 45000,
  start_frame: 0,
  duration_frames: 1080,
  timing_transform: {
    mode: "repeat_then_trim",
    source_duration_ms: 2000,
    output_duration_ms: 45000,
    repeat_count: 23,
    final_repeat_duration_ms: 1000,
  },
}];
sourceClipBody.sections[0].audio = {
  mode: "source_clip",
  sources: [],
  timing_transform: {
    mode: "source_clip",
    source_duration_ms: 45000,
    output_duration_ms: 45000,
    atempo_chain: [],
    caption_scale: 1,
  },
  gain_db: -3,
};
sourceClipBody.sections[0].captions[0].text = "SOURCE CLIP · APPROVED NATIVE AUDIO";

export const STORYENGINE_SHOWCASE_SOURCE_CLIP_PROOF_PROPS: CustomFilmRemotionProps = {
  ...sourceClipBody,
  props_hash: sha256Hex(canonicalJson(sourceClipBody)),
};
