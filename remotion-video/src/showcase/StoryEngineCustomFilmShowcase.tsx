import React from "react";
import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig} from "remotion";
import type {CustomFilmRemotionProps} from "../custom-film/schema";
import {MotionTimelineProvider} from "../motion-library/MotionTimelineContext";
import {ShowcaseCueScene} from "./ShowcaseScene";
import {ShowcaseAudio} from "./ShowcaseAudio";
import {compileShowcaseManifest} from "./manifest";
import {showcasePulseFrame} from "./timing";
import {ApprovedCaptionLayer, ApprovedMediaLayer} from "./ApprovedMedia";

export const StoryEngineCustomFilmShowcase: React.FC<CustomFilmRemotionProps> = (
  input,
) => {
  const absoluteFrame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const manifest = compileShowcaseManifest(input);
  return (
    <MotionTimelineProvider value={showcasePulseFrame(absoluteFrame)}>
      <AbsoluteFill>
        <ApprovedMediaLayer
          slots={manifest.media_slots}
          recipes={manifest.recipes}
          reference={manifest.reference_authored_timing}
        />
        {manifest.recipes.map((cue) => (
          <Sequence
            key={cue.id}
            name={cue.id}
            from={cue.from}
            durationInFrames={cue.durationInFrames}
            premountFor={fps}
          >
            <ShowcaseCueScene cue={cue} />
          </Sequence>
        ))}
        <ShowcaseAudio
          recipes={manifest.recipes}
          totalFrames={input.video.total_frames}
          fps={fps}
          reference={manifest.reference_authored_timing}
        />
        <ApprovedCaptionLayer
          sections={input.sections}
          recipes={manifest.recipes}
          reference={manifest.reference_authored_timing}
        />
      </AbsoluteFill>
    </MotionTimelineProvider>
  );
};
