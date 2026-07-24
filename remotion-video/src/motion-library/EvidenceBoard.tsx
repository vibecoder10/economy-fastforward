import React from "react";
import {Img, interpolate, spring, useCurrentFrame, useVideoConfig} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";
import {assertLocalMotionSources} from "./contracts";

export const EvidenceBoard: React.FC<{photoSrc?: string; timelineOffsetFrames?: number}> = ({
  photoSrc,
  timelineOffsetFrames = 0,
}) => {
  if (photoSrc) assertLocalMotionSources([photoSrc]);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const cards = [
    {x: 250, y: 210, r: -4, title: "RELAY 07", kind: "photo"},
    {x: 685, y: 165, r: 2, title: "MAINTENANCE LOG", kind: "doc"},
    {x: 1120, y: 245, r: 5, title: "VOICE PACKET", kind: "wave"},
  ];
  return (
    <PrimitiveFrame
      title="Evidence Board"
      kicker="Cross-reference / three sources"
      titleStyle={{bottom: 190, textAlign: "center"}}
    >
      <svg style={{position: "absolute", inset: 0}} viewBox="0 0 1920 1080">
        <path d="M540 450 C710 390 880 370 1120 420" stroke={COLORS.turquoiseDim} strokeWidth="4" fill="none" />
        <path d="M850 520 C920 570 1030 590 1240 560" stroke={COLORS.amber} strokeWidth="3" fill="none" />
      </svg>
      {cards.map((card, index) => {
        const enter = spring({frame: frame + timelineOffsetFrames - index * 10, fps, config: {damping: 18}});
        return (
          <div
            key={card.title}
            style={{
              position: "absolute",
              left: card.x,
              top: card.y,
              width: 360,
              height: 430,
              padding: 24,
              background: "#e8e0ce",
              color: "#152025",
              transform: `translateY(${(1 - enter) * 90}px) rotate(${card.r}deg)`,
              opacity: enter,
              boxShadow: "0 26px 60px rgba(0,0,0,.45)",
            }}
          >
            <div style={{fontSize: 16, letterSpacing: 3}}>{card.title}</div>
            <div style={{height: 250, marginTop: 18, background: "#24373b", overflow: "hidden"}}>
              {photoSrc && card.kind === "photo" ? (
                <Img src={photoSrc} style={{width: "100%", height: "100%", objectFit: "cover"}} />
              ) : (
                <div style={{height: "100%", background: card.kind === "photo" ? "linear-gradient(140deg,#1e3c43,#9b7758)" : "repeating-linear-gradient(0deg,#d2c8b3 0 18px,#aa9e88 19px 21px)"}} />
              )}
            </div>
            {card.kind === "doc" && [0, 1, 2].map((line) => (
              <div key={line} style={{position: "absolute", left: 52, top: 185 + line * 52, width: 250 - line * 30, height: 19, background: "#111"}} />
            ))}
            <div style={{marginTop: 18, fontSize: 20, fontWeight: 700}}>
              {index === 2 ? "HIDDEN RHYTHM FOUND" : "SOURCE VERIFIED"}
            </div>
            <div style={{height: 4, marginTop: 13, width: `${interpolate(frame, [10, fps * 2], [0, 100], {extrapolateRight: "clamp"})}%`, background: COLORS.turquoise}} />
          </div>
        );
      })}
      <div style={{position: "absolute", left: 730, width: 460, top: 690, textAlign: "center", padding: "12px 18px", background: COLORS.panel, color: COLORS.turquoise, fontSize: 21}}>
        ACTIVE EVIDENCE · MAINTENANCE LOG
      </div>
      <SignalPulse phase={2} compact />
    </PrimitiveFrame>
  );
};
