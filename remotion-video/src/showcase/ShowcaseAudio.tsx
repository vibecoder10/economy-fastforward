import React from "react";
import {Audio} from "@remotion/media";
import {Sequence, staticFile, useCurrentFrame} from "remotion";
import {SHOWCASE_AUDIO_CUES, showcaseBedGain} from "./timing";

const ContinuousBed: React.FC = () => {
  const absoluteFrame = useCurrentFrame();
  return (
    <Audio
      loop
      src={staticFile("motion-audio/music-bed.wav")}
      volume={showcaseBedGain(absoluteFrame) * 0.22}
    />
  );
};

export const ShowcaseAudio: React.FC = () => (
  <>
    <Sequence from={0} durationInFrames={7200} premountFor={24}>
      <ContinuousBed />
    </Sequence>
    {SHOWCASE_AUDIO_CUES.map((cue) => (
      <Sequence
        key={cue.id}
        name={cue.id}
        from={cue.from}
        durationInFrames={cue.to - cue.from + 1}
        premountFor={24}
      >
        <Audio
          loop={cue.loop}
          src={staticFile(cue.path)}
          volume={(frame) => {
            const duration = cue.to - cue.from + 1;
            const edge = Math.min(1, frame / 12, (duration - frame) / 12);
            return Math.max(0, edge) * 0.28;
          }}
        />
      </Sequence>
    ))}
  </>
);
