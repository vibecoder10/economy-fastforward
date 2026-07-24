import React from "react";
import {interpolate, useCurrentFrame, useVideoConfig} from "remotion";
import {PrimitiveFrame} from "./PrimitiveFrame";
import {SignalPulse} from "./SignalPulse";
import {COLORS} from "./theme";
import {routeProgress} from "./contracts";

const pins = [
  [310, 240], [520, 170], [720, 310], [870, 210], [1040, 360], [680, 470], [420, 430],
] as const;

export const OutageMap: React.FC = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const route = routeProgress(frame, Math.round(fps * 0.25), Math.round(fps * 2.5));
  const camera = interpolate(frame, [0, fps * 4], [1.08, 1.18], {
    extrapolateRight: "clamp",
  });
  return (
    <PrimitiveFrame title="Outage Map" kicker="Signal path / 09:17">
      <div
        style={{
          position: "absolute",
          left: 260,
          top: 160,
          width: 1400,
          height: 700,
          transform: `scale(${camera}) translateX(${(route - 0.5) * -18}px)`,
          transformOrigin: "center",
        }}
      >
        <svg viewBox="0 0 1280 620" width="100%" height="100%">
          <rect width="1280" height="620" rx="28" fill="#071419" stroke="#1a3439" />
          {Array.from({length: 12}, (_, index) => (
            <path
              key={`street-${index}`}
              d={`M ${30 + index * 105} 0 C ${80 + index * 80} 180, ${10 + index * 120} 390, ${90 + index * 95} 620`}
              fill="none"
              stroke="#17323a"
              strokeWidth={index % 3 === 0 ? 5 : 2}
            />
          ))}
          <path
            d="M310 240 C430 80 590 270 720 310 S920 180 1040 360 S790 560 680 470 S500 510 420 430"
            fill="none"
            stroke={COLORS.turquoise}
            strokeWidth="8"
            strokeLinecap="round"
            pathLength="1"
            strokeDasharray="1"
            strokeDashoffset={1 - route}
            style={{filter: `drop-shadow(0 0 10px ${COLORS.turquoise})`}}
          />
          {pins.map(([x, y], index) => {
            const visible = route >= index / pins.length;
            const ring = visible ? 18 + ((frame + index * 7) % fps) / fps * 16 : 0;
            return (
              <g key={`${x}-${y}`} opacity={visible ? 1 : 0.15}>
                <circle cx={x} cy={y} r={ring} fill="none" stroke={COLORS.turquoise} opacity=".35" />
                <circle cx={x} cy={y} r="9" fill={index < 4 ? COLORS.red : COLORS.turquoise} />
                <text x={x + 18} y={y - 14} fill={COLORS.cream} fontSize="20">
                  RELAY {String(index + 1).padStart(2, "0")}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <SignalPulse phase={1} compact />
    </PrimitiveFrame>
  );
};
