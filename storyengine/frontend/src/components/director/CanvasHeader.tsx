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

// `built: false` marks a tab whose CanvasStage.tsx view is still a
// placeholder (ShotAltitudePlaceholder — still admits as much in its own
// body text). Honesty pass (2026-07-27): those tabs used to look exactly as
// clickable as Scene, so a user had no way to know before tapping one that
// it dead-ends in "not designed yet" copy. Genuinely `disabled` (not just
// muted color) plus the same faint-text + "coming soon" tag already used for
// Preview/Export below and DirectorHome's ComingSoonButton — one honesty
// recipe, reused everywhere it applies, instead of a one-off for this
// control.
//
// Timeline flipped to `built: true` in chunk T2 (2026-07-28): the old
// TimelineAltitudePlaceholder static mock (and its own "New — doesn't exist
// in the product yet" pill) is gone from CanvasStage.tsx, replaced by a
// real, read-only TimelineAltitudeView reading the same
// video-script/video-assets data Scene already uses. See
// TIMELINE-WORKBENCH-PLAN.md.
const ALTITUDES: { id: Altitude; label: string; built: boolean }[] = [
  { id: "shot", label: "Shot", built: false },
  { id: "scene", label: "Scene", built: true },
  { id: "timeline", label: "Timeline", built: true },
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
    <div className="relative z-40 flex flex-none flex-col gap-2 border-b border-line bg-surface px-3 py-2 lg:h-[54px] lg:flex-row lg:items-center lg:gap-2 lg:px-3 lg:py-0">
      {/* left cluster — full-width row below `lg`; fixed 330px on the left at `lg`+ */}
      <div className="flex min-w-0 items-center gap-2.5 lg:w-[330px] lg:flex-none">
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

      {/* altitude segmented control — its own row below `lg` (never absolutely
          centered there, so it can never collide with the right cluster).
          At `lg`+ this used to be `absolute left-1/2 -translate-x-1/2`,
          centered on the FULL bar width with no awareness of how wide the
          right cluster actually is — found live (2026-07-27) overlapping
          "Timeline" under "Preview" at 1440px once Preview/Export grew a
          "coming soon" label: the right cluster's real width (~650px at
          1440px) pushes past where dead-center sits, and an absolutely
          positioned element doesn't yield space to its siblings. Fixed by
          putting it back in normal flex flow as a `flex-1` sibling between
          the fixed-330px left cluster and the right cluster — flex children
          never overlap by construction, so it centers in whatever space is
          actually left instead of the whole bar, and shrinks gracefully
          before it can collide with anything. `min-w-0`/`basis-0` let it
          shrink below its content size instead of forcing an overflow. */}
      <div className="flex flex-none self-start lg:min-w-0 lg:flex-1 lg:basis-0 lg:justify-center lg:self-auto">
        <div className="flex flex-none gap-0.5 rounded-[10px] border border-line-soft bg-deep p-[3px]">
          {ALTITUDES.map((a) => (
            <button
              key={a.id}
              type="button"
              data-tab={a.id}
              disabled={!a.built}
              title={a.built ? undefined : `${a.label} — not available yet`}
              onClick={() => setAltitude(a.id)}
              className={`flex h-[26px] items-center gap-1 rounded-[7px] px-3.5 text-[12.5px] font-semibold transition-colors disabled:cursor-not-allowed ${
                altitude === a.id
                  ? "bg-turquoise/[0.14] text-turquoise shadow-[inset_0_0_0_1px_rgba(0,212,170,0.28)]"
                  : a.built
                    ? "text-dim hover:text-ink"
                    : "text-faint"
              }`}
            >
              {a.label}
              {!a.built && (
                <span className="text-[8px] font-semibold uppercase tracking-wide text-faint/70">soon</span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* right cluster — below `2xl` the truly-decorative placeholders
          (Undo, Redo, the divider, Preview, Export) drop out and the row
          spreads its load-bearing survivors (16:9, cost pill, Build) to
          opposite edges so nothing can be clipped by the viewport.
          `flex-none` (not `ml-auto` — that's what the altitude control's
          `flex-1` neighbor already handles, see its comment) keeps this
          cluster sized to its own content while sitting flush right in the
          row.
          Undo/Redo/divider/Preview/Export switched from `lg:` to `2xl:`
          (2026-07-27, honesty pass): giving Preview/Export a visible "not
          available yet" reason (see below) makes each ~45px wider than the
          plain-text buttons they replaced. Measured live at a real 1440px
          laptop width: left cluster (330px, fixed) + this cluster's old
          content width (~650px, with the 16:9 pill still in it) left only
          ~150px for the altitude control's flex-1 slot — less than its own
          content (~190px+), so it overflowed both directions and visually
          overlapped "Timeline" under the honest "Preview" button, the exact
          overlap this pass exists to remove. `2xl` (1536px) is the first
          standard breakpoint with room for every one of these five plus the
          altitude tabs with margin to spare; below it they hide, same as
          today's mobile behavior.
          The 16:9 pill is pulled OUT of that group and kept unconditional
          (2026-07-27, follow-up): it's the one control here backed by a
          real, persisted field — `videos.aspect_ratio`, set at creation in
          CreateVideoStep.tsx and PATCHable after via `PATCH /api/videos/{id}`
          (routes/videos.py's `allowed_fields`, validated against
          {"16:9","9:16","1:1","4:3","3:4"}) — not a stub like the other
          four. It was ALSO silently wrong before this fix: hardcoded literal
          "16:9" text regardless of the video's actual ratio, so a 9:16
          Shorts video still showed "16:9" here. Now reads the real value.
          Hiding it behind the 2xl gate would have hidden a genuine,
          already-correct-when-fixed readout at the exact 1440px width the
          product owner uses — so it keeps the original `lg` tier instead of
          following its four dead neighbors up to `2xl`. Still read-only
          (matches this component's original doc comment, "a read-only 16:9
          pill") — editing aspect ratio mid-production has real cost/rework
          implications for an already-generated video that deserve their own
          confirm-and-cost flow, not a silent side effect of an honesty
          pass. */}
      <div className="flex items-center justify-between gap-1.5 2xl:flex-none 2xl:justify-normal">
        {/* Undo/Redo — genuinely unbuilt (no undo stack exists yet). Grouped
            in one card so the "not built" signal reads without a hover: faint
            icons plus a visible "soon" tag, not just a disabled attribute a
            user can't see. Native title tooltip still carries the full reason
            on hover, same wording as before. */}
        <div
          className="hidden items-center gap-0.5 rounded-card-sm border border-line-soft bg-white/[0.02] py-1 pl-1.5 pr-2 2xl:flex"
          title="Undo and Redo — not available yet"
        >
          <button
            type="button"
            disabled
            title="Undo — not available yet"
            className="flex h-6 w-6 flex-none items-center justify-center text-faint disabled:cursor-not-allowed"
          >
            <Undo2 size={14} />
          </button>
          <button
            type="button"
            disabled
            title="Redo — not available yet"
            className="flex h-6 w-6 flex-none items-center justify-center text-faint disabled:cursor-not-allowed"
          >
            <Redo2 size={14} />
          </button>
          <span className="pl-0.5 text-[9px] font-semibold uppercase tracking-wide text-faint/80">soon</span>
        </div>

        <div
          className="hidden h-7 items-center rounded-full border border-line-soft bg-deep px-2 text-xs text-dim lg:flex"
          title="This video's aspect ratio — set at creation, read-only here"
        >
          {video?.aspect_ratio || "16:9"}
        </div>

        <div className="hidden h-[22px] w-px bg-line-soft 2xl:block" />

        {/* Preview/Export — same "genuinely disabled" recipe as the home
            screen's ComingSoonButton (faint text, not full-contrast ink, plus
            a visible "coming soon" tag) so this reads the same everywhere in
            the app, not as a one-off. */}
        <button
          type="button"
          disabled
          title="Preview — not available yet"
          className="hidden h-8 items-center gap-1.5 rounded-[9px] border border-line-soft bg-white/[0.03] px-3.5 text-[13px] font-medium text-faint disabled:cursor-not-allowed 2xl:flex"
        >
          Preview <span className="text-[9px] uppercase tracking-wide text-faint/70">&middot; coming soon</span>
        </button>
        <button
          type="button"
          disabled
          title="Export — not available yet"
          className="hidden h-8 items-center gap-1.5 rounded-[9px] border border-line-soft bg-white/[0.03] px-3.5 text-[13px] font-medium text-faint disabled:cursor-not-allowed 2xl:flex"
        >
          Export <span className="text-[9px] uppercase tracking-wide text-faint/70">&middot; coming soon</span>
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
