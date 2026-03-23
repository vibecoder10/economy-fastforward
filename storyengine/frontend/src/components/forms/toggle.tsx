"use client";

import { cn } from "@/lib/utils";

interface ToggleProps {
  label?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  helperText?: string;
}

export function Toggle({
  label,
  checked,
  onChange,
  disabled,
  helperText,
}: ToggleProps) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="flex cursor-pointer items-center gap-3">
        <button
          type="button"
          role="switch"
          aria-checked={checked}
          disabled={disabled}
          onClick={() => onChange(!checked)}
          className={cn(
            "relative h-6 w-11 shrink-0 rounded-full transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-[var(--accent)] focus:ring-offset-2 focus:ring-offset-[var(--background)]",
            "disabled:cursor-not-allowed disabled:opacity-50",
            checked ? "bg-[var(--accent)]" : "bg-[var(--border)]"
          )}
        >
          <span
            className={cn(
              "block h-5 w-5 rounded-full bg-white shadow-sm transition-transform",
              "absolute top-0.5",
              checked ? "translate-x-[22px]" : "translate-x-0.5"
            )}
          />
        </button>
        {label && (
          <span className="text-sm font-medium text-[var(--text-primary)]">
            {label}
          </span>
        )}
      </label>
      {helperText && (
        <span className="text-xs text-[var(--text-secondary)]">{helperText}</span>
      )}
    </div>
  );
}
