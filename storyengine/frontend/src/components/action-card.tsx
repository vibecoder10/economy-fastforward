"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

interface ActionCardProps {
  title: string;
  message: string;
  href: string;
  actionLabel?: string;
  status?: "warning" | "error" | "info";
}

export function ActionCard({
  title,
  message,
  href,
  actionLabel = "Review",
  status = "warning",
}: ActionCardProps) {
  const dotColor = {
    warning: "var(--amber)",
    error: "var(--red)",
    info: "var(--teal)",
  }[status];

  return (
    <Link
      href={href}
      className="block rounded-xl p-4 transition-colors"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-2.5 h-2.5 rounded-full mt-1.5 shrink-0"
          style={{ background: dotColor }}
        />
        <div className="flex-1 min-w-0">
          <h3
            className="text-sm font-semibold truncate"
            style={{ color: "var(--text-primary)" }}
          >
            {title}
          </h3>
          <p
            className="text-sm mt-0.5"
            style={{ color: "var(--text-secondary)" }}
          >
            {message}
          </p>
        </div>
        <div
          className="flex items-center gap-1 text-sm font-medium shrink-0"
          style={{ color: "var(--amber)" }}
        >
          {actionLabel}
          <ArrowRight size={14} />
        </div>
      </div>
    </Link>
  );
}
