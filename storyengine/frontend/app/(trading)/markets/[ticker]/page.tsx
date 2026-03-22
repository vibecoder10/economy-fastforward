"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { TradingPanel } from "@/components/trading/TradingPanel";
import { OrderbookDisplay } from "@/components/trading/OrderbookDisplay";
import { PriceChart } from "@/components/trading/PriceChart";
import type { KalshiMarket, KalshiOrderbook } from "@/lib/kalshi-types";

export default function MarketDetailPage() {
  const params = useParams();
  const ticker = params.ticker as string;

  const [market, setMarket] = useState<KalshiMarket | null>(null);
  const [orderbook, setOrderbook] = useState<KalshiOrderbook | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [marketRes, portfolioRes] = await Promise.all([
          fetch(`/api/kalshi/markets/${ticker}`),
          fetch("/api/kalshi/portfolio"),
        ]);

        const marketData = await marketRes.json();
        setMarket(marketData.market);
        setOrderbook(marketData.orderbook);

        const portfolioData = await portfolioRes.json();
        setConnected(portfolioData.connected ?? false);
      } catch {
        // Handled by UI
      }
      setLoading(false);
    }

    load();
  }, [ticker]);

  if (loading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-6 bg-surface rounded w-1/4" />
        <div className="h-10 bg-surface rounded w-3/4" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-6">
            <div className="h-48 bg-surface rounded-xl" />
            <div className="h-64 bg-surface rounded-xl" />
          </div>
          <div className="h-96 bg-surface rounded-xl" />
        </div>
      </div>
    );
  }

  if (!market) {
    return (
      <div className="text-center py-16">
        <p className="text-xl text-text-secondary mb-4">Market not found</p>
        <Link href="/markets" className="text-accent hover:text-accent-hover">
          Back to markets
        </Link>
      </div>
    );
  }

  const yesPrice = market.yes_bid || market.last_price;
  const noPrice = market.no_bid || (100 - yesPrice);

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-US", {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });

  const formatVolume = (v: number) => {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
    return String(v);
  };

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm text-text-tertiary">
        <Link href="/markets" className="hover:text-text-secondary transition-colors">
          Markets
        </Link>
        <span>/</span>
        <span className="text-text-secondary">{market.event_ticker}</span>
      </div>

      {/* Title */}
      <div>
        <h1 className="text-2xl font-bold mb-2">{market.title}</h1>
        <div className="flex items-center gap-4 text-sm text-text-tertiary">
          <span className="px-2 py-0.5 bg-surface rounded text-text-secondary">
            {market.category || "Geopolitics"}
          </span>
          <span>{formatVolume(market.volume)} contracts traded</span>
          <span>Expires {formatDate(market.close_time)}</span>
        </div>
      </div>

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Price chart */}
          <PriceChart currentPrice={yesPrice} title={market.title} />

          {/* Stats grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Yes Price", value: `${yesPrice}¢`, color: "text-success" },
              { label: "No Price", value: `${noPrice}¢`, color: "text-error" },
              { label: "Volume 24h", value: formatVolume(market.volume_24h) },
              { label: "Open Interest", value: formatVolume(market.open_interest) },
            ].map((stat) => (
              <div
                key={stat.label}
                className="bg-surface border border-border rounded-xl p-4"
              >
                <div className="text-xs text-text-tertiary mb-1">{stat.label}</div>
                <div className={`text-lg font-mono font-semibold ${stat.color || "text-text-primary"}`}>
                  {stat.value}
                </div>
              </div>
            ))}
          </div>

          {/* Orderbook */}
          {orderbook && <OrderbookDisplay orderbook={orderbook} />}
        </div>

        {/* Right: Trading */}
        <div className="lg:sticky lg:top-24 lg:self-start">
          <TradingPanel
            ticker={ticker}
            yesPrice={yesPrice}
            noPrice={noPrice}
            connected={connected}
          />
        </div>
      </div>
    </div>
  );
}
