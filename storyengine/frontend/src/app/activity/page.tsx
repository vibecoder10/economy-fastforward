"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getActivity, getActivityStats } from "@/lib/api";
import { ActivityFeed } from "@/components/activity-feed";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatCard } from "@/components/ui/StatCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { formatCost } from "@/lib/utils";
import { motion } from "framer-motion";
import { Bot, AlertTriangle, DollarSign } from "lucide-react";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.1 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

const FILTER_OPTIONS = [
  { key: "all", label: "All", color: "turquoise" as const },
  { key: "running", label: "Running", color: "green" as const },
  { key: "failed", label: "Errors", color: "red" as const },
  { key: "completed", label: "Completed", color: "gold" as const },
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
    <motion.div
      className="space-y-5"
      variants={container}
      initial="hidden"
      animate="show"
    >
      <motion.h1 variants={item} className="text-2xl font-display" style={{ color: "var(--text-primary)" }}>
        Activity
      </motion.h1>

      {/* Stats cards */}
      <motion.div variants={item} className="grid grid-cols-3 gap-3">
        <StatCard
          label="Bots Running"
          value={`${stats?.bots_running ?? 0}`}
          color={(stats?.bots_running ?? 0) > 0 ? "var(--turquoise)" : "var(--text-secondary)"}
          icon={Bot}
        />
        <StatCard
          label="Errors Today"
          value={`${stats?.errors_today ?? 0}`}
          color={(stats?.errors_today ?? 0) > 0 ? "var(--red)" : "var(--text-secondary)"}
          icon={AlertTriangle}
        />
        <StatCard
          label="Cost Today"
          value={formatCost(stats?.cost_today ?? 0)}
          color="var(--gold)"
          icon={DollarSign}
        />
      </motion.div>

      {/* Filter chips */}
      <motion.div variants={item} className="flex gap-2">
        {FILTER_OPTIONS.map((opt) => (
          <div
            key={opt.key}
            onClick={() => setFilter(opt.key)}
            style={{ cursor: "pointer" }}
          >
            <StatusPill
              label={opt.label}
              color={filter === opt.key ? opt.color : "gold"}
              size="md"
            />
          </div>
        ))}
      </motion.div>

      {/* Loading */}
      {isLoading && (
        <motion.div variants={item} className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-16 animate-pulse rounded-xl glass-card" />
          ))}
        </motion.div>
      )}

      {/* Feed */}
      {!isLoading && (
        <motion.div variants={item}>
          <ActivityFeed entries={entries} />
        </motion.div>
      )}
    </motion.div>
  );
}
