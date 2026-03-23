"use client";

import { useQuery } from "@tanstack/react-query";
import { getDashboardSummary } from "@/lib/api";
import { StatCard } from "@/components/stat-card";
import { ProgressDots } from "@/components/progress-dots";
import { formatCost, formatNumber } from "@/lib/utils";
import { PIPELINE_STAGES } from "@/lib/constants";
import { Bot, ClipboardCheck, AlertTriangle, DollarSign, ListVideo, Play } from "lucide-react";
import Link from "next/link";

export default function HomePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: getDashboardSummary,
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-bold">Dashboard</h1>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-[var(--surface)]" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-bold">Dashboard</h1>

      {/* Stat cards grid */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
        <Link href="/activity">
          <StatCard
            label="Active Bots"
            value={data.active_bots}
            icon={
              data.active_bots > 0 ? (
                <span className="relative flex h-2.5 w-2.5">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75" />
                  <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
                </span>
              ) : (
                <Bot size={16} />
              )
            }
            accent={data.active_bots > 0}
          />
        </Link>

        <Link href="/review">
          <StatCard
            label="Pending Review"
            value={data.pending_review}
            icon={<ClipboardCheck size={16} />}
          />
        </Link>

        <StatCard
          label="Pipeline"
          value={data.total_videos}
          icon={<ListVideo size={16} />}
          trend={
            <div className="flex flex-wrap gap-1">
              {PIPELINE_STAGES.slice(0, 5).map((stage) => {
                const count = data.pipeline_distribution[stage.key] || 0;
                if (count === 0) return null;
                return (
                  <span key={stage.key} className="text-[10px] text-[var(--text-secondary)]">
                    {stage.label}: {count}
                  </span>
                );
              })}
            </div>
          }
        />

        <StatCard
          label="Cost Today"
          value={formatCost(data.cost_today)}
          icon={<DollarSign size={16} />}
        />

        {data.errors > 0 && (
          <StatCard
            label="Errors"
            value={data.errors}
            icon={<AlertTriangle size={16} />}
            error
          />
        )}

        {data.latest_video && (
          <Link href="/pipeline" className="col-span-2 md:col-span-1">
            <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="h-[45px] w-[80px] flex-shrink-0 overflow-hidden rounded-lg bg-[var(--surface-elevated)]">
                {data.latest_video.thumbnail_url ? (
                  <img src={data.latest_video.thumbnail_url} alt="" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center">
                    <Play size={16} className="text-[var(--text-secondary)]" />
                  </div>
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium uppercase tracking-wider text-[var(--text-secondary)]">
                  Latest Video
                </p>
                <p className="line-clamp-1 text-sm font-medium">{data.latest_video.video_title || "Untitled"}</p>
                <ProgressDots status={data.latest_video.status} />
              </div>
            </div>
          </Link>
        )}
      </div>
    </div>
  );
}
