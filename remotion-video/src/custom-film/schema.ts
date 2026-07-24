import {z} from "zod";
import {canonicalJson, sha256Hex} from "./canonical";
import {assertExactFrameLayout, secondsToFrames} from "./frameMath";

export const REMOTION_PROPS_VERSION = "custom-film-remotion-props-v1" as const;

const hashSchema = z.string().regex(/^[0-9a-f]{64}$/);
const nonEmptyTextSchema = z.string().min(1);
const exactIntSchema = z.number().int().nonnegative();
const positiveIntSchema = z.number().int().positive();
const jsonObjectSchema = z.record(z.unknown());

const assetTimingTransformSchema = z.discriminatedUnion("mode", [
  z
    .object({
      mode: z.literal("none"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
    })
    .strict(),
  z
    .object({
      mode: z.literal("trim"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
      trim_start_ms: exactIntSchema,
      trim_end_ms: positiveIntSchema,
    })
    .strict(),
  z
    .object({
      mode: z.literal("repeat_then_trim"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
      repeat_count: positiveIntSchema,
      final_repeat_duration_ms: positiveIntSchema,
    })
    .strict(),
  z
    .object({
      mode: z.literal("static_hold"),
      source_duration_ms: z.null(),
      output_duration_ms: positiveIntSchema,
    })
    .strict(),
]);

const audioTimingTransformSchema = z.discriminatedUnion("mode", [
  z
    .object({
      mode: z.literal("none"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
      atempo_chain: z.array(z.number().positive()),
      caption_scale: z.number().positive(),
    })
    .strict(),
  z
    .object({
      mode: z.literal("source_clip"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
      atempo_chain: z.array(z.number().positive()),
      caption_scale: z.number().positive(),
    })
    .strict(),
  z
    .object({
      mode: z.literal("atempo"),
      source_duration_ms: positiveIntSchema,
      output_duration_ms: positiveIntSchema,
      atempo_chain: z.array(z.number().positive()).min(1),
      caption_scale: z.number().positive(),
    })
    .strict(),
  z
    .object({
      mode: z.literal("pending_source_probe"),
      source_duration_ms: z.null(),
      output_duration_ms: positiveIntSchema,
      atempo_chain: z.array(z.number().positive()),
      caption_scale: z.null(),
    })
    .strict(),
]);

const transitionSchema = z
  .object({
    type: nonEmptyTextSchema,
    duration_frames: exactIntSchema,
    overlap_frames: z.literal(0),
    accounting: z.literal("inside_section"),
    audio: nonEmptyTextSchema,
  })
  .strict();

const assetSchema = z
  .object({
    asset_id: nonEmptyTextSchema,
    source_key: nonEmptyTextSchema,
    source_sha256: hashSchema,
    provenance_hash: hashSchema,
    caption_hash: hashSchema,
    caption_card: jsonObjectSchema.nullable(),
    actual_duration_ms: positiveIntSchema.nullable(),
    assigned_duration_ms: positiveIntSchema.nullable(),
    start_frame: exactIntSchema,
    duration_frames: positiveIntSchema,
    timing_transform: assetTimingTransformSchema,
    camera: jsonObjectSchema,
  })
  .strict();

const captionSchema = z
  .object({
    scene_id: nonEmptyTextSchema,
    text: nonEmptyTextSchema,
    language: jsonObjectSchema,
    section_start_ms: exactIntSchema,
    section_end_ms: positiveIntSchema,
    start_frame: exactIntSchema,
    end_frame: positiveIntSchema,
  })
  .strict();

const sectionSchema = z
  .object({
    section_id: nonEmptyTextSchema,
    order_index: exactIntSchema,
    role: nonEmptyTextSchema,
    render_mode: nonEmptyTextSchema,
    visual_profile: nonEmptyTextSchema,
    dialogue_audio: nonEmptyTextSchema,
    scene_ids: z.array(nonEmptyTextSchema).min(1),
    start_frame: exactIntSchema,
    duration_frames: positiveIntSchema,
    transition_in: transitionSchema,
    transition_out: transitionSchema,
    assets: z.array(assetSchema).min(1),
    audio: z
      .object({
        mode: nonEmptyTextSchema,
        sources: z.array(
          z
            .object({
              source_key: nonEmptyTextSchema,
              source_sha256: hashSchema,
              source_duration_ms: positiveIntSchema,
            })
            .strict(),
        ),
        timing_transform: audioTimingTransformSchema,
        gain_db: z.number().finite().min(-120),
      })
      .strict(),
    captions: z.array(captionSchema).min(1),
  })
  .strict();

export const CustomFilmRemotionPropsSchema = z
  .object({
    schema_version: z.literal(REMOTION_PROPS_VERSION),
    identity: z
      .object({
        assembly_version: nonEmptyTextSchema,
        assembly_manifest_hash: hashSchema,
        tenant_id: nonEmptyTextSchema,
        video_id: nonEmptyTextSchema,
        plan_id: nonEmptyTextSchema,
        plan_hash: hashSchema,
        quote_inputs_hash: hashSchema,
        approval_hash: hashSchema,
        runtime_hash: hashSchema,
        runtime_job_id: nonEmptyTextSchema,
        max_spend: z.number().finite().nonnegative(),
        render_engine: z.enum(["ffmpeg", "remotion"]),
        renderer_contract_version: z
          .literal("custom-film-remotion-renderer-v1")
          .optional(),
        renderer_bundle_hash: hashSchema.optional(),
      })
      .strict(),
    video: z
      .object({
        fps: positiveIntSchema,
        width: positiveIntSchema,
        height: positiveIntSchema,
        total_duration_seconds: positiveIntSchema,
        total_frames: positiveIntSchema,
      })
      .strict(),
    transition_accounting: z
      .object({
        type: nonEmptyTextSchema,
        duration_source: nonEmptyTextSchema,
        overlap_frames_total: z.literal(0),
        duration_lives_inside_assigned_sections: z.literal(true),
      })
      .strict(),
    sections: z.array(sectionSchema).min(1),
    props_hash: hashSchema,
  })
  .strict()
  .superRefine((props, context) => {
    const isAssemblyV3 = props.identity.assembly_version === "custom-film-assembly-v3";
    const hasRendererIdentity =
      props.identity.renderer_contract_version ===
        "custom-film-remotion-renderer-v1" &&
      typeof props.identity.renderer_bundle_hash === "string";
    if (isAssemblyV3 !== hasRendererIdentity) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Custom Film renderer identity does not match assembly version",
        path: ["identity", "renderer_contract_version"],
      });
    }
    const {props_hash: propsHash, ...body} = props;
    if (sha256Hex(canonicalJson(body)) !== propsHash) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Custom Film Remotion props hash changed",
        path: ["props_hash"],
      });
    }
    if (
      props.video.total_frames !==
      secondsToFrames(
        props.video.total_duration_seconds,
        props.video.fps,
      )
    ) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Custom Film duration and total frame identity changed",
        path: ["video", "total_frames"],
      });
    }
    try {
      assertExactFrameLayout(props.sections, props.video.total_frames);
    } catch (error) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          error instanceof Error ? error.message : "Invalid frame layout",
        path: ["sections"],
      });
    }
    for (const [sectionIndex, section] of props.sections.entries()) {
      for (const [captionIndex, caption] of section.captions.entries()) {
        const expectedStart =
          section.start_frame +
          Math.floor((caption.section_start_ms * props.video.fps) / 1000);
        const expectedEnd =
          section.start_frame +
          Math.floor((caption.section_end_ms * props.video.fps) / 1000);
        if (
          caption.start_frame !== expectedStart ||
          caption.end_frame !== expectedEnd ||
          !section.scene_ids.includes(caption.scene_id)
        ) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Custom Film caption timing or scene identity changed",
            path: ["sections", sectionIndex, "captions", captionIndex],
          });
        }
      }
    }
  });

export type CustomFilmRemotionProps = z.infer<
  typeof CustomFilmRemotionPropsSchema
>;

export const validateCustomFilmRemotionProps = (
  value: unknown,
): CustomFilmRemotionProps => CustomFilmRemotionPropsSchema.parse(value);
