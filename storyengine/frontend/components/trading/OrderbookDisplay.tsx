"use client";

import type { KalshiOrderbook } from "@/lib/kalshi-types";

interface OrderbookDisplayProps {
  orderbook: KalshiOrderbook;
}

export function OrderbookDisplay({ orderbook }: OrderbookDisplayProps) {
  const maxQty = Math.max(
    ...orderbook.yes.map((l) => l.quantity),
    ...orderbook.no.map((l) => l.quantity),
    1
  );

  return (
    <div className="bg-surface border border-border rounded-xl p-5">
      <h3 className="text-sm font-semibold text-text-secondary mb-4">
        Order Book
      </h3>

      <div className="grid grid-cols-2 gap-4">
        {/* Yes (bids) */}
        <div>
          <div className="flex justify-between text-xs text-text-tertiary mb-2 px-1">
            <span>Price</span>
            <span>Qty</span>
          </div>
          <div className="space-y-1">
            {orderbook.yes.map((level, i) => (
              <div key={i} className="relative">
                <div
                  className="absolute inset-y-0 right-0 bg-success/10 rounded"
                  style={{ width: `${(level.quantity / maxQty) * 100}%` }}
                />
                <div className="relative flex justify-between px-2 py-1 text-sm font-mono">
                  <span className="text-success">{level.price}¢</span>
                  <span className="text-text-secondary">{level.quantity}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* No (asks) */}
        <div>
          <div className="flex justify-between text-xs text-text-tertiary mb-2 px-1">
            <span>Price</span>
            <span>Qty</span>
          </div>
          <div className="space-y-1">
            {orderbook.no.map((level, i) => (
              <div key={i} className="relative">
                <div
                  className="absolute inset-y-0 left-0 bg-error/10 rounded"
                  style={{ width: `${(level.quantity / maxQty) * 100}%` }}
                />
                <div className="relative flex justify-between px-2 py-1 text-sm font-mono">
                  <span className="text-error">{level.price}¢</span>
                  <span className="text-text-secondary">{level.quantity}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-border flex justify-between text-xs text-text-tertiary">
        <span>YES bids</span>
        <span>NO asks</span>
      </div>
    </div>
  );
}
