import React from "react";
import {AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig} from "remotion";
import {BilingualCaptions} from "./BilingualCaptions";
import {EvidenceBoard} from "./EvidenceBoard";
import {IncidentTimeline} from "./IncidentTimeline";
import {MotionAudioSystem} from "./MotionAudioSystem";
import {NetworkExplainer} from "./NetworkExplainer";
import {OutageMap} from "./OutageMap";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {RadioWaveform} from "./RadioWaveform";
import {SignalPulse} from "./SignalPulse";
import {StoryEngineReveal} from "./StoryEngineReveal";
import {previewSegments} from "./contracts";
import {COLORS} from "./theme";
import {MotionTimelineProvider} from "./MotionTimelineContext";

const SignalPulseDemo: React.FC = () => (
  <PrimitiveFrame kicker="Recurring story / brand motif" title="Signal pulse">
    <SignalPulse />
    <div style={{position: "absolute", left: 630, right: 630, top: 660, textAlign: "center", color: COLORS.cream, fontSize: 24}}>
      One signal, evolving through every section.
    </div>
  </PrimitiveFrame>
);

const PRIMITIVES = [
  SignalPulseDemo,
  OutageMap,
  EvidenceBoard,
  IncidentTimeline,
  RadioWaveform,
  BilingualCaptions,
  NetworkExplainer,
  StoryEngineReveal,
  MotionAudioSystem,
] as const;

export const MotionLibraryPreview: React.FC = () => {
  const {fps} = useVideoConfig();
  const timelineFrame = useCurrentFrame();
  const segments = previewSegments(fps);
  return (
    <AbsoluteFill>
      {segments.map((segment, index) => {
        const Component = PRIMITIVES[index];
        return (
          <Sequence
            key={segment.name}
            name={segment.name}
            from={segment.from}
            durationInFrames={segment.durationInFrames}
            premountFor={fps}
          >
            <MotionTimelineProvider value={timelineFrame}>
              <Component />
            </MotionTimelineProvider>
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
