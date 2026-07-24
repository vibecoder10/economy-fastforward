import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";

export const RadioWaveform: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const reveal = interpolate(frame, [fps * 1.5, fps * 3], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  const bars = Array.from({length: 48}, (_, index) => {
    const level = 20 + 75 * Math.abs(Math.sin(index * 0.73 + frame * 0.16));
    return <div key={index} style={{width: 9, height: level, background: index % 7 === 0 ? COLORS.amber : COLORS.turquoise, opacity: 0.45 + level / 180}} />;
  });
  return <PrimitiveFrame kicker="Recovered transmission" title="Radio waveform">
    <div style={{position: "absolute", left: 270, right: 270, top: 410, height: 180, display: "flex", gap: 12, alignItems: "center", justifyContent: "center", borderTop: "1px solid #1b4b50", borderBottom: "1px solid #1b4b50"}}>{bars}</div>
    <div style={{position: "absolute", left: 680, width: 560, top: 650, textAlign: "center", fontSize: 24, letterSpacing: 4, color: COLORS.cream, opacity: 1 - reveal}}>09 · 04 · 21 · 16</div>
    <div style={{position: "absolute", left: 700, width: 520, top: 625, boxSizing: "border-box", textAlign: "center", padding: "18px 20px", border: `1px solid ${COLORS.turquoise}`, fontSize: 28, fontWeight: 700, color: COLORS.turquoise, opacity: reveal, transform: `scale(${0.85 + reveal * 0.15})`}}>RECOVERY KEY 09-04-21-16</div>
    <SignalPulse compact phase={4} />
  </PrimitiveFrame>;
};
