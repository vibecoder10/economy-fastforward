import React from "react";
import {Audio} from "@remotion/media";
import {Sequence, staticFile, useCurrentFrame, useVideoConfig} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";
import {CropSafeColumn} from "./CropSafe";
import {
  SILENCE_DROP_WINDOW_SECONDS,
  motionBedGain,
  motionMixGains,
  pulseEntryGain,
} from "./contracts";

const Meter: React.FC<{label: string; level: number; top: number}> = ({label, level, top}) => <div style={{position: "absolute", left: 300, right: 300, top, display: "grid", gridTemplateColumns: "260px 1fr", alignItems: "center", gap: 24}}>
  <div style={{fontSize: 23, color: COLORS.cream}}>{label}</div><div style={{height: 18, background: "#152c32"}}><div style={{height: "100%", width: `${level * 100}%`, background: COLORS.turquoise}} /></div>
</div>;

export const MotionAudioSystem: React.FC<{segmentDurationInFrames?: number}> = ({
  segmentDurationInFrames,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const durationInFrames = segmentDurationInFrames ?? fps * 4;
  const gains = motionMixGains(frame, fps);
  const pulse = gains.pulse;
  const bed = gains.bed;
  const silenceStart = Math.round(SILENCE_DROP_WINDOW_SECONDS.start * fps);
  const silenceEnd = Math.round(SILENCE_DROP_WINDOW_SECONDS.end * fps);
  const silenceCueFrames = Math.max(1, Math.round(0.18 * fps));
  return <PrimitiveFrame kicker="Synthetic local fixtures" title="Motion audio system">
    <CropSafeColumn top={285} bottom={250}>
      <div style={{fontSize: 18, letterSpacing: 3, color: frame >= silenceStart && frame < silenceEnd ? COLORS.amber : COLORS.turquoise}}>
        {frame >= silenceStart && frame < silenceEnd ? "SILENCE DROP" : pulse > 0 ? "PULSE ENTRY" : "MIX ACTIVE"}
      </div>
    </CropSafeColumn>
    <Meter label="Music bed / ducking" level={bed} top={360} />
    <Meter label="Signal pulse entry" level={pulse} top={455} />
    <Meter label="Data clicks" level={gains.clicks} top={550} />
    <Meter label="Transition envelope" level={gains.transition} top={645} />
    <Sequence premountFor={fps} from={0} durationInFrames={durationInFrames}><Audio src={staticFile("motion-audio/music-bed.wav")} volume={(audioFrame) => motionBedGain(audioFrame, fps) * .22} /></Sequence>
    <Sequence premountFor={fps} from={silenceStart - silenceCueFrames} durationInFrames={silenceCueFrames}><Audio src={staticFile("motion-audio/silence-drop.wav")} volume={(audioFrame) => motionMixGains(audioFrame + silenceStart - silenceCueFrames, fps).silenceCue} /></Sequence>
    <Sequence premountFor={fps} from={silenceEnd} durationInFrames={Math.min(fps, Math.max(1, durationInFrames - silenceEnd))}><Audio src={staticFile("motion-audio/signal-pulse.wav")} volume={(audioFrame) => pulseEntryGain(audioFrame + silenceEnd, fps) * .32} /></Sequence>
    <Sequence premountFor={fps} from={silenceEnd} durationInFrames={Math.min(fps, Math.max(1, durationInFrames - silenceEnd))}><Audio src={staticFile("motion-audio/data-click.wav")} volume={(audioFrame) => motionMixGains(audioFrame + silenceEnd, fps).clicks * .25} /></Sequence>
    <Sequence premountFor={fps} from={fps * 2} durationInFrames={Math.min(fps, Math.max(1, durationInFrames - fps * 2))}><Audio src={staticFile("motion-audio/transition-envelope.wav")} volume={0.25} /></Sequence>
    <SignalPulse compact phase={8} />
  </PrimitiveFrame>;
};
