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
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import {
  runPipelineStage, runBuild, getRosterDashboard, clearStaleTask,
  type VideoDetail, type VideoActions, type RosterDashboard, type Asset,
} from "@/lib/api";

export type StaticDocuStageKey = "roster" | "research" | "script" | "voice" | "pictures" | "video";
export type StageStatus = "done" | "in_progress" | "blocked" | "not_started";

interface StageInfo {
  status: StageStatus;
  detail: string;
}

const STAGE_META: Record<StaticDocuStageKey, { label: string; icon: typeof Search }> = {
  roster: { label: "Roster", icon: ImageIcon },
  research: { label: "Research", icon: Search },
  script: { label: "Script", icon: FileText },
  voice: { label: "Voice", icon: Volume2 },
  pictures: { label: "Pictures", icon: Images },
  video: { label: "Video", icon: Film },
};

const STAGE_ORDER: StaticDocuStageKey[] = ["roster", "research", "script", "voice", "pictures", "video"];

// C6: a scene's static-documentary image is "blocked" the same way roster
// treats a missing reference photo — a state the operator must go fix (Roster
// tab's Add photo, or the qa_rejected Approve/Redraw in the Pictures panel),
// never something a re-run alone clears.
const PICTURE_BLOCKED_STATUSES = new Set(["blocked_no_reference", "qa_rejected"]);

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

  const total = rosterDashboard?.total ?? 0;
  const verified = (rosterDashboard?.units ?? []).filter((u) => u.reference?.status === "verified").length;
  const roster: StageInfo =
    total === 0
      ? { status: "not_started", detail: "No roster established yet — run Research." }
      : verified === total
        ? { status: "done", detail: `${verified}/${total} machine(s) have a verified reference photo.` }
        : { status: "blocked", detail: `${verified}/${total} verified — ${total - verified} machine(s) still need a photo.` };

  const hasResearchPayload = Boolean(video.research_payload && Object.keys(video.research_payload).length > 0);
  let research: StageInfo;
  if (!hasResearchPayload) {
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

  // C6: one archival image per scene (backend/static_docu.py) — pictures are
  // gated on Voice being green, same chain every other stage follows.
  // done/blocked/gray only (no live "in_progress" color here beyond the
  // 'generating' pulse the Pictures panel itself shows per-card) — a scene
  // whose generation row never landed (a total-failure case that DELETES the
  // placeholder row) is neither done nor blocked, just still to do.
  const staticAssets = (assets ?? []).filter((a) => !a.generation_method || a.generation_method === "static_docu");
  const picByScene = new Map<number, Asset>();
  for (const a of staticAssets) {
    if (a.scene != null) picByScene.set(a.scene, a);
  }
  const picDone = Array.from(picByScene.values()).filter((a) => a.status === "done").length;
  const picBlocked = Array.from(picByScene.values()).filter((a) => PICTURE_BLOCKED_STATUSES.has(a.status || "")).length;
  const picGenerating = Array.from(picByScene.values()).filter((a) => a.status === "generating").length;
  const pictures: StageInfo =
    scenes === 0
      ? { status: "not_started", detail: "No scenes yet — write the script first." }
      : picBlocked > 0
        ? { status: "blocked", detail: `${picBlocked} scene(s) need attention (no reference photo, or a rejected render).` }
        : picDone >= scenes
          ? { status: "done", detail: `All ${scenes} segment picture(s) made.` }
          : picGenerating > 0
            ? { status: "in_progress", detail: `${picDone}/${scenes} done — drawing more now…` }
            : { status: "not_started", detail: `${picDone}/${scenes} segment picture(s) made.` };

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

  return { roster, research, script, voice, pictures, video: videoStage };
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
  const researchGreen = stages.research.status === "done";
  const scriptGreen = stages.script.status === "done";
  const voiceGreen = stages.voice.status === "done";
  const picturesGreen = stages.pictures.status === "done";
  return {
    roster: true,
    research: stages.roster.status !== "blocked",
    script: rosterGreen && researchGreen,
    voice: rosterGreen && researchGreen && scriptGreen,
    pictures: rosterGreen && researchGreen && scriptGreen && voiceGreen,
    // C6: Video (thumbnail + render) now also waits on Pictures — a render
    // must not ship before every segment's picture is drawn (or the operator
    // has explicitly cleared the blocked ones).
    video: rosterGreen && researchGreen && scriptGreen && voiceGreen && picturesGreen,
  };
}

