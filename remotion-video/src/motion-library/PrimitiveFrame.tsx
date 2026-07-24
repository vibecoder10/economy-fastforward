import React from "react";
import {AbsoluteFill} from "remotion";
import {COLORS, FONT_FAMILY, SAFE_X, SAFE_Y} from "./theme";
import {CENTER_CROP_BOUNDS} from "./contracts";

export const PrimitiveFrame: React.FC<{
  title: string;
  kicker: string;
  children: React.ReactNode;
}> = ({title, kicker, children}) => (
  <AbsoluteFill
    style={{
      background:
        "radial-gradient(circle at 72% 18%, #10343b 0%, #071216 32%, #04080b 72%)",
      color: COLORS.cream,
      fontFamily: FONT_FAMILY,
      overflow: "hidden",
    }}
  >
    <div
      style={{
        position: "absolute",
        left: CENTER_CROP_BOUNDS.criticalX,
        right: SAFE_X,
        top: SAFE_Y,
        display: "flex",
        justifyContent: "space-between",
        alignItems: "baseline",
        zIndex: 20,
      }}
    >
      <div style={{fontSize: 22, letterSpacing: 5, color: COLORS.turquoise}}>
        {kicker.toUpperCase()}
      </div>
      <div style={{fontSize: 18, letterSpacing: 3, opacity: 0.48}}>
        STORYENGINE / MOTION SYSTEM
      </div>
    </div>
    <div
      style={{
        position: "absolute",
        left: CENTER_CROP_BOUNDS.criticalX,
        width: CENTER_CROP_BOUNDS.criticalWidth,
        bottom: SAFE_Y - 12,
        fontSize: 42,
        fontWeight: 700,
        letterSpacing: -1,
        zIndex: 20,
      }}
    >
      {title}
    </div>
    {children}
  </AbsoluteFill>
);
