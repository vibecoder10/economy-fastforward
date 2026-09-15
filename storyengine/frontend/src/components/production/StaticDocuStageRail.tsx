"use client";

import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Check, Loader2, Lock, AlertTriangle, Zap, ImageIcon, Images, Search, FileText, Volume2, Film,
} from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { useToast } from "@/components/ui/toast";
import { useConfirm } from "@/components/ui/confirm";
import { staticDocuRunAllPreflight } from "@/lib/static-docu-navigation";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import {
  runPipelineStage, runBuild, getRosterDashboard, clearStaleTask,
  type VideoDetail, type VideoActions, type RosterDashboard, type Asset,
} from "@/lib/api";
import { getStaticDocuReadiness } from "@/lib/static-docu";
import { persistedTaskActivity } from "@/lib/persisted-task-state";
import { useDrainMode } from "@/components/system/DrainModeProvider";

export type StaticDocuStageKey = "roster" | "image_gather" | "research" | "script" | "voice" | "pictures" | "video";
export type StageStatus = "done" | "in_progress" | "blocked" | "not_started";

interface StageInfo {
  status: StageStatus;
  detail: string;
}

const STAGE_META: Record<StaticDocuStageKey, { label: string; icon: typeof Search }> = {
  roster: { label: "Roster", icon: ImageIcon },
  image_gather: { label: "Gather images", icon: Images },
  research: { label: "Research", icon: Search },
  script: { label: "Script", icon: FileText },
  voice: { label: "Voice", icon: Volume2 },
  pictures: { label: "Pictures", icon: Images },
  video: { label: "Video", icon: Film },
};

const STAGE_ORDER: StaticDocuStageKey[] = ["roster", "image_gather", "research", "script", "voice", "pictures", "video"];

const RENDER_DONE_STATUSES = new Set(["rendered", "uploaded_draft", "uploaded", "done", "published"]);

/** Derive each of the 5 stages' live status from data the app already
 * fetches — no new read endpoint. Mirrors (at the UI layer) the same
 * done/in_progress/not_started logic backend/production_guide.py's
 * _stage_snapshot computes for the MCP co-pilot's guide tool, so an
 * operator staring at this rail and an agent calling get_production_guide
 * see the same picture of the video. */
