import {signalPulseEnergy} from "./contracts";

export const COLORS = {
  ink: "#05090d",
  panel: "#0b151a",
  panelSoft: "#102229",
  turquoise: "#2de2d0",
  turquoiseDim: "#0b817a",
  cream: "#f3efe3",
  amber: "#ffb454",
  red: "#ff615f",
  blue: "#6ba7ff",
} as const;

export {FONT_FAMILY} from "./font";
export const SAFE_X = 210;
export const SAFE_Y = 94;

export const motifValue = (
  frame: number,
  fps: number,
): number => {
  return 0.18 + signalPulseEnergy(frame, fps) * 0.82;
};
