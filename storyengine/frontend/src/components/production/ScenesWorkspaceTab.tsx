"use client";

/**
 * ScenesWorkspaceTab — ONE workspace per scene: boards → final pictures →
 * clips, redo at any level in place (Ryan's answer 1, 2026-06-12). The
 * separate Storyboard and Video Clips tabs collapsed into this.
 *
 * Design bar (decisions.md): the page banner is the ONLY primary CTA;
 * everything here is a per-item contextual control or lives behind ⋯.
 * Clips follow the trust-ladder contract: tap a card = animate (~$0.10,
 * no confirm), "Animate this scene" per group, "Animate the rest" in the
 * strip; confirms only above $0.50. Bad crops wear a red badge with a
 * one-tap Re-crop that also re-animates stale clips server-side.
 */

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, Loader2, Image as ImageIcon, RefreshCw,
  Lock, Unlock, ArrowLeft, X, MoreHorizontal, Play, Pause,
  MessageCircle, AlertTriangle, Film, Sparkles, RotateCcw, Scissors, MapPin, Volume2, LayoutGrid, Download, Ratio,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { PromptExpander } from "@/components/video-detail/prompt-expander";
import { VoicePlayer } from "@/components/video-detail/voice-player";
import {
  getVideoScript, getVideoAssets, getDialogueMap, updateStoryboardMode,
  clearSceneStoryboard, clearAllStoryboards, clearStoryboardSlot,
  clearAllExtractedPanels, clearExtractedPanel, uploadStoryboardGrid,
  runPipelineStage, clearStaleTask, updateVideoStyles, updateVideo,
  getDefaultVideoMotionPrompt, getAudioToken, advanceVideo, unlockStory,
  deleteClip, recropAsset, getEnvironments, updateVideoPrompt, updateImagePrompt, improvePrompt,
} from "@/lib/api";
import { clipCost } from "@/lib/next-action";
import { useTaskWatcher } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { VideoDetail, Asset } from "@/lib/api";
import { toDisplayImageUrl, toDisplayVideoUrl } from "@/lib/utils";
import { API_URL } from "@/lib/env";
import { AnimaticPlayer } from "@/components/production/AnimaticPlayer";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";

/** Models with a live generation path (the registry rejects the rest). */
const WIRED_MODELS: { id: string; label: string }[] = [
  { id: "grok-imagine", label: "Grok Imagine — $0.10/clip" },
  { id: "seedance-2-fast", label: "Seedance 2.0 Cinematic — $0.30/clip" },
  { id: "veo-3.1-fast", label: "Veo 3.1 Fast — $0.30/clip" },
  { id: "veo-3.1-quality", label: "Veo 3.1 Quality — $1.25/clip" },
];

/** Loose containment match for the 💬 badge — mirrors backend match_lines. */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

/** Fetches a short-lived audio token, then renders VoicePlayer with scoped URL */
function SecureAudioPlayer({ videoId, scene }: { videoId: string; scene: number }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getAudioToken(videoId).then(({ token }) => {
      // API_URL, not window.location:8001 — the old guess produced an
      // unreachable port in prod and every player rendered dead at 0:00.
      if (!cancelled) setAudioUrl(`${API_URL}/api/videos/${videoId}/audio/${scene}?token=${token}`);
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => { cancelled = true; };
  }, [videoId, scene]);
  if (failed) return null;
  if (!audioUrl) return <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>Loading audio...</p>;
  return <div className="mb-3"><VoicePlayer audioUrl={audioUrl} /></div>;
}

interface SceneGroup {
  sceneNumber: number;
  narrationText: string;
  duration: string;
  voiceOverUrl: string | null;
  sceneVideoUrl: string | null;
  storyboardBeats: Array<{ beatNumber: number; prompt: string; gridUrl: string | null }>;
  storyboardStatus: string | null;
  storyboardBeatCount: number | null;
  storyboardGridCount: number;
  hasStoryboardPrompt: boolean;
  hasStoryboardData: boolean;
  /** Cache-bust key — boards update in place at the same URL, so the <img>
   *  must change its src when the scene's row changes or the browser/CDN
   *  serves a stale grid. */
  gridVersion: number;
  assets: Asset[];
}

function parseStoryboardPromptBlocks(promptText: string | null | undefined) {
  const prompt = (promptText || "").trim();
  if (!prompt) return [];
  const beatRegex = /--- BEAT (\d+) ---\s*\n([\s\S]*?)(?=\n--- BEAT \d+ ---|$)/g;
  const beats = Array.from(prompt.matchAll(beatRegex)).map((match) => ({
    beatNumber: Number(match[1]),
    prompt: match[2].trim(),
  }));
  if (beats.length > 0) return beats;
  return [{ beatNumber: 1, prompt }];
}

interface ScenesWorkspaceTabProps {
  video: VideoDetail & { id: string };
  onGoToScriptVoice?: () => void;
  onGoToEnvironments?: () => void;
  onAdvanced?: () => void;
}

