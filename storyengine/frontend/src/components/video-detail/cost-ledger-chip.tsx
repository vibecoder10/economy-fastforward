"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Loader2, AlertTriangle } from "lucide-react";
import { getVideoLedger } from "@/lib/api";
import { formatCost } from "@/lib/utils";

// Cost ledger chip + drawer (checklist §0.3d / C10). "Est." is the existing
// live spend estimate (from asset counts — see the page's `estimatedCost`);
// "Actual" is videos.total_cost, the generation_ledger rollup. Both numbers
// come from the server — no local price table lives in this component.
const STAGE_LABELS: Record<string, string> = {
  pictures: "Pictures",
  images: "Pictures",
  clips: "Clips",
  animate: "Clips",
  voice: "Voice",
  thumbnail: "Thumbnail",
  sound: "Sound",
  render: "Render",
  other: "Other",
};

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage.charAt(0).toUpperCase() + stage.slice(1);
}

interface CostLedgerChipProps {
  videoId: string;
  estimatedCost: number;
  actualCost: number;
}

export function CostLedgerChip({ videoId, estimatedCost, actualCost }: CostLedgerChipProps) {
  const [open, setOpen] = useState(false);

  // Fetch only once the drawer is opened — the chip itself needs no extra
  // request (it already has estimatedCost + actualCost from the page).
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["video-ledger", videoId],
    queryFn: () => getVideoLedger(videoId),
    enabled: open,
  });

  const stages = data ? Object.entries(data.by_stage).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-2 rounded-lg px-3 py-2 text-right transition-colors hover:brightness-110 active:scale-[0.98]"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        aria-expanded={open}
        aria-label="Cost breakdown: estimate vs actual spend"
      >
        <div>
          <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
            Est. → Actual
          </p>
          <p className="text-lg font-mono font-semibold" style={{ color: "var(--gold)" }}>
            {formatCost(estimatedCost)} → {formatCost(actualCost)}
          </p>
        </div>
        <ChevronDown
          size={16}
          style={{
            color: "var(--text-tertiary)",
            transform: open ? "rotate(180deg)" : undefined,
            transition: "transform 0.15s",
          }}
        />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 top-full mt-2 z-50 w-80 rounded-xl p-4 space-y-3"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
          >
            <div className="flex items-center justify-between">
              <p className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Spend breakdown
              </p>
              <p className="text-xs font-mono" style={{ color: "var(--text-tertiary)" }}>
                {formatCost(estimatedCost)} → {formatCost(actualCost)}
              </p>
            </div>

            {isLoading && (
              <div className="flex items-center gap-2 py-4 justify-center">
                <Loader2 size={16} className="animate-spin" style={{ color: "var(--turquoise)" }} />
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Loading ledger…</span>
              </div>
            )}

            {!isLoading && error && (
              <div className="space-y-2 py-2">
                <div className="flex items-center gap-2" style={{ color: "var(--red)" }}>
                  <AlertTriangle size={14} />
                  <span className="text-xs">Couldn&apos;t load the ledger.</span>
                </div>
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="text-xs underline"
                  style={{ color: "var(--turquoise)" }}
                >
                  Try again
                </button>
              </div>
            )}

            {!isLoading && !error && stages.length === 0 && (
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                No spend recorded yet — actual cost is $0.00 until the first paid step finishes.
              </p>
            )}

            {!isLoading && !error && stages.length > 0 && (
              <div className="space-y-1.5">
                {stages.map(([stage, cost]) => (
                  <div key={stage} className="flex items-center justify-between text-xs">
                    <span style={{ color: "var(--text-secondary)" }}>{stageLabel(stage)}</span>
                    <span className="font-mono" style={{ color: "var(--text-primary)" }}>{formatCost(cost)}</span>
                  </div>
                ))}
                <div
                  className="flex items-center justify-between text-xs pt-2 mt-1"
                  style={{ borderTop: "1px solid var(--border)" }}
                >
                  <span style={{ color: "var(--text-tertiary)" }}>Total actual</span>
                  <span className="font-mono font-semibold" style={{ color: "var(--gold)" }}>
                    {formatCost(data?.total_cost ?? actualCost)}
                  </span>
                </div>
              </div>
            )}

            <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
              Estimate is projected from what&apos;s been made so far; actual is the real ledgered spend.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
