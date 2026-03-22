"use client";

import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

interface StatCardProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  trend?: ReactNode;
  accent?: boolean;
  error?: boolean;
  onClick?: () => void;
}

export function StatCard({ label, value, icon, trend, accent, error, onClick }: StatCardProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex flex-col gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 text-left transition-colors",
        onClick && "cursor-pointer hover:bg-[var(--surface-elevated)]",
        !onClick && "cursor-default"
      )}
    >
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wider text-[var(--text-secondary)]">
          {label}
        </span>
        {icon && <span className="text-[var(--text-secondary)]">{icon}</span>}
      </div>
      <div className="flex items-end gap-2">
        <span
          className={cn(
            "text-2xl font-bold",
            accent && "text-[var(--accent)]",
            error && "text-[var(--error)]"
          )}
        >
          {value}
        </span>
        {trend}
      </div>
    </button>
  );
}
