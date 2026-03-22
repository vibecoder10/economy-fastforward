"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { cn } from "@/lib/utils";
import type { BrainStatus, ActiveBet } from "@/lib/betting-brain";

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

interface CycleResponse {
  action: string;
  reason: string;
  marketsScanned?: number;
  isMock?: boolean;
  rankings?: Array<{
    market: { title: string; ticker: string };
    score: number;
    side: string;
    edgeCents: number;
  }>;
}

interface HistoryResponse {
  patterns: {
    categoryScores: Record<string, number>;
    priceRanges: Record<string, { wins: number; total: number }>;
  };
  summary: {
    totalBets: number;
    wins: number;
    losses: number;
    winRate: number;
    totalPnlCents: number;
  };
}

export default function BrainPage() {
  const [data, setData] = useState<BrainResponse | null>(null);
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [lastResult, setLastResult] = useState<CycleResponse | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "history" | "config">("overview");
  const [autoCycle, setAutoCycle] = useState(false);
  const [autoCycleMinutes, setAutoCycleMinutes] = useState(60);
  const [nextAutoRun, setNextAutoRun] = useState<number | null>(null);
  const autoTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadData = useCallback(async () => {
    try {
      const [brainRes, historyRes] = await Promise.all([
        fetch("/api/trading/brain"),
        fetch("/api/trading/brain/history"),
      ]);
      const brainJson = await brainRes.json();
      const historyJson = await historyRes.json();
      setData(brainJson);
      setHistory(historyJson);
    } catch {
      // handled by UI
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-cycle: run cycle + monitor on interval
  useEffect(() => {
    if (autoTimerRef.current) clearInterval(autoTimerRef.current);
    if (countdownRef.current) clearInterval(countdownRef.current);

    if (!autoCycle) {
      setNextAutoRun(null);
      return;
    }

    const intervalMs = autoCycleMinutes * 60 * 1000;
    setNextAutoRun(Date.now() + intervalMs);

    // Countdown ticker (updates every 10s)
    countdownRef.current = setInterval(() => {
      setNextAutoRun((prev) => prev); // force re-render
    }, 10000);

    autoTimerRef.current = setInterval(async () => {
      // Run cycle then monitor
      try {
        await fetch("/api/trading/brain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "cycle" }),
        });
        await fetch("/api/trading/brain", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "monitor" }),
        });
        await loadData();
        setNextAutoRun(Date.now() + intervalMs);
      } catch {
        // continue
      }
    }, intervalMs);

    return () => {
      if (autoTimerRef.current) clearInterval(autoTimerRef.current);
      if (countdownRef.current) clearInterval(countdownRef.current);
    };
  }, [autoCycle, autoCycleMinutes, loadData]);

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
        <div className="grid grid-cols-1 sm:grid-cols-5 gap-4">
          {[1, 2, 3, 4, 5].map((i) => (
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Betting Brain</h1>
            <button
              onClick={() => {
                const newMode = status?.mode === "paper" ? "live" : "paper";
                handleAction("set-mode", { mode: newMode });
              }}
              disabled={actionLoading}
              className={cn(
                "text-xs px-2 py-0.5 rounded font-medium transition-colors cursor-pointer",
                status?.mode === "paper"
                  ? "bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30"
                  : "bg-green-500/20 text-green-400 hover:bg-green-500/30"
              )}
              title={`Click to switch to ${status?.mode === "paper" ? "live" : "paper"} mode`}
            >
              {status?.mode === "paper" ? "PAPER" : "LIVE"}
            </button>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Every bet is an experiment. Every outcome is data.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleAction("toggle", { enabled: !status?.enabled })}
            disabled={actionLoading}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors",
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
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-accent/20 text-accent hover:bg-accent/30 transition-colors disabled:opacity-50"
          >
            {actionLoading ? "Running..." : "Run Cycle"}
          </button>
          <button
            onClick={() => handleAction("force")}
            disabled={actionLoading || !status?.enabled}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            Force
          </button>
          <button
            onClick={() => handleAction("monitor")}
            disabled={actionLoading}
            className="px-3 py-1.5 rounded-lg text-xs font-medium bg-surface text-text-secondary hover:bg-surface-hover transition-colors disabled:opacity-50"
          >
            Monitor
          </button>
          <div className="h-4 w-px bg-border" />
          <button
            onClick={() => setAutoCycle(!autoCycle)}
            className={cn(
              "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5",
              autoCycle
                ? "bg-accent/20 text-accent"
                : "bg-surface text-text-tertiary hover:text-text-secondary"
            )}
          >
            <span className={cn("w-1.5 h-1.5 rounded-full", autoCycle ? "bg-accent animate-pulse" : "bg-text-tertiary")} />
            Auto
            {autoCycle && nextAutoRun && (
              <span className="text-text-tertiary ml-1">
                ({formatCountdown(nextAutoRun - Date.now())})
              </span>
            )}
          </button>
          {autoCycle && (
            <select
              value={autoCycleMinutes}
              onChange={(e) => setAutoCycleMinutes(Number(e.target.value))}
              className="text-xs bg-surface border border-border rounded-lg px-2 py-1.5 text-text-secondary"
            >
              <option value={15}>15m</option>
              <option value={30}>30m</option>
              <option value={60}>1h</option>
              <option value={240}>4h</option>
            </select>
          )}
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
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
          label="Active"
          value={`${status?.activeBets ?? 0} / ${status?.maxPositions ?? 5}`}
        />
        <StatCard
          label="Record"
          value={`${history?.summary?.wins ?? 0}W - ${history?.summary?.losses ?? 0}L`}
          sub={status?.lastBet ? `Last: ${timeAgo(status.lastBet)}` : "No bets yet"}
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
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-text-primary">Last Cycle</span>
              <span
                className={cn(
                  "text-xs px-2 py-0.5 rounded",
                  lastResult.action === "bet_placed"
                    ? "bg-green-500/20 text-green-400"
                    : "bg-surface text-text-secondary"
                )}
              >
                {lastResult.action.replace("_", " ")}
              </span>
            </div>
            {lastResult.marketsScanned !== undefined && (
              <span className="text-xs text-text-tertiary">
                {lastResult.marketsScanned} markets scanned
                {lastResult.isMock ? " (mock)" : ""}
              </span>
            )}
          </div>
          <p className="text-sm text-text-secondary">{lastResult.reason}</p>

          {/* Top Rankings */}
          {lastResult.rankings && lastResult.rankings.length > 0 && (
            <div className="mt-3 pt-3 border-t border-border">
              <div className="text-xs text-text-tertiary mb-2">Top Scored Markets:</div>
              <div className="space-y-1">
                {lastResult.rankings.slice(0, 3).map((r, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="text-text-secondary truncate mr-3">
                      {i + 1}. {r.market.title}
                    </span>
                    <div className="flex items-center gap-2 shrink-0">
                      <span
                        className={cn(
                          "px-1.5 py-0.5 rounded font-medium",
                          r.side === "yes" ? "bg-green-500/10 text-green-400" : "bg-red-500/10 text-red-400"
                        )}
                      >
                        {r.side.toUpperCase()}
                      </span>
                      <span className="font-mono text-text-primary">{r.score.toFixed(0)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {(["overview", "history", "config"] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              "px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px",
              activeTab === tab
                ? "text-accent border-accent"
                : "text-text-tertiary border-transparent hover:text-text-secondary"
            )}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          {/* Active Bets */}
          <div>
            <h2 className="text-lg font-semibold text-text-primary mb-3">Active Bets</h2>
            {activeBets.length === 0 ? (
              <div className="p-6 rounded-xl bg-surface border border-border text-center">
                <p className="text-sm text-text-tertiary">No active bets. Run a cycle to analyze markets and place a bet.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {activeBets.map((bet) => (
                  <BetCard key={bet.id} bet={bet} />
                ))}
              </div>
            )}
          </div>

          {/* Settled Bets */}
          {recentSettled.length > 0 && (
            <div>
              <h2 className="text-lg font-semibold text-text-primary mb-3">Recent Results</h2>
              <div className="space-y-2">
                {recentSettled.map((bet) => (
                  <div
                    key={bet.id}
                    className="p-3 rounded-xl bg-surface border border-border flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <span
                        className={cn(
                          "text-xs px-2 py-0.5 rounded font-medium shrink-0",
                          bet.result === "won"
                            ? "bg-green-500/20 text-green-400"
                            : "bg-red-500/20 text-red-400"
                        )}
                      >
                        {bet.result?.toUpperCase()}
                      </span>
                      <span className="text-sm text-text-primary truncate">{bet.title}</span>
                    </div>
                    <div className="flex items-center gap-4 text-sm shrink-0">
                      <span className="text-text-tertiary">
                        {bet.side?.toUpperCase()} @ {bet.entryPrice}c
                      </span>
                      <span
                        className={cn(
                          "font-mono font-medium",
                          (bet.pnl ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                        )}
                      >
                        {(bet.pnl ?? 0) >= 0 ? "+" : ""}${((bet.pnl ?? 0) / 100).toFixed(2)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "history" && (
        <div className="space-y-6">
          {/* Category Performance */}
          <div>
            <h2 className="text-lg font-semibold text-text-primary mb-3">Learned Patterns</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Category Scores */}
              <div className="p-4 rounded-xl bg-surface border border-border">
                <h3 className="text-sm font-medium text-text-primary mb-3">Category Win Rates</h3>
                {history?.patterns?.categoryScores &&
                Object.keys(history.patterns.categoryScores).length > 0 ? (
                  <div className="space-y-2">
                    {Object.entries(history.patterns.categoryScores)
                      .sort(([, a], [, b]) => b - a)
                      .map(([cat, score]) => (
                        <div key={cat} className="flex items-center justify-between text-sm">
                          <span className="text-text-secondary">{cat}</span>
                          <div className="flex items-center gap-2">
                            <div className="w-20 h-1.5 bg-surface-hover rounded-full overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full",
                                  score >= 60 ? "bg-green-500" : score >= 40 ? "bg-yellow-500" : "bg-red-500"
                                )}
                                style={{ width: `${score}%` }}
                              />
                            </div>
                            <span className="font-mono text-text-primary w-10 text-right">{score}%</span>
                          </div>
                        </div>
                      ))}
                  </div>
                ) : (
                  <p className="text-xs text-text-tertiary">
                    Need 3+ settled bets per category to generate patterns.
                  </p>
                )}
              </div>

              {/* Price Range Performance */}
              <div className="p-4 rounded-xl bg-surface border border-border">
                <h3 className="text-sm font-medium text-text-primary mb-3">Price Range Performance</h3>
                {history?.patterns?.priceRanges &&
                Object.keys(history.patterns.priceRanges).length > 0 ? (
                  <div className="space-y-2">
                    {Object.entries(history.patterns.priceRanges).map(([range, stats]) => {
                      const winRate = stats.total > 0 ? Math.round((stats.wins / stats.total) * 100) : 0;
                      return (
                        <div key={range} className="flex items-center justify-between text-sm">
                          <span className="text-text-secondary capitalize">{range}</span>
                          <div className="flex items-center gap-2">
                            <span className="text-xs text-text-tertiary">
                              {stats.wins}W / {stats.total}
                            </span>
                            <span className="font-mono text-text-primary">{winRate}%</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p className="text-xs text-text-tertiary">No price range data yet.</p>
                )}
              </div>
            </div>
          </div>

          {/* Equity Curve (text-based until we add a chart lib) */}
          <div className="p-4 rounded-xl bg-surface border border-border">
            <h3 className="text-sm font-medium text-text-primary mb-3">Performance Summary</h3>
            <div className="grid grid-cols-4 gap-4 text-sm">
              <div>
                <span className="text-text-tertiary">Total Bets</span>
                <div className="font-mono text-text-primary text-lg">{history?.summary?.totalBets ?? 0}</div>
              </div>
              <div>
                <span className="text-text-tertiary">Win Rate</span>
                <div className="font-mono text-text-primary text-lg">{history?.summary?.winRate ?? 0}%</div>
              </div>
              <div>
                <span className="text-text-tertiary">Total P&L</span>
                <div
                  className={cn(
                    "font-mono text-lg",
                    (history?.summary?.totalPnlCents ?? 0) >= 0 ? "text-green-400" : "text-red-400"
                  )}
                >
                  {(history?.summary?.totalPnlCents ?? 0) >= 0 ? "+" : ""}$
                  {((history?.summary?.totalPnlCents ?? 0) / 100).toFixed(2)}
                </div>
              </div>
              <div>
                <span className="text-text-tertiary">Avg P&L / Bet</span>
                <div className="font-mono text-text-primary text-lg">
                  {(history?.summary?.totalBets ?? 0) > 0
                    ? `$${((history?.summary?.totalPnlCents ?? 0) / (history?.summary?.totalBets ?? 1) / 100).toFixed(2)}`
                    : "$0.00"}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {activeTab === "config" && (
        <div className="p-4 rounded-xl bg-surface border border-border">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-6 text-sm">
            <div>
              <h3 className="font-medium text-text-primary mb-3">Scoring Weights</h3>
              <div className="space-y-1.5">
                {data?.config?.weights &&
                  Object.entries(data.config.weights).map(([k, v]) => (
                    <div key={k} className="flex justify-between text-text-secondary">
                      <span>{k.replace(/_/g, " ")}</span>
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-surface-hover rounded-full overflow-hidden">
                          <div className="h-full bg-accent rounded-full" style={{ width: `${v * 100}%` }} />
                        </div>
                        <span className="font-mono w-10 text-right">{(v * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  ))}
              </div>
            </div>
            <div>
              <h3 className="font-medium text-text-primary mb-3">Thresholds</h3>
              <div className="space-y-1.5">
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
      )}
    </div>
  );
}

// ---------- Components ----------

function BetCard({ bet }: { bet: ActiveBet }) {
  const daysUntilClose = Math.max(
    0,
    (new Date(bet.closeTime).getTime() - Date.now()) / (1000 * 60 * 60 * 24)
  );

  return (
    <div className="p-4 rounded-xl bg-surface border border-border">
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-text-primary text-sm">{bet.title}</span>
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">
            {daysUntilClose < 1 ? "<1d" : `${daysUntilClose.toFixed(0)}d`} left
          </span>
          <span
            className={cn(
              "text-xs px-2 py-0.5 rounded font-medium",
              bet.side === "yes"
                ? "bg-green-500/20 text-green-400"
                : "bg-red-500/20 text-red-400"
            )}
          >
            {bet.side.toUpperCase()} @ {bet.entryPrice}c
          </span>
        </div>
      </div>
      <div className="grid grid-cols-4 gap-4 text-xs text-text-secondary">
        <div>
          <span className="text-text-tertiary">Contracts: </span>
          {bet.contracts}
        </div>
        <div>
          <span className="text-text-tertiary">Cost: </span>
          ${(bet.totalCost / 100).toFixed(2)}
        </div>
        <div>
          <span className="text-text-tertiary">Potential: </span>
          <span className="text-green-400">${(bet.contracts - bet.totalCost / 100).toFixed(2)}</span>
        </div>
        <div>
          <span className="text-text-tertiary">Confidence: </span>
          {bet.confidence.toFixed(0)}/100
        </div>
      </div>
      {/* Reasoning expandable */}
      <details className="mt-2">
        <summary className="text-xs text-text-tertiary cursor-pointer hover:text-text-secondary">
          Scoring breakdown
        </summary>
        <div className="mt-1 text-xs text-text-tertiary space-y-0.5 pl-2 border-l border-border">
          {bet.reasoning.map((r, i) => (
            <div key={i}>{r}</div>
          ))}
        </div>
      </details>
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
    <div className="p-3 rounded-xl bg-surface border border-border">
      <div className="text-xs text-text-tertiary mb-1">{label}</div>
      <div className={cn("text-lg font-bold font-mono", valueColor ?? "text-text-primary")}>
        {value}
      </div>
      {sub && (
        <div className={cn("text-xs mt-0.5", subColor ?? "text-text-tertiary")}>{sub}</div>
      )}
    </div>
  );
}

function formatCountdown(ms: number): string {
  if (ms <= 0) return "now";
  const mins = Math.floor(ms / 60000);
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  const remainMins = mins % 60;
  return `${hrs}h${remainMins > 0 ? `${remainMins}m` : ""}`;
}

function timeAgo(isoDate: string): string {
  const ms = Date.now() - new Date(isoDate).getTime();
  const hours = Math.floor(ms / (1000 * 60 * 60));
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}
