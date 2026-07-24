import React from "react";
import {AbsoluteFill, Sequence, useCurrentFrame} from "remotion";
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
  const manifest = compileShowcaseManifest(input);
  return (
    <MotionTimelineProvider value={showcasePulseFrame(absoluteFrame)}>
      <AbsoluteFill>
        {manifest.cues.map((cue) => (
          <Sequence
            key={cue.id}
            name={cue.id}
            from={cue.from}
            durationInFrames={cue.durationInFrames}
            premountFor={24}
          >
            <ShowcaseCueScene cue={cue} />
          </Sequence>
        ))}
        <ApprovedMediaLayer slots={manifest.media_slots} />
        <ShowcaseAudio />
        <ApprovedCaptionLayer sections={input.sections} />
      </AbsoluteFill>
    </MotionTimelineProvider>
  );
};
