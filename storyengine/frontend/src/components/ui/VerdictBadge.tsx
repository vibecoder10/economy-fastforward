import { cn } from "@/lib/utils";

const VERDICT_CONFIG = {
  hit: { color: "var(--green)", bg: "var(--green-dim)", label: "Hit" },
  steady: { color: "var(--yellow)", bg: "var(--yellow-dim)", label: "Steady" },
  underperformed: { color: "var(--red)", bg: "var(--red-dim)", label: "Underperformed" },
};

interface VerdictBadgeProps {
  verdict: "hit" | "steady" | "underperformed";
}

export function VerdictBadge({ verdict }: VerdictBadgeProps) {
  const config = VERDICT_CONFIG[verdict];
  return (
    <span
      className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-medium"
      style={{ background: config.bg, color: config.color }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full animate-pulse-dot"
        style={{ background: config.color, boxShadow: `0 0 6px ${config.color}` }}
      />
      {config.label}
    </span>
  );
}
