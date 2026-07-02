"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getCalendarVideos,
  CalendarVideo,
  getCalendarPlan,
  CalendarPlanSlot,
  launchCandidate,
  launchQueueItem,
  patchQueueItem,
  deleteQueueItem,
} from "@/lib/api";
import { getStageLabel, getStageColor } from "@/lib/constants";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorCard } from "@/components/ui/ErrorCard";
import { ChevronLeft, ChevronRight, ChevronUp, ChevronDown, CalendarDays, Rocket, Loader2, ListOrdered, X } from "lucide-react";
import { motion } from "framer-motion";

function formatMonth(date: Date): string {
  return date.toLocaleDateString("en-US", { month: "long", year: "numeric" });
}

function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function getMonthRange(year: number, month: number) {
  const start = new Date(year, month, 1);
  const end = new Date(year, month + 1, 0);
  return { start: toDateStr(start), end: toDateStr(end) };
}

function getCalendarDays(year: number, month: number) {
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const days: (number | null)[] = [];
  // leading blanks
  for (let i = 0; i < firstDay; i++) days.push(null);
  for (let d = 1; d <= daysInMonth; d++) days.push(d);
  return days;
}

const STATUS_DOT_COLORS: Record<string, string> = {
  idea_logged: "var(--text-tertiary)",
  ready_for_scripting: "var(--turquoise)",
  ready_for_voice: "var(--turquoise)",
  ready_for_storyboards: "var(--turquoise)",
  ready_for_images: "var(--turquoise)",
  ready_for_thumbnail: "var(--turquoise)",
  ready_to_render: "var(--orange)",
  rendered: "var(--green)",
  uploaded_draft: "var(--gold)",
  done: "var(--green)",
};

function statusDotColor(status: string | null): string {
  if (!status) return "var(--text-tertiary)";
  return STATUS_DOT_COLORS[status] || "var(--turquoise)";
}

const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.02 } },
};
const item = {
  hidden: { opacity: 0, y: 8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.3 } },
};

