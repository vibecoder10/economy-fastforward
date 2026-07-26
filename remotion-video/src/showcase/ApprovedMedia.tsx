import React from "react";
import {Audio} from "@remotion/media";
import {
  AbsoluteFill,
  Img,
  Loop,
  OffthreadVideo,
  Sequence,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import type {CustomFilmRemotionProps} from "../custom-film/schema";
import {CENTER_CROP_BOUNDS} from "../motion-library/contracts";
import {COLORS, FONT_FAMILY} from "../motion-library/theme";
import type {ShowcaseMediaSlot} from "./manifest";
import type {LayeredSceneRecipe} from "./orchestration";
import {
  approvedCaptionOpacity,
  approvedMediaOpacity,
  recipeBedGain,
  recipeCaptionOpacity,
  recipeMediaOpacity,
  showcaseBedGain,
} from "./timing";

const ApprovedVisual: React.FC<{
  slot: Extract<ShowcaseMediaSlot, {kind: "visual"}>;
  slots: ReadonlyArray<ShowcaseMediaSlot>;
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  reference: boolean;
}> = ({slot, slots, recipes, reference}) => {
  const frame = useCurrentFrame();
  const absoluteFrame = slot.startFrame + frame;
  const nativeAudioGain = 10 ** (slot.nativeAudioGainDb / 20);
  const loopDurationInFrames = Math.max(
    1,
    Math.round(
      (slot.sourceDurationFrames ?? slot.durationInFrames) /
      slot.nativeAudioPlaybackRate,
    ),
  );
  const recipe = recipes.find(({from, to}) => absoluteFrame >= from && absoluteFrame <= to);
  if (!recipe) throw new Error("Approved visual has no orchestration recipe");
  const mediaOpacity = reference
    ? approvedMediaOpacity(slot.role, absoluteFrame)
    : recipeMediaOpacity(recipe);
  const overlapping = slots.filter(
    (candidate) =>
      candidate.kind === "visual" &&
      candidate.startFrame <= recipe.to &&
      candidate.startFrame + candidate.durationInFrames - 1 >= recipe.from,
  );
  const layerRank = overlapping.findIndex(({sourceKey}) => sourceKey === slot.sourceKey);
  const isSecondary = layerRank === 1;
  if (layerRank > 1) return null;
  const cameraScale = recipe.camera.mode === "locked"
    ? 1
    : 1 + recipe.camera.intensity * (recipe.camera.mode === "reactive-push" ? .065 : .04);
  const zoom = interpolate(
    frame,
    [0, Math.max(1, slot.durationInFrames - 1)],
    [1, cameraScale],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp"},
  );
  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: `scale(${zoom}) translateX(${recipe.camera.mode === "investigative-drift" ? Math.sin(frame / 50) * 1.2 : 0}%)`,
  };
  return (
    <div
      data-approved-source-key={slot.sourceKey}
      data-approved-source-sha256={slot.sourceSha256}
      data-approved-layer={isSecondary ? "secondary" : "primary"}
      data-approved-camera={recipe.camera.mode}
      style={{
        position: "absolute",
        left: 150,
        right: 150,
        top: 145,
        bottom: 190,
        overflow: "hidden",
        border: `2px solid ${COLORS.turquoise}`,
        boxShadow: "0 24px 70px rgba(0,0,0,.5)",
        opacity: mediaOpacity * (isSecondary ? recipe.media.secondaryIntensity : 1),
        zIndex: isSecondary ? recipe.media.secondaryZIndex : recipe.media.primaryZIndex,
        mixBlendMode: isSecondary ? recipe.media.secondaryBlend : "normal",
      }}
    >
      {slot.mediaType === "image" ? (
        <Img src={staticFile(slot.localPath)} style={style} />
      ) : (
        <Loop durationInFrames={loopDurationInFrames}>
          <OffthreadVideo
            muted={!slot.nativeAudioEnabled}
            playbackRate={slot.nativeAudioPlaybackRate}
            src={staticFile(slot.localPath)}
            style={style}
            volume={
              slot.nativeAudioEnabled
                ? (
                    reference
                      ? showcaseBedGain(absoluteFrame)
                      : recipeBedGain(recipe, absoluteFrame)
                  ) * nativeAudioGain
                : 0
            }
          />
        </Loop>
      )}
      <div style={{position: "absolute", left: 18, top: 18, padding: "8px 12px", background: "rgba(2,8,10,.82)", color: COLORS.turquoise, fontFamily: FONT_FAMILY, fontSize: 15, letterSpacing: 2}}>
        APPROVED {slot.mediaType.toUpperCase()} · {slot.role.toUpperCase()}
      </div>
    </div>
  );
};

