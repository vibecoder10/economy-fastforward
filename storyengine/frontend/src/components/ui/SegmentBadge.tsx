import { cn } from "@/lib/utils";

interface SegmentBadgeProps {
  label: string;
  color?: string;
  className?: string;
}

export function SegmentBadge({ label, color, className }: SegmentBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center justify-center px-2 py-0.5 rounded text-[10px] font-mono font-medium",
        className
      )}
      style={{
        background: color ? `${color}22` : "var(--turquoise-dim)",
        color: color || "var(--turquoise)",
        border: `1px solid ${color ? `${color}33` : "var(--turquoise-dim)"}`,
      }}
    >
      {label}
    </span>
  );
}
