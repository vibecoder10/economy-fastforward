"use client";

interface PanelMagnifierProps {
  gridUrl: string;
  panelIndex: number; // 0-8 within the grid
  size?: number;
  className?: string;
}

export function PanelMagnifier({ gridUrl, panelIndex, size = 200, className = "" }: PanelMagnifierProps) {
  const row = Math.floor(panelIndex / 3);
  const col = panelIndex % 3;

  return (
    <div
      className={`rounded-lg ${className}`}
      style={{
        width: size,
        height: size,
        backgroundImage: `url(${gridUrl})`,
        backgroundSize: "300% 300%",
        backgroundPosition: `${col * 50}% ${row * 50}%`,
        backgroundRepeat: "no-repeat",
        flexShrink: 0,
      }}
    />
  );
}
