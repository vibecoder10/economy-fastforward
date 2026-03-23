"use client";

import { cn } from "@/lib/utils";
import type { InputHTMLAttributes } from "react";

interface TextInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "className"> {
  label?: string;
  error?: string;
  helperText?: string;
}

export function TextInput({
  label,
  error,
  helperText,
  id,
  ...props
}: TextInputProps) {
  const inputId = id || `input-${label?.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label
          htmlFor={inputId}
          className="text-sm font-medium text-[var(--text-secondary)]"
        >
          {label}
        </label>
      )}
      <input
        id={inputId}
        className={cn(
          "w-full rounded-lg border bg-[var(--surface)] px-3 py-2 text-sm",
          "placeholder:text-[var(--text-secondary)]/50",
          "focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          error
            ? "border-[var(--error)] focus:border-[var(--error)] focus:ring-[var(--error)]"
            : "border-[var(--border)]"
        )}
        {...props}
      />
      {error && (
        <span className="text-xs text-[var(--error)]">{error}</span>
      )}
      {helperText && !error && (
        <span className="text-xs text-[var(--text-secondary)]">{helperText}</span>
      )}
    </div>
  );
}
