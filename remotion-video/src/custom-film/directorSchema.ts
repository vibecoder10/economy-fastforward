import {z} from "zod";
import {canonicalJson, sha256Hex} from "./canonical";

export const DIRECTOR_REMOTION_PROPS_VERSION =
  "custom-film-director-remotion-v1" as const;

const hashSchema = z.string().regex(/^[0-9a-f]{64}$/);
const textSchema = z.string().min(1);
const frameSchema = z.number().int().nonnegative();
const positiveFrameSchema = z.number().int().positive();

const sourceSchema = z
  .object({
    source_key: textSchema,
    local_path: textSchema,
    source_sha256: hashSchema,
  })
  .strict();

const measuredWordSchema = z
  .object({
    text: textSchema,
    from_frame: frameSchema,
    to_frame: positiveFrameSchema,
  })
  .strict();

const spokenLineSchema = z
  .object({
    line_index: frameSchema,
    speaker_id: textSchema,
    kind: z.enum(["dialogue", "narration"]),
    text: textSchema,
    source: sourceSchema,
    start_frame: frameSchema,
    end_frame: positiveFrameSchema,
    measured_words: z.array(measuredWordSchema).min(1),
  })
  .strict();

const soundLayerSchema = z
  .object({
    layer_id: textSchema,
    kind: z.enum(["ambient", "score", "sfx"]),
    source: sourceSchema,
    start_frame: frameSchema,
    end_frame: positiveFrameSchema,
    gain_db: z.number().finite().min(-120).max(12),
    loop: z.boolean(),
  })
  .strict();

const shotSchema = z
  .object({
    shot_id: textSchema,
    shot_key: textSchema,
    section_id: textSchema,
    order_index: frameSchema,
    start_frame: frameSchema,
    end_frame: frameSchema,
    duration_frames: positiveFrameSchema,
    technique: z.enum([
      "poco_dialogue",
      "dvsu_documentary",
      "power_doctrine_exposition",
      "cinematic_action",
    ]),
    performance_mode: z.enum(["dialogue", "exposition", "silent_action"]),
    caption_mode: z.enum(["dialogue", "narration", "none"]),
    transition_from_previous: z.enum([
      "opening",
      "continuous",
      "time_cut",
      "location_cut",
      "montage",
      "memory",
    ]),
    transition_duration_frames: frameSchema,
    clip: sourceSchema,
    spoken_lines: z.array(spokenLineSchema),
    sound_layers: z.array(soundLayerSchema).min(1),
  })
  .strict();

