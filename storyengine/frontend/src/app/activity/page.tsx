"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getActivity, getActivityStats } from "@/lib/api";
import { ActivityFeed } from "@/components/activity-feed";
import { StatCard } from "@/components/stat-card";
import { formatCost } from "@/lib/utils";
import { cn } from "@/lib/utils";
import { Bot, AlertTriangle, DollarSign } from "lucide-react";

const FILTER_OPTIONS = [
  { key: "all", label: "All" },
  { key: "running", label: "Running" },
  { key: "failed", label: "Errors" },
  { key: "completed", label: "Completed" },
];

export default function ActivityPage() {
  const [filter, setFilter] = useState("all");

  const { data: entries = [], isLoading } = useQuery({
    queryKey: ["activity", filter],
    queryFn: () => getActivity(filter === "all" ? undefined : filter),
    refetchInterval: 10_000, // Poll every 10s
  });

  const { data: stats } = useQuery({
    queryKey: ["activity-stats"],
    queryFn: getActivityStats,
    refetchInterval: 10_000,
  });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold">Activity</h1>

      {/* Stats mini cards */}
      <div className="grid grid-cols-3 gap-2">
        <StatCard
          label="Bots Running"
          value={`${stats?.bots_running ?? 0}`}
          icon={<Bot size={14} />}
          accent={(stats?.bots_running ?? 0) > 0}
        />
        <StatCard
          label="Errors Today"
          value={stats?.errors_today ?? 0}
          icon={<AlertTriangle size={14} />}
          error={(stats?.errors_today ?? 0) > 0}
        />
        <StatCard
          label="Cost Today"
          value={formatCost(stats?.cost_today ?? 0)}
          icon={<DollarSign size={14} />}
        />
      </div>

      {/* Filter chips */}
      <div className="flex gap-2">
        {FILTER_OPTIONS.map((opt) => (
          <button
            key={opt.key}
            onClick={() => setFilter(opt.key)}
            className={cn(
              "rounded-full px-3 py-1.5 text-xs font-medium transition-colors",
              filter === opt.key
                ? "bg-[var(--accent)] text-black"
                : "bg-[var(--surface)] text-[var(--text-secondary)]"
            )}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl bg-[var(--surface)]" />
          ))}
        </div>
      )}

      {/* Feed */}
      {!isLoading && <ActivityFeed entries={entries} />}
    </div>
  );
}
