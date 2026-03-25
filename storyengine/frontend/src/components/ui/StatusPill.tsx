"use client";

import { cn } from "@/lib/utils";

const COLOR_MAP: Record<string, { bg: string; text: string }> = {
  turquoise: { bg: "rgba(0, 212, 170, 0.15)", text: "var(--turquoise)" },
  gold: { bg: "rgba(212, 168, 82, 0.15)", text: "var(--gold)" },
  orange: { bg: "rgba(255, 120, 73, 0.15)", text: "var(--orange)" },
  red: { bg: "rgba(255, 77, 106, 0.15)", text: "var(--red)" },
  green: { bg: "rgba(0, 230, 138, 0.15)", text: "var(--green)" },
  purple: { bg: "rgba(139, 92, 246, 0.15)", text: "var(--purple)" },
  yellow: { bg: "rgba(255, 208, 88, 0.15)", text: "var(--yellow)" },
};

interface StatusPillProps {
  label: string;
  color?: string;
  pulse?: boolean;
  size?: "sm" | "md";
}

export function StatusPill({ label, color = "turquoise", pulse, size = "sm" }: StatusPillProps) {
  const mapped = COLOR_MAP[color] || { bg: `${color}22`, text: color };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full font-medium font-body",
        size === "sm" ? "px-2.5 py-0.5 text-[11px]" : "px-3 py-1 text-xs",
        pulse && "animate-pulse-dot"
      )}
      style={{ background: mapped.bg, color: mapped.text }}
    >
      {pulse && (
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: mapped.text }}
        />
      )}
      {label}
    </span>
  );
}
