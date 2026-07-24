import React from "react";
import {CENTER_CROP_BOUNDS} from "./contracts";

export const CropSafeColumn: React.FC<{
  children: React.ReactNode;
  top?: number;
  bottom?: number;
  style?: React.CSSProperties;
}> = ({
  children,
  top = CENTER_CROP_BOUNDS.criticalTop,
  bottom = 1080 - CENTER_CROP_BOUNDS.criticalBottom,
  style,
}) => (
  <div
    data-crop-safe="critical-9x16"
    style={{
      position: "absolute",
      left: CENTER_CROP_BOUNDS.criticalX,
      width: CENTER_CROP_BOUNDS.criticalWidth,
      top,
      bottom,
      ...style,
    }}
  >
    {children}
  </div>
);
