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
} from "remotion";
import type {CustomFilmRemotionProps} from "../custom-film/schema";
import {CENTER_CROP_BOUNDS} from "../motion-library/contracts";
import {COLORS, FONT_FAMILY} from "../motion-library/theme";
import type {ShowcaseMediaSlot} from "./manifest";
import {
  approvedCaptionOpacity,
  approvedMediaOpacity,
  showcaseBedGain,
} from "./timing";

const ApprovedVisual: React.FC<{
  slot: Extract<ShowcaseMediaSlot, {kind: "visual"}>;
}> = ({slot}) => {
  const frame = useCurrentFrame();
  const absoluteFrame = slot.startFrame + frame;
  const mediaOpacity = approvedMediaOpacity(slot.role, absoluteFrame);
  const nativeAudioGain = 10 ** (slot.nativeAudioGainDb / 20);
  const loopDurationInFrames = Math.max(
    1,
    Math.round(
      (slot.sourceDurationFrames ?? slot.durationInFrames) /
      slot.nativeAudioPlaybackRate,
    ),
  );
  const zoom = interpolate(
    frame,
    [0, Math.max(1, slot.durationInFrames - 1)],
    [1, 1.035],
    {extrapolateLeft: "clamp", extrapolateRight: "clamp"},
  );
  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "cover",
    transform: `scale(${zoom})`,
  };
  return (
    <div
      data-approved-source-key={slot.sourceKey}
      data-approved-source-sha256={slot.sourceSha256}
      style={{
        position: "absolute",
        left: 150,
        right: 150,
        top: 145,
        bottom: 190,
        overflow: "hidden",
        border: `2px solid ${COLORS.turquoise}`,
        boxShadow: "0 24px 70px rgba(0,0,0,.5)",
        opacity: mediaOpacity,
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
                ? showcaseBedGain(absoluteFrame) * nativeAudioGain
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
}> = ({slot}) => {
  const localFrame = useCurrentFrame();
  const absoluteFrame = slot.startFrame + localFrame;
  const approvedGain = 10 ** (slot.gainDb / 20);
  return (
    <Audio
      playbackRate={slot.playbackRate}
      src={staticFile(slot.localPath)}
      volume={showcaseBedGain(absoluteFrame) * approvedGain}
    />
  );
};

export const ApprovedMediaLayer: React.FC<{
  slots: ReadonlyArray<ShowcaseMediaSlot>;
}> = ({slots}) => (
  <AbsoluteFill>
    {slots.map((slot) => {
      if (slot.kind === "procedural") return null;
      if (slot.kind === "visual") {
        return (
          <Sequence
            key={`visual:${slot.sourceKey}`}
            name={`approved-visual:${slot.sectionId}`}
            from={slot.startFrame}
            durationInFrames={slot.durationInFrames}
            premountFor={24}
          >
            <ApprovedVisual slot={slot} />
          </Sequence>
        );
      }
      if (slot.sourceKey.startsWith("synthetic:")) return null;
      return (
        <Sequence
          key={`audio:${slot.sourceKey}`}
          name={`approved-audio:${slot.sectionId}`}
          from={slot.startFrame}
          durationInFrames={slot.durationInFrames}
          premountFor={24}
        >
          <ApprovedAudioTrack slot={slot} />
        </Sequence>
      );
    })}
  </AbsoluteFill>
);

export const ApprovedCaptionLayer: React.FC<{
  sections: CustomFilmRemotionProps["sections"];
}> = ({sections}) => {
  const absoluteFrame = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
    {sections.flatMap((section) =>
      section.captions.map((caption) => (
        <Sequence
          key={`${section.section_id}:${caption.scene_id}:${caption.start_frame}`}
          name={`approved-caption:${caption.scene_id}`}
          from={caption.start_frame}
          durationInFrames={caption.end_frame - caption.start_frame}
          premountFor={24}
        >
          <div
            data-approved-caption-scene={caption.scene_id}
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
              opacity: approvedCaptionOpacity(
                section.role,
                absoluteFrame,
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
