"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getDashboardSummary, getVideos } from "@/lib/api";
import { ActionCard } from "@/components/action-card";
import { formatCost, timeAgo } from "@/lib/utils";
import {
  CheckCircle2,
  Clock,
  DollarSign,
  Film,
  AlertCircle,
} from "lucide-react";

const ATTENTION_STATUSES = [
  "ready_for_scripting",
  "ready_for_storyboards",
  "ready_for_thumbnail",
];

function getAttentionMessage(status: string): string {
  const messages: Record<string, string> = {
    ready_for_scripting: "Script ready for review",
    ready_for_storyboards: "Storyboard ready for review",
    ready_for_thumbnail: "Thumbnail ready for review",
  };
  return messages[status] || "Needs attention";
}

export default function DashboardPage() {
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: getDashboardSummary,
  });

  const { data: videos, isLoading: videosLoading } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
  });

  const actionItems = (videos || []).filter((v: any) =>
    ATTENTION_STATUSES.includes(v.status)
  );

  const recentActivity = (videos || [])
    .filter(
      (v: any) =>
        v.status === "done" ||
        v.status === "uploaded_draft" ||
        v.status === "rendered"
    )
    .sort(
      (a: any, b: any) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )
    .slice(0, 5);

  const isLoading = summaryLoading || videosLoading;

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1
          className="text-2xl font-bold"
          style={{ color: "var(--text-primary)" }}
        >
          Good morning, Ryan
        </h1>
        <p className="mt-1" style={{ color: "var(--text-secondary)" }}>
          {actionItems.length > 0
            ? `${actionItems.length} video${actionItems.length !== 1 ? "s" : ""} need${actionItems.length === 1 ? "s" : ""} approval`
            : "All clear — no approvals pending"}
        </p>
      </div>

      {/* Main grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Action items */}
        <div className="space-y-3">
          {isLoading ? (
            <>
              <SkeletonCard />
              <SkeletonCard />
            </>
          ) : actionItems.length > 0 ? (
            actionItems.map((v: any) => (
              <ActionCard
                key={v.id}
                title={v.video_title}
                message={getAttentionMessage(v.status)}
                href={`/pipeline?video=${v.id}`}
              />
            ))
          ) : (
            <div
              className="rounded-xl p-6 text-center"
              style={{
                background: "var(--bg-card)",
                border: "1px solid var(--border)",
              }}
            >
              <CheckCircle2
                size={32}
                className="mx-auto mb-2"
                style={{ color: "var(--green)" }}
              />
              <p
                className="text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                No approvals needed
              </p>
            </div>
          )}
        </div>

        {/* Center: Recent activity */}
        <div>
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            Recent Activity
          </h2>
          <div className="space-y-1">
            {isLoading ? (
              <>
                <SkeletonLine />
                <SkeletonLine />
                <SkeletonLine />
              </>
            ) : recentActivity.length > 0 ? (
              recentActivity.map((v: any) => (
                <Link
                  key={v.id}
                  href={`/pipeline?video=${v.id}`}
                  className="flex items-center gap-3 py-2 rounded-lg px-2 -mx-2 transition-colors hover:bg-[var(--bg-card)]"
                >
                  <div
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{
                      background:
                        v.status === "done"
                          ? "var(--green)"
                          : "var(--teal)",
                    }}
                  />
                  <span
                    className="text-sm truncate flex-1"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {v.video_title}
                  </span>
                  <span
                    className="text-xs shrink-0"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {v.status === "done"
                      ? "published"
                      : v.status.replace(/_/g, " ")}
                  </span>
                </Link>
              ))
            ) : (
              <p
                className="text-sm"
                style={{ color: "var(--text-muted)" }}
              >
                No recent activity
              </p>
            )}
          </div>
        </div>

        {/* Right: Quick stats */}
        <div>
          <h2
            className="text-sm font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-muted)" }}
          >
            Quick Stats
          </h2>
          <div className="grid grid-cols-2 gap-3">
            <QuickStat
              label="Published"
              value={`${summary?.pipeline_distribution?.done || 0} videos`}
              icon={Film}
            />
            <QuickStat
              label="Pending"
              value={`${summary?.pending_review || 0} reviews`}
              icon={AlertCircle}
            />
            <QuickStat
              label="Pipeline"
              value={`${summary?.total_videos || 0} total`}
              icon={Clock}
            />
            <QuickStat
              label="Spend"
              value={
                summary?.cost_today
                  ? formatCost(summary.cost_today)
                  : "$0"
              }
              icon={DollarSign}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function QuickStat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: any;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      <div className="flex items-center justify-between mb-2">
        <span
          className="text-xs uppercase tracking-wider"
          style={{ color: "var(--text-muted)" }}
        >
          {label}
        </span>
        <Icon size={14} style={{ color: "var(--text-muted)" }} />
      </div>
      <p
        className="text-lg font-bold"
        style={{ color: "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div
      className="rounded-xl p-4 animate-pulse"
      style={{ background: "var(--bg-card)" }}
    >
      <div
        className="h-4 rounded w-3/4 mb-2"
        style={{ background: "var(--border)" }}
      />
      <div
        className="h-3 rounded w-1/2"
        style={{ background: "var(--border)" }}
      />
    </div>
  );
}

function SkeletonLine() {
  return (
    <div className="flex items-center gap-3 py-2 animate-pulse">
      <div
        className="w-2 h-2 rounded-full"
        style={{ background: "var(--border)" }}
      />
      <div
        className="h-3 rounded flex-1"
        style={{ background: "var(--border)" }}
      />
    </div>
  );
}
