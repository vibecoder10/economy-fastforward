"use client";

import {
  Check, Loader2, Search, FileText, Users, MapPin, Video, Volume2, Film, Upload, BarChart3,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import type { ProductionGuide, ProductionGuideStage } from "@/lib/api";

/** The 3 states this rail ever shows. Production-guide stages can also come
 * back "skipped_by_format" — those are handled separately (excluded from the
 * segment's state, segment hidden if every member is skipped) rather than
 * given a 4th visual state here. */
type SegmentState = "not_started" | "in_progress" | "done";

const STATE_ORDER: Record<SegmentState, number> = { not_started: 0, in_progress: 1, done: 2 };

const STATUS_COLOR: Record<SegmentState, string> = {
  done: "var(--turquoise)",
  in_progress: "var(--gold)",
  not_started: "var(--text-tertiary)",
};

/** One segment per clickable tab on the regular (non-static_docu) pipeline
 * page — now ALL 10 tabs from the page's own TABS array (U5: this rail is
 * the ONLY tab switcher on the page, the old numbered tab strip is gone, so
 * every tab needs a bubble). Results has no build stage of its own to
 * track, so it rides the Upload stage's state — same mapping page.tsx's own
 * TAB_STAGES already used for the "performance" tab (`performance: ["upload"]`).
 * Order matches TABS in page.tsx. */
const SEGMENTS: { tabId: string; label: string; icon: typeof Search; stageKeys: string[] }[] = [
  { tabId: "research", label: "Research", icon: Search, stageKeys: ["research"] },
  { tabId: "script-voice", label: "Script & Voice", icon: FileText, stageKeys: ["script", "voice"] },
  { tabId: "characters", label: "Characters", icon: Users, stageKeys: ["characters"] },
  { tabId: "environments", label: "Environments", icon: MapPin, stageKeys: ["environments"] },
  { tabId: "scenes", label: "Scenes", icon: Video, stageKeys: ["storyboards", "images", "video"] },
  { tabId: "sound", label: "Sound", icon: Volume2, stageKeys: ["sound"] },
  { tabId: "thumbnail", label: "Thumbnail", icon: Film, stageKeys: ["thumbnail"] },
  { tabId: "render", label: "Render", icon: Film, stageKeys: ["render"] },
  { tabId: "upload", label: "Upload", icon: Upload, stageKeys: ["upload"] },
  { tabId: "performance", label: "Results", icon: BarChart3, stageKeys: ["upload"] },
];

interface SegmentInfo {
  tabId: string;
  label: string;
  icon: typeof Search;
  state: SegmentState;
  detail: string;
  /** Some (but not all) member stages are skipped_by_format — dim the
   * segment a touch, but it still shows real status from its live members. */
  partiallySkipped: boolean;
}

/** Folds a segment's member stage keys down to one state + caption: worst
 * state wins (not_started < in_progress < done), skipped_by_format members
 * are dropped from the vote entirely. Returns null when every member is
 * skipped — the caller hides the segment in that case. */
function computeSegment(
  seg: (typeof SEGMENTS)[number],
  stages: ProductionGuideStage[],
): SegmentInfo | null {
  const members = seg.stageKeys
    .map((k) => stages.find((s) => s.key === k))
    .filter((s): s is ProductionGuideStage => Boolean(s));
  const live = members.filter((s) => s.state !== "skipped_by_format");
  if (members.length === 0 || live.length === 0) return null;

  const worst = live.reduce((acc, s) => (STATE_ORDER[s.state as SegmentState] < STATE_ORDER[acc.state as SegmentState] ? s : acc));
  return {
    tabId: seg.tabId,
    label: seg.label,
    icon: seg.icon,
    state: worst.state as SegmentState,
    detail: worst.detail,
    partiallySkipped: live.length < members.length,
  };
}

interface StageRailProps {
  guide: ProductionGuide;
  activeTab: string;
  onSelect: (tabId: string) => void;
  /** Declutter (2026-07-22): a stage-owned control block can portal itself in
   * here — right now only the Scenes tab's progress summary + bulk-generate
   * button (see ScenesWorkspaceTab's `stageRailSlot` prop), which used to be
   * its own full-width green banner below this card. Empty div, zero footprint,
   * whenever no tab has anything to show. */
  slotRef?: React.RefObject<HTMLDivElement | null>;
}

/** The regular (non-static_docu) pipeline page's clickable stage rail —
 * navigation only, no Run/Run All (every tab is already reachable and each
 * tab owns its own run actions). U5: this is now the ONLY tab switcher on
 * the page — the old numbered tab strip below it was removed as a
 * duplicate. Reuses StaticDocuStageRail's visual language (icon circles,
 * connector line, status colors) so the two rails read as one family
 * across formats. */
export function StageRail({ guide, activeTab, onSelect, slotRef }: StageRailProps) {
  const segments = SEGMENTS
    .map((seg) => computeSegment(seg, guide.stages))
    .filter((s): s is SegmentInfo => s !== null);

  return (
    <GlassCard className="p-4">
      {/* Rail takes priority: shrink-0 + its own overflow-x-auto keeps the
          icon row intact and scrollable rather than letting the slot content
          squeeze or wrap it at ~1280px. The slot only wraps to its own line
          (parent flex-wrap) when both don't fit side by side. */}
      <div className="flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide shrink-0">
        {segments.map((seg, idx) => {
          const Icon = seg.icon;
          const isActive = activeTab === seg.tabId;
          const color = STATUS_COLOR[seg.state];
          const doneSoFar = segments.slice(0, idx + 1).every((s) => s.state === "done");
          return (
            <div key={seg.tabId} className="flex items-center shrink-0">
              <button
                onClick={() => onSelect(seg.tabId)}
                title={seg.detail}
                className="flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-all"
                style={{
                  background: isActive ? "var(--turquoise-bg)" : "transparent",
                  minWidth: 92,
                  opacity: seg.partiallySkipped ? 0.6 : 1,
                }}
              >
                <div
                  className="flex items-center justify-center rounded-full"
                  style={{
                    width: 32, height: 32,
                    background: seg.state === "done" ? "var(--turquoise)" : "var(--bg-elevated)",
                    border: `2px solid ${color}`,
                    color: seg.state === "done" ? "var(--bg-void)" : color,
                  }}
                >
                  {seg.state === "in_progress" ? <Loader2 size={14} className="animate-spin" /> : seg.state === "done" ? <Check size={14} strokeWidth={3} /> : <Icon size={14} />}
                </div>
                <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: isActive ? "var(--turquoise)" : "var(--text-secondary)" }}>
                  {seg.label}
                </span>
                <span className="text-[9px] text-center leading-tight line-clamp-2" style={{ color: "var(--text-tertiary)", maxWidth: 88 }}>
                  {seg.detail}
                </span>
              </button>
              {idx < segments.length - 1 && (
                <div className="w-4 h-0.5 shrink-0" style={{ background: doneSoFar ? "var(--turquoise)" : "var(--border-subtle)" }} />
              )}
            </div>
          );
        })}
        </div>
        {/* Slot for a stage's own control block (e.g. Scenes' bulk-generate
            button), portaled in from the active tab. Empty + weightless
            (no min-height/padding) when nothing targets it. ml-auto pins it
            right, vertically centered with the icon rail via items-center
            on the parent row above. */}
        <div ref={slotRef} className="flex items-center gap-3 flex-wrap ml-auto" />
      </div>
    </GlassCard>
  );
}
