"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { MarketDisplayData } from "@/lib/trading-types";

interface MarketCardProps {
  market: MarketDisplayData;
  onToggleWatchlist?: (ticker: string) => void;
}

export function MarketCard({ market, onToggleWatchlist }: MarketCardProps) {
  const yesPercent = market.yesPrice ?? 50;
  const isHighProbability = yesPercent >= 50;

  const formatVolume = (v: number) => {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
    return String(v);
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <Link
      href={`/markets/${market.ticker}`}
      className="block bg-surface border border-border rounded-xl p-5 hover:border-accent/30 hover:bg-surface-hover transition-all group"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-4">
        <h3 className="text-sm font-medium text-text-primary leading-snug line-clamp-2 group-hover:text-accent transition-colors">
          {market.title}
        </h3>
        {onToggleWatchlist && (
          <button
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleWatchlist(market.ticker);
            }}
            className="shrink-0 p-1 rounded hover:bg-surface transition-colors"
          >
            <svg
              className={cn("w-4 h-4", market.isWatchlisted ? "text-accent fill-accent" : "text-text-tertiary")}
              viewBox="0 0 24 24"
              fill={market.isWatchlisted ? "currentColor" : "none"}
              stroke="currentColor"
              strokeWidth={1.5}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M11.48 3.499a.562.562 0 0 1 1.04 0l2.125 5.111a.563.563 0 0 0 .475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 0 0-.182.557l1.285 5.385a.562.562 0 0 1-.84.61l-4.725-2.885a.562.562 0 0 0-.586 0L6.982 20.54a.562.562 0 0 1-.84-.61l1.285-5.386a.562.562 0 0 0-.182-.557l-4.204-3.602a.562.562 0 0 1 .321-.988l5.518-.442a.563.563 0 0 0 .475-.345L11.48 3.5Z" />
            </svg>
          </button>
        )}
      </div>

      {/* Price display */}
      <div className="flex items-end gap-4 mb-4">
        <div>
          <div className="text-xs text-text-tertiary mb-1">Yes</div>
          <div
            className={cn(
              "text-2xl font-bold font-mono",
              isHighProbability ? "text-success" : "text-error"
            )}
          >
            {yesPercent}¢
          </div>
        </div>
        <div>
          <div className="text-xs text-text-tertiary mb-1">No</div>
          <div className="text-lg font-mono text-text-secondary">
            {market.noPrice}¢
          </div>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 bg-border rounded-full mb-3 overflow-hidden">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            isHighProbability ? "bg-success" : "bg-error"
          )}
          style={{ width: `${Math.max(0, Math.min(100, yesPercent))}%` }}
        />
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between text-xs text-text-tertiary">
        <div className="flex items-center gap-3">
          <span>{formatVolume(market.volume ?? 0)} Vol</span>
          <span className="text-border">|</span>
          <span>{market.category}</span>
        </div>
        <span>Expires {formatDate(market.closeTime)}</span>
      </div>
    </Link>
  );
}