export function computeStaticDocuStages(
  video: VideoDetail,
  videoActions: VideoActions | undefined,
  rosterDashboard: RosterDashboard | undefined,
  assets?: Asset[],
): Record<StaticDocuStageKey, StageInfo> {
  const summary = videoActions?.summary;
  const scenes = summary?.scenes ?? 0;
  const voiced = summary?.voiced ?? 0;

  const payload = video.research_payload || {};
  const selection = payload.roster_selection as Record<string, unknown> | undefined;
  const selectionMode = selection?.version === 1;
  const selectedUnits = Array.isArray(payload.unit_roster) ? payload.unit_roster : [];
  const targetCount = Number(selection?.target_count || selectedUnits.length || 0);
  const phase = String(payload.research_phase || "");
  const liveVerdict = payload.unit_roster_validation as Record<string, unknown> | undefined;
  const holdVerdict = payload.unit_research_hold_validation as Record<string, unknown> | undefined;
  const displayName = (item: unknown) => {
    if (typeof item === "string") return item.trim();
    const row = item as Record<string, unknown>;
    const name = String(row?.name || row?.unit || row?.machine || "").trim();
    const designation = String(row?.designation || "").trim();
    return designation && name && !name.toLowerCase().includes(designation.toLowerCase()) ? `${designation} ${name}` : name || designation;
  };
  const selectedNames = selectedUnits.map(displayName).filter(Boolean);
  const selectedSet = new Set(selectedNames);
  const dashboardUnits = rosterDashboard?.units ?? [];
  const dashboardNames = dashboardUnits.map((u) => u.machine.trim());
  const exactDashboard = selectedNames.length > 0 && selectedSet.size === selectedNames.length
    && rosterDashboard?.total === selectedNames.length && dashboardNames.length === selectedNames.length
    && new Set(dashboardNames).size === dashboardNames.length
    && dashboardNames.every((name) => selectedSet.has(name));
  const verified = exactDashboard ? dashboardUnits.filter((u) => u.reference?.status === "verified"
    && u.reference?.kind === "photo" && Boolean(u.reference?.hosted_url?.trim()) && Boolean(u.reference?.source_url?.trim())).length : 0;
  const total = selectedNames.length || rosterDashboard?.total || 0;
  // never-built (2026-07-30): a cancelled programme with no completed hardware
  // (reason_code "never_built", surfaced as retryable === false) can NEVER
  // have a verified photo — C5 skips it before any lookup, by design. Counting
  // it as "still needs a photo" made the roster gate impossible for any roster
  // containing one (the live case: CVA-01 froze the carrier video at 22/23
  // forever). Satisfied = verified OR never-built; only retryable misses block.
  const stillMissing = total - verified;
  const roster: StageInfo = selectionMode
    ? selection?.status === "completed" && selectedUnits.length > 0 && liveVerdict?.passed === true
      ? { status: "done", detail: `${selectedUnits.length}/${targetCount || selectedUnits.length} selected and independently accepted.` }
      : selection?.status === "needs_review" || selection?.status === "insufficient"
        ? { status: "blocked", detail: String(selection?.reason || "Roster selection needs review.") }
        : selectedUnits.length > 0
          ? { status: "in_progress", detail: `${selectedUnits.length}/${targetCount || selectedUnits.length} saved roster draft.` }
          : { status: "not_started", detail: "No roster established yet — run All to select one." }
    : liveVerdict?.passed === true
      ? { status: "done", detail: `${selectedUnits.length || total} saved roster entries accepted.` }
      : liveVerdict
        ? { status: "blocked", detail: "Saved roster facts need review before detailed research." }
      : total === 0
        ? { status: "not_started", detail: "No roster established yet — run Research." }
        : { status: "done", detail: `${selectedUnits.length || total} saved roster entries accepted.` };

  const receipt = payload.roster_images as Record<string, unknown> | undefined;
  const imagesComplete = exactDashboard && total > 0 && verified === total;
  const image_gather: StageInfo = imagesComplete
    ? { status: "done", detail: `${verified}/${total} verified photo references saved.` }
    : receipt?.status === "running"
      ? { status: "in_progress", detail: `${verified}/${total} verified reference images.` }
      : receipt?.status === "needs_review" || receipt?.status === "failed"
        ? { status: "blocked", detail: String(receipt.error || `${stillMissing} saved roster images still need review.`) }
        : { status: "not_started", detail: `${verified}/${total} verified reference images.` };

  const hasResearchPayload = Boolean(payload && (
    (Array.isArray(payload.unit_roster) && payload.unit_roster.length > 0)
    || (typeof payload.fact_sheet === "string" && payload.fact_sheet.trim())
    || (typeof payload.source_bibliography === "string" && payload.source_bibliography.trim())
  ));
  let research: StageInfo;
  if (selectionMode) {
    const readyCards = exactDashboard ? (rosterDashboard?.ready ?? 0) : 0;
    const holdUnits = Array.isArray(holdVerdict?.units) ? holdVerdict.units as Record<string, unknown>[] : [];
    const holdPassed = selectedNames.length > 0 && holdVerdict?.passed === true && holdUnits.length >= selectedNames.length && selectedNames.every((name) => holdUnits.some((unit) => (unit.machine === name || unit.name === name) && unit.passed === true));
    const cardsReady = selectedNames.length > 0 && readyCards >= selectedNames.length;
    research = holdPassed || cardsReady
      ? { status: "done", detail: `Research is ready for all ${targetCount || readyCards} saved roster entries.` }
      : phase === "unit_research"
        ? { status: "in_progress", detail: `${readyCards}/${targetCount || selectedUnits.length} saved roster research card(s) ready.` }
        : { status: "not_started", detail: "Roster is selected; detailed research has not started." };
  } else if (selectedUnits.length > 0) {
    const readyCards = exactDashboard ? (rosterDashboard?.ready ?? 0) : 0;
    const holdUnits = Array.isArray(holdVerdict?.units) ? holdVerdict.units as Record<string, unknown>[] : [];
    const holdPassed = selectedNames.length > 0 && holdVerdict?.passed === true && holdUnits.length >= selectedNames.length && selectedNames.every((name) => holdUnits.some((unit) => (unit.machine === name || unit.name === name) && unit.passed === true));
    const cardsReady = selectedUnits.length > 0 && readyCards >= selectedUnits.length;
    research = holdPassed || cardsReady
      ? { status: "done", detail: `Research is ready for all ${selectedUnits.length} saved roster entries.` }
      : phase === "unit_research"
        ? { status: "in_progress", detail: `${readyCards}/${selectedUnits.length} saved roster research card(s) ready.` }
        : { status: "not_started", detail: "Roster is saved; detailed research has not started." };
  } else if (!hasResearchPayload) {
    research = { status: "not_started", detail: "Not researched yet." };
  } else if (rosterDashboard && rosterDashboard.total > 0) {
    research = rosterDashboard.ready >= rosterDashboard.total
      ? { status: "done", detail: `All ${rosterDashboard.total} machine research card(s) are ready.` }
      : { status: "in_progress", detail: `${rosterDashboard.ready}/${rosterDashboard.total} machine research card(s) ready.` };
  } else {
    research = { status: "done", detail: "Research brief exists." };
  }

  const script: StageInfo = scenes > 0
    ? { status: "done", detail: `${scenes} segment(s) written.` }
    : { status: "not_started", detail: "Script not written yet." };

  const voice: StageInfo = scenes > 0 && voiced >= scenes
    ? { status: "done", detail: `All ${scenes} segment(s) voiced.` }
    : voiced > 0
      ? { status: "in_progress", detail: `${voiced}/${scenes} segment(s) voiced.` }
      : { status: "not_started", detail: "No narration yet." };

  // New aircraft target three views and become render-ready at two approved
  // views. Legacy one-image rows remain valid through the shared helper.
  const sceneNumbers = Array.from({ length: scenes }, (_, index) => index + 1);
  const pictureReadiness = getStaticDocuReadiness(assets ?? [], sceneNumbers);
  const pictures: StageInfo =
    scenes === 0
      ? { status: "not_started", detail: "No scenes yet — write the script first." }
      : pictureReadiness.blockedUnits > 0
        ? { status: "blocked", detail: `${pictureReadiness.blockedUnits} aircraft need more verified views or a reference fix.` }
        : pictureReadiness.allReady
          ? { status: "done", detail: `All ${scenes} aircraft ready (${pictureReadiness.readyViews} verified views).` }
          : pictureReadiness.generatingUnits > 0
            ? { status: "in_progress", detail: `${pictureReadiness.readyUnits}/${scenes} aircraft ready — drawing more views now…` }
            : { status: "not_started", detail: `${pictureReadiness.readyUnits}/${scenes} aircraft ready (${pictureReadiness.readyViews} verified views).` };

  const renderDone = RENDER_DONE_STATUSES.has(video.status || "");
  const hasThumb = Boolean(video.thumbnail_url);
  const videoStage: StageInfo =
    renderDone && hasThumb
      ? { status: "done", detail: "Rendered, with a thumbnail." }
      : video.status === "rendering"
        ? { status: "in_progress", detail: "Rendering now…" }
        : renderDone
          ? { status: "in_progress", detail: "Rendered — thumbnail still needed." }
          : hasThumb
            ? { status: "in_progress", detail: "Thumbnail set — awaiting render." }
            : { status: "not_started", detail: "Not rendered yet." };

  return { roster, image_gather, research, script, voice, pictures, video: videoStage };
}

