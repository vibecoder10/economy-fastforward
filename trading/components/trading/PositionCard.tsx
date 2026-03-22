"use client";

import Link from "next/link";
import { cn } from "@/lib/utils";
import type { KalshiPosition } from "@/lib/kalshi-types";
import { mockMarkets } from "@/lib/kalshi-mock";

interface PositionCardProps {
  position: KalshiPosition;
}

export function PositionCard({ position }: PositionCardProps) {
  const isYes = position.position > 0;
  const contracts = Math.abs(position.position);
  const exposure = position.market_exposure / 100; // cents to dollars
  const pnl = position.realized_pnl / 100;

  // Try to find market title from mock data
  const market = mockMarkets.find((m) => m.ticker === position.ticker);
  const title = market?.title ?? position.ticker;
  const currentPrice = market
    ? isYes
      ? market.yes_bid
      : market.no_bid
    : 50;

  return (
    <Link
      href={`/markets/${position.ticker}`}
      className="block bg-surface border border-border rounded-xl p-5 hover:border-accent/30 transition-all"
    >
      <div className="flex items-start justify-between mb-3">
        <h3 className="text-sm font-medium text-text-primary leading-snug line-clamp-2 pr-3">
          {title}
        </h3>
        <span
          className={cn(
            "shrink-0 px-2 py-0.5 rounded text-xs font-semibold",
            isYes
              ? "bg-success/10 text-success"
              : "bg-error/10 text-error"
          )}
        >
          {isYes ? "YES" : "NO"}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <div className="text-xs text-text-tertiary mb-0.5">Contracts</div>
          <div className="font-mono font-medium">{contracts}</div>
        </div>
        <div>
          <div className="text-xs text-text-tertiary mb-0.5">Current</div>
          <div className="font-mono font-medium">{currentPrice}¢</div>
        </div>
        <div>
          <div className="text-xs text-text-tertiary mb-0.5">Exposure</div>
          <div className="font-mono font-medium">${exposure.toFixed(2)}</div>
        </div>
      </div>

      {pnl !== 0 && (
        <div className="mt-3 pt-3 border-t border-border flex justify-between items-center">
          <span className="text-xs text-text-tertiary">Realized P&L</span>
          <span
            className={cn(
              "font-mono font-medium text-sm",
              pnl >= 0 ? "text-success" : "text-error"
            )}
          >
            {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}
          </span>
        </div>
      )}
    </Link>
  );
}
