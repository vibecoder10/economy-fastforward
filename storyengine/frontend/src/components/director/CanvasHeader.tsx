"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, Redo2, Undo2 } from "lucide-react";
import { useDirector, type Altitude } from "./DirectorContext";
import { getVideo, getVideoActions, getVideoLedger, runBuild } from "@/lib/api";
import { formatCost } from "@/lib/utils";
import { useConfirm } from "@/components/ui/confirm";
import { useToast } from "@/components/ui/toast";

/**
 * Full-width topbar for the Director canvas (Chunk 1.E). Mirrors
 * storyengine/tasks/director-mockup/index.html `.topbar` (~L749-820):
 * back arrow, logo mark, project title/subtitle, centered altitude
 * segmented control, then Undo/Redo, a read-only 16:9 pill, Preview/Export,
 * the cost dial, and Build.
 *
 * `TERMINAL_STATUSES` is duplicated here (not imported) — the pipeline page
 * (src/app/pipeline/[videoId]/page.tsx) defines its own local copy too and
 * doesn't export one. Same 4-value set, single source of truth would be a
 * follow-up, not this chunk's job.
 */
const TERMINAL_STATUSES = new Set(["uploaded", "uploaded_draft", "done", "published"]);

const STAGE_LABELS: Record<string, string> = {
  pictures: "Pictures",
  images: "Pictures",
  clips: "Clips",
  animate: "Clips",
  voice: "Voice",
  thumbnail: "Thumbnail",
  sound: "Sound",
  render: "Render",
  other: "Other",
};

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage.charAt(0).toUpperCase() + stage.slice(1);
}

