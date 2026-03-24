"use client";

import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, AlertTriangle, CheckCircle, ChevronRight } from "lucide-react";
import Link from "next/link";
import { cn } from "@/lib/utils";

export interface CTRAlert {
  videoId: string;
  title: string;
  ctr: number;
  checkType: "6h" | "24h" | "48h" | "7d";
  status: "critical" | "warning" | "normal" | "strong";
  publishedAt: string;
}

interface CTRAlertsProps {
  alerts: CTRAlert[];
  className?: string;
}

const statusConfig = {
  critical: {
    icon: AlertTriangle,
    color: "text-[var(--error)]",
    bgColor: "bg-[var(--error)]/10",
    borderColor: "border-[var(--error)]/30",
    label: "Critical",
  },
  warning: {
    icon: TrendingDown,
    color: "text-[var(--warning)]",
    bgColor: "bg-[var(--warning)]/10",
    borderColor: "border-[var(--warning)]/30",
    label: "Warning",
  },
  normal: {
    icon: TrendingUp,
    color: "text-[var(--text-secondary)]",
    bgColor: "bg-[var(--surface-elevated)]",
    borderColor: "border-[var(--border)]",
    label: "Normal",
  },
  strong: {
    icon: CheckCircle,
    color: "text-green-500",
    bgColor: "bg-green-500/10",
    borderColor: "border-green-500/30",
    label: "Strong",
  },
};

function formatTimeAgo(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60));

  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

export function CTRAlerts({ alerts, className }: CTRAlertsProps) {
  if (alerts.length === 0) {
    return null;
  }

  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--text-secondary)]">
          CTR Alerts
        </h2>
        <Link
          href="/analytics"
          className="flex items-center gap-1 text-xs font-medium text-[var(--accent)]"
        >
          View All
          <ChevronRight size={14} />
        </Link>
      </div>

      <div className="space-y-2">
        {alerts.map((alert, index) => {
          const config = statusConfig[alert.status];
          const Icon = config.icon;

          return (
            <motion.div
              key={alert.videoId}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
            >
              <Link
                href={`/pipeline?video=${alert.videoId}`}
                className={cn(
                  "flex items-center gap-3 rounded-lg border p-3 transition-colors hover:bg-[var(--surface-elevated)]",
                  config.borderColor,
                  config.bgColor
                )}
              >
                {/* Status icon */}
                <div
                  className={cn(
                    "flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg",
                    config.bgColor
                  )}
                >
                  <Icon size={16} className={config.color} />
                </div>

                {/* Content */}
                <div className="min-w-0 flex-1">
                  <p className="line-clamp-1 text-sm font-medium">
                    {alert.title}
                  </p>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                    <span>{formatTimeAgo(alert.publishedAt)}</span>
                    <span className="text-[var(--border)]">•</span>
                    <span>{alert.checkType} check</span>
                  </div>
                </div>

                {/* CTR value */}
                <div className="flex-shrink-0 text-right">
                  <p className={cn("text-sm font-semibold", config.color)}>
                    {alert.ctr.toFixed(1)}%
                  </p>
                  <p className="text-xs text-[var(--text-secondary)]">CTR</p>
                </div>
              </Link>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
