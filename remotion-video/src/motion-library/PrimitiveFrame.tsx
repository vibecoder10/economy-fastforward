import React from "react";
import {AbsoluteFill} from "remotion";
import {COLORS, FONT_FAMILY, SAFE_X, SAFE_Y} from "./theme";
import {CENTER_CROP_BOUNDS} from "./contracts";

export const PrimitiveFrame: React.FC<{
  title: string;
  kicker: string;
  children: React.ReactNode;
  titleStyle?: React.CSSProperties;
  mediaAware?: boolean;
}> = ({title, kicker, children, titleStyle, mediaAware = false}) => (
  <AbsoluteFill
    style={{
      background:
        mediaAware
          ? "radial-gradient(circle at 72% 18%, rgba(16,52,59,.36) 0%, rgba(7,18,22,.48) 36%, rgba(4,8,11,.62) 78%)"
          : "radial-gradient(circle at 72% 18%, rgba(16,52,59,.88) 0%, rgba(7,18,22,.9) 32%, rgba(4,8,11,.94) 72%)",
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
        gap: 48,
        zIndex: 20,
      }}
    >
      <div style={{fontSize: 18, letterSpacing: 4, color: COLORS.turquoise, whiteSpace: "nowrap"}}>
        {kicker.toUpperCase()}
      </div>
      <div style={{fontSize: 15, letterSpacing: 2.5, opacity: 0.48, whiteSpace: "nowrap", flexShrink: 0}}>
        STORYENGINE / MOTION SYSTEM
      </div>
    </div>
    <div
      style={{
        position: "absolute",
        left: CENTER_CROP_BOUNDS.criticalX,
        width: CENTER_CROP_BOUNDS.criticalWidth,
        bottom: 190,
        fontSize: 42,
        fontWeight: 700,
        letterSpacing: -1,
        textAlign: "center",
        zIndex: 20,
        ...titleStyle,
      }}
    >
      {title}
    </div>
    {children}
  </AbsoluteFill>
);