function humanize(id: string | null | undefined): string | null {
  if (!id) return null;
  return id
    .split(/[_-]/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

const ALTITUDES: { id: Altitude; label: string }[] = [
  { id: "shot", label: "Shot" },
  { id: "scene", label: "Scene" },
  { id: "timeline", label: "Timeline" },
];

export function CanvasHeader({ videoId }: { videoId: string }) {
  const { setSelectedVideoId, altitude, setAltitude } = useDirector();

  // Sibling video query — title/subtitle AND the status the cost-ledger poll
  // below keys off of. Deliberately a plain useQuery (not a ref/callback)
  // so `videoQuery.data?.status` reads the live value on every render.
  const videoQuery = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });

  const actionsQuery = useQuery({
    queryKey: ["video-actions", videoId],
    queryFn: () => getVideoActions(videoId),
    refetchInterval: () => {
      const s = videoQuery.data?.status;
      if (!s || TERMINAL_STATUSES.has(s)) return false;
      return 10000;
    },
  });

  const [costOpen, setCostOpen] = useState(false);
  const ledgerQuery = useQuery({
    queryKey: ["video-ledger", videoId],
    queryFn: () => getVideoLedger(videoId),
    // Critical rule (chunk brief): poll while WORK IS RUNNING, read off the
    // sibling video query's status — not this query's own state.data.status
    // (that's the bug the pipeline page's pattern would reproduce here).
    refetchInterval: () => {
      const s = videoQuery.data?.status;
      if (!s || TERMINAL_STATUSES.has(s)) return false;
      return 5000;
    },
  });

  const confirm = useConfirm();
  const toast = useToast();
  const [building, setBuilding] = useState(false);

  const video = videoQuery.data;
  const summary = actionsQuery.data?.summary;
  const styleLabel = humanize(video?.production_style_id ?? null);
  const shotsMade = summary ? summary.pics + summary.clips : null;
  const subtitleParts = [
    styleLabel,
    summary ? `${summary.scenes} scene${summary.scenes === 1 ? "" : "s"}` : null,
    shotsMade !== null ? `${shotsMade} shot${shotsMade === 1 ? "" : "s"}` : null,
  ].filter((p): p is string => Boolean(p));

  const buildInfo = actionsQuery.data?.actions.find((a) => a.verb === "build");
  const buildLabel = actionsQuery.data?.build_target === "finish" ? "Finish the video" : "Build";
  const buildDisabled = !actionsQuery.data || building || (video && TERMINAL_STATUSES.has(video.status || ""));

  const handleBuild = async () => {
    if (!actionsQuery.data) return;
    const ok = await confirm({
      title: buildLabel,
      message: buildInfo?.cost_text
        ? `${buildInfo.blocked ?? "This runs the next production stage."} Estimated cost: ${buildInfo.cost_text}.`
        : "This runs the next production stage.",
      confirmLabel: buildLabel,
    });
    if (!ok) return;
    setBuilding(true);
    try {
      await runBuild(videoId, actionsQuery.data.build_target);
      toast.info(`${buildLabel} started — follow along in the tracker.`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Couldn't start the build.");
    } finally {
      setBuilding(false);
    }
  };

  const stages = ledgerQuery.data ? Object.entries(ledgerQuery.data.by_stage).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="relative z-40 flex h-[54px] flex-none items-center gap-3 border-b border-line bg-surface px-3.5">
      {/* left cluster */}
      <div className="flex w-[330px] min-w-0 items-center gap-2.5">
        <button
          type="button"
          onClick={() => setSelectedVideoId(null)}
          title="Back to home"
          className="flex h-8 w-8 flex-none items-center justify-center rounded-card-sm text-dim transition-colors hover:border hover:border-line-soft hover:bg-raise hover:text-ink"
        >
          <ArrowLeft size={16} />
        </button>
        <div
          className="flex h-[26px] w-[26px] flex-none items-center justify-center rounded-[8px] text-[13px] font-extrabold text-[#04120E]"
          style={{ background: "linear-gradient(140deg,#00D4AA,#0B7F9E)" }}
        >
          S
        </div>
        <div className="min-w-0">
          <div className="truncate text-[13px] font-semibold text-ink">
            {videoQuery.isLoading ? "Loading…" : video?.video_title || "Untitled video"}
          </div>
          <div className="truncate text-[11px] text-faint">
            {videoQuery.isError
              ? "Couldn't load this video"
              : subtitleParts.length > 0
                ? subtitleParts.join(" · ")
                : "—"}
          </div>
        </div>
      </div>

      {/* centered altitude segmented control */}
      <div className="absolute left-1/2 flex -translate-x-1/2 gap-0.5 rounded-[10px] border border-line-soft bg-deep p-[3px]">
        {ALTITUDES.map((a) => (
          <button
            key={a.id}
            type="button"
            data-tab={a.id}
            onClick={() => setAltitude(a.id)}
            className={`h-[26px] rounded-[7px] px-4 text-[12.5px] font-semibold transition-colors ${
              altitude === a.id
                ? "bg-turquoise/[0.14] text-turquoise shadow-[inset_0_0_0_1px_rgba(0,212,170,0.28)]"
                : "text-dim hover:text-ink"
            }`}
          >
            {a.label}
          </button>
        ))}
      </div>

      {/* right cluster */}
      <div className="ml-auto flex items-center gap-2">
        <button
          type="button"
          disabled
          title="Undo — not available yet"
          className="flex h-8 w-8 flex-none items-center justify-center rounded-card-sm text-faint opacity-50"
        >
          <Undo2 size={15} />
        </button>
        <button
          type="button"
          disabled
          title="Redo — not available yet"
          className="flex h-8 w-8 flex-none items-center justify-center rounded-card-sm text-faint opacity-50"
        >
          <Redo2 size={15} />
        </button>

        <div className="flex h-7 items-center rounded-full border border-line-soft bg-deep px-2.5 text-xs text-dim">
          16:9
        </div>

        <div className="h-[22px] w-px bg-line-soft" />

        <button
          type="button"
          disabled
          title="Preview — not available yet"
          className="h-8 rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink opacity-50"
        >
          Preview
        </button>
        <button
          type="button"
          disabled
          title="Export — not available yet"
          className="h-8 rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink opacity-50"
        >
          Export
        </button>

        {/* cost dial */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setCostOpen((o) => !o)}
            className="flex h-8 items-center gap-2 rounded-[10px] border border-turquoise/35 bg-turquoise/[0.08] px-3 transition-colors hover:border-turquoise/60 hover:bg-turquoise/[0.15]"
          >
            <div className="text-left leading-none">
              <div className="text-[9.5px] font-semibold uppercase tracking-[0.1em] text-faint">This video</div>
              <div className="text-[15px] font-bold leading-[1.1] text-turquoise tabular-nums">
                {ledgerQuery.data ? formatCost(ledgerQuery.data.total_cost) : video ? formatCost(video.total_cost) : "$0.00"}
              </div>
            </div>
            <ChevronDown size={11} className="text-faint" />
          </button>

          {costOpen && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setCostOpen(false)} />
              <div className="absolute right-0 top-[42px] z-50 w-[360px] rounded-card border border-line bg-surface p-[18px] shadow-[0_26px_60px_rgba(0,0,0,0.7)]">
                <div className="mb-1 text-[14.5px] font-semibold text-ink">What this video costs</div>
                <div className="mb-3.5 text-xs leading-relaxed text-dim">
                  Real spend so far, by stage — the same ledger every dollar figure in this app reads from.
                </div>

                {ledgerQuery.isLoading && <div className="py-3 text-xs text-faint">Loading the ledger…</div>}
                {ledgerQuery.isError && (
                  <div className="py-3 text-xs text-red">Couldn&apos;t load the ledger.</div>
                )}
                {!ledgerQuery.isLoading && !ledgerQuery.isError && stages.length === 0 && (
                  <div className="py-3 text-xs leading-relaxed text-dim">
                    Nothing spent yet — this hits $0.00 until the first paid step finishes.
                  </div>
                )}
                {stages.length > 0 && (
                  <div className="space-y-1.5">
                    {stages.map(([stage, cost]) => (
                      <div key={stage} className="flex items-center justify-between rounded-[11px] border border-line-soft bg-deep px-3 py-2 text-[12.5px]">
                        <span className="text-dim">{stageLabel(stage)}</span>
                        <span className="font-semibold tabular-nums text-ink">{formatCost(cost)}</span>
                      </div>
                    ))}
                    <div className="flex items-center justify-between border-t border-line-soft pt-2 text-[12.5px]">
                      <span className="text-faint">Total spent</span>
                      <span className="font-bold tabular-nums text-turquoise">
                        {formatCost(ledgerQuery.data?.total_cost ?? 0)}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={handleBuild}
          disabled={buildDisabled}
          title={buildInfo?.blocked ?? buildInfo?.cost_text ?? undefined}
          className="h-8 rounded-[9px] px-3.5 text-[13px] font-semibold text-[#04120E] shadow-[0_2px_14px_rgba(0,212,170,0.28)] transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: "linear-gradient(180deg,#00E4B8,#00B492)" }}
        >
          {building ? "Starting…" : buildLabel}
        </button>
      </div>
    </div>
  );
}
