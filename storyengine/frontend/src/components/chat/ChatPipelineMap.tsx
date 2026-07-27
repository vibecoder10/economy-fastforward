"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Check, Loader2, Minus, TriangleAlert, Wifi, WifiOff } from "lucide-react";
import {
  getProductionGuide,
  type CustomFilmPlan,
  type CustomFilmPlanSection,
  type ProductionGuideStage,
  type VideoDetail,
} from "@/lib/api";
import type {
  SSEStageChangeEvent,
  SSETaskProgressEvent,
} from "@/hooks/use-pipeline-sse";

// Ryan's testing feedback (2026-07-27): "it looks like they're stalled out
// and I have no idea what happened." The pipeline strip below already named
// the current step, but between backend progress messages it went visually
// silent — nothing counted, nothing moved. This block (modeled on OpenArt's
// "Ori has been at it for 13s" status — see Screenshot 2026-07-24 at
// 7.46.01 AM in ~/Desktop/Open Art UI/) is ALWAYS visibly alive while a task
// is running: a counting elapsed timer (real — Date.now() against the
// moment we first observed taskProgress.status==="running", never a
// fabricated estimate) plus a small rotating plain-English line. The
// rotating line is flavor text only when there is no real backend message;
// a real `taskProgress.message` always wins over invented copy.
const STEP_FLAVOR: Record<string, string[]> = {
  Research: ["Digging up the facts…", "Reading around the topic…", "Checking what's true…"],
  Script: ["Writing the scenes…", "Finding the hook…", "Shaping the story beats…"],
  Voice: ["Recording the narration…", "Matching tone to the story…"],
  Characters: ["Sketching your cast…", "Giving them faces…", "Locking down how they look…"],
  Environments: ["Building the world…", "Setting each scene's backdrop…"],
  Storyboards: ["Blocking out each shot…", "Drawing the beats…"],
  Pictures: ["Painting the frames…", "Rendering the final look…"],
  Sound: ["Laying in the audio…", "Picking the right effects…"],
  Clips: ["Bringing the stills to life…", "Animating the motion…"],
  Thumbnail: ["Designing the cover…", "Trying a few looks…"],
  Render: ["Stitching everything together…", "Assembling the final cut…"],
};

function fmtElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m > 0 ? `${m}m ${r}s` : `${r}s`;
}

// `key` is the production_guide.py GUIDE_STAGES key for this step — the
// SAME key backend/production_guide.py's get_production_guide returns per
// stage (research/script/voice/characters/environments/storyboards/images/
// sound/video/thumbnail/render). This is what lets the stepper below read
// each step's REAL state instead of guessing from status order (bug (a)
// fix, 2026-07-27: "the stepper shows Environments as DONE when no
// environments exist" — it was inferring done-ness from status order, which
// says nothing about whether that specific stage's work actually happened).
const PIPELINE_STEPS = [
  { label: "Research", plan: "research", key: "research" },
  { label: "Script", plan: "script", key: "script" },
  { label: "Voice", plan: "voice", key: "voice" },
  { label: "Characters", plan: "images", key: "characters" },
  { label: "Environments", plan: "images", key: "environments" },
  { label: "Storyboards", plan: "images", key: "storyboards" },
  { label: "Pictures", plan: "images", key: "images" },
  { label: "Sound", plan: "sound", key: "sound" },
  { label: "Clips", plan: "video", key: "video" },
  { label: "Thumbnail", plan: "thumbnail", key: "thumbnail" },
  { label: "Render", plan: "render", key: "render" },
] as const;

type CustomFilmSectionView = {
  key: string;
  order: number;
  role: string;
  share: string;
  purpose: string;
  feel: string;
};

const CREATOR_SECTION_ROLES = new Set([
  "full_film",
  "opening",
  "context",
  "explanation",
  "evidence",
  "contrast",
  "case_study",
  "resolution",
  "closing",
]);

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function sectionFeel(section: CustomFilmPlanSection): string {
  const knobs = objectValue(section.knobs);
  const animation = objectValue(knobs.animation);
  const language = objectValue(knobs.language);
  if (knobs.render_mode === "static_docu") {
    return "Grounded still-image documentary treatment";
  }
  if (language.mode === "bilingual") {
    return "Bilingual performed character animation";
  }
  if (animation.enabled === true) {
    return "Animated visual storytelling";
  }
  return "Focused documentary treatment";
}

