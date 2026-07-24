import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";

const NODES = ["GRID", "RELAY", "RADIO", "CITY"] as const;

export const NetworkExplainer: React.FC = () => {
  const frame = useCurrentFrame();
  return <PrimitiveFrame kicker="Four-node model" title="Failure → ordered reconnection">
    <div style={{position: "absolute", left: 720, width: 480, top: 250, display: "grid", gridTemplateColumns: "1fr 1fr", gap: 32}}>
      {NODES.map((node, index) => {
        const on = interpolate(frame, [18 + index * 16, 30 + index * 16], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        return <div key={node} style={{width: 190, height: 190, justifySelf: index % 2 === 0 ? "start" : "end", borderRadius: 99, display: "grid", placeItems: "center", border: `3px solid ${on > .5 ? COLORS.turquoise : COLORS.red}`, background: on > .5 ? "rgba(45,226,208,.12)" : "rgba(255,97,95,.08)", color: on > .5 ? COLORS.turquoise : COLORS.red, fontWeight: 700, fontSize: 25, boxShadow: `0 0 ${on * 38}px ${COLORS.turquoiseDim}`}}>{node}</div>;
      })}
    </div>
    <svg style={{position: "absolute", left: 720, top: 250}} width="480" height="412" viewBox="0 0 480 412">
      <path d="M95 95 H385 V317 H95" fill="none" stroke={COLORS.turquoise} strokeWidth="3" strokeDasharray="700" strokeDashoffset={700 * (1 - Math.min(1, frame / 80))} />
    </svg>
    <div style={{position: "absolute", left: 700, width: 520, top: 690, textAlign: "center", color: COLORS.turquoise, fontSize: 21}}>CURRENT STATE · {NODES[Math.min(3, Math.floor(Math.max(0, frame - 18) / 16))]}</div>
    <SignalPulse compact phase={6} />
  </PrimitiveFrame>;
};
