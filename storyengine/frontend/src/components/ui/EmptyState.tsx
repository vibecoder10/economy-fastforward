"use client";

import type { LucideIcon } from "lucide-react";
import { GlassCard } from "./GlassCard";
import { ActionButton } from "./ActionButton";

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  actionHref?: string;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  actionLabel,
  onAction,
  actionHref,
  className,
}: EmptyStateProps) {
  const handleAction = () => {
    if (actionHref) {
      window.location.href = actionHref;
    } else if (onAction) {
      onAction();
    }
  };

  return (
    <GlassCard className={className}>
      <div className="flex flex-col items-center justify-center py-12 text-center">
        {Icon && (
          <div
            className="mb-4 rounded-full p-4"
            style={{ background: "var(--turquoise-dim)" }}
          >
            <Icon size={32} style={{ color: "var(--turquoise)" }} />
          </div>
        )}
        <h3
          className="text-lg font-semibold font-body mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          {title}
        </h3>
        {description && (
          <p
            className="text-sm font-body max-w-md mb-6"
            style={{ color: "var(--text-secondary)" }}
          >
            {description}
          </p>
        )}
        {actionLabel && (onAction || actionHref) && (
          <ActionButton onClick={handleAction}>{actionLabel}</ActionButton>
        )}
      </div>
    </GlassCard>
  );
}