export function customFilmSectionViews(
  plan: CustomFilmPlan | null | undefined,
): CustomFilmSectionView[] {
  if (!plan || !Array.isArray(plan.sections)) return [];
  return [...plan.sections]
    .filter((section) => (
      Number.isInteger(section.order_index)
      && Number.isFinite(section.duration_units)
      && section.duration_units > 0
      && typeof section.purpose === "string"
      && section.purpose.trim().length > 0
    ))
    .sort((a, b) => a.order_index - b.order_index)
    .map((section) => ({
      key: section.section_id || `section-${section.order_index}`,
      order: section.order_index + 1,
      role: CREATOR_SECTION_ROLES.has(section.role)
        ? section.role.replaceAll("_", " ")
        : "section",
      share: `${(section.duration_units / 10_000).toFixed(1).replace(/\.0$/, "")}%`,
      purpose: section.purpose.trim(),
      feel: sectionFeel(section),
    }));
}

export function customFilmStatusLabel(
  status: string | null | undefined,
): string {
  const value = String(status || "").toLowerCase();
  if (["rendered", "uploaded", "uploaded_draft", "published", "done"].includes(value)) {
    return "Film ready";
  }
  if (value === "rendering" || value === "ready_to_render") return "Assembling film";
  if (value === "custom_film_ready") return "Plan approved";
  return "Section-aware production";
}

function pipelineIndex(status: string | null | undefined): number {
  const value = String(status || "").toLowerCase();
  if (["rendered", "uploaded", "uploaded_draft", "published", "done"].includes(value)) return 11;
  if (value === "rendering" || value === "ready_to_render") return 10;
  if (value === "ready_for_thumbnail") return 9;
  if (value === "ready_for_video_scripts" || value === "ready_for_video_generation") return 8;
  if (value === "ready_for_sound_design" || value === "ready_for_sound_effects") return 7;
  if (value === "ready_for_images" || value === "ready_for_storyboard_extraction") return 6;
  if (value === "ready_for_storyboards" || value === "ready_for_storyboard_images") return 5;
  if (value === "ready_for_environments") return 4;
  if (value === "ready_for_image_prompts" || value === "ready_for_characters") return 3;
  if (value === "ready_for_voice" || value === "voice") return 2;
  if (value === "ready_for_scripting" || value === "scripting" || value === "needs_script_review") return 1;
  return 0;
}

