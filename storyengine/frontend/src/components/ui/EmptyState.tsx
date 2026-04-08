"use client";

import { type LucideIcon } from "lucide-react";
import Link from "next/link";

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
  actionHref?: string;
}

export function EmptyState({ icon: Icon, title, description, actionLabel, onAction, actionHref }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-4 rounded-full bg-white/5 p-4">
        <Icon className="h-8 w-8 text-[var(--text-tertiary)]" />
      </div>
      <h3 className="text-lg font-medium text-[var(--text-primary)]">{title}</h3>
      {description && (
        <p className="mt-2 max-w-sm text-sm text-[var(--text-secondary)]">{description}</p>
      )}
      {actionLabel && actionHref && (
        <Link
          href={actionHref}
          className="mt-4 rounded-lg bg-[var(--turquoise)] px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90"
        >
          {actionLabel}
        </Link>
      )}
      {actionLabel && onAction && !actionHref && (
        <button
          onClick={onAction}
          className="mt-4 rounded-lg bg-[var(--turquoise)] px-4 py-2 text-sm font-medium text-black transition-opacity hover:opacity-90"
        >
          {actionLabel}
        </button>
      )}
    </div>
  );
}