export function ScenesWorkspaceTab({ video, onGoToScriptVoice, onGoToEnvironments, onAdvanced }: ScenesWorkspaceTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const model = video.video_model || "grok-imagine";
  const perClip = clipCost(model, 1);

  // The "video" (animation) stage can be switched OFF at creation (an images-
  // only plan). When it is, keep the picture workspace but hide every animate/
  // clip affordance — the backend refuses those triggers too. Full-pipeline
  // videos (no plan) and any plan that includes "video" keep everything.
  const videoStageEnabled = useMemo(() => {
    const plan = video.pipeline_stages;
    if (!Array.isArray(plan) || plan.length === 0) return true;
    return plan.includes("video");
  }, [video.pipeline_stages]);

  // ── Data ──
  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });
  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });
  const { data: dialogueMap } = useQuery({
    queryKey: ["dialogue-map", video.id],
    queryFn: () => getDialogueMap(video.id),
    staleTime: 60_000,
  });

  // Storyboards require the environments step to be done (approved OR skipped) —
  // the backend enforces this; we mirror it here so the creator sees a clear
  // banner and we never fire a generation that will just fail.
  const { data: environmentsData } = useQuery({
    queryKey: ["video-environments", video.id],
    queryFn: () => getEnvironments(video.id),
    staleTime: 30_000,
  });
  const environmentsReady = !!environmentsData?.approved_at;

  // Guard every storyboard-generating action: bounce with a clear message
  // (and a pointer to the Environments tab) instead of firing a doomed task.
  const requireEnvironments = useCallback(() => {
    if (environmentsReady) return true;
    toast.error('Design your environments first — open the Environments tab (or hit "No locations — skip" there) before generating storyboards.');
    return false;
  }, [environmentsReady, toast]);

  const hasVoice = useMemo(
    () => (scriptScenes ?? []).some((s) => !!s.voice_over_url),
    [scriptScenes],
  );

  // Voice is optional. When AI voice-over is off (skip_voice / no "voice" stage),
  // image segmentation is timed from word count instead (the backend's
  // deterministic splitter falls back to a default words-per-second), so the
  // Scenes step must NOT hard-block on voice.
  const voiceSkipped = useMemo(() => {
    if (video.skip_voice) return true;
    const plan = video.pipeline_stages;
    return Array.isArray(plan) && plan.length > 0 && !plan.includes("voice");
  }, [video.skip_voice, video.pipeline_stages]);

  // Storyboarding is MANDATORY: boards are the only path to image spend.
  useEffect(() => {
    if (scriptScenes && scriptScenes.length > 0) {
      const anyOff = scriptScenes.some((s) => s.storyboard_on_off !== "On");
      if (anyOff) updateStoryboardMode(video.id, true).catch(() => { /* best-effort */ });
    }
  }, [scriptScenes, video.id]);

  // ── Scene groups: boards + the scene's full asset rows ──
  const scenes = useMemo<SceneGroup[]>(() => {
    if (!scriptScenes || !assets) return [];
    return scriptScenes.map((scene) => {
      const gridUrls = [
        scene.storyboard_1_url || null,
        scene.storyboard_2_url || null,
        scene.storyboard_3_url || null,
        scene.storyboard_4_url || null,
        scene.storyboard_5_url || null,
      ];
      const parsedBeats = parseStoryboardPromptBlocks(scene.storyboard_prompts).map((beat) => ({
        ...beat,
        gridUrl: gridUrls[beat.beatNumber - 1] || null,
      }));
      // The cheap one-image storyboard writes only storyboard_N_url (no prompts → no
      // parsed beats). Synthesize a board per filled slot so the sheet stays visible.
      const storyboardBeats = parsedBeats.length > 0
        ? parsedBeats
        : gridUrls.flatMap((url, i) => (url ? [{ beatNumber: i + 1, prompt: "", gridUrl: url }] : []));
      return {
        sceneNumber: scene.scene || 0,
        narrationText: scene.scene_text || "",
        duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
        voiceOverUrl: scene.voice_over_url || null,
        sceneVideoUrl: scene.scene_video_url || null,
        storyboardBeats,
        storyboardStatus: scene.storyboard_status || null,
        storyboardBeatCount: scene.storyboard_beat_count ?? (storyboardBeats.length || null),
        storyboardGridCount: gridUrls.filter(Boolean).length,
        hasStoryboardPrompt: !!scene.storyboard_prompts,
        hasStoryboardData: !!(
          scene.storyboard_prompts || scene.storyboard_status ||
          scene.storyboard_beat_count != null || gridUrls.some(Boolean)
        ),
        gridVersion: scene.updated_at ? Date.parse(scene.updated_at) || 0 : 0,
        assets: assets
          .filter((a) => a.scene === scene.scene)
          .sort((a, b) => (a.image_index || 0) - (b.image_index || 0)),
      };
    });
  }, [scriptScenes, assets]);

  // ── Local state ──
  const [generatingClipIds, setGeneratingClipIds] = useState<Set<string>>(new Set());
  const [failedClipIds, setFailedClipIds] = useState<Set<string>>(new Set());
  const [confirmKey, setConfirmKey] = useState<string | null>(null); // "scene-3" | "all"
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [recropping, setRecropping] = useState<string | null>(null);
  const [generatingScene, setGeneratingScene] = useState<number | null>(null);
  const [clearingScene, setClearingScene] = useState<number | null>(null);
  const [clearingAllStoryboards, setClearingAllStoryboards] = useState(false);
  const [clearingExtracted, setClearingExtracted] = useState(false);
  const [uploadingGrid, setUploadingGrid] = useState<string | null>(null); // "scene-beat"
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [clearingSlot, setClearingSlot] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showMotionPrompt, setShowMotionPrompt] = useState(false);
  const [imageModel, setImageModel] = useState(video.image_model_override || "gpt-image-2");
  const [savingModel, setSavingModel] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [locking, setLocking] = useState(false);
  // Replace-in-place uploads keep the same URL — bump a cache key per slot
  // so the <img> refetches the new pixels.
  const [gridBust, setGridBust] = useState<Record<string, number>>({});
  const promptsAutoRan = useRef(false);

  // Per-scene auto-chain: "Start scene over" runs plan → pictures back to back.
  // A queue of remaining pipeline steps to run sequentially (one task at a time).
  // Each step is a (stage, scene) pair; bulk "Generate all scenes" enqueues a
  // plan+draw pair per scene. Per-scene calls bypass the global stage gate, so
  // this works at any storyboard sub-stage.
  const chainRef = useRef<{ queue: Array<{ stage: string; scene?: number }> } | null>(null);

  // Clip auto-resume: "Animate the rest" keeps re-triggering the additive backend
  // (each round only animates clips still missing a video_clip_url) until every clip
  // is done — surviving server restarts and transient failures with no manual
  // re-click and no double-charge. Guards below stop any runaway loop.
  const clipResumeRef = useRef<{ active: boolean; rounds: number; lastPending: number; stale: number }>(
    { active: false, rounds: 0, lastPending: Infinity, stale: 0 });
  const prevRunningRef = useRef(false);

  const refreshAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  }, [queryClient, video.id]);

  // ALWAYS-ON watcher (lessons, twice): the strip must show whatever holds
  // the video's task slot — banner runs, silent prompt auto-run, recrop
  // chains — not just work this component started.
  const { running, message: taskMessage, markStarted } = useTaskWatcher({
    videoId: video.id,
    onProgress: () => {
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onComplete: async () => {
      const chain = chainRef.current;
      if (chain && chain.queue.length > 0) {
        const step = chain.queue.shift()!;
        const stageParams = step.scene != null ? { scene: step.scene } : undefined;
        try {
          queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
          try {
            await runPipelineStage(video.id, step.stage, stageParams);
          } catch (err) {
            if (!((err as Error).message || "").includes("409")) throw err;
            await clearStaleTask(video.id);
            await runPipelineStage(video.id, step.stage, stageParams);
          }
          setGeneratingScene(step.scene ?? null);
          markStarted();
          return;
        } catch (err) {
          chainRef.current = null;
          toast.error(
            `${step.scene != null ? `Scene ${step.scene}` : "Storyboards"} couldn't continue: ${(err as Error).message}`,
          );
        }
      }
      chainRef.current = null;
      setGeneratingScene(null);
      setGeneratingClipIds(new Set());
      setConfirmKey(null);
      setRecropping(null);
      refreshAll();
    },
    onFailed: (error) => {
      chainRef.current = null;
      setGeneratingScene(null);
      setFailedClipIds((prev) => new Set([...prev, ...generatingClipIds]));
      setGeneratingClipIds(new Set());
      setConfirmKey(null);
      setRecropping(null);
      if (generatingClipIds.size > 0) {
        toast.error(error || "Clip generation hit a problem — tap the card to try again.");
      }
      refreshAll();
    },
  });

  // Stop must stand down any queued chain stage: a cancelled task reads as
  // "completed" to pollers, which would otherwise fire the next paid stage.
  useEffect(() => {
    const onStop = (e: Event) => {
      if ((e as CustomEvent).detail?.videoId === video.id) {
        chainRef.current = null;
        clipResumeRef.current.active = false;  // Stop halts the auto-resume loop too
        setGeneratingScene(null);
        setGeneratingClipIds(new Set());
      }
    };
    window.addEventListener("se:stop-requested", onStop);
    return () => window.removeEventListener("se:stop-requested", onStop);
  }, [video.id]);

  useEffect(() => {
    setImageModel(video.image_model_override || "gpt-image-2");
  }, [video.image_model_override]);

  // ── Derived counts ──
  const allAssets = useMemo(() => scenes.flatMap((s) => s.assets), [scenes]);
  const totalSegments = allAssets.length;
  const extractedCount = allAssets.filter((a) => a.image_url).length;
  const clipCards = useMemo(() => allAssets.filter((a) => a.image_url), [allAssets]);
  const clipsDone = clipCards.filter((a) => a.video_clip_url).length;
  const clipsPending = clipCards.length - clipsDone;
  const promptlessCount = clipCards.filter((a) => !a.video_prompt && !a.video_clip_url).length;
  const badCropCount = allAssets.filter((a) => (a.extraction_flags?.length ?? 0) > 0).length;
  const upscaledCount = allAssets.filter((a) => a.image_url?.includes("_hd")).length;
  const needsUpscale = extractedCount > 0 && extractedCount - upscaledCount > 2;
  const boardsDone = scenes.reduce((n, s) => n + s.storyboardGridCount, 0);
  const boardsTotal = scenes.reduce((n, s) => n + (s.storyboardBeatCount || 1), 0);
  const remainingCost = clipCost(model, clipsPending);
  // ONE stage-aware bulk action: run the step the most scenes need next. Driven by
  // the SAME lists the button acts on, so it can never show-but-no-op (the old bug).
  const needStoryboard = scenes.filter((s) => s.storyboardGridCount === 0);
  const needPictures = scenes.filter((s) => s.storyboardGridCount > 0 && !s.assets.some((a) => a.image_url));
  const bulk: { kind: "gen"; stage: string; label: string; scenes: typeof scenes } | { kind: "animate"; label: string } | null =
    needStoryboard.length ? { kind: "gen", stage: "storyboard-images", label: `Generate all storyboards (${needStoryboard.length})`, scenes: needStoryboard }
    : needPictures.length ? { kind: "gen", stage: "coverage-images", label: `Generate all pictures (${needPictures.length})`, scenes: needPictures }
    : (videoStageEnabled && clipsPending > 0) ? { kind: "animate", label: `Animate everything · $${remainingCost.toFixed(2)}` }
    : null;
  const modelLabel = WIRED_MODELS.find((m) => m.id === model)?.label.split(" — ")[0] ?? model;
  const storyLocked = !!video.story_locked_at;

  // Scene → dialogue lines for the 💬 badge.
  const dialogueByScene = useMemo(() => {
    const map = new Map<number, { speaker: string; text: string }[]>();
    for (const sc of dialogueMap?.scenes ?? []) {
      map.set(sc.scene, sc.segments
        .filter((s) => s.type === "dialogue" && s.speaker && s.text)
        .map((s) => ({ speaker: s.speaker as string, text: norm(s.text) })));
    }
    return map;
  }, [dialogueMap]);

  const speakerFor = useCallback((asset: Asset): string | null => {
    const lines = dialogueByScene.get(asset.scene ?? -1);
    if (!lines?.length || !asset.sentence_text) return null;
    const text = norm(asset.sentence_text);
    return lines.find((l) => text.includes(l.text) || l.text.includes(text))?.speaker ?? null;
  }, [dialogueByScene]);

  // Motion prompts are plumbing, not a decision: write them silently the
  // moment the workspace sees animatable cards without one.
  useEffect(() => {
    if (!videoStageEnabled || promptsAutoRan.current || running || clipCards.length === 0 || promptlessCount === 0) return;
    promptsAutoRan.current = true;
    (async () => {
      try {
        await runPipelineStage(video.id, "video-scripts");
        markStarted();
      } catch {
        promptsAutoRan.current = false; // 409 etc. — retry on next mount
      }
    })();
  }, [videoStageEnabled, clipCards.length, promptlessCount, running, video.id, markStarted]);

  // ── Stage helpers (storyboard side) ──
  const runStageWith409Retry = useCallback(async (stage: string, params?: Record<string, string | number>) => {
    try {
      await runPipelineStage(video.id, stage, params);
      markStarted();
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        await clearStaleTask(video.id);
        await runPipelineStage(video.id, stage, params);
        markStarted();
        return;
      }
      throw err;
    }
  }, [video.id, markStarted]);

  const handleRedoSceneFromScratch = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    const confirmed = window.confirm(
      `Redo Scene ${sceneNumber}'s pictures? We'll draw fresh per-shot pictures, replacing the current ones (≈ $0.08 each).\n\nTo remove just one picture, hover it and click the X.`
    );
    if (!confirmed) return;
    setClearingScene(sceneNumber);
    try {
      await clearSceneStoryboard(video.id, sceneNumber);
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("coverage-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't redo Scene ${sceneNumber}: ${(err as Error).message}`);
    } finally {
      setClearingScene(null);
    }
  }, [video.id, queryClient, toast, runStageWith409Retry, requireEnvironments]);

  // Draw a scene's grids only (no re-plan) — used by empty-slot clicks on a
  // scene that already has a plan.
  const handleGenerateSceneGrids = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    chainRef.current = null;
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Scene ${sceneNumber} failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // One per-scene action: PLAN then DRAW as two chained tasks (the draw runs
  // from onComplete, after the plan task finishes — separate tasks so the draw
  // reads the freshly-written plan; an in-process plan+draw can't see its own
  // new prompts). Always plans first, so a draw never fires without a plan.
  // Step 1 — the CHEAP one-image storyboard (a quick "do I like the direction?"
  // preview). storyboard-images → generate_storyboard_sheet_for_scene.
  const handleGenerateScene = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    try {
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't generate Scene ${sceneNumber} storyboard: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // Step 2 — draw the REAL per-shot pictures (coverage), after the storyboard
  // preview. coverage-images → generate_coverage_for_video; replaces any pictures.
  const handleGenerateRealImages = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    try {
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("coverage-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't generate Scene ${sceneNumber} pictures: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // Manual per-scene stitch — FFmpeg-concats the scene's clips into one video.
  // Auto-stitch already covers the animate paths; this is the explicit button +
  // re-stitch on demand (shown once every clip in the scene is animated).
  const handleStitchScene = useCallback(async (sceneNumber: number) => {
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("stitch-scene", { scene: sceneNumber });
    } catch (err) {
      setGeneratingScene(null);
      toast.error(`Couldn't stitch Scene ${sceneNumber}: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast]);

  // Bulk: run ONE stage for every scene in the list, one task at a time (the
  // onComplete chain runs the queue in order). Used by the stage-aware header
  // button — storyboards for all, or pictures for all, never both.
  const handleBulkGen = useCallback(async (stage: string, list: typeof scenes) => {
    if (!requireEnvironments()) return;
    if (list.length === 0) return;
    const what = stage === "coverage-images" ? "pictures" : "storyboards";
    if (!window.confirm(
      `Generate ${what} for ${list.length} scene${list.length === 1 ? "" : "s"} (≈ $0.08 each). You can Stop anytime.`,
    )) return;
    const steps = list.map((s) => ({ stage, scene: s.sceneNumber }));
    const [first, ...rest] = steps;
    try {
      chainRef.current = { queue: rest };
      setGeneratingScene(first.scene ?? null);
      await runStageWith409Retry(first.stage, { scene: first.scene });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't start generating all ${what}: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  const handleClearAllStoryboards = useCallback(async () => {
    if (!window.confirm(
      "Start the storyboard over? Every board and every scene plan gets thrown away. Your script and voice stay. You’ll rebuild from the big button at the top.",
    )) return;
    setClearingAllStoryboards(true);
    try {
      await clearAllStoryboards(video.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-script", video.id] }),
        queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
      ]);
    } finally {
      setClearingAllStoryboards(false);
    }
  }, [video.id, queryClient]);

  const handleClearAllExtracted = useCallback(async () => {
    if (!window.confirm("Delete all the final pictures? Your storyboards stay — you can create the final pictures again afterwards.")) return;
    setClearingExtracted(true);
    try {
      await clearAllExtractedPanels(video.id);
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setClearingExtracted(false);
    }
  }, [video.id, queryClient]);

  const handleGridDrop = useCallback(async (sceneNumber: number, beatNumber: number, file: File) => {
    const key = `${sceneNumber}-${beatNumber}`;
    setUploadingGrid(key);
    try {
      await uploadStoryboardGrid(video.id, sceneNumber, beatNumber, file);
      setGridBust((prev) => ({ ...prev, [key]: Date.now() }));
      toast.success(`Your image is now storyboard S${sceneNumber}.${beatNumber}.`);
      await queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message || "please try again."}`);
    } finally {
      setUploadingGrid(null);
      setDragOver(null);
    }
  }, [video.id, queryClient, toast]);

  const handleClearGridSlot = useCallback(async (sceneNumber: number, beatNumber: number) => {
    if (!window.confirm(
      `Remove storyboard picture S${sceneNumber}.${beatNumber}? Your scene descriptions and prompts stay — only this image goes. You can regenerate it or drop in your own.`
    )) return;
    const key = `${sceneNumber}-${beatNumber}`;
    setClearingSlot(key);
    try {
      await clearStoryboardSlot(video.id, sceneNumber, beatNumber);
      await queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch (err) {
      toast.error(`Couldn't remove that picture: ${(err as Error).message || "please try again."}`);
    } finally {
      setClearingSlot(null);
    }
  }, [video.id, queryClient, toast]);

  const handleClearExtractedPanel = useCallback(async (assetId: string) => {
    try {
      await clearExtractedPanel(video.id, assetId);
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch { /* silent */ }
  }, [video.id, queryClient]);

  const handleUnlockStory = useCallback(async () => {
    setLocking(true);
    try {
      await unlockStory(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      toast.info("Story unlocked — keep iterating on the boards.");
    } catch (err) {
      toast.error((err as Error).message || "Couldn't unlock the story.");
    } finally {
      setLocking(false);
    }
  }, [video.id, queryClient, toast]);

  const handleReExtract = useCallback(async () => {
    try {
      try { await clearStaleTask(video.id); } catch { /* ok */ }
      await runPipelineStage(video.id, "storyboard-extract");
      markStarted();
    } catch (err: unknown) {
      toast.error(`Couldn't start: ${(err as Error).message || "Unknown error"}`);
    }
  }, [video.id, markStarted, toast]);

  const handleUpscalePanels = useCallback(async () => {
    try {
      try { await clearStaleTask(video.id); } catch { /* ok */ }
      await runPipelineStage(video.id, "upscale-panels");
      markStarted();
    } catch (err: unknown) {
      toast.error(`Upscale failed: ${(err as Error).message || "Unknown error"}`);
    }
  }, [video.id, markStarted, toast]);

  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      refreshAll();
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, refreshAll, onAdvanced, toast]);

  const handleImageModelChange = useCallback(async (next: string) => {
    setImageModel(next);
    setSavingModel(true);
    try {
      await updateVideoStyles(video.id, { image_model_override: next });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error(`Failed to update image model: ${(err as Error).message}`);
      setImageModel(video.image_model_override || "gpt-image-2");
    } finally {
      setSavingModel(false);
    }
  }, [queryClient, video.id, video.image_model_override, toast]);

  const handleClipModelChange = useCallback(async (next: string) => {
    try {
      await updateVideoStyles(video.id, { video_model: next });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  // ── Clip actions (trust-ladder contract) ──
  const startClipTask = useCallback(async (params: Record<string, string | number>, ids: string[]) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}. This card will be tappable the moment it's done.`);
      return;
    }
    setFailedClipIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    setGeneratingClipIds(new Set(ids));
    try {
      await runPipelineStage(video.id, "clip", params);
      markStarted();
    } catch (err) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "clip", params);
          markStarted();
          return;
        } catch (retryErr) {
          toast.error((retryErr as Error).message);
        }
      } else {
        toast.error(message || "Couldn't start the clip.");
      }
      setGeneratingClipIds(new Set());
    }
  }, [running, taskMessage, video.id, toast, markStarted]);

  const animateOne = (asset: Asset, force = false) => {
    clipResumeRef.current.active = false;  // a manual single-card tap isn't a batch
    startClipTask(force ? { asset_id: asset.id, force: "true" } : { asset_id: asset.id }, [asset.id]);
  };

  const animateScene = (scene: number, pendingIds: string[]) => {
    clipResumeRef.current.active = false;  // a single-scene run isn't the full batch
    startClipTask({ scene }, pendingIds);
  };

  const animateAll = () => {
    // Arm auto-resume: keep going until the backend says nothing's left to animate.
    clipResumeRef.current = { active: true, rounds: 0, lastPending: Infinity, stale: 0 };
    startClipTask({}, clipCards.filter((a) => !a.video_clip_url).map((a) => a.id));
  };

  // After each clip batch ends (done, failed, or "server restarted"), if clips are
  // still missing, re-trigger — until none remain, no progress happens twice in a
  // row, or a safety cap is hit. The backend is additive, so this never double-charges.
  const maybeResumeClips = useCallback(async () => {
    const st = clipResumeRef.current;
    if (!st.active) return;
    let pending: string[] = [];
    try {
      const fresh = await getVideoAssets(video.id);
      pending = fresh.filter((a) => a.image_url && !a.video_clip_url).map((a) => a.id);
    } catch {
      st.active = false;  // can't check — stop rather than loop blind
      return;
    }
    if (pending.length === 0) {
      st.active = false;
      toast.success("All clips animated 🎬");
      refreshAll();
      return;
    }
    st.rounds += 1;
    if (pending.length < st.lastPending) st.stale = 0;
    else st.stale += 1;
    st.lastPending = pending.length;
    if (st.rounds > 25 || st.stale >= 2) {
      st.active = false;
      toast.error(`${pending.length} clip(s) still need animating — tap "Animate the rest" to keep going.`);
      refreshAll();
      return;
    }
    await new Promise((r) => setTimeout(r, 1500));
    if (clipResumeRef.current.active) startClipTask({}, pending);
  }, [video.id, toast, refreshAll, startClipTask]);

  // Fire the resumer on each running → idle transition.
  useEffect(() => {
    const wasRunning = prevRunningRef.current;
    prevRunningRef.current = running;
    if (wasRunning && !running && clipResumeRef.current.active) {
      void maybeResumeClips();
    }
  }, [running, maybeResumeClips]);

  const removeClip = useCallback(async (asset: Asset) => {
    try {
      await deleteClip(video.id, asset.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  // One-tap bad-crop fix: free re-crop of the whole beat; the backend
  // re-animates any clips the new pictures made stale (~$0.10 each).
  const recropOne = useCallback(async (asset: Asset) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}.`);
      return;
    }
    setRecropping(asset.id);
    try {
      await recropAsset(video.id, asset.id);
      markStarted();
      toast.info("Re-cropping this picture's storyboard — clips that go stale re-animate automatically (~$0.10 each).");
    } catch (err) {
      setRecropping(null);
      toast.error((err as Error).message || "Couldn't start the re-crop.");
    }
  }, [video.id, running, taskMessage, markStarted, toast]);

  const redrawOne = useCallback(async (asset: Asset) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}.`);
      return;
    }
    setRecropping(asset.id);  // reuse the per-card "working" dim until onComplete clears it
    try {
      await runStageWith409Retry("redraw-image", { asset_id: asset.id });
      toast.info("Redrawing this picture from your prompt (~$0.08), anchored on the locked cast. Re-animate after.");
    } catch (err) {
      setRecropping(null);
      toast.error((err as Error).message || "Couldn't start the redraw.");
    }
  }, [running, taskMessage, toast, runStageWith409Retry]);

  /** Confirm-then-run for anything over $0.50; cheaper actions just go. */
  const confirmable = (key: string, dollars: number, run: () => void) => {
    if (dollars <= 0.5 || confirmKey === key) {
      setConfirmKey(null);
      run();
    } else {
      setConfirmKey(key);
    }
  };

  // ── Guards ──
  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--purple)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading your scenes...</span>
      </div>
    );
  }

  if (!hasVoice && !voiceSkipped) {
    return (
      <GlassCard className="p-10 text-center max-w-lg mx-auto">
        <div className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4"
          style={{ background: "rgba(255, 165, 0, 0.12)", border: "1px solid rgba(255, 165, 0, 0.25)" }}>
          <Lock size={20} style={{ color: "var(--orange)" }} />
        </div>
        <h3 className="text-lg font-display font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Voice Required
        </h3>
        <p className="text-sm leading-relaxed mb-6" style={{ color: "var(--text-secondary)" }}>
          Voice must be generated before visuals. Voice audio timing drives image
          segmentation — without it, images will be incorrectly timed.
        </p>
        {onGoToScriptVoice && (
          <button onClick={onGoToScriptVoice}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
            <ArrowLeft size={14} />
            Go to Script &amp; Voice
          </button>
        )}
      </GlassCard>
    );
  }

  if (scenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Your scenes will appear here
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          {running
            ? (taskMessage || "Working on it…")
            : "Use the big button at the top of the page — it always knows the next step."}
        </p>
      </GlassCard>
    );
  }

  // ── Render ──
  return (
    <div className="flex flex-col gap-4">
      {/* Environments gate: storyboards need locations locked (or skipped)
          first — guide the creator there instead of generating drifting
          backgrounds. The generation handlers are guarded too. */}
      {!environmentsReady && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap"
          style={{ background: "rgba(245, 158, 11, 0.10)", border: "1px solid rgba(245, 158, 11, 0.35)" }}>
          <MapPin size={16} style={{ color: "var(--gold)" }} className="shrink-0" />
          <p className="text-sm flex-1 min-w-[12rem]" style={{ color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>Design your environments first.</strong>{" "}
            Storyboards lock each location so backgrounds stay consistent. Approve them in the
            Environments tab — or mark “No locations” there if this video has none.
          </p>
          {onGoToEnvironments && (
            <button
              onClick={onGoToEnvironments}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110 shrink-0"
              style={{ background: "var(--gold)", color: "var(--bg-void)" }}>
              <MapPin size={13} /> Design environments
            </button>
          )}
        </div>
      )}
      {/* Model controls — always visible at the top (no longer buried in the Advanced menu). */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <ImageIcon size={13} style={{ color: "var(--text-tertiary)" }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Pictures</span>
          <select value={imageModel} onChange={(e) => handleImageModelChange(e.target.value)} disabled={savingModel}
            className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
            <option value="nano-banana-2">Nano Banana 2</option>
            <option value="gpt-image-2">GPT Image 2</option>
            <option value="z-image">Z Image</option>
          </select>
        </div>
        {videoStageEnabled && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <Film size={13} style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Clips</span>
            <select value={model} onChange={(e) => handleClipModelChange(e.target.value)}
              className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
              {WIRED_MODELS.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        )}
        {videoStageEnabled && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <Volume2 size={13} style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Voice</span>
            <select value={video.dialogue_audio || "voice_over"}
              onChange={async (e) => {
                try {
                  await updateVideo(video.id, { dialogue_audio: e.target.value });
                  queryClient.invalidateQueries({ queryKey: ["video", video.id] });
                } catch (err) { toast.error((err as Error).message); }
              }}
              className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
              <option value="voice_over">Character voice-over</option>
              <option value="grok_native">Grok native</option>
            </select>
          </div>
        )}
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <Ratio size={13} style={{ color: "var(--text-tertiary)" }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Aspect</span>
          <select value={video.aspect_ratio || "16:9"}
            onChange={async (e) => {
              try {
                await updateVideo(video.id, { aspect_ratio: e.target.value });
                queryClient.invalidateQueries({ queryKey: ["video", video.id] });
              } catch (err) { toast.error((err as Error).message); }
            }}
            className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
            <option value="16:9">16:9 wide</option>
            <option value="9:16">9:16 tall</option>
            <option value="1:1">1:1 square</option>
          </select>
        </div>
      </div>

      {/* Prominent command bar — progress at a glance + the one big bulk action.
          order-first floats it to the top of the workspace, above the model pickers. */}
      <div className="order-first rounded-xl px-5 py-4 flex items-center gap-3 flex-wrap"
        style={{ background: "rgba(0, 230, 138, 0.06)", border: "1px solid rgba(0, 230, 138, 0.22)" }}>
        <p className="text-base font-medium" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{scenes.length} scenes</strong>
          {" · "}
          <strong style={{ color: boardsDone >= boardsTotal ? "var(--green)" : "var(--text-primary)" }}>
            {boardsDone}/{boardsTotal} boards
          </strong>
          {extractedCount > 0 && (
            <>
              {" · "}
              <strong style={{ color: "var(--green)" }}>{extractedCount}/{totalSegments} pictures</strong>
              {videoStageEnabled && (
                <>
                  {" · "}
                  <strong style={{ color: clipsDone === clipCards.length ? "var(--green)" : "var(--text-primary)" }}>
                    {clipsDone}/{clipCards.length} animated
                  </strong>
                  {clipsPending > 0 && (
                    <span style={{ color: "var(--text-tertiary)" }}> · ≈ ${remainingCost.toFixed(2)} to finish · {modelLabel}</span>
                  )}
                </>
              )}
            </>
          )}
          {badCropCount > 0 && (
            <span className="ml-2 text-xs font-semibold" style={{ color: "rgb(255,110,110)" }}>
              <AlertTriangle size={11} className="inline mr-0.5 -mt-0.5" /> {badCropCount} bad crop{badCropCount === 1 ? "" : "s"}
            </span>
          )}
          {storyLocked && (
            <span className="ml-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
              <Lock size={11} className="inline mr-0.5 -mt-0.5" /> Story locked
            </span>
          )}
        </p>
        {running && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            style={{ background: "rgba(139, 92, 246, 0.15)", color: "var(--purple)", border: "1px solid rgba(139, 92, 246, 0.35)" }}>
            <Loader2 size={12} className="animate-spin" />
            {(taskMessage || "Working…").replace(/[*_]/g, "").slice(0, 80)}
          </span>
        )}
        <div className="flex-1" />
        {/* ONE stage-aware bulk button: storyboards → pictures → animate everything. */}
        {!running && !storyLocked && environmentsReady && bulk && (
          bulk.kind === "animate" ? (
            <button
              onClick={() => confirmable("all", remainingCost, animateAll)}
              disabled={running}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-40 transition-all hover:brightness-110"
              style={{ background: confirmKey === "all" ? "var(--gold)" : "var(--green)", color: "var(--bg-void)" }}>
              <Play size={16} /> {confirmKey === "all" ? `Confirm — $${remainingCost.toFixed(2)}` : bulk.label}
            </button>
          ) : (
            <button
              onClick={() => handleBulkGen(bulk.stage, bulk.scenes)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110"
              style={{ background: bulk.stage === "coverage-images" ? "var(--orange)" : "var(--purple)", color: "var(--bg-void)" }}
              title="Run this step for every scene that needs it">
              <ImageIcon size={16} /> {bulk.label}
            </button>
          )
        )}
        {confirmKey === "all" && (
          <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            Cancel
          </button>
        )}
        <StopGenerationButton videoId={video.id} running={running} />
        {storyLocked && (
          <button onClick={handleUnlockStory} disabled={locking || running}
            className="text-xs font-medium px-3 py-1.5 rounded-lg transition-all disabled:opacity-40"
            style={{ color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.12)" }}
            title="Unlock to keep editing boards">
            {locking ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Unlock size={12} className="inline mr-1" />}
            Unlock
          </button>
        )}
        <div className="relative">
          <button onClick={() => setShowAdvanced(!showAdvanced)}
            className="p-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)]"
            style={{ color: "var(--text-tertiary)" }} aria-label="Advanced options" title="Advanced options">
            <MoreHorizontal size={18} />
          </button>
          {showAdvanced && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowAdvanced(false)} />
              <div className="absolute right-0 top-full mt-2 z-50 w-72 rounded-xl p-2 space-y-0.5"
                style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>
                  Pictures
                </p>
                {extractedCount > 0 && needsUpscale && (
                  <button onClick={() => { setShowAdvanced(false); handleUpscalePanels(); }} disabled={running}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--text-secondary)" }}>
                    Upscale final pictures <span style={{ color: "var(--text-tertiary)" }}>({upscaledCount}/{extractedCount} done)</span>
                  </button>
                )}
                {storyLocked && totalSegments > 0 && extractedCount < totalSegments && (
                  <button onClick={() => { setShowAdvanced(false); handleReExtract(); }} disabled={running}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--text-secondary)" }}>
                    Create missing final pictures <span style={{ color: "var(--text-tertiary)" }}>({totalSegments - extractedCount} to make)</span>
                  </button>
                )}
                {videoStageEnabled && (
                <>
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>
                  Clips
                </p>
                <button
                  onClick={() => {
                    setShowAdvanced(false);
                    runPipelineStage(video.id, "video-scripts").then(() => markStarted())
                      .catch((e) => toast.error((e as Error).message));
                  }}
                  disabled={running}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 disabled:opacity-40 flex items-center gap-2"
                  style={{ color: "var(--text-secondary)" }}>
                  <Sparkles size={12} /> Re-write motion directions
                </button>
                <button onClick={() => { setShowMotionPrompt((v) => !v); setShowAdvanced(false); }}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 flex items-center gap-2"
                  style={{ color: "var(--text-secondary)" }}>
                  <Film size={12} /> {showMotionPrompt ? "Hide" : "Edit"} motion instructions
                </button>
                <div className="border-t my-1" style={{ borderColor: "rgba(255,255,255,0.08)" }} />
                </>
                )}
                {extractedCount > 0 && (
                  <button onClick={() => { setShowAdvanced(false); handleClearAllExtracted(); }}
                    disabled={running || clearingExtracted}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--orange)" }}>
                    Delete all final pictures <span style={{ color: "var(--text-tertiary)" }}>— boards stay</span>
                  </button>
                )}
                <button onClick={() => { setShowAdvanced(false); handleClearAllStoryboards(); }}
                  disabled={running || clearingAllStoryboards || storyLocked}
                  title={storyLocked ? "Unlock the story first" : undefined}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--orange)" }}>
                  Clear ALL storyboards <span style={{ color: "var(--text-tertiary)" }}>— deletes every board + plan</span>
                </button>
                <button onClick={() => { setShowAdvanced(false); handleAdvanceStage(); }} disabled={advancing}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--text-secondary)" }}>
                  Skip ahead to the next stage
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {showMotionPrompt && (
        <SystemPromptEditor
          label="Video Motion System Prompt"
          currentValue={video.video_motion_system_prompt}
          onSave={async (text) => {
            await updateVideo(video.id, { video_motion_system_prompt: text || null });
            queryClient.invalidateQueries({ queryKey: ["video", video.id] });
          }}
          onReset={async () => {
            const res = await getDefaultVideoMotionPrompt();
            await updateVideo(video.id, { video_motion_system_prompt: null });
            queryClient.invalidateQueries({ queryKey: ["video", video.id] });
            return res.prompt;
          }}
        />
      )}

      {/* ── Scene cards: boards → pictures+clips, one card per scene ── */}
      {scenes.map((scene) => {
        const sceneCards = scene.assets.filter((a) => a.image_url);
        const scenePending = sceneCards.filter((a) => !a.video_clip_url);
        const sceneCost = clipCost(model, scenePending.length);
        const sceneKey = `scene-${scene.sceneNumber}`;
        return (
          <GlassCard key={scene.sceneNumber} id={sceneKey} className="p-5">
            {/* Scene header: identity + per-scene verbs */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <SegmentBadge label={`Scene ${scene.sceneNumber}`} color="var(--purple)" />
              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {scene.duration}
              </span>
              {sceneCards.length > 0 && (
                <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                  {sceneCards.length - scenePending.length} of {sceneCards.length} animated
                </span>
              )}
              <div className="ml-auto flex items-center gap-2 flex-wrap">
                {generatingScene === scene.sceneNumber ? (
                  <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--purple)" }}>
                    <Loader2 size={13} className="animate-spin" /> Generating this scene…
                  </span>
                ) : (
                  <>
                    {/* ONE big primary = this scene's next step. Stage colour:
                        1 storyboard (purple) → 2 pictures (orange) → 3 animate (green).
                        Redo is a small secondary once pictures exist. */}
                    {sceneCards.length === 0 && scene.storyboardGridCount === 0 ? (
                      <button onClick={() => handleGenerateScene(scene.sceneNumber)}
                        disabled={running || storyLocked}
                        title={storyLocked ? "Unlock the story first (top right)" : "Write a quick one-image storyboard to preview the direction"}
                        className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                        style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
                        <LayoutGrid size={15} /> Generate storyboard
                      </button>
                    ) : sceneCards.length === 0 ? (
                      <>
                        {/* Storyboard exists but no pictures yet: let them REDO the board
                            (e.g. after changing the cast or environments) OR move to pictures. */}
                        <button onClick={() => handleGenerateScene(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Redraw this scene's storyboard (after changing the cast, environments, or script)"}
                          className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "transparent", border: "1px solid var(--purple)", color: "var(--purple)" }}>
                          <LayoutGrid size={15} /> Regenerate storyboard
                        </button>
                        <button onClick={() => handleGenerateRealImages(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Draw the real per-shot pictures for this scene"}
                          className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "var(--orange)", color: "var(--bg-void)" }}>
                          <ImageIcon size={15} /> Generate pictures
                        </button>
                      </>
                    ) : (
                      <>
                        {videoStageEnabled && scenePending.length > 0 && (
                          <>
                            {confirmKey === sceneKey && (
                              <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                                Cancel
                              </button>
                            )}
                            <button
                              onClick={() => confirmable(sceneKey, sceneCost, () => animateScene(scene.sceneNumber, scenePending.map((a) => a.id)))}
                              disabled={running}
                              className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg disabled:opacity-40 transition-all hover:brightness-110"
                              style={confirmKey === sceneKey
                                ? { background: "var(--gold)", color: "var(--bg-void)" }
                                : { background: "var(--green)", color: "var(--bg-void)" }}>
                              <Play size={15} />
                              {confirmKey === sceneKey ? `Confirm — $${sceneCost.toFixed(2)}` : `Animate scene · $${sceneCost.toFixed(2)}`}
                            </button>
                          </>
                        )}
                        {videoStageEnabled && scenePending.length === 0 && (
                          <button onClick={() => handleStitchScene(scene.sceneNumber)}
                            disabled={running}
                            title="Stitch this scene's clips into one video you can watch"
                            className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
                            <Film size={15} /> {scene.sceneVideoUrl ? "Re-stitch scene" : "Stitch scene"}
                          </button>
                        )}
                        <button onClick={() => handleRedoSceneFromScratch(scene.sceneNumber)}
                          disabled={running || storyLocked || clearingScene === scene.sceneNumber}
                          title={storyLocked ? "Unlock the story first (top right)" : "Draw fresh pictures, replacing the current ones"}
                          className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg transition-all hover:bg-white/5 disabled:opacity-40"
                          style={{ color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.15)" }}>
                          {clearingScene === scene.sceneNumber ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={13} />} Redo
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Board + animatic side by side — equal halves, same line. */}
            <div className="flex flex-col lg:flex-row gap-4 mb-3 lg:items-stretch">
            {(scene.storyboardBeats.length > 0 || scene.hasStoryboardData) && (
              <div className="lg:flex-1 min-w-0">
                <div className={`flex gap-4 pb-2 ${scene.storyboardBeats.length === 1 ? "" : "overflow-x-auto"}`} style={{ scrollbarWidth: "thin" }}>
                  {scene.storyboardBeats.map((beat) => {
                    const slotKey = `${scene.sceneNumber}-${beat.beatNumber}`;
                    // Boards update in place at the same URL — cache-bust by the
                    // scene's updated_at (changes on every regen) so the browser/
                    // CDN never shows a stale grid. A manual upload bumps gridBust
                    // for that one slot and takes precedence.
                    const bust = gridBust[slotKey] || scene.gridVersion;
                    const displayUrl = beat.gridUrl
                      ? `${toDisplayImageUrl(beat.gridUrl)}${bust ? `?cb=${bust}` : ""}`
                      : undefined;
                    return (
                      <div key={`grid-${slotKey}`} className={`relative group/board ${scene.storyboardBeats.length === 1 ? "w-full" : "flex-shrink-0"}`}>
                        <div
                          className="relative rounded-lg overflow-hidden cursor-pointer transition-all hover:ring-2 hover:ring-[var(--purple)]"
                          style={{
                            ...(scene.storyboardBeats.length === 1
                              ? { width: "100%", aspectRatio: "16 / 9" }
                              : { width: 300, height: 176 }),
                            background: "var(--bg-elevated)",
                            border: dragOver === slotKey
                              ? "2px solid var(--green)"
                              : beat.gridUrl
                                ? "1px solid rgba(0, 230, 138, 0.25)"
                                : "1px dashed rgba(255,255,255,0.1)",
                          }}
                          onClick={() => {
                            if (beat.gridUrl) window.open(beat.gridUrl, "_blank");
                            else if (!running) handleGenerateSceneGrids(scene.sceneNumber);
                          }}
                          onDragOver={(e) => { e.preventDefault(); setDragOver(slotKey); }}
                          onDragLeave={() => setDragOver(null)}
                          onDrop={(e) => {
                            e.preventDefault();
                            setDragOver(null);
                            const file = e.dataTransfer.files[0];
                            if (file && file.type.startsWith("image/")) {
                              handleGridDrop(scene.sceneNumber, beat.beatNumber, file);
                            }
                          }}
                          title={beat.gridUrl ? "Click to open full size · drop an image here to replace it" : "Click to generate or drag & drop an image"}
                        >
                          {beat.gridUrl ? (
                            <>
                              <img src={displayUrl} alt={`S${scene.sceneNumber} board ${beat.beatNumber}`} className="w-full h-full object-cover" />
                              {(dragOver === slotKey || uploadingGrid === slotKey || clearingSlot === slotKey) && (
                                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2" style={{ background: "rgba(0,0,0,0.65)" }}>
                                  {uploadingGrid === slotKey || clearingSlot === slotKey ? (
                                    <>
                                      <Loader2 size={22} className="animate-spin" style={{ color: "var(--green)" }} />
                                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                                        {uploadingGrid === slotKey ? "Saving your image..." : "Removing..."}
                                      </span>
                                    </>
                                  ) : (
                                    <>
                                      <ImageIcon size={22} style={{ color: "var(--green)" }} />
                                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                                        Drop to replace this board
                                      </span>
                                    </>
                                  )}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center gap-2 transition-colors hover:bg-[rgba(168,85,247,0.08)]">
                              {uploadingGrid === slotKey ? (
                                <>
                                  <Loader2 size={20} className="animate-spin" style={{ color: "var(--green)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>Uploading...</span>
                                </>
                              ) : dragOver === slotKey ? (
                                <>
                                  <ImageIcon size={20} style={{ color: "var(--green)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>Drop to Upload</span>
                                </>
                              ) : generatingScene === scene.sceneNumber ? (
                                <>
                                  <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>Generating...</span>
                                </>
                              ) : (
                                <>
                                  <ImageIcon size={20} style={{ color: "var(--purple)", opacity: 0.6 }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>Click or Drop Image</span>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                        {beat.gridUrl && clearingSlot !== slotKey && uploadingGrid !== slotKey && (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleClearGridSlot(scene.sceneNumber, beat.beatNumber); }}
                            disabled={running}
                            title="Remove just this board (prompts stay)"
                            className="absolute top-1.5 right-1.5 rounded-full p-1 opacity-0 group-hover/board:opacity-100 transition-opacity disabled:opacity-0"
                            style={{ background: "rgba(0,0,0,0.75)", color: "rgba(239, 68, 68, 0.95)" }}>
                            <X size={14} />
                          </button>
                        )}
                        <p className="text-center mt-1.5 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          Board S{scene.sceneNumber}.{beat.beatNumber}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Animatic (right half): pictures + narration = the scene as a film, $0 */}
            <div className="lg:flex-1 min-w-0">
            {(() => {
              // Real stitched scene video (FFmpeg concat of the clips) wins over the
              // still-image animatic. Cache-bust by the scene's updated_at so a
              // re-stitch shows the new cut.
              if (scene.sceneVideoUrl) {
                // Drive-hosted stitches don't stream in <video> directly — route
                // through the media proxy (Supabase/other URLs pass through).
                const base = toDisplayVideoUrl(scene.sceneVideoUrl) ?? scene.sceneVideoUrl;
                const v = `${base}${scene.gridVersion ? `${base.includes("?") ? "&" : "?"}cb=${scene.gridVersion}` : ""}`;
                return (
                  <>
                    <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--turquoise)" }}>Watch this scene</p>
                    <video key={v} src={v} controls playsInline className="w-full rounded-xl"
                      style={{ aspectRatio: "16 / 9", background: "#000" }} />
                  </>
                );
              }
              const panels = scene.assets
                .filter((a) => a.image_url)
                .map((a) => ({ url: toDisplayImageUrl(a.image_url)!, text: a.sentence_text || "" }));
              if (panels.length > 0) {
                return <AnimaticPlayer videoId={video.id} scene={scene.sceneNumber} panels={panels} />;
              }
              return scene.voiceOverUrl
                ? <SecureAudioPlayer videoId={video.id} scene={scene.sceneNumber} />
                : <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>No voice generated yet</p>;
            })()}
            </div>
            </div>

            {/* Narration text — collapsed */}
            <details className="mb-3">
              <summary className="text-[11px] cursor-pointer" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--text-tertiary)" }}>
                  {scene.narrationText.slice(0, 80).trim()}{scene.narrationText.length > 80 ? "..." : ""}
                </span>
              </summary>
              <p className="text-sm leading-relaxed mt-2 pl-4"
                style={{ color: "var(--text-primary)", borderLeft: "2px solid var(--border-subtle)" }}>
                {scene.narrationText}
              </p>
            </details>

            {/* Beat prompts — collapsed. Only for storyboards with a written plan;
                the cheap one-image storyboard has no per-beat text (the plan is the
                picture), so skip the empty accordion. */}
            {(() => {
              const planned = scene.storyboardBeats.filter((b) => b.prompt.trim());
              if (planned.length === 0) return null;
              return (
                <details className="mb-3">
                  <summary className="text-[10px] cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
                    {planned.length} picture plan{planned.length !== 1 ? "s" : ""}
                  </summary>
                  <div className="space-y-2 mt-2">
                    {planned.map((beat) => (
                      <PromptExpander key={`prompt-${scene.sceneNumber}-${beat.beatNumber}`}
                        prompt={beat.prompt} label={`Beat ${beat.beatNumber}`} previewLength={120} />
                    ))}
                  </div>
                </details>
              );
            })()}

            {/* ── Pictures + clips: one card per story segment ── */}
            {sceneCards.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mt-1">
                {sceneCards.map((asset) => (
                  <SegmentCard
                    key={asset.id}
                    asset={asset}
                    speaker={speakerFor(asset)}
                    perClip={perClip}
                    canAnimate={videoStageEnabled}
                    isGenerating={generatingClipIds.has(asset.id) && running}
                    isRecropping={recropping === asset.id && running}
                    isFailed={failedClipIds.has(asset.id)}
                    isPlaying={playingId === asset.id}
                    disabled={running}
                    onTap={() => {
                      if (asset.video_clip_url) setPlayingId((p) => (p === asset.id ? null : asset.id));
                      else if (videoStageEnabled) animateOne(asset);
                    }}
                    onRedoClip={() => animateOne(asset, true)}
                    onDeleteClip={() => removeClip(asset)}
                    onDeletePicture={() => handleClearExtractedPanel(asset.id)}
                    onRecrop={() => recropOne(asset)}
                    onRedraw={() => redrawOne(asset)}
                  />
                ))}
              </div>
            )}
          </GlassCard>
        );
      })}
    </div>
  );
}

/** One story segment: shows the clip when it exists (tap = play), else the
 * final picture (tap = animate, ~$0.10). Bad crops wear a red badge whose
 * one-tap Re-crop is free and re-animates stale clips automatically. */
function SegmentCard({ asset, speaker, perClip, canAnimate, isGenerating, isRecropping, isFailed, isPlaying, disabled, onTap, onRedoClip, onDeleteClip, onDeletePicture, onRecrop, onRedraw }: {
  asset: Asset;
  speaker: string | null;
  perClip: number;
  canAnimate: boolean;
  isGenerating: boolean;
  isRecropping: boolean;
  isFailed: boolean;
  isPlaying: boolean;
  disabled: boolean;
  onTap: () => void;
  onRedoClip: () => void;
  onDeleteClip: () => void;
  onDeletePicture: () => void;
  onRecrop: () => void;
  onRedraw: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hasClip = Boolean(asset.video_clip_url);
  const badCrop = (asset.extraction_flags?.length ?? 0) > 0;
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  // Per-clip motion prompt: edit before animating. Saved to assets.video_prompt,
  // which the clip stage reads — so this override drives the next animate.
  const [prompt, setPrompt] = useState(asset.video_prompt || "");
  const [promptState, setPromptState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [imgPrompt, setImgPrompt] = useState(asset.image_prompt || "");
  const [imgState, setImgState] = useState<"idle" | "saving" | "error">("idle");
  // "✨ Improve": the prompt studio's model-aware rewrite fills the box — the
  // creator reviews and saves; nothing is applied automatically.
  const [improving, setImproving] = useState<"" | "image" | "motion">("");
  const improve = async (surface: "image" | "motion") => {
    setImproving(surface);
    try {
      const res = await improvePrompt(asset.video_id, surface, surface === "image" ? imgPrompt : prompt);
      if (surface === "image") { setImgPrompt(res.prompt); setImgState("idle"); }
      else { setPrompt(res.prompt); setPromptState("idle"); }
    } catch { /* leave the box as-is */ }
    setImproving("");
  };

  // useState only seeds on mount, so when the server value changes under an open
  // page (e.g. coverage just rewrote the motion prompt) the box kept showing its
  // stale/empty initial text. Re-sync from the asset when the SAVED value changes,
  // unless a save is mid-flight (don't clobber what the user is writing).
  const serverPrompt = asset.video_prompt || "";
  const serverImgPrompt = asset.image_prompt || "";
  useEffect(() => {
    if (promptState !== "saving") setPrompt(serverPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverPrompt]);
  useEffect(() => {
    if (imgState !== "saving") setImgPrompt(serverImgPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverImgPrompt]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isPlaying) v.play().catch(() => undefined);
    else { v.pause(); v.currentTime = 0; }
  }, [isPlaying]);

  return (
    <GlassCard
      className={`p-0 overflow-hidden group ${hasClip || canAnimate ? "cursor-pointer" : "cursor-default"}`}
      style={isFailed ? { border: "1px solid rgba(255,90,90,0.5)" }
        : badCrop ? { border: "1px solid rgba(255,110,110,0.45)" } : undefined}
      onClick={onTap}
    >
      <div className="aspect-video relative flex items-center justify-center" style={{ background: "var(--bg-elevated)" }}>
        {hasClip ? (
          <video
            ref={videoRef}
            src={toDisplayImageUrl(asset.video_clip_url) ?? undefined}
            poster={toDisplayImageUrl(asset.image_url) ?? undefined}
            preload="none"
            playsInline
            loop
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          asset.image_url && (
            <img
              src={toDisplayImageUrl(asset.image_url)}
              alt={label}
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover"
              style={{ opacity: isGenerating || isRecropping ? 0.4 : 0.85 }}
            />
          )
        )}

        {/* Dialogue badge — this picture will SPEAK */}
        {speaker && (
          <span className="absolute top-2 left-2 z-10 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium"
            style={{ background: "rgba(0,0,0,0.55)", color: "var(--turquoise)", backdropFilter: "blur(4px)" }}>
            <MessageCircle size={10} /> {speaker}
          </span>
        )}

        {/* Bad crop badge — one tap fixes it for free */}
        {badCrop && !isGenerating && !isRecropping && (
          <button
            onClick={(e) => { e.stopPropagation(); onRecrop(); }}
            disabled={disabled}
            title="This picture was cut wrong from its storyboard. Re-crop it for free — a clip on it re-animates automatically (~$0.10)."
            className="absolute bottom-2 left-2 z-20 inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold transition-all hover:brightness-125 disabled:opacity-50"
            style={{ background: "rgba(220, 50, 50, 0.92)", color: "white" }}>
            <Scissors size={10} /> Bad crop — fix it
          </button>
        )}

        {/* State overlays */}
        {(isGenerating || isRecropping) && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2">
            <Loader2 size={22} className="animate-spin" style={{ color: "var(--purple)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
              {isRecropping ? "Re-cropping…" : "Bringing it to life…"}
            </span>
          </div>
        )}
        {isFailed && !isGenerating && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2" style={{ background: "rgba(40,0,0,0.45)" }}>
            <AlertTriangle size={18} style={{ color: "rgb(255,120,120)" }} />
            <span className="px-2 py-1 rounded-md text-[11px] font-semibold" style={{ background: "rgba(255,90,90,0.9)", color: "white" }}>
              Try again
            </span>
          </div>
        )}
        {canAnimate && !hasClip && !isGenerating && !isRecropping && !isFailed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.45)" }}>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
              <Play size={12} /> Animate · ${perClip.toFixed(2)}
            </span>
          </div>
        )}
        {hasClip && !isPlaying && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.35)" }}>
            <Play size={28} style={{ color: "white" }} />
          </div>
        )}
        {hasClip && isPlaying && (
          <div className="absolute bottom-2 right-2 z-10">
            <Pause size={16} style={{ color: "white", opacity: 0.8 }} />
          </div>
        )}

        {/* Hover actions: clip level when a clip exists, picture level otherwise */}
        {!isGenerating && !isRecropping && (
          <>
            <div className="absolute top-2 right-2 z-20 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {asset.image_url && (
                <a
                  href={`${asset.image_url}${asset.image_url.includes("?") ? "&" : "?"}download=${label}.png`}
                  download={`${label}.png`}
                  onClick={(e) => e.stopPropagation()}
                  title="Download this picture"
                  className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                  style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}>
                  <Download size={13} />
                </a>
              )}
              {hasClip ? (
                <>
                  <button
                    onClick={(e) => { e.stopPropagation(); onRedoClip(); }}
                    title={`Redo this clip · $${perClip.toFixed(2)}`}
                    className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                    style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}>
                    <RotateCcw size={13} />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDeleteClip(); }}
                    title="Remove this clip (keeps the picture)"
                    className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                    style={{ background: "rgba(0,0,0,0.6)", color: "rgb(255,120,120)" }}>
                    <X size={13} />
                  </button>
                </>
              ) : (
                <button
                  onClick={(e) => { e.stopPropagation(); onDeletePicture(); }}
                  title="Remove this picture (the storyboard stays — re-extract to refill)"
                  className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                  style={{ background: "rgba(0,0,0,0.6)", color: "rgb(255,120,120)" }}>
                  <X size={13} />
                </button>
              )}
            </div>
            {hasClip && (
              <div className="absolute top-2 right-2 z-10 w-7 h-7 rounded-full flex items-center justify-center group-hover:opacity-0 transition-opacity"
                style={{ background: "rgba(0, 230, 138, 0.2)", color: "var(--green)" }}>
                <Check size={14} />
              </div>
            )}
          </>
        )}
      </div>

      <div className="p-3">
        <div className="flex items-center gap-2 mb-1.5">
          <SegmentBadge label={label} />
        </div>
        <p className="text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--text-secondary)" }}>
          {asset.sentence_text || asset.video_prompt || "—"}
        </p>
        {/* Image prompt — edit + redraw just this picture (anchored on the locked cast). */}
        <details className="mt-2" onClick={(e) => e.stopPropagation()}>
          <summary className="text-[10px] cursor-pointer select-none inline-flex items-center gap-1" style={{ color: "var(--text-tertiary)" }}>
            <ImageIcon size={10} /> Image prompt — edit &amp; redraw
          </summary>
          <textarea
            value={imgPrompt}
            onChange={(e) => { setImgPrompt(e.target.value); setImgState("idle"); }}
            onClick={(e) => e.stopPropagation()}
            rows={4}
            placeholder="Describe this picture. Redraw keeps your locked characters."
            className="w-full mt-1.5 text-[11px] rounded-lg p-2 outline-none resize-y"
            style={{ background: "var(--bg-void)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,0.12)" }}
          />
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              onClick={async (e) => {
                e.stopPropagation();
                setImgState("saving");
                try { await updateImagePrompt(asset.id, imgPrompt); onRedraw(); setImgState("idle"); }
                catch { setImgState("error"); }
              }}
              disabled={imgState === "saving"}
              className="inline-flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}>
              <RotateCcw size={11} /> {imgState === "saving" ? "Starting…" : imgState === "error" ? "Failed — retry" : "Redraw picture · ~$0.08"}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); improve("image"); }}
              disabled={improving !== ""}
              title="AI rewrites this prompt to be stronger — review it, then redraw."
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
              {improving === "image" ? "Improving…" : "✨ Improve"}
            </button>
          </div>
        </details>
        {/* Motion prompt — click to fine-tune how this shot moves before animating.
            stopPropagation so editing never triggers the card's tap-to-animate. */}
        <details className="mt-2" onClick={(e) => e.stopPropagation()}>
          <summary className="text-[10px] cursor-pointer select-none inline-flex items-center gap-1" style={{ color: "var(--text-tertiary)" }}>
            <Film size={10} /> Motion prompt{hasClip ? "" : " — edit before animating"}
          </summary>
          <textarea
            value={prompt}
            onChange={(e) => { setPrompt(e.target.value); setPromptState("idle"); }}
            onClick={(e) => e.stopPropagation()}
            rows={4}
            placeholder="How should this shot move? Leave blank to auto-write it."
            className="w-full mt-1.5 text-[11px] rounded-lg p-2 outline-none resize-y"
            style={{ background: "var(--bg-void)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,0.12)" }}
          />
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              onClick={async (e) => {
                e.stopPropagation();
                setPromptState("saving");
                try { await updateVideoPrompt(asset.id, prompt); setPromptState("saved"); }
                catch { setPromptState("error"); }
              }}
              disabled={promptState === "saving"}
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
              {promptState === "saving" ? "Saving…" : promptState === "saved" ? "Saved ✓" : promptState === "error" ? "Failed — retry" : "Save prompt"}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); improve("motion"); }}
              disabled={improving !== ""}
              title="AI rewrites this motion prompt to be stronger — review it, then save."
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
              {improving === "motion" ? "Improving…" : "✨ Improve"}
            </button>
          </div>
        </details>
      </div>
    </GlassCard>
  );
}