export function ChatPipelineMap({
  video,
  stageChange,
  taskProgress,
  connected,
}: {
  video: VideoDetail | undefined;
  stageChange: SSEStageChangeEvent | null;
  taskProgress: SSETaskProgressEvent | null;
  connected: boolean;
}) {
  // Real elapsed timer: starts counting the moment we OBSERVE the task
  // actually running, never a fabricated estimate. `tick` exists only to
  // force a re-render once a second while running so the displayed number
  // keeps counting up (OpenArt's "Ori has been at it for 13s").
  const taskRunning = taskProgress?.status === "running";
  const taskFailed = taskProgress?.status === "failed";
  const [runningSince, setRunningSince] = useState<number | null>(null);
  const [, setTick] = useState(0);
  useEffect(() => {
    if (taskRunning) {
      setRunningSince((prev) => prev ?? Date.now());
    } else {
      setRunningSince(null);
    }
  }, [taskRunning]);
  useEffect(() => {
    if (!taskRunning) return;
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, [taskRunning]);
  const elapsedSeconds = runningSince ? (Date.now() - runningSince) / 1000 : 0;

  // Real per-step durations: `stageChange.duration_seconds` is the backend's
  // own measured time for the transition (stage_transitions table) — never
  // invented here. The step that just finished is the one that was ACTIVE
  // going into this transition, i.e. the step at pipelineIndex(from_status).
  // Accumulates across every stage_change observed this session; a step
  // completed before this panel mounted (or in an earlier session) simply
  // has no caption — honest silence instead of a guessed number.
  const [stepDurations, setStepDurations] = useState<Record<string, number>>({});
  const lastProcessedKeyRef = useRef<string | null>(null);
  useEffect(() => {
    if (!stageChange || stageChange.duration_seconds == null) return;
    const key = `${stageChange.created_at}|${stageChange.from_status}|${stageChange.to_status}`;
    if (lastProcessedKeyRef.current === key) return;
    lastProcessedKeyRef.current = key;
    const completedIdx = pipelineIndex(stageChange.from_status);
    const completedStep = PIPELINE_STEPS[completedIdx];
    if (completedStep) {
      const duration = stageChange.duration_seconds;
      setStepDurations((d) => ({ ...d, [completedStep.label]: duration }));
    }
  }, [stageChange]);

  // The production guide (backend/production_guide.py's get_production_
  // guide, same REST route the /pipeline page's StageRail already trusts) is
  // the SINGLE source of truth for each stage's real state — done /
  // in_progress / not_started / skipped_by_format, read from actual stored
  // data (video_characters/video_environments rows, storyboard columns,
  // etc), never guessed from status order. Bug (a) fix, 2026-07-27: the
  // stepper used to derive "done" purely from `pipelineIndex(video.status)`
  // — any step before the current coarse status was assumed finished, which
  // is exactly how it showed Environments as done on a video with ZERO
  // environments ever designed (proof: video f32ed182-be1f-4a24-a8de-
  // bb8db4ac88df, status "rendered", production-guide reports environments
  // "not_started" — "No environments designed yet" — 8 undesigned
  // locations). Reusing the same route the pipeline page already relies on
  // means this stepper and that page's rail can never disagree.
  const queryClient = useQueryClient();
  const videoId = video?.id;
  const { data: guide } = useQuery({
    queryKey: ["production-guide", videoId],
    queryFn: () => getProductionGuide(videoId as string),
    enabled: Boolean(videoId),
    staleTime: 5_000,
  });
  // Re-check the guide whenever a real signal says the video's stage state
  // may have moved: a stage_change SSE event, or a background task going
  // from running to finished (some real actions — e.g. approving
  // environments — change guide state without a stage_change event at all).
  useEffect(() => {
    if (!videoId || !stageChange) return;
    queryClient.invalidateQueries({ queryKey: ["production-guide", videoId] });
  }, [stageChange, videoId, queryClient]);
  const prevTaskRunningRef = useRef(false);
  useEffect(() => {
    if (prevTaskRunningRef.current && !taskRunning && videoId) {
      queryClient.invalidateQueries({ queryKey: ["production-guide", videoId] });
    }
    prevTaskRunningRef.current = taskRunning;
  }, [taskRunning, videoId, queryClient]);

  // Everything below is a plain (non-hook) derivation, safe to compute even
  // when `video` is undefined (guarded with `video?.` / `?? []`) — this lets
  // ALL hooks above stay unconditional (same order every render) while the
  // "loading" early return still happens, just further down, after hooks.
  //
  // `plan` (video.pipeline_stages) only powers the BEFORE-the-guide-loads
  // fallback list — once the guide has loaded, every step renders (the
  // format-excluded ones show as "skipped", not hidden; see visualStateFor
  // below), since the guide's own skipped_by_format already accounts for
  // this same plan (and the SFX-block case the plan alone can't see, e.g. a
  // render path that can never play sound effects even though "sound" is
  // in the coarse plan — docs/failure-modes.md's SFX row).
  const plan = video?.pipeline_stages;
  const legacyVisible = PIPELINE_STEPS.filter((step) => !plan || plan.includes(step.plan));
  const visible = guide ? PIPELINE_STEPS : legacyVisible;

  function stageFor(key: string): ProductionGuideStage | undefined {
    return guide?.stages.find((s) => s.key === key);
  }

  // doneAll / activeKey / activeLabel all come from the SAME next_step the
  // guide already computed (production_guide.py's _recommend_next_step) —
  // never a second, independently-guessed "what's next" answer. Before the
  // guide has loaded, doneAll is false and activeLabel is null — an honest
  // "no evidence yet" default, never a guessed done state.
  const doneAll = guide?.next_step?.action === "celebrate";
  const activeKey = !doneAll ? guide?.next_step?.stage ?? null : null;
  const activeLabel = activeKey
    ? PIPELINE_STEPS.find((step) => step.key === activeKey)?.label ?? null
    : null;

  type StepVisual = "done" | "active" | "not_started" | "skipped";
  function visualStateFor(step: (typeof PIPELINE_STEPS)[number]): StepVisual {
    const stage = stageFor(step.key);
    // No guide data yet — never claim done/skipped without evidence.
    if (!stage) return "not_started";
    if (stage.state === "skipped_by_format") return "skipped";
    if (stage.state === "done") return "done";
    if (stage.state === "in_progress") return "active";
    // not_started: only the ONE next actionable step (next_step.stage) gets
    // the "active" highlight; later not-started steps stay plain grey.
    return step.key === activeKey ? "active" : "not_started";
  }

  // Rotating plain-English flavor line for the active step — text-only
  // "we're cooking" copy, never a time claim. Resets to the first phrase
  // whenever the active step changes so it never rotates into a phrase for
  // the WRONG step.
  const [flavorIdx, setFlavorIdx] = useState(0);
  useEffect(() => {
    setFlavorIdx(0);
  }, [activeLabel]);
  useEffect(() => {
    if (!taskRunning) return;
    const id = setInterval(() => setFlavorIdx((i) => i + 1), 4000);
    return () => clearInterval(id);
  }, [taskRunning, activeLabel]);
  const flavorOptions = (activeLabel && STEP_FLAVOR[activeLabel]) || ["Working on it…"];
  const flavorText = flavorOptions[flavorIdx % flavorOptions.length];
  const realMessage = taskProgress?.message?.trim() || null;

  if (!video) {
    return (
      <div
        className="rounded-xl px-3 py-3 text-xs"
        style={{ background: "var(--bg-surface)", color: "var(--text-tertiary)" }}
      >
        Loading this video&apos;s production map…
      </div>
    );
  }

  const profile = video.production_style_snapshot;
  const customFilmSections = customFilmSectionViews(video.custom_film_plan);
  const isCustomFilm = Boolean(video.custom_film_plan);

  return (
    <section
      aria-label="Video production progress"
      className="rounded-xl p-3 space-y-3"
      style={{
        background: "var(--bg-surface)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          {/* `profile` (production_style_snapshot) is null whenever a video was
              created WITHOUT picking one of the four channel cards — which is
              the NORMAL case for the single-prompt entry box (DirectorHome),
              not a sign the video is aged. The PRIOR fallback copy here
              called a video created seconds ago "legacy" and implied it was
              old, which is simply false — found live 2026-07-27 on a
              brand-new video. The classification (no snapshot => no locked
              production profile) is correct; only the WORDING was wrong.
              Fixed at the wording, not the classification. */}
          <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
            {isCustomFilm ? "Custom Film" : profile?.label || "Standard production"}
          </p>
          <p className="text-[10px] leading-relaxed mt-0.5" style={{ color: "var(--text-tertiary)" }}>
            {isCustomFilm
              ? `${customFilmSections.length} ordered sections work together as one film.`
              : profile?.description || "No locked production profile for this video — it runs the default pipeline."}
          </p>
        </div>
        <span
          className="shrink-0 inline-flex items-center gap-1 text-[9px]"
          style={{ color: connected ? "var(--green)" : "var(--text-tertiary)" }}
          title={connected ? "Live progress connected" : "Reconnecting to live progress"}
        >
          {connected ? <Wifi size={11} /> : <WifiOff size={11} />}
          {connected ? "Live" : "Reconnecting"}
        </span>
      </div>

      {/* The "it's alive" block (bug (a) — Ryan: "it looks like they're
          stalled out"). Visible ONLY while a task is actually running, so it
          never lingers as a stale claim once work stops. The elapsed number
          is real (Date.now() delta); the rotating line below it is flavor
          copy UNLESS the backend sent a real message, which always wins. */}
      {taskRunning && (
        <div
          className="flex items-center gap-2.5 rounded-lg px-3 py-2.5"
          style={{ background: "rgba(0,212,170,0.08)", border: "1px solid rgba(0,212,170,0.18)" }}
        >
          <span className="relative flex h-6 w-6 shrink-0 items-center justify-center">
            <motion.span
              className="absolute inline-flex h-full w-full rounded-full"
              style={{ background: "var(--turquoise)" }}
              animate={{ scale: [1, 1.7, 1], opacity: [0.55, 0, 0.55] }}
              transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            />
            <Loader2 size={14} className="relative animate-spin" style={{ color: "var(--turquoise)" }} />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
              Working on {activeLabel ?? "your video"} — {fmtElapsed(elapsedSeconds)}
            </p>
            <AnimatePresence mode="wait" initial={false}>
              <motion.p
                key={realMessage ?? flavorText}
                initial={{ opacity: 0, y: 3 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -3 }}
                transition={{ duration: 0.25 }}
                className="text-[10px] mt-0.5 truncate"
                style={{ color: "var(--text-secondary)" }}
              >
                {realMessage ?? flavorText}
              </motion.p>
            </AnimatePresence>
          </div>
        </div>
      )}

      {isCustomFilm && (
        <div
          aria-label="Custom Film section mix"
          className="rounded-lg p-2.5 space-y-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center justify-between gap-2">
            <p className="text-[10px] font-semibold" style={{ color: "var(--text-secondary)" }}>
              Ordered section mix
            </p>
            <span
              className="text-[9px] rounded-full px-2 py-0.5"
              style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
            >
              {customFilmStatusLabel(stageChange?.current_status || video.status)}
            </span>
          </div>
          <ol className="space-y-1.5">
            {customFilmSections.map((section) => (
              <li
                key={section.key}
                className="grid grid-cols-[24px_minmax(0,1fr)_auto] gap-2 items-start rounded-md px-2 py-1.5"
                style={{ background: "var(--bg-surface)" }}
              >
                <span
                  className="w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-semibold"
                  style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
                >
                  {section.order}
                </span>
                <span className="min-w-0">
                  <span
                    className="block text-[10px] font-semibold capitalize"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {section.role}
                  </span>
                  <span className="block text-[9px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                    {section.purpose}
                  </span>
                  <span className="block text-[9px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    {section.feel}
                  </span>
                </span>
                <span className="text-[9px] font-semibold" style={{ color: "var(--text-secondary)" }}>
                  {section.share}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}

      <div className="overflow-x-auto pb-1">
        <ol className="flex min-w-max items-start">
          {visible.map((step, index) => {
            // Four HONEST, distinguishable states (bug (a) fix) — "skipped"
            // (not part of this video's plan/format) is never collapsed into
            // "done" (it didn't happen) or "not_started" (it's not missing,
            // it was never supposed to run). See visualStateFor above.
            const visual = visualStateFor(step);
            const done = visual === "done";
            const active = visual === "active";
            const skipped = visual === "skipped";
            const stage = stageFor(step.key);
            return (
              <li key={step.label} className="flex items-start">
                <div className="w-[70px] flex flex-col items-center text-center" style={{ opacity: skipped ? 0.55 : 1 }}>
                  <span
                    title={stage?.detail}
                    className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold"
                    style={{
                      background: done
                        ? "var(--green)"
                        : active
                          ? "var(--turquoise)"
                          : "var(--bg-deep)",
                      color: done || active ? "var(--bg-void)" : "var(--text-tertiary)",
                      border: done || active ? "none" : `1px dashed var(--border)`,
                    }}
                  >
                    {done ? <Check size={13} /> : skipped ? <Minus size={13} /> : index + 1}
                  </span>
                  <span
                    className="text-[9px] mt-1 leading-tight"
                    style={{
                      color: active
                        ? "var(--turquoise)"
                        : done
                          ? "var(--text-secondary)"
                          : "var(--text-tertiary)",
                      fontWeight: active ? 700 : 500,
                    }}
                  >
                    {step.label}
                  </span>
                  {/* Real duration caption (checklist detail line, OpenArt-
                      modeled) — only appears when we actually measured this
                      step's transition; never a guess. */}
                  {done && stepDurations[step.label] != null && (
                    <span className="text-[8px] mt-0.5 leading-tight" style={{ color: "var(--text-tertiary)" }}>
                      Done in {fmtElapsed(stepDurations[step.label])}
                    </span>
                  )}
                  {/* Skipped caption — the backend's own reason (real
                      format/plan text, e.g. "static-documentary render — no
                      motion/sound"), never a guessed label. */}
                  {skipped && (
                    <span className="text-[8px] mt-0.5 leading-tight" style={{ color: "var(--text-tertiary)" }}>
                      Skipped
                    </span>
                  )}
                </div>
                {index < visible.length - 1 && (
                  <span
                    aria-hidden
                    className="w-4 h-px mt-3 -mx-2"
                    style={{
                      background: done ? "var(--green)" : "var(--border)",
                    }}
                  />
                )}
              </li>
            );
          })}
        </ol>
      </div>

      {/* Failed/completed message only — the running case now lives in the
          "it's alive" block above (showing it twice was noise, not signal). */}
      {taskProgress?.message && !taskRunning && (
        <div
          role={taskFailed ? "alert" : "status"}
          className="flex items-start gap-2 rounded-lg px-2.5 py-2 text-[10px] leading-relaxed"
          style={{
            background: taskFailed ? "rgba(239,68,68,0.08)" : "rgba(0,212,170,0.07)",
            color: taskFailed ? "var(--red)" : "var(--text-secondary)",
          }}
        >
          {taskFailed ? (
            <TriangleAlert size={13} className="shrink-0 mt-0.5" />
          ) : (
            <Check size={13} className="shrink-0 mt-0.5" style={{ color: "var(--green)" }} />
          )}
          <span>{taskProgress.message}</span>
        </div>
      )}
    </section>
  );
}