/** Locked-until-previous-green gating, with ONE deliberate bootstrap
 * exception: Research is what DISCOVERS the roster in the first place (the
 * roster is a byproduct of the research payload — see static_docu.py /
 * pipeline_executor._machine_documentary_hold_roster), so Research can't
 * literally wait on a green Roster or nothing could ever start. Research is
 * only locked once a roster ALREADY EXISTS with a missing reference — at
 * that point, re-running research/script is spend the operator should stop
 * to fix a known-missing photo first, not the very first bootstrap call. */
export function computeCanRun(stages: Record<StaticDocuStageKey, StageInfo>): Record<StaticDocuStageKey, boolean> {
  const rosterGreen = stages.roster.status === "done";
  const imagesGreen = stages.image_gather.status === "done";
  const researchGreen = stages.research.status === "done";
  const scriptGreen = stages.script.status === "done";
  const voiceGreen = stages.voice.status === "done";
  const picturesGreen = stages.pictures.status === "done";
  return {
    roster: true,
    image_gather: rosterGreen,
    research: rosterGreen && imagesGreen,
    script: rosterGreen && imagesGreen && researchGreen,
    voice: rosterGreen && imagesGreen && researchGreen && scriptGreen,
    pictures: rosterGreen && imagesGreen && researchGreen && scriptGreen && voiceGreen,
    // C6: Video (thumbnail + render) now also waits on Pictures — a render
    // must not ship before every segment's picture is drawn (or the operator
    // has explicitly cleared the blocked ones).
    video: rosterGreen && imagesGreen && researchGreen && scriptGreen && voiceGreen && picturesGreen,
  };
}