const ApprovedAudioTrack: React.FC<{
  slot: Extract<ShowcaseMediaSlot, {kind: "audio"}>;
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  reference: boolean;
}> = ({slot, recipes, reference}) => {
  const localFrame = useCurrentFrame();
  const absoluteFrame = slot.startFrame + localFrame;
  const approvedGain = 10 ** (slot.gainDb / 20);
  const recipe = recipes.find(
    ({from, to}) => absoluteFrame >= from && absoluteFrame <= to,
  );
  if (!recipe) throw new Error("Approved audio has no orchestration recipe");
  return (
    <Audio
      playbackRate={slot.playbackRate}
      trimBefore={slot.sourceTrimStartFrame ?? undefined}
      trimAfter={slot.sourceTrimEndFrame ?? undefined}
      src={staticFile(slot.localPath)}
      volume={
        (
          reference
            ? showcaseBedGain(absoluteFrame)
            : recipeBedGain(recipe, absoluteFrame)
        ) * approvedGain
      }
    />
  );
};

export const ApprovedMediaLayer: React.FC<{
  slots: ReadonlyArray<ShowcaseMediaSlot>;
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  reference: boolean;
}> = ({slots, recipes, reference}) => {
  const {fps} = useVideoConfig();
  return <AbsoluteFill style={{zIndex: 10}}>
    {slots.map((slot) => {
      if (slot.kind === "procedural") return null;
      if (slot.kind === "visual") {
        return (
          <Sequence
            key={`visual:${slot.sourceKey}`}
            name={`approved-visual:${slot.sectionId}`}
            from={slot.startFrame}
            durationInFrames={slot.durationInFrames}
            premountFor={fps}
          >
            <ApprovedVisual slot={slot} slots={slots} recipes={recipes} reference={reference} />
          </Sequence>
        );
      }
      if (slot.sourceKey.startsWith("synthetic:")) return null;
      return (
        <Sequence
          key={`audio:${slot.sourceKey}:${slot.sourceIndex}:${slot.startFrame}`}
          name={`approved-audio:${slot.sectionId}`}
          from={slot.startFrame}
          durationInFrames={slot.durationInFrames}
          premountFor={fps}
        >
          <ApprovedAudioTrack slot={slot} recipes={recipes} reference={reference} />
        </Sequence>
      );
    })}
  </AbsoluteFill>;
};

export const ApprovedCaptionLayer: React.FC<{
  sections: CustomFilmRemotionProps["sections"];
  recipes: ReadonlyArray<LayeredSceneRecipe>;
  reference: boolean;
}> = ({sections, recipes, reference}) => {
  const absoluteFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <AbsoluteFill style={{pointerEvents: "none", zIndex: 100}}>
    {sections.flatMap((section) =>
      section.captions.map((caption) => (
        <Sequence
          key={`${section.section_id}:${caption.scene_id}:${caption.start_frame}`}
          name={`approved-caption:${caption.scene_id}`}
          from={caption.start_frame}
          durationInFrames={caption.end_frame - caption.start_frame}
          premountFor={fps}
        >
          <div
            data-approved-caption-scene={caption.scene_id}
            data-caption-recipe={recipes.find(({from, to}) => caption.start_frame >= from && caption.start_frame <= to)?.id}
            style={{
              position: "absolute",
              left: CENTER_CROP_BOUNDS.criticalX,
              width: CENTER_CROP_BOUNDS.criticalWidth,
              top: 760,
              boxSizing: "border-box",
              padding: "12px 18px",
              background: "rgba(2,8,10,.82)",
              borderLeft: `4px solid ${section.role === "case_study" ? COLORS.amber : COLORS.turquoise}`,
              color: COLORS.cream,
              fontFamily: FONT_FAMILY,
              fontSize: 20,
              lineHeight: 1.3,
              textAlign: "center",
              opacity: reference
                ? approvedCaptionOpacity(section.role, absoluteFrame)
                : recipeCaptionOpacity(
                    recipes.find(({from, to}) =>
                      absoluteFrame >= from && absoluteFrame <= to,
                    )!,
                  ),
            }}
          >
            {caption.text}
          </div>
        </Sequence>
      )),
    )}
    </AbsoluteFill>
  );
};
