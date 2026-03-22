"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface TradingPanelProps {
  ticker: string;
  yesPrice: number;
  noPrice: number;
  connected: boolean;
}

export function TradingPanel({
  ticker,
  yesPrice,
  noPrice,
  connected,
}: TradingPanelProps) {
  const [side, setSide] = useState<"yes" | "no">("yes");
  const [contracts, setContracts] = useState(1);
  const [price, setPrice] = useState(side === "yes" ? yesPrice : noPrice);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ type: "success" | "error"; message: string } | null>(null);

  const totalCost = (contracts * price) / 100;
  const maxPayout = (contracts * 100) / 100;
  const profit = maxPayout - totalCost;

  const handleSideChange = (newSide: "yes" | "no") => {
    setSide(newSide);
    setPrice(newSide === "yes" ? yesPrice : noPrice);
    setResult(null);
  };

  const handleSubmit = async () => {
    if (!connected) return;
    setSubmitting(true);
    setResult(null);

    try {
      const res = await fetch("/api/kalshi/orders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ticker,
          side,
          action: "buy",
          contracts,
          price,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        setResult({ type: "error", message: data.error || "Order failed" });
      } else {
        setResult({
          type: "success",
          message: `Order placed: ${contracts} ${side.toUpperCase()} @ ${price}¢`,
        });
        setContracts(1);
      }
    } catch {
      setResult({ type: "error", message: "Network error" });
    }
    setSubmitting(false);
  };

  if (!connected) {
    return (
      <div className="bg-surface border border-border rounded-xl p-6">
        <h3 className="text-lg font-semibold mb-4">Trade</h3>
        <div className="text-center py-8">
          <div className="text-4xl mb-3">🔗</div>
          <p className="text-text-secondary mb-4">
            Connect your Kalshi account to start trading
          </p>
          <a
            href="/settings"
            className="inline-block px-6 py-2.5 bg-accent hover:bg-accent-hover text-background font-semibold rounded-lg transition-colors"
          >
            Connect Kalshi Account
          </a>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-border rounded-xl p-6">
      <h3 className="text-lg font-semibold mb-4">Trade</h3>

      {/* Side toggle */}
      <div className="grid grid-cols-2 gap-2 mb-5">
        <button
          onClick={() => handleSideChange("yes")}
          className={cn(
            "py-2.5 rounded-lg font-semibold text-sm transition-all",
            side === "yes"
              ? "bg-success text-background"
              : "bg-surface-hover text-text-secondary hover:text-text-primary"
          )}
        >
          Yes {yesPrice}¢
        </button>
        <button
          onClick={() => handleSideChange("no")}
          className={cn(
            "py-2.5 rounded-lg font-semibold text-sm transition-all",
            side === "no"
              ? "bg-error text-white"
              : "bg-surface-hover text-text-secondary hover:text-text-primary"
          )}
        >
          No {noPrice}¢
        </button>
      </div>

      {/* Price input */}
      <div className="mb-4">
        <label className="block text-xs text-text-tertiary mb-1.5">
          Price (¢)
        </label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPrice((p) => Math.max(1, p - 1))}
            className="w-10 h-10 rounded-lg bg-surface-hover text-text-secondary hover:text-text-primary text-lg font-medium transition-colors"
          >
            -
          </button>
          <input
            type="number"
            min={1}
            max={99}
            value={price}
            onChange={(e) => setPrice(Math.min(99, Math.max(1, Number(e.target.value))))}
            className="flex-1 text-center px-3 py-2 bg-background border border-border rounded-lg text-text-primary font-mono text-lg focus:outline-none focus:border-accent"
          />
          <button
            onClick={() => setPrice((p) => Math.min(99, p + 1))}
            className="w-10 h-10 rounded-lg bg-surface-hover text-text-secondary hover:text-text-primary text-lg font-medium transition-colors"
          >
            +
          </button>
        </div>
      </div>

      {/* Contracts input */}
      <div className="mb-5">
        <label className="block text-xs text-text-tertiary mb-1.5">
          Contracts
        </label>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setContracts((c) => Math.max(1, c - 1))}
            className="w-10 h-10 rounded-lg bg-surface-hover text-text-secondary hover:text-text-primary text-lg font-medium transition-colors"
          >
            -
          </button>
          <input
            type="number"
            min={1}
            max={1000}
            value={contracts}
            onChange={(e) => setContracts(Math.min(1000, Math.max(1, Number(e.target.value))))}
            className="flex-1 text-center px-3 py-2 bg-background border border-border rounded-lg text-text-primary font-mono text-lg focus:outline-none focus:border-accent"
          />
          <button
            onClick={() => setContracts((c) => Math.min(1000, c + 1))}
            className="w-10 h-10 rounded-lg bg-surface-hover text-text-secondary hover:text-text-primary text-lg font-medium transition-colors"
          >
            +
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="bg-background rounded-lg p-4 mb-5 space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-text-secondary">Total cost</span>
          <span className="font-mono font-medium">${totalCost.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-text-secondary">Max payout</span>
          <span className="font-mono font-medium">${maxPayout.toFixed(2)}</span>
        </div>
        <div className="flex justify-between text-sm border-t border-border pt-2">
          <span className="text-text-secondary">Potential profit</span>
          <span className="font-mono font-medium text-success">
            +${profit.toFixed(2)}
          </span>
        </div>
      </div>

      {/* Result message */}
      {result && (
        <div
          className={cn(
            "p-3 rounded-lg text-sm mb-4",
            result.type === "success"
              ? "bg-success/10 text-success border border-success/20"
              : "bg-error/10 text-error border border-error/20"
          )}
        >
          {result.message}
        </div>
      )}

      {/* Submit */}
      <button
        onClick={handleSubmit}
        disabled={submitting}
        className={cn(
          "w-full py-3 rounded-lg font-semibold text-sm transition-all disabled:opacity-50",
          side === "yes"
            ? "bg-success hover:bg-success/90 text-background"
            : "bg-error hover:bg-error/90 text-white"
        )}
      >
        {submitting
          ? "Placing order..."
          : `Buy ${side === "yes" ? "Yes" : "No"} — $${totalCost.toFixed(2)}`}
      </button>
    </div>
  );
}
