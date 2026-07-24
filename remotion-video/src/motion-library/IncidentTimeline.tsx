import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";

const EVENTS = [
  {date: "18:02", label: "Substation fault", color: COLORS.red},
  {date: "18:11", label: "Relay cascade", color: COLORS.amber},
  {date: "18:26", label: "Radio clue", color: COLORS.turquoise},
] as const;

export const IncidentTimeline: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const progress = interpolate(frame, [8, fps * 2.2], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
  return (
    <PrimitiveFrame kicker="Causal reconstruction" title="Incident timeline">
      <div style={{position: "absolute", left: 250, right: 250, top: 460, height: 4, background: "#244148"}}><div style={{width: `${progress * 100}%`, height: "100%", background: COLORS.turquoise}} /></div>
      {EVENTS.map((event, index) => {
        const reveal = interpolate(frame, [18 + index * 22, 32 + index * 22], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        return <div key={event.date} style={{position: "absolute", left: 260 + index * 520, top: 315, width: 360, opacity: reveal, transform: `translateY(${(1 - reveal) * 24}px)`}}>
          <div style={{fontSize: 34, fontWeight: 700, color: event.color}}>{event.date}</div>
          <div style={{marginTop: 100, fontSize: 25, color: COLORS.cream}}>{event.label}</div>
          <div style={{position: "absolute", left: 0, top: 137, width: 18, height: 18, borderRadius: 99, background: event.color, boxShadow: `0 0 ${24 * reveal}px ${event.color}`}} />
        </div>;
      })}
      <div style={{position: "absolute", right: 255, top: 670, fontSize: 72, fontWeight: 700, color: COLORS.turquoise}}>{Math.round(progress * 47)} min</div>
      <div style={{position: "absolute", left: 700, width: 520, top: 650, textAlign: "center", fontSize: 24, color: COLORS.cream}}>
        ACTIVE · {progress > .75 ? "RADIO CLUE" : progress > .38 ? "RELAY CASCADE" : "SUBSTATION FAULT"}
      </div>
      <SignalPulse compact phase={3} />
    </PrimitiveFrame>
  );
};
