import React from "react";
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {COLORS, motifValue} from "./theme";
import {SIGNAL_PULSE_CYCLE_SECONDS, signalPulseCycleFrame} from "./contracts";
import {useMotionTimelineFrame} from "./MotionTimelineContext";

export const SignalPulse: React.FC<{
  phase?: number;
  compact?: boolean;
  timelineFrame?: number;
}> = ({phase = 0, compact = false, timelineFrame}) => {
  const localFrame = useCurrentFrame();
  const inheritedTimelineFrame = useMotionTimelineFrame();
  const frame = timelineFrame ?? inheritedTimelineFrame ?? localFrame;
  const {fps} = useVideoConfig();
  const pulse = motifValue(frame, fps);
  const travel = interpolate(
    signalPulseCycleFrame(frame, fps),
    [0, fps * SIGNAL_PULSE_CYCLE_SECONDS],
    [-8, 108],
  );
  const size = compact ? 58 : 260;
  return (
    <AbsoluteFill style={{pointerEvents: "none"}}>
      <div
        style={{
          position: "absolute",
          left: compact ? 142 + phase * 2 : 820,
          top: compact ? 64 + (phase % 3) * 2 : 370,
          width: size,
          height: size,
          borderRadius: "50%",
          border: `2px solid ${COLORS.turquoise}`,
          opacity: pulse * 0.8,
          transform: `scale(${0.72 + pulse * 0.45})`,
          boxShadow: `0 0 ${20 + pulse * 80}px ${COLORS.turquoiseDim}`,
        }}
      />
      <div
        style={{
          position: "absolute",
          left: compact ? 170 : 340,
          right: compact ? 170 : 340,
          top: compact ? 92 : 500,
          height: 2,
          background: `linear-gradient(90deg, transparent, ${COLORS.turquoise}, transparent)`,
          opacity: 0.35 + pulse * 0.5,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: `${travel}%`,
            top: -4,
            width: 10,
            height: 10,
            borderRadius: "50%",
            background: COLORS.turquoise,
            boxShadow: `0 0 24px ${COLORS.turquoise}`,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};
