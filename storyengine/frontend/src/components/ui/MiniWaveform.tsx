"use client";

import { useMemo } from "react";

interface MiniWaveformProps {
  color?: string;
  width?: number;
  height?: number;
  bars?: number;
  className?: string;
}

export function MiniWaveform({
  color = "var(--green)",
  width = 200,
  height = 32,
  bars = 40,
  className,
}: MiniWaveformProps) {
  const barData = useMemo(() => {
    return Array.from({ length: bars }, (_, i) => {
      const center = bars / 2;
      const distFromCenter = Math.abs(i - center) / center;
      const base = (1 - distFromCenter * 0.6) * 0.7;
      const random = Math.random() * 0.3;
      return Math.max(0.1, Math.min(1, base + random));
    });
  }, [bars]);

  const barWidth = width / bars * 0.6;
  const gap = width / bars * 0.4;

  return (
    <svg width={width} height={height} className={className} viewBox={`0 0 ${width} ${height}`}>
      {barData.map((h, i) => (
        <rect
          key={i}
          x={i * (barWidth + gap)}
          y={height * (1 - h) / 2}
          width={barWidth}
          height={height * h}
          rx={barWidth / 2}
          fill={color}
          opacity={0.7 + h * 0.3}
        />
      ))}
    </svg>
  );
}
