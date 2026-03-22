"use client";

import { useState, useEffect, useCallback } from "react";
import { MarketCard } from "@/components/trading/MarketCard";
import { cn } from "@/lib/utils";
import type { MarketDisplayData, MarketCategory } from "@/lib/trading-types";
import { CATEGORIES } from "@/lib/trading-types";
import type { KalshiMarket } from "@/lib/kalshi-types";

function toDisplayData(m: KalshiMarket, watchlist: Set<string>): MarketDisplayData {
  return {
    ticker: m.ticker,
    eventTicker: m.event_ticker,
    title: m.title,
    yesPrice: m.yes_bid || m.last_price,
    noPrice: m.no_bid || (100 - (m.yes_bid || m.last_price)),
    volume: m.volume,
    volume24h: m.volume_24h,
    closeTime: m.close_time,
    category: m.category || "Geopolitics",
    status: m.status,
    isWatchlisted: watchlist.has(m.ticker),
  };
}

export default function MarketsPage() {
  const [markets, setMarkets] = useState<MarketDisplayData[]>([]);
  const [loading, setLoading] = useState(true);
  const [category, setCategory] = useState<MarketCategory>("All");
  const [search, setSearch] = useState("");
  const [watchlist, setWatchlist] = useState<Set<string>>(new Set());

  const fetchMarkets = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (category !== "All") params.set("category", category);
      if (search) params.set("search", search);

      const res = await fetch(`/api/kalshi/markets?${params}`);
      const data = await res.json();
      setMarkets(
        (data.markets || []).map((m: KalshiMarket) => toDisplayData(m, watchlist))
      );
    } catch {
      setMarkets([]);
    }
    setLoading(false);
  }, [category, search, watchlist]);

  useEffect(() => {
    // Load watchlist
    fetch("/api/trading/watchlist")
      .then((r) => r.json())
      .then((data) => {
        const tickers = new Set<string>(
          (data.items || []).map((i: { marketTicker: string }) => i.marketTicker)
        );
        setWatchlist(tickers);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMarkets();
  }, [fetchMarkets]);

  const toggleWatchlist = async (ticker: string) => {
    const isWatched = watchlist.has(ticker);
    const market = markets.find((m) => m.ticker === ticker);

    if (isWatched) {
      await fetch(`/api/trading/watchlist?marketTicker=${ticker}`, {
        method: "DELETE",
      });
      setWatchlist((prev) => {
        const next = new Set(prev);
        next.delete(ticker);
        return next;
      });
    } else if (market) {
      await fetch("/api/trading/watchlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          eventTicker: market.eventTicker,
          marketTicker: ticker,
          title: market.title,
        }),
      });
      setWatchlist((prev) => new Set(prev).add(ticker));
    }

    // Update display
    setMarkets((prev) =>
      prev.map((m) =>
        m.ticker === ticker ? { ...m, isWatchlisted: !isWatched } : m
      )
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Prediction Markets</h1>
        <p className="text-text-secondary mt-1">
          Trade on geopolitics, economics, and world events
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4">
        {/* Category tabs */}
        <div className="flex gap-1 overflow-x-auto pb-1">
          {CATEGORIES.map((cat) => (
            <button
              key={cat}
              onClick={() => setCategory(cat)}
              className={cn(
                "px-4 py-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors",
                category === cat
                  ? "bg-accent text-background"
                  : "bg-surface text-text-secondary hover:text-text-primary hover:bg-surface-hover"
              )}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="flex-1 max-w-sm">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search markets..."
            className="w-full px-4 py-2 bg-surface border border-border rounded-lg text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none focus:border-accent transition-colors"
          />
        </div>
      </div>

      {/* Markets grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="bg-surface border border-border rounded-xl p-5 animate-pulse"
            >
              <div className="h-4 bg-border rounded w-3/4 mb-4" />
              <div className="h-8 bg-border rounded w-1/3 mb-3" />
              <div className="h-1.5 bg-border rounded mb-3" />
              <div className="h-3 bg-border rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : markets.length === 0 ? (
        <div className="text-center py-16 text-text-secondary">
          <p className="text-lg mb-2">No markets found</p>
          <p className="text-sm text-text-tertiary">
            Try a different category or search term
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {markets.map((market) => (
            <MarketCard
              key={market.ticker}
              market={market}
              onToggleWatchlist={toggleWatchlist}
            />
          ))}
        </div>
      )}
    </div>
  );
}
