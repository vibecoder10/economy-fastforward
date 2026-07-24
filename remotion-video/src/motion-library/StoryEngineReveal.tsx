import React from "react";
import {interpolate, useCurrentFrame} from "remotion";
import {CropSafeColumn} from "./CropSafe";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";

const SECTIONS = ["Outage opening", "Investigation", "Mara witness", "Recovery"] as const;
const LANES = [
  {label: "MAP", x: 230, y: 315},
  {label: "EVIDENCE", x: 230, y: 430},
  {label: "CAPTIONS", x: 1450, y: 315},
  {label: "AUDIO", x: 1450, y: 430},
  {label: "MOTION", x: 1450, y: 545},
] as const;

export const StoryEngineReveal: React.FC = () => {
  const frame = useCurrentFrame();
  const connectorProgress = interpolate(frame, [34, 76], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const master = interpolate(frame, [64, 92], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <PrimitiveFrame kicker="Plan → tracks → master" title="StoryEngine reveal">
      <CropSafeColumn top={165} bottom={180}>
        <div style={{padding: 22, borderRadius: 14, background: "#122329", border: "1px solid #2e4a51"}}>
          <div style={{fontSize: 16, letterSpacing: 2, color: COLORS.turquoise, fontWeight: 700}}>CUSTOM FILM REQUEST</div>
          <div style={{fontSize: 25, lineHeight: 1.35, marginTop: 12, color: COLORS.cream}}>
            “Trace the blackout—and the signal that brought the city back.”
          </div>
        </div>
        <div style={{marginTop: 18, fontSize: 15, letterSpacing: 2, color: COLORS.turquoise}}>APPROVED FOUR-SECTION PLAN</div>
        <div style={{display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 10}}>
          {SECTIONS.map((section, index) => {
            const visible = interpolate(frame, [6 + index * 7, 14 + index * 7], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
            return (
              <div key={section} style={{height: 42, display: "flex", alignItems: "center", padding: "0 12px", background: COLORS.panelSoft, borderLeft: `3px solid ${COLORS.turquoise}`, opacity: visible, fontSize: 16}}>
                <b style={{color: COLORS.turquoise, marginRight: 8}}>0{index + 1}</b>{section}
              </div>
            );
          })}
        </div>
        <div style={{marginTop: 104, textAlign: "center", color: COLORS.turquoise, fontSize: 16, letterSpacing: 3}}>STORYENGINE</div>
        <div style={{height: 5, marginTop: 14, width: `${master * 100}%`, background: COLORS.turquoise, boxShadow: `0 0 ${master * 28}px ${COLORS.turquoise}`}} />
        <div style={{marginTop: 12, textAlign: "center", color: COLORS.cream, fontSize: 20, fontWeight: 700, opacity: master}}>ONE VERIFIED MASTER · 300.000s · 24 FPS</div>
      </CropSafeColumn>

      <div style={{position: "absolute", left: 205, top: 260, fontSize: 14, letterSpacing: 3, color: COLORS.amber}}>PRODUCTION LANES</div>
      {LANES.map((lane, index) => {
        const visible = interpolate(frame, [20 + index * 5, 30 + index * 5], [0, 1], {extrapolateLeft: "clamp", extrapolateRight: "clamp"});
        return (
          <div key={lane.label} style={{position: "absolute", left: lane.x, top: lane.y, width: 240, padding: "15px 18px", boxSizing: "border-box", background: "#0e2026", border: "1px solid #26434a", color: COLORS.cream, fontSize: 17, letterSpacing: 2, opacity: visible}}>
            {lane.label}
          </div>
        );
      })}
      <svg style={{position: "absolute", inset: 0}} width="1920" height="1080" viewBox="0 0 1920 1080">
        {LANES.map((lane) => {
          const startX = lane.x < 960 ? lane.x + 240 : lane.x;
          return (
            <path
              key={lane.label}
              d={`M ${startX} ${lane.y + 26} C ${lane.x < 960 ? 610 : 1310} ${lane.y + 26}, ${lane.x < 960 ? 720 : 1200} 690, 960 690`}
              fill="none"
              stroke={COLORS.turquoise}
              strokeWidth="3"
              pathLength="1"
              strokeDasharray="1"
              strokeDashoffset={1 - connectorProgress}
              opacity=".75"
            />
          );
        })}
      </svg>
      <SignalPulse compact phase={7} />
    </PrimitiveFrame>
  );
};
