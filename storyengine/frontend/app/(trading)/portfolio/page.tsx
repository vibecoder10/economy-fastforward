"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { cn } from "@/lib/utils";
import { PositionCard } from "@/components/trading/PositionCard";
import { TradeHistory } from "@/components/trading/TradeHistory";
import type { KalshiPosition, KalshiBalance } from "@/lib/kalshi-types";

interface TradeLogEntry {
  id: string;
  marketTicker: string;
  side: string;
  action: string;
  contracts: number;
  pricePerContract: number;
  totalCost: number;
  status: string;
  createdAt: string;
}

export default function PortfolioPage() {
  const [balance, setBalance] = useState<KalshiBalance | null>(null);
  const [positions, setPositions] = useState<KalshiPosition[]>([]);
  const [trades, setTrades] = useState<TradeLogEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const res = await fetch("/api/kalshi/portfolio");
        const data = await res.json();
        setBalance(data.balance ?? null);
        setPositions(data.positions ?? []);
        setConnected(data.connected ?? false);
      } catch {
        // Handled by UI
      }
      setLoading(false);
    }

    load();
  }, []);

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-surface rounded w-1/4" />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="h-24 bg-surface rounded-xl" />
          <div className="h-24 bg-surface rounded-xl" />
          <div className="h-24 bg-surface rounded-xl" />
        </div>
      </div>
    );
  }

  if (!connected) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold">Portfolio</h1>
        <div className="text-center py-16 bg-surface border border-border rounded-xl">
          <div className="text-5xl mb-4">📊</div>
          <h2 className="text-xl font-semibold mb-2">Connect Your Kalshi Account</h2>
          <p className="text-text-secondary mb-6 max-w-md mx-auto">
            Link your Kalshi trading account to see your portfolio, positions,
            and trade history here.
          </p>
          <Link
            href="/settings"
            className="inline-block px-8 py-3 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
          >
            Connect Account
          </Link>
          <p className="text-xs text-text-tertiary mt-4">
            Demo data shown until you connect your account
          </p>
        </div>
      </div>
    );
  }

  const balanceDollars = balance ? (balance.balance / 100).toFixed(2) : "0.00";
  const portfolioDollars = balance
    ? (balance.portfolio_value / 100).toFixed(2)
    : "0.00";
  const totalPnl = positions.reduce((sum, p) => sum + p.realized_pnl, 0) / 100;

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Portfolio</h1>

      {/* Balance cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-xs text-text-tertiary mb-1">Cash Balance</div>
          <div className="text-2xl font-bold font-mono">${balanceDollars}</div>
        </div>
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-xs text-text-tertiary mb-1">Portfolio Value</div>
          <div className="text-2xl font-bold font-mono text-accent">
            ${portfolioDollars}
          </div>
        </div>
        <div className="bg-surface border border-border rounded-xl p-5">
          <div className="text-xs text-text-tertiary mb-1">Realized P&L</div>
          <div
            className={cn(
              "text-2xl font-bold font-mono",
              totalPnl >= 0 ? "text-success" : "text-error"
            )}
          >
            {totalPnl >= 0 ? "+" : ""}${totalPnl.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Positions */}
      <div>
        <h2 className="text-lg font-semibold mb-4">
          Open Positions ({positions.length})
        </h2>
        {positions.length === 0 ? (
          <div className="bg-surface border border-border rounded-xl p-8 text-center">
            <p className="text-text-secondary">No open positions</p>
            <Link
              href="/markets"
              className="text-sm text-accent hover:text-accent-hover mt-2 inline-block"
            >
              Browse markets to start trading
            </Link>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {positions.map((pos) => (
              <PositionCard key={pos.ticker} position={pos} />
            ))}
          </div>
        )}
      </div>

      {/* Trade history */}
      <div>
        <h2 className="text-lg font-semibold mb-4">Recent Trades</h2>
        <TradeHistory trades={trades} />
      </div>
    </div>
  );
}