function lockReason(key: StaticDocuStageKey, stages: Record<StaticDocuStageKey, StageInfo>): string | null {
  if (key === "roster") return null;
  if (key === "image_gather") return stages.roster.status === "done" ? null : "Accept the saved roster first.";
  if (key === "research") return stages.roster.status === "blocked"
    ? "Accept the selected machine roster before starting detailed research."
    : stages.image_gather.status !== "done" ? "Gather verified reference images first." : null;
  if (key === "script") {
    if (stages.roster.status !== "done") return "Locked until the Roster stage is green.";
    if (stages.research.status !== "done") return "Locked until Research is done.";
  }
  if (key === "voice") {
    if (stages.roster.status !== "done") return "Locked until the Roster stage is green.";
    if (stages.research.status !== "done") return "Locked until Research is done.";
    if (stages.script.status !== "done") return "Locked until the Script is written.";
  }
  if (key === "pictures") {
    if (stages.roster.status !== "done") return "Locked until the Roster stage is green.";
    if (stages.research.status !== "done") return "Locked until Research is done.";
    if (stages.script.status !== "done") return "Locked until the Script is written.";
    if (stages.voice.status !== "done") return "Locked until Voice is recorded.";
  }
  if (key === "video") {
    if (stages.roster.status !== "done") return "Locked until the Roster stage is green.";
    if (stages.research.status !== "done") return "Locked until Research is done.";
    if (stages.script.status !== "done") return "Locked until the Script is written.";
    if (stages.voice.status !== "done") return "Locked until Voice is recorded.";
    if (stages.pictures.status !== "done") return "Locked until every aircraft has at least its required verified views.";
  }
  return null;
}

const STATUS_COLOR: Record<StageStatus, string> = {
  done: "var(--turquoise)",
  in_progress: "var(--gold)",
  blocked: "var(--red)",
  not_started: "var(--text-tertiary)",
};

interface StaticDocuStageRailProps {
  video: VideoDetail & { id: string };
  videoActions: VideoActions | undefined;
  rosterDashboard: RosterDashboard | undefined;
  /** C6: drives the Pictures stage's done/blocked/gray read — the same
   * ["video-assets", videoId] query the page and the Pictures panel share. */
  assets: Asset[] | undefined;
  activeStage: StaticDocuStageKey;
  onSelectStage: (stage: StaticDocuStageKey) => void;
  taskWatcher: TaskWatcherBridge;
}

/**
 * C3c/C6: the 6-stage pipeline rail for static-documentary (render_mode ===
 * 'static_docu') videos — Roster, Research, Script, Voice, Pictures, Video
 * (render+thumbnail). No storyboard stage: static docs draw their own
 * verified three-view aircraft set via static_docu.py, never the regular
 * multi-angle coverage flow. Each stage is locked until the previous is green (see
 * computeCanRun), and "Run All" chains the whole build automatically.
 */
