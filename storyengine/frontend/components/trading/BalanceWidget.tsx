"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

export function BalanceWidget() {
  const [balance, setBalance] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    async function fetchBalance() {
      try {
        const res = await fetch("/api/kalshi/portfolio");
        if (!res.ok) return;
        const data = await res.json();
        setBalance(data.balance?.balance ?? null);
        setConnected(data.connected ?? false);
      } catch {
        // Silent fail
      }
    }

    fetchBalance();
    const interval = setInterval(fetchBalance, 30000);
    return () => clearInterval(interval);
  }, []);

  if (!connected && balance === null) {
    return (
      <Link
        href="/settings"
        className="px-3 py-1.5 text-xs font-medium bg-accent/10 text-accent border border-accent/20 rounded-lg hover:bg-accent/20 transition-colors"
      >
        Connect Kalshi
      </Link>
    );
  }

  const dollars = balance !== null ? (balance / 100).toFixed(2) : "--";

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 bg-surface border border-border rounded-lg">
      <div className="w-2 h-2 rounded-full bg-success" />
      <span className="text-sm font-mono font-medium text-text-primary">
        ${dollars}
      </span>
    </div>
  );
}
