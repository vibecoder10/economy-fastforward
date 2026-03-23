"use client";

import { cn } from "@/lib/utils";
import type { TextareaHTMLAttributes } from "react";

interface TextareaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, "className"> {
  label?: string;
  error?: string;
  helperText?: string;
}

export function Textarea({
  label,
  error,
  helperText,
  id,
  ...props
}: TextareaProps) {
  const textareaId = id || `textarea-${label?.toLowerCase().replace(/\s+/g, "-")}`;

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label
          htmlFor={textareaId}
          className="text-sm font-medium text-[var(--text-secondary)]"
        >
          {label}
        </label>
      )}
      <textarea
        id={textareaId}
        className={cn(
          "w-full rounded-lg border bg-[var(--surface)] px-3 py-2 text-sm",
          "placeholder:text-[var(--text-secondary)]/50",
          "focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "resize-y min-h-[80px]",
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