export function StaticDocuStageRail({
  video, videoActions, rosterDashboard, assets, activeStage, onSelectStage, taskWatcher,
}: StaticDocuStageRailProps) {
  const toast = useToast();
  const { draining } = useDrainMode();
  const confirmDialog = useConfirm();
  const queryClient = useQueryClient();
  const [taskRunning, setTaskRunning] = useState(false);
  const [runningStage, setRunningStage] = useState<StaticDocuStageKey | null>(null);
  const [runAllActive, setRunAllActive] = useState(false);
  const [runAllError, setRunAllError] = useState<{ stage: StaticDocuStageKey; message: string } | null>(null);
  const persistedActivity = persistedTaskActivity(
    taskWatcher.running ? "running" : "idle",
    taskWatcher.taskType,
    video.status,
  );

  const stages = useMemo(
    () => computeStaticDocuStages(video, videoActions, rosterDashboard, assets),
    [video, videoActions, rosterDashboard, assets],
  );
  const canRun = useMemo(() => computeCanRun(stages), [stages]);
  const visibleRunAllError = runAllError || (!taskWatcher.running && taskWatcher.failure ? {
    stage: video.status === "ready_for_scripting" ? "script" : STAGE_ORDER.find((key) => stages[key].status !== "done") || "research",
    message: taskWatcher.failure,
  } : null);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-actions", video.id] });
    queryClient.invalidateQueries({ queryKey: ["roster-dashboard", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  };

  useSharedTaskWatcher({
    bridge: taskWatcher,
    enabled: taskRunning || persistedActivity.active,
    onComplete: (msg) => {
      setTaskRunning(false);
      setRunningStage(null);
      setRunAllActive(false);
      setRunAllError(null);
      refresh();
      if (msg) toast.success(msg);
    },
    onFailed: (error) => {
      setTaskRunning(false);
      // Whichever stage is FIRST not-done, in order, is where the chain was
      // working when it failed — good enough to highlight without the
      // backend needing to report a stage name explicitly.
      const failedAt = video.status === "ready_for_scripting" ? "script" : STAGE_ORDER.find((k) => stages[k].status !== "done") || runningStage || "roster";
      setRunningStage(null);
      if (runAllActive || persistedActivity.runAllActive) {
        setRunAllActive(false);
        setRunAllError({ stage: failedAt, message: error });
      } else {
        toast.error(`${STAGE_META[failedAt].label} failed: ${error}`);
      }
      refresh();
    },
  });

  const costFor = (verb: string) => videoActions?.actions.find((a) => a.verb === verb);

  const startStage = async (
    stage: string,
    label: string,
    verbForCost: string,
    displayStage?: StaticDocuStageKey,
  ) => {
    const info = costFor(verbForCost);
    const costLine = info?.cost_text && info.cost_text !== "no extra cost" ? ` Estimated: ${info.cost_text}.` : "";
    if (!(await confirmDialog({ title: label, message: `Run ${label.toLowerCase()}?${costLine}` }))) return false;
    setRunningStage(displayStage || stage as StaticDocuStageKey);
    try {
      await runPipelineStage(video.id, stage);
      setTaskRunning(true);
      return true;
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, stage);
          setTaskRunning(true);
          return true;
        } catch (retryErr) {
          toast.error(`${label} failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`${label} failed: ${message}`);
      }
      setRunningStage(null);
      return false;
    }
  };

  const handleRunAll = async () => {
    setRunAllError(null);
    // Fresh roster read — the whole point of Run All's pre-flight gate is
    // to never let a stale "looked fine a minute ago" start real spend.
    let freshRoster = rosterDashboard;
    try {
      freshRoster = await getRosterDashboard(video.id);
      queryClient.setQueryData(["roster-dashboard", video.id], freshRoster);
    } catch {
      // fall back to the last-known dashboard rather than blocking on a transient read error
    }
    const total = freshRoster?.total ?? 0;
    const verified = (freshRoster?.units ?? []).filter((u) => u.reference?.status === "verified").length;
    const rosterPreflight = staticDocuRunAllPreflight(total, verified);
    const buildInfo = costFor("build");
    const costLine = buildInfo?.cost_text ? ` Estimated: ${buildInfo.cost_text}${video.render_mode === "static_docu" ? " (picture cost is approximate for this format)" : ""}.` : "";
    const ok = await confirmDialog({
      title: "Run All",
      message: `Runs roster → gather images → research, then script, voice, pictures, thumbnail, and render${video.pipeline_stages?.includes("upload") ? ", then verified unlisted YouTube upload" : ""} — stopping the moment anything fails. ${rosterPreflight.note}${costLine} Continue?`,
    });
    if (!ok) return;
    setRunAllActive(true);
    setRunningStage(null);
    try {
      await runBuild(video.id, "finish");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runBuild(video.id, "finish");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Couldn't start Run All: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Couldn't start Run All: ${message}`);
      }
      setRunAllActive(false);
    }
  };

  const allGreen = STAGE_ORDER.every((k) => stages[k].status === "done");
  const visibleRunAllActive = runAllActive || persistedActivity.runAllActive;
  const busy = taskRunning || runAllActive || persistedActivity.active;

  return (
    <div className="space-y-3">
      <GlassCard className="p-4">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
          {STAGE_ORDER.map((key, idx) => {
            const meta = STAGE_META[key];
            const savedInfo = stages[key];
            const info = key === "video" && persistedActivity.renderActive
              ? {
                  status: "in_progress" as StageStatus,
                  detail: persistedActivity.runAllActive ? "Run All is finishing the video…" : "Render job in progress…",
                }
              : savedInfo;
            const Icon = meta.icon;
            const locked = !canRun[key];
            const reason = lockReason(key, stages);
            const isActive = activeStage === key;
            const isBusy = runningStage === key
              || (visibleRunAllActive && info.status !== "done" && STAGE_ORDER.slice(0, idx).every((k) => stages[k].status === "done"))
              || (key === "video" && persistedActivity.renderActive);
            const color = STATUS_COLOR[info.status];
            return (
              <div key={key} className="flex items-center shrink-0">
                <button
                  onClick={() => onSelectStage(key)}
                  title={reason || info.detail}
                  className="flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-all"
                  style={{
                    background: isActive ? "var(--turquoise-bg)" : "transparent",
                    minWidth: 92,
                  }}
                >
                  <div
                    className="flex items-center justify-center rounded-full"
                    style={{
                      width: 32, height: 32,
                      background: info.status === "done" ? "var(--turquoise)" : "var(--bg-elevated)",
                      border: `2px solid ${color}`,
                      color: info.status === "done" ? "var(--bg-void)" : color,
                    }}
                  >
                    {isBusy ? <Loader2 size={14} className="animate-spin" /> : info.status === "done" ? <Check size={14} strokeWidth={3} /> : locked ? <Lock size={12} /> : <Icon size={14} />}
                  </div>
                  <span className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: isActive ? "var(--turquoise)" : "var(--text-secondary)" }}>
                    {meta.label}
                  </span>
                  <span className="text-[9px] text-center leading-tight line-clamp-2" style={{ color: "var(--text-tertiary)", maxWidth: 88 }}>
                    {info.detail}
                  </span>
                </button>
                {idx < STAGE_ORDER.length - 1 && (
                  <div className="w-4 h-0.5 shrink-0" style={{ background: STAGE_ORDER.slice(0, idx + 1).every((k) => stages[k].status === "done") ? "var(--turquoise)" : "var(--border-subtle)" }} />
                )}
              </div>
            );
          })}

          <div className="ml-auto pl-3 shrink-0 flex items-center gap-2">
            <button
              onClick={handleRunAll}
              disabled={busy || draining || allGreen}
              title={
                draining
                  ? "Generation is briefly paused for a safe update"
                  : allGreen
                    ? "Every stage is already done."
                    : "Run the whole pipeline automatically, stopping on any error."
              }
              data-generation-action
              data-testid="run-all"
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-40"
              style={{ background: "var(--gold)", color: "var(--bg-void)" }}
            >
              {visibleRunAllActive ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
              {busy ? "Production running…" : allGreen ? "Complete" : (visibleRunAllError || video.status !== "idea_logged") ? "Resume" : "Run All"}
            </button>
          </div>
        </div>
      </GlassCard>

      {visibleRunAllError && (
        <GlassCard className="p-4" style={{ borderColor: "var(--red)" }}>
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} style={{ color: "var(--red)" }} className="shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--red)" }}>
                Run All stopped at {STAGE_META[visibleRunAllError.stage].label}
              </p>
              <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{visibleRunAllError.message}</p>
            </div>
          </div>
        </GlassCard>
      )}


    </div>
  );
}

function StageRunButton({
  onClick, disabled, running, label, lockedReason, testId,
}: {
  onClick: () => void;
  disabled: boolean;
  running: boolean;
  label: string;
  lockedReason: string | null;
  testId?: string;
}) {
  return (
    <motion.button
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      title={disabled ? (lockedReason || undefined) : undefined}
      whileTap={disabled ? undefined : { scale: 0.98 }}
      className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all disabled:opacity-40"
      style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
    >
      {running ? <Loader2 size={15} className="animate-spin" /> : disabled ? <Lock size={13} /> : null}
      {running ? "Running…" : label}
    </motion.button>
  );
}
