"use client";

import { AlertTriangle } from "lucide-react";
import { GlassCard } from "./GlassCard";
import { ActionButton } from "./ActionButton";

interface ErrorCardProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}

export function ErrorCard({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: ErrorCardProps) {
  return (
    <GlassCard className={className}>
      <div className="flex flex-col items-center justify-center py-10 text-center">
        <div
          className="mb-4 rounded-full p-3"
          style={{ background: "var(--red-dim)" }}
        >
          <AlertTriangle size={28} style={{ color: "var(--red)" }} />
        </div>
        <h3
          className="text-lg font-semibold font-body mb-1"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </h3>
        {message && (
          <p
            className="text-sm font-body max-w-md mb-5"
            style={{ color: "var(--text-secondary)" }}
          >
            {message}
          </p>
        )}
        {onRetry && (
          <ActionButton variant="outline" onClick={onRetry}>
            Retry
          </ActionButton>
        )}
      </div>
    </GlassCard>
  );
}
