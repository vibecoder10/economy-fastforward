"use client";

import { cn } from "@/lib/utils";

interface Trade {
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

interface TradeHistoryProps {
  trades: Trade[];
}

export function TradeHistory({ trades }: TradeHistoryProps) {
  if (trades.length === 0) {
    return (
      <div className="bg-surface border border-border rounded-xl p-8 text-center">
        <p className="text-text-secondary">No trades yet</p>
        <p className="text-sm text-text-tertiary mt-1">
          Your trade history will appear here
        </p>
      </div>
    );
  }

  const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });

  return (
    <div className="bg-surface border border-border rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className="text-left px-4 py-3 text-xs font-medium text-text-tertiary">
                Date
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-tertiary">
                Market
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-text-tertiary">
                Side
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-text-tertiary">
                Qty
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-text-tertiary">
                Price
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-text-tertiary">
                Total
              </th>
              <th className="text-right px-4 py-3 text-xs font-medium text-text-tertiary">
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {trades.map((trade) => (
              <tr
                key={trade.id}
                className="border-b border-border/50 hover:bg-surface-hover transition-colors"
              >
                <td className="px-4 py-3 text-text-secondary font-mono text-xs">
                  {formatDate(trade.createdAt)}
                </td>
                <td className="px-4 py-3 text-text-primary font-medium">
                  {trade.marketTicker}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded text-xs font-semibold",
                      trade.side === "yes"
                        ? "bg-success/10 text-success"
                        : "bg-error/10 text-error"
                    )}
                  >
                    {trade.side.toUpperCase()}
                  </span>
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  {trade.contracts}
                </td>
                <td className="px-4 py-3 text-right font-mono">
                  {(trade.pricePerContract * 100).toFixed(0)}¢
                </td>
                <td className="px-4 py-3 text-right font-mono font-medium">
                  ${trade.totalCost.toFixed(2)}
                </td>
                <td className="px-4 py-3 text-right">
                  <span
                    className={cn(
                      "text-xs",
                      trade.status === "filled"
                        ? "text-success"
                        : trade.status === "canceled"
                          ? "text-error"
                          : "text-warning"
                    )}
                  >
                    {trade.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
