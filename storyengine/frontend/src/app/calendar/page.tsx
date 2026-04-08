"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getCalendarVideos, CalendarVideo } from "@/lib/api";
import { getStageLabel, getStageColor } from "@/lib/constants";
import { Spinner } from "@/components/ui/spinner";
import { EmptyState } from "@/components/ui/EmptyState";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
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

  const { data, isLoading } = useQuery({
    queryKey: ["calendar", start, end],
    queryFn: () => getCalendarVideos(start, end),
  });

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