function lockReason(key: StaticDocuStageKey, stages: Record<StaticDocuStageKey, StageInfo>): string | null {
  if (key === "roster") return null;
  if (key === "research") return stages.roster.status === "blocked"
    ? "Fix the roster's missing reference photos first — no research/script spend until every machine has a photo."
    : null;
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
    if (stages.pictures.status !== "done") return "Locked until every segment's picture is drawn.";
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
 * (render+thumbnail). No storyboard stage: static docs draw ONE archival
 * image per segment via static_docu.py, never the multi-angle coverage
 * flow. Each stage is locked until the previous is green (see
 * computeCanRun), and "Run All" chains the whole build automatically.
 */
export function StaticDocuStageRail({
  video, videoActions, rosterDashboard, assets, activeStage, onSelectStage, taskWatcher,
}: StaticDocuStageRailProps) {
  const toast = useToast();
  const confirmDialog = useConfirm();
  const queryClient = useQueryClient();
  const [taskRunning, setTaskRunning] = useState(false);
  const [runningStage, setRunningStage] = useState<StaticDocuStageKey | null>(null);
  const [runAllActive, setRunAllActive] = useState(false);
  const [runAllError, setRunAllError] = useState<{ stage: StaticDocuStageKey; message: string } | null>(null);

  const stages = useMemo(
    () => computeStaticDocuStages(video, videoActions, rosterDashboard, assets),
    [video, videoActions, rosterDashboard, assets],
  );
  const canRun = useMemo(() => computeCanRun(stages), [stages]);

  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-actions", video.id] });
    queryClient.invalidateQueries({ queryKey: ["roster-dashboard", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  };

  useSharedTaskWatcher({
    bridge: taskWatcher,
    enabled: taskRunning,
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
      const failedAt = STAGE_ORDER.find((k) => stages[k].status !== "done") || runningStage || "roster";
      setRunningStage(null);
      if (runAllActive) {
        setRunAllActive(false);
        setRunAllError({ stage: failedAt, message: error });
      } else {
        toast.error(`${STAGE_META[failedAt].label} failed: ${error}`);
      }
      refresh();
    },
  });

  const costFor = (verb: string) => videoActions?.actions.find((a) => a.verb === verb);

  const startStage = async (stage: string, label: string, verbForCost: string) => {
    const info = costFor(verbForCost);
    const costLine = info?.cost_text && info.cost_text !== "no extra cost" ? ` Estimated: ${info.cost_text}.` : "";
    if (!(await confirmDialog({ title: label, message: `Run ${label.toLowerCase()}?${costLine}` }))) return;
    setRunningStage(stage as StaticDocuStageKey);
    try {
      await runPipelineStage(video.id, stage);
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, stage);
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`${label} failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`${label} failed: ${message}`);
      }
      setRunningStage(null);
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
    if (total === 0) {
      setRunAllError({ stage: "roster", message: "No machine roster yet. Run All can't start until Research discovers the roster." });
      return;
    }
    if (verified < total) {
      setRunAllError({
        stage: "roster",
        message: `${total - verified} machine(s) still need a verified reference photo. Fix the Roster stage, then run Run All again.`,
      });
      return;
    }
    const buildInfo = costFor("build");
    const costLine = buildInfo?.cost_text ? ` Estimated: ${buildInfo.cost_text}${video.render_mode === "static_docu" ? " (picture cost is approximate for this format)" : ""}.` : "";
    const ok = await confirmDialog({
      title: "Run All",
      message: `Runs the whole pipeline automatically — research (if needed), script, voice, pictures, thumbnail, and render — stopping the moment anything fails.${costLine} Continue?`,
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
  const busy = taskRunning || runAllActive;

  return (
    <div className="space-y-3">
      <GlassCard className="p-4">
        <div className="flex items-center gap-1 overflow-x-auto scrollbar-hide">
          {STAGE_ORDER.map((key, idx) => {
            const meta = STAGE_META[key];
            const info = stages[key];
            const Icon = meta.icon;
            const locked = !canRun[key];
            const reason = lockReason(key, stages);
            const isActive = activeStage === key;
            const isBusy = runningStage === key || (runAllActive && info.status !== "done" && STAGE_ORDER.slice(0, idx).every((k) => stages[k].status === "done"));
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

          <div className="ml-auto pl-3 shrink-0">
            <button
              onClick={handleRunAll}
              disabled={busy}
              title={allGreen ? "Every stage is already done." : "Run the whole pipeline automatically, stopping on any error."}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-40"
              style={{ background: "var(--gold)", color: "var(--bg-void)" }}
            >
              {runAllActive ? <Loader2 size={16} className="animate-spin" /> : <Zap size={16} />}
              {runAllActive ? "Running All…" : allGreen ? "All Done" : "Run All"}
            </button>
          </div>
        </div>
      </GlassCard>

      {runAllError && (
        <GlassCard className="p-4" style={{ borderColor: "var(--red)" }}>
          <div className="flex items-start gap-3">
            <AlertTriangle size={18} style={{ color: "var(--red)" }} className="shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--red)" }}>
                Run All stopped at {STAGE_META[runAllError.stage].label}
              </p>
              <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{runAllError.message}</p>
            </div>
          </div>
        </GlassCard>
      )}

      {/* Per-stage run buttons — research/script/voice/video each get their
          own quote->confirm action, same as every other tab in the app.
          Roster's and Pictures' actions live in their own panels (Add photo /
          Re-check, and per-scene Redraw/Approve — free-or-per-scene work that
          doesn't fit a single "run" button). */}
      {activeStage !== "roster" && activeStage !== "pictures" && (
        <div className="flex items-center justify-end gap-2">
          {activeStage === "research" && (
            <StageRunButton
              disabled={!canRun.research || busy}
              lockedReason={lockReason("research", stages)}
              running={runningStage === "research"}
              onClick={() => startStage("research", "Research", "research")}
              label={stages.research.status === "done" ? "Re-run research" : "Run research"}
            />
          )}
          {activeStage === "script" && (
            <StageRunButton
              disabled={!canRun.script || busy}
              lockedReason={lockReason("script", stages)}
              running={runningStage === "script"}
              onClick={() => startStage("script", "Script", "script")}
              label={stages.script.status === "done" ? "Re-run script" : "Write the script"}
            />
          )}
          {activeStage === "voice" && (
            <StageRunButton
              disabled={!canRun.voice || busy}
              lockedReason={lockReason("voice", stages)}
              running={runningStage === "voice"}
              onClick={() => startStage("voice", "Voice", "voice")}
              label={stages.voice.status === "done" ? "Re-record voice" : "Record the voiceover"}
            />
          )}
          {activeStage === "video" && (
            <StageRunButton
              disabled={!canRun.video || busy}
              lockedReason={lockReason("video", stages)}
              running={runningStage === "video"}
              onClick={() => startStage(
                video.thumbnail_url ? "render" : "thumbnail",
                video.thumbnail_url ? "Render" : "Thumbnail",
                video.thumbnail_url ? "render" : "thumbnail",
              )}
              label={video.thumbnail_url ? "Render the video" : "Generate the thumbnail"}
            />
          )}
        </div>
      )}
    </div>
  );
}

function StageRunButton({
  onClick, disabled, running, label, lockedReason,
}: {
  onClick: () => void;
  disabled: boolean;
  running: boolean;
  label: string;
  lockedReason: string | null;
}) {
  return (
    <motion.button
      onClick={onClick}
      disabled={disabled}
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
