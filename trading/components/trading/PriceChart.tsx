"use client";

import { cn } from "@/lib/utils";

interface PriceChartProps {
  currentPrice: number; // cents
  title: string;
}

/**
 * Simple visual price indicator chart.
 * Uses CSS-only rendering (no external chart library needed for v1).
 * Can be upgraded to lightweight-charts in v2.
 */
export function PriceChart({ currentPrice, title }: PriceChartProps) {
  // Generate a simple mock price history for visual display
  const points = generatePriceHistory(currentPrice, 30);
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;

  // Build SVG path
  const width = 100;
  const height = 40;
  const pathData = points
    .map((p, i) => {
      const x = (i / (points.length - 1)) * width;
      const y = height - ((p - min) / range) * height;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");

  const areaPath = `${pathData} L ${width} ${height} L 0 ${height} Z`;
  const isUp = points[points.length - 1] >= points[0];

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-text-secondary">
          Price History
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              "text-2xl font-bold font-mono",
              isUp ? "text-success" : "text-error"
            )}
          >
            {currentPrice}¢
          </span>
          <span
            className={cn(
              "text-xs px-1.5 py-0.5 rounded",
              isUp ? "bg-success/10 text-success" : "bg-error/10 text-error"
            )}
          >
            {isUp ? "▲" : "▼"}
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="relative h-24">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          preserveAspectRatio="none"
          className="w-full h-full"
        >
          {/* Area fill */}
          <path
            d={areaPath}
            fill={isUp ? "rgba(48, 209, 88, 0.08)" : "rgba(255, 69, 58, 0.08)"}
          />
          {/* Line */}
          <path
            d={pathData}
            fill="none"
            stroke={isUp ? "#30D158" : "#FF453A"}
            strokeWidth="0.8"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>

      {/* Time labels */}
      <div className="flex justify-between text-xs text-text-tertiary mt-2">
        <span>30d ago</span>
        <span>Now</span>
      </div>
    </div>
  );
}

/** Generate a random-walk price history around the current price */
function generatePriceHistory(current: number, days: number): number[] {
  // Seed based on current price for consistency
  const points: number[] = [];
  let price = current + (Math.sin(current) * 10);

  for (let i = 0; i < days; i++) {
    const noise = Math.sin(i * 0.5 + current * 0.1) * 3 +
      Math.cos(i * 0.3 + current * 0.2) * 2;
    price = Math.max(1, Math.min(99, price + noise));
    points.push(Math.round(price));
  }

  // Ensure last point is the current price
  points[points.length - 1] = current;
  return points;
}