export default function CalendarPage() {
  const today = new Date();
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());

  const { start, end } = useMemo(() => getMonthRange(year, month), [year, month]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () => getCalendarVideos(start, end),
  });

  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: plan } = useQuery({
    queryKey: ["calendar-plan"],
    queryFn: () => getCalendarPlan(30),
  });
  const [buildingId, setBuildingId] = useState<string | null>(null);
  const buildMutation = useMutation({
    mutationFn: launchCandidate,
    onSuccess: (res) => router.push(`/pipeline/${res.video_id}`),
    onError: () => setBuildingId(null),
  });
  const buildQueueMutation = useMutation({
    mutationFn: launchQueueItem,
    onSuccess: (res) => router.push(`/pipeline/${res.video_id}`),
    onError: () => setBuildingId(null),
  });
  const refreshPlan = () => queryClient.invalidateQueries({ queryKey: ["calendar-plan"] });
  const reorderMutation = useMutation({
    mutationFn: ({ id, position }: { id: string; position: number }) =>
      patchQueueItem(id, { position }),
    onSuccess: refreshPlan,
  });
  const removeMutation = useMutation({
    mutationFn: deleteQueueItem,
    onSuccess: refreshPlan,
  });
  // Move a queued slot one place up/down: land between its neighbors using the
  // position gaps (queue positions move in steps of 10).
  const queuedSlots = useMemo(
    () => (plan?.slots ?? []).filter((s) => s.kind === "queued"),
    [plan]
  );
  function moveQueued(slot: CalendarPlanSlot, dir: -1 | 1) {
    const idx = queuedSlots.findIndex((q) => q.queue_id === slot.queue_id);
    const target = queuedSlots[idx + dir];
    if (!slot.queue_id || !target?.position) return;
    reorderMutation.mutate({ id: slot.queue_id, position: target.position + (dir === -1 ? -5 : 5) });
  }

  const days = useMemo(() => getCalendarDays(year, month), [year, month]);
  const todayStr = toDateStr(today);
  const totalVideos = useMemo(() => {
    if (!data) return 0;
    return Object.values(data).reduce(
      (sum, vids) => sum + (vids as CalendarVideo[]).length,
      0
    );
  }, [data]);

  function goPrev() {
    if (month === 0) {
      setMonth(11);
      setYear(year - 1);
    } else {
      setMonth(month - 1);
    }
  }

  function goNext() {
    if (month === 11) {
      setMonth(0);
      setYear(year + 1);
    } else {
      setMonth(month + 1);
    }
  }

  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
  }

  return (
    <div className="p-4 md:p-8 max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl md:text-3xl font-display font-bold" style={{ color: "var(--text-primary)" }}>
          Production Calendar
        </h1>
        <button
          onClick={goToday}
          className="text-xs font-mono px-3 py-1.5 rounded-lg transition-colors"
          style={{
            border: "1px solid var(--border)",
            color: "var(--text-secondary)",
          }}
        >
          Today
        </button>
      </div>

      {/* Strategic plan (forward-looking, one-click build) */}
      {plan && plan.slots.length > 0 && (
        <div
          className="mb-8 rounded-xl p-4"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)" }}
        >
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <CalendarDays size={16} style={{ color: "var(--turquoise)" }} />
            <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Your strategic plan
            </h2>
            <span className="text-[10px]" style={{ color: "var(--text-tertiary)" }}>
              next {plan.slots.length} videos · ~every {plan.interval_days}d · easy wins first
            </span>
          </div>
          <p className="text-[11px] mb-3" style={{ color: "var(--text-tertiary)" }}>
            Ranked from what is winning in your niche, spaced to avoid format fatigue. Build any one with a click.
          </p>
          <div className="space-y-2">
            {plan.slots.map((s: CalendarPlanSlot) => {
              const isQueued = s.kind === "queued";
              const slotId = (isQueued ? s.queue_id : s.candidate_id) ?? "";
              const qIdx = isQueued ? queuedSlots.findIndex((q) => q.queue_id === s.queue_id) : -1;
              return (
                <div
                  key={slotId}
                  className="flex items-center gap-3 rounded-lg p-2.5"
                  style={{
                    background: isQueued ? "rgba(64,224,208,0.04)" : "rgba(255,255,255,0.02)",
                    border: isQueued ? "1px solid rgba(64,224,208,0.18)" : "1px solid rgba(255,255,255,0.05)",
                  }}
                >
                  <div className="text-center flex-shrink-0 w-12">
                    <p className="text-[9px] uppercase" style={{ color: "var(--text-tertiary)" }}>
                      {new Date(s.date + "T00:00:00").toLocaleDateString(undefined, { month: "short" })}
                    </p>
                    <p className="text-base font-bold leading-none" style={{ color: "var(--text-primary)" }}>
                      {new Date(s.date + "T00:00:00").getDate()}
                    </p>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5 min-w-0">
                      {isQueued && (
                        <span
                          className="flex-shrink-0 inline-flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded"
                          style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
                        >
                          <ListOrdered size={9} /> Queued by you
                        </span>
                      )}
                      <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>
                        {s.source_title}
                      </p>
                    </div>
                    <p className="text-[10px] truncate" style={{ color: "var(--text-secondary)" }}>
                      {s.source_channel} · {s.why}
                    </p>
                  </div>
                  {isQueued ? (
                    <div className="flex-shrink-0 flex items-center gap-0.5">
                      <button
                        onClick={() => moveQueued(s, -1)}
                        disabled={qIdx <= 0 || reorderMutation.isPending}
                        aria-label="Move up"
                        className="p-1 rounded transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-25"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        <ChevronUp size={14} />
                      </button>
                      <button
                        onClick={() => moveQueued(s, 1)}
                        disabled={qIdx === queuedSlots.length - 1 || reorderMutation.isPending}
                        aria-label="Move down"
                        className="p-1 rounded transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-25"
                        style={{ color: "var(--text-secondary)" }}
                      >
                        <ChevronDown size={14} />
                      </button>
                      <button
                        onClick={() => s.queue_id && removeMutation.mutate(s.queue_id)}
                        disabled={removeMutation.isPending}
                        aria-label="Remove from queue"
                        className="p-1 rounded transition-colors hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-25"
                        style={{ color: "var(--text-tertiary)" }}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ) : (
                    <div className="flex-shrink-0 text-center w-10">
                      <p className="text-sm font-bold" style={{ color: "var(--turquoise)" }}>{s.score}</p>
                      <p className="text-[8px]" style={{ color: "var(--text-tertiary)" }}>score</p>
                    </div>
                  )}
                  <button
                    onClick={() => {
                      setBuildingId(slotId);
                      if (isQueued && s.queue_id) buildQueueMutation.mutate(s.queue_id);
                      else if (s.candidate_id) buildMutation.mutate(s.candidate_id);
                    }}
                    disabled={buildingId === slotId}
                    className="flex-shrink-0 flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
                    style={{ background: "var(--turquoise)", color: "#0a0a0a" }}
                  >
                    {buildingId === slotId ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : (
                      <Rocket size={12} />
                    )}
                    Build
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Month nav */}
      <div className="flex items-center gap-4 mb-6">
        <button
          onClick={goPrev}
          className="p-2 rounded-lg transition-colors hover:bg-[rgba(255,255,255,0.05)]"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronLeft size={20} />
        </button>
        <span
          className="text-lg font-body font-semibold min-w-[180px] text-center"
          style={{ color: "var(--text-primary)" }}
        >
          {formatMonth(new Date(year, month))}
        </span>
        <button
          onClick={goNext}
          className="p-2 rounded-lg transition-colors hover:bg-[rgba(255,255,255,0.05)]"
          style={{ color: "var(--text-secondary)" }}
        >
          <ChevronRight size={20} />
        </button>
      </div>

      {/* Weekday headers */}
      <div className="grid grid-cols-7 mb-1">
        {WEEKDAYS.map((d) => (
          <div
            key={d}
            className="text-center text-[11px] font-mono uppercase tracking-wider py-2"
            style={{ color: "var(--text-tertiary)" }}
          >
            {d}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Spinner size="lg" />
        </div>
      ) : error ? (
        <ErrorCard
          title="Calendar unavailable"
          message="Could not load calendar data. The server may be down."
          onRetry={() => window.location.reload()}
        />
      ) : (
        <motion.div
          className="grid grid-cols-7"
          variants={container}
          initial="hidden"
          animate="show"
          key={`${year}-${month}`}
        >
          {days.map((day, i) => {
            if (day === null) {
              return <div key={`blank-${i}`} className="min-h-[90px] md:min-h-[110px]" />;
            }

            const dateStr = `${year}-${pad2(month + 1)}-${pad2(day)}`;
            const videos: CalendarVideo[] = data?.[dateStr] || [];
            const isToday = dateStr === todayStr;

            return (
              <motion.div
                key={dateStr}
                variants={item}
                className="min-h-[90px] md:min-h-[110px] p-1.5 md:p-2 rounded-lg"
                style={{
                  border: isToday ? "1px solid var(--turquoise)" : "1px solid var(--border-subtle)",
                  background: isToday ? "rgba(0,212,170,0.04)" : "transparent",
                }}
              >
                {/* Day number */}
                <div
                  className="text-[11px] font-mono mb-1"
                  style={{ color: isToday ? "var(--turquoise)" : "var(--text-tertiary)" }}
                >
                  {day}
                </div>

                {/* Video chips */}
                <div className="space-y-0.5">
                  {videos.slice(0, 3).map((v) => (
                    <Link
                      key={v.id}
                      href={`/pipeline/${v.id}`}
                      className="flex items-center gap-1 px-1 py-0.5 rounded transition-colors hover:bg-[rgba(255,255,255,0.06)] group"
                    >
                      <span
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ background: statusDotColor(v.status) }}
                      />
                      <span
                        className="text-[10px] font-body truncate group-hover:text-[var(--turquoise)]"
                        style={{ color: "var(--text-secondary)" }}
                        title={`${v.video_title || "Untitled"} — ${getStageLabel(v.status || "idea_logged")}`}
                      >
                        {v.video_title || "Untitled"}
                      </span>
                    </Link>
                  ))}
                  {videos.length > 3 && (
                    <span
                      className="text-[9px] font-mono px-1"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      +{videos.length - 3} more
                    </span>
                  )}
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      )}

      {/* Empty month indicator */}
      {!isLoading && totalVideos === 0 && (
        <EmptyState
          icon={CalendarDays}
          title="No videos scheduled this month"
          description="Videos appear on their creation or upload date"
        />
      )}
    </div>
  );
}