export const DirectorRemotionPropsSchema = z
  .object({
    schema_version: z.literal(DIRECTOR_REMOTION_PROPS_VERSION),
    identity: z
      .object({
        director_contract_hash: hashSchema,
        storyboard_gate_hash: hashSchema,
        picture_gate_hash: hashSchema,
        visual_gate_hash: hashSchema,
        admission_hash: hashSchema,
      })
      .strict(),
    video: z
      .object({
        fps: positiveFrameSchema,
        width: positiveFrameSchema,
        height: positiveFrameSchema,
        total_frames: positiveFrameSchema,
      })
      .strict(),
    shots: z.array(shotSchema).min(1),
    props_hash: hashSchema,
  })
  .strict()
  .superRefine((props, context) => {
    const {props_hash: propsHash, ...body} = props;
    if (sha256Hex(canonicalJson(body)) !== propsHash) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Custom Film director Remotion props hash changed",
        path: ["props_hash"],
      });
    }
    const shotIds = new Set<string>();
    let nextFrame = 0;
    for (const [shotIndex, shot] of props.shots.entries()) {
      const path = ["shots", shotIndex];
      if (
        shot.order_index !== shotIndex ||
        shotIds.has(shot.shot_id) ||
        shot.start_frame !== nextFrame ||
        shot.end_frame !== shot.start_frame + shot.duration_frames - 1
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Custom Film director shot timing or identity changed",
          path,
        });
      }
      shotIds.add(shot.shot_id);
      nextFrame = shot.end_frame + 1;

      const isOpening = shotIndex === 0;
      if (
        (isOpening && shot.transition_from_previous !== "opening") ||
        (!isOpening && shot.transition_from_previous === "opening") ||
        (["opening", "continuous"].includes(shot.transition_from_previous) &&
          shot.transition_duration_frames !== 0) ||
        (!["opening", "continuous"].includes(shot.transition_from_previous) &&
          (shot.transition_duration_frames < 1 ||
            shot.transition_duration_frames >= shot.duration_frames))
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Custom Film director transition accounting changed",
          path: [...path, "transition_duration_frames"],
        });
      }

      const expectedCaptionMode =
        shot.performance_mode === "dialogue"
          ? "dialogue"
          : shot.performance_mode === "exposition"
            ? "narration"
            : "none";
      if (
        shot.caption_mode !== expectedCaptionMode ||
        (shot.performance_mode === "silent_action" &&
          shot.spoken_lines.length !== 0)
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Custom Film director caption ownership changed",
          path: [...path, "caption_mode"],
        });
      }
      if (shot.performance_mode === "dialogue") {
        const speakers = shot.spoken_lines.map(({speaker_id}) => speaker_id);
        if (
          shot.spoken_lines.length < 2 ||
          new Set(speakers).size < 2 ||
          shot.spoken_lines.some(({kind}) => kind !== "dialogue") ||
          speakers.some(
            (speaker, index) => index > 0 && speaker === speakers[index - 1],
          )
        ) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Custom Film director dialogue performance changed",
            path: [...path, "spoken_lines"],
          });
        }
      }
      if (
        shot.performance_mode === "exposition" &&
        (shot.spoken_lines.length < 1 ||
          shot.spoken_lines.some(({kind}) => kind !== "narration"))
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Custom Film director narration ownership changed",
          path: [...path, "spoken_lines"],
        });
      }

      for (const [lineIndex, line] of shot.spoken_lines.entries()) {
        const words = line.measured_words;
        const normalizedWords = words
          .map(({text}) => text)
          .join("")
          .replace(/\s+/g, " ")
          .trim();
        const normalizedLine = line.text.replace(/\s+/g, " ").trim();
        if (
          line.line_index !== lineIndex ||
          line.start_frame < shot.start_frame ||
          line.end_frame > shot.end_frame + 1 ||
          line.end_frame <= line.start_frame ||
          words[0]?.from_frame !== line.start_frame ||
          words[words.length - 1]?.to_frame !== line.end_frame ||
          words.some(
            (word, wordIndex) =>
              word.from_frame < line.start_frame ||
              word.to_frame > line.end_frame ||
              word.to_frame <= word.from_frame ||
              (wordIndex > 0 &&
                word.from_frame < words[wordIndex - 1].to_frame),
          ) ||
          normalizedWords !== normalizedLine
        ) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Custom Film measured caption timing changed",
            path: [...path, "spoken_lines", lineIndex],
          });
        }
      }
      for (const [layerIndex, layer] of shot.sound_layers.entries()) {
        if (
          layer.start_frame < shot.start_frame ||
          layer.end_frame > shot.end_frame + 1 ||
          layer.end_frame <= layer.start_frame
        ) {
          context.addIssue({
            code: z.ZodIssueCode.custom,
            message: "Custom Film sound layer timing changed",
            path: [...path, "sound_layers", layerIndex],
          });
        }
      }
    }
    if (nextFrame !== props.video.total_frames) {
      context.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Custom Film director timeline does not fill the film",
        path: ["video", "total_frames"],
      });
    }
  });

export type DirectorRemotionProps = z.infer<
  typeof DirectorRemotionPropsSchema
>;

export const validateDirectorRemotionProps = (
  value: unknown,
): DirectorRemotionProps => DirectorRemotionPropsSchema.parse(value);

export const withDirectorPropsHash = (
  body: Omit<DirectorRemotionProps, "props_hash">,
): DirectorRemotionProps =>
  validateDirectorRemotionProps({
    ...body,
    props_hash: sha256Hex(canonicalJson(body)),
  });
