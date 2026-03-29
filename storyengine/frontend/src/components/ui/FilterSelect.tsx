"use client";

import { cn } from "@/lib/utils";

interface FilterSelectProps {
  options: { value: string; label: string }[];
  value: string;
  onChange: (value: string) => void;
  label?: string;
  className?: string;
  disabled?: boolean;
  title?: string;
}

export function FilterSelect({ options, value, onChange, label, className, disabled = false, title }: FilterSelectProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      {label && (
        <label className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>
          {label}
        </label>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        title={title}
        className="px-3 py-2 rounded-lg text-sm font-body outline-none transition-all"
        style={{
          background: "var(--bg-elevated)",
          color: disabled ? "var(--text-tertiary)" : "var(--text-primary)",
          border: "1px solid var(--border)",
          opacity: disabled ? 0.65 : 1,
          cursor: disabled ? "not-allowed" : "pointer",
        }}
        onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
        onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    </div>
  );
}
