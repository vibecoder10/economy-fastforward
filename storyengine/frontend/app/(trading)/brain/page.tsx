"use client";

import { useState, useEffect, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { BrainStatus, ActiveBet, CycleResult } from "@/lib/betting-brain";

interface SettledBetDisplay {
  id: string;
  ticker: string;
  title: string;
  side: string;
  contracts: number;
  entryPrice: number;
  totalCost: number;
  confidence: number;
  result: string | null;
  pnl: number | null;
  settledAt: string;
}

interface BrainResponse {
  status: BrainStatus;
  activeBets: ActiveBet[];
  recentSettled: SettledBetDisplay[];
  config: {
    mode: string;
    weights: Record<string, number>;
    thresholds: Record<string, number>;
  };
}

export default function BrainPage() {
  const [data, setData] = useState<BrainResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [lastResult, setLastResult] = useState<CycleResult | null>(null);

  const loadData = useCallback(async () => {
    try {
      const res = await fetch("/api/trading/brain");
      const json = await res.json();
      setData(json);
    } catch {
      // handled by UI
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  async function handleAction(action: string, extra?: Record<string, unknown>) {
    setActionLoading(true);
    try {
      const res = await fetch("/api/trading/brain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, ...extra }),
      });
      const result = await res.json();
      setLastResult(result);
      await loadData();
    } catch {
      // handled
    }
    setActionLoading(false);
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-surface rounded w-1/4" />
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-surface rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  const status = data?.status;
  const activeBets = data?.activeBets ?? [];
  const recentSettled = data?.recentSettled ?? [];

  const pnlColor = (status?.totalPnl ?? 0) >= 0 ? "text-green-400" : "text-red-400";
  const bankrollPct = status
    ? ((status.bankroll / status.startingBankroll - 1) * 100).toFixed(1)
    : "0";

  return (
    <div className="space-y-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Betting Brain</h1>
          <p className="text-sm text-text-secondary mt-1">
            {status?.mode === "paper" ? "Paper Trading" : "Live Trading"} — Every bet is an experiment
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => handleAction("toggle", { enabled: !status?.enabled })}
            disabled={actionLoading}
            className={cn(
              "px-4 py-2 rounded-lg text-sm font-medium transition-colors",
              status?.enabled
                ? "bg-green-500/20 text-green-400 hover:bg-green-500/30"
                : "bg-red-500/20 text-red-400 hover:bg-red-500/30"
            )}
          >
            {status?.enabled ? "ON" : "OFF"}
          </button>
          <button
            onClick={() => handleAction("cycle")}
            disabled={actionLoading || !status?.enabled}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-accent/20 text-accent hover:bg-accent/30 transition-colors disabled:opacity-50"
          >
            {actionLoading ? "Running..." : "Run Cycle"}
          </button>
          <button
            onClick={() => handleAction("force")}
            disabled={actionLoading || !status?.enabled}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            Force Bet
          </button>
          <button
            onClick={() => handleAction("monitor")}
            disabled={actionLoading}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-surface text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            Monitor
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <StatCard
          label="Bankroll"
          value={`$${status?.bankroll?.toFixed(2) ?? "0.00"}`}
          sub={`${Number(bankrollPct) >= 0 ? "+" : ""}${bankrollPct}%`}
          subColor={Number(bankrollPct) >= 0 ? "text-green-400" : "text-red-400"}
        />
        <StatCard
          label="Total P&L"
          value={`${(status?.totalPnl ?? 0) >= 0 ? "+" : ""}$${status?.totalPnl?.toFixed(2) ?? "0.00"}`}
          valueColor={pnlColor}
        />
        <StatCard
          label="Win Rate"
          value={`${status?.winRate?.toFixed(0) ?? 0}%`}
          sub={`${status?.totalBets ?? 0} bets`}
        />
        <StatCard
          label="Active Bets"
          value={`${status?.activeBets ?? 0} / ${status?.maxPositions ?? 5}`}
        />
      </div>

      {/* Last Cycle Result */}
      {lastResult && (
        <div
          className={cn(
            "p-4 rounded-xl border",
            lastResult.action === "bet_placed"
              ? "border-green-500/30 bg-green-500/5"
              : lastResult.action === "no_bet"
                ? "border-yellow-500/30 bg-yellow-500/5"
                : "border-border bg-surface"
          )}
        >
          <div className="flex items-center gap-2 mb-2">
            <span className="text-sm font-medium text-text-primary">Last Cycle</span>
            <span
              className={cn(
                "text-xs px-2 py-0.5 rounded",
                lastResult.action === "bet_placed"
                  ? "bg-green-500/20 text-green-400"
                  : "bg-surface text-text-secondary"
              )}
            >
              {lastResult.action}
            </span>
          </div>
          <p className="text-sm text-text-secondary">{lastResult.reason}</p>
        </div>
      )}

      {/* Active Bets */}
      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-4">Active Bets</h2>
        {activeBets.length === 0 ? (
          <p className="text-sm text-text-tertiary">No active bets. Run a cycle to place one.</p>
        ) : (
          <div className="space-y-3">
            {activeBets.map((bet) => (
              <div
                key={bet.id}
                className="p-4 rounded-xl bg-surface border border-border"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-text-primary">{bet.title}</span>
                  <span
                    className={cn(
                      "text-xs px-2 py-0.5 rounded font-medium",
                      bet.side === "yes"
                        ? "bg-green-500/20 text-green-400"
                        : "bg-red-500/20 text-red-400"
                    )}
                  >
                    {bet.side.toUpperCase()}
                  </span>
                </div>
                <div className="grid grid-cols-4 gap-4 text-sm text-text-secondary">
                  <div>
                    <span className="text-text-tertiary">Entry: </span>
                    {bet.entryPrice}c
                  </div>
                  <div>
                    <span className="text-text-tertiary">Contracts: </span>
                    {bet.contracts}
                  </div>
                  <div>
                    <span className="text-text-tertiary">Cost: </span>$
                    {(bet.totalCost / 100).toFixed(2)}
                  </div>
                  <div>
                    <span className="text-text-tertiary">Confidence: </span>
                    {bet.confidence.toFixed(0)}/100
                  </div>
                </div>
                <div className="mt-2 text-xs text-text-tertiary">
                  {bet.reasoning.slice(0, 3).map((r, i) => (
                    <div key={i}>{r}</div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Settled Bets */}
      {recentSettled.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-text-primary mb-4">Recent Settled</h2>
          <div className="space-y-3">
            {recentSettled
              .slice()
              .reverse()
              .map((bet) => (
                <div
                  key={bet.id}
                  className="p-4 rounded-xl bg-surface border border-border"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-medium text-text-primary">{bet.title}</span>
                    <span
                      className={cn(
                        "text-xs px-2 py-0.5 rounded font-medium",
                        bet.result === "won"
                          ? "bg-green-500/20 text-green-400"
                          : "bg-red-500/20 text-red-400"
                      )}
                    >
                      {bet.result?.toUpperCase()}
                    </span>
                  </div>
                  <div className="grid grid-cols-4 gap-4 text-sm text-text-secondary">
                    <div>
                      <span className="text-text-tertiary">Side: </span>
                      {bet.side.toUpperCase()} @ {bet.entryPrice}c
                    </div>
                    <div>
                      <span className="text-text-tertiary">Contracts: </span>
                      {bet.contracts}
                    </div>
                    <div>
                      <span className="text-text-tertiary">Cost: </span>$
                      {(bet.totalCost / 100).toFixed(2)}
                    </div>
                    <div
                      className={
                        (bet.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                      }
                    >
                      {(bet.pnl ?? 0) >= 0 ? "+" : ""}$
                      {((bet.pnl ?? 0) / 100).toFixed(2)}
                    </div>
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Config Display */}
      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-4">Config</h2>
        <div className="p-4 rounded-xl bg-surface border border-border">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <h3 className="font-medium text-text-primary mb-2">Scoring Weights</h3>
              {data?.config?.weights &&
                Object.entries(data.config.weights).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-text-secondary">
                    <span>{k.replace(/_/g, " ")}</span>
                    <span className="font-mono">{(v * 100).toFixed(0)}%</span>
                  </div>
                ))}
            </div>
            <div>
              <h3 className="font-medium text-text-primary mb-2">Thresholds</h3>
              {data?.config?.thresholds &&
                Object.entries(data.config.thresholds).map(([k, v]) => (
                  <div key={k} className="flex justify-between text-text-secondary">
                    <span>{k.replace(/_/g, " ")}</span>
                    <span className="font-mono">{v}</span>
                  </div>
                ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueColor,
  subColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
  subColor?: string;
}) {
  return (
    <div className="p-4 rounded-xl bg-surface border border-border">
      <div className="text-xs text-text-tertiary mb-1">{label}</div>
      <div className={cn("text-xl font-bold font-mono", valueColor ?? "text-text-primary")}>
        {value}
      </div>
      {sub && (
        <div className={cn("text-xs mt-1", subColor ?? "text-text-tertiary")}>
          {sub}
        </div>
      )}
    </div>
  );
}
