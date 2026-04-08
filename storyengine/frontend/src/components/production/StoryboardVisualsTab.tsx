"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  Play, Pause, Check, Loader2, Pencil, Image as ImageIcon, RefreshCw, Trash2, AlertTriangle,
  Lock, ArrowLeft, ToggleLeft, ToggleRight, Layers, Scissors, X, ChevronRight,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { ActionButton } from "@/components/ui/ActionButton";
import { PromptExpander } from "@/components/video-detail/prompt-expander";
import { VoicePlayer } from "@/components/video-detail/voice-player";
import {
  getVideoScript, getVideoAssets, updateStoryboardMode, clearSceneStoryboard, clearAllStoryboards,
  clearAllExtractedPanels, clearExtractedPanel, uploadStoryboardGrid,
  runPipelineStage, updateSceneSegments, runImageForSegment, runImageVariants, clearStaleTask, updateVideoStyles,
  getAudioToken, advanceVideo,
} from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { VideoDetail, ScriptScene as ApiScriptScene, Asset } from "@/lib/api";

/** Fetches a short-lived audio token, then renders VoicePlayer with scoped URL */
function SecureAudioPlayer({ videoId, scene }: { videoId: string; scene: number }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const apiBase = typeof window !== "undefined"
      ? (localStorage.getItem("storyengine_api_url") || `${window.location.protocol}//${window.location.hostname}:8001`)
      : "";
    getAudioToken(videoId).then(({ token }) => {
      if (!cancelled) setAudioUrl(`${apiBase}/api/videos/${videoId}/audio/${scene}?token=${token}`);
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => { cancelled = true; };
  }, [videoId, scene]);
  if (failed) return null;
  if (!audioUrl) return <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>Loading audio...</p>;
  return <div className="mb-3"><VoicePlayer audioUrl={audioUrl} /></div>;
}

interface StoryboardVisualsTabProps {
  video: VideoDetail & { id: string };
  onGoToScriptVoice?: () => void;
  onAdvanced?: () => void;
}

const STATUS_ICON: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  done: { icon: <Check size={10} />, color: "var(--green)", label: "Generated" },
  generating: { icon: <Loader2 size={10} className="animate-spin" />, color: "var(--purple)", label: "Generating" },
  pending: { icon: <ImageIcon size={10} />, color: "var(--text-tertiary)", label: "Pending" },
};

interface VisualSegment {
  id: string;
  segmentId: string;
  sentenceText: string;
  imagePrompt: string;
  imageUrl: string | undefined;
  status: "pending" | "generating" | "done";
  sceneNumber: number;
  imageIndex: number;
}

interface SceneGroup {
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  duration: string;
  voiceOverUrl: string | null;
  storyboardPrompt: string | null;
  storyboardBeats: Array<{
    beatNumber: number;
    prompt: string;
    gridUrl: string | null;
  }>;
  storyboardStatus: string | null;
  storyboardBeatCount: number | null;
  storyboardGridCount: number;
  hasStoryboardPrompt: boolean;
  hasStoryboardData: boolean;
  segments: VisualSegment[];
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

export function StoryboardVisualsTab({ video, onGoToScriptVoice, onAdvanced }: StoryboardVisualsTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();

  // --- Voice guard rail check ---
  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const hasVoice = useMemo(() => {
    if (!scriptScenes) return false;
    return scriptScenes.some((scene) => !!scene.voice_over_url);
  }, [scriptScenes]);

  // --- Storyboard mode toggle ---
  const [storyboardMode, setStoryboardMode] = useState(false);
  const [togglingStoryboard, setTogglingStoryboard] = useState(false);

  useEffect(() => {
    if (scriptScenes && scriptScenes.length > 0) {
      const anyOn = scriptScenes.some((s) => s.storyboard_on_off === "On");
      setStoryboardMode(anyOn);
    }
  }, [scriptScenes]);

  const handleToggleStoryboard = useCallback(async () => {
    setTogglingStoryboard(true);
    try {
      const newMode = !storyboardMode;
      await updateStoryboardMode(video.id, newMode);
      setStoryboardMode(newMode);
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } finally {
      setTogglingStoryboard(false);
    }
  }, [storyboardMode, video.id, queryClient]);

  // --- Compute scene groups ---
  const computedScenes = useMemo<SceneGroup[]>(() => {
    if (!scriptScenes || !assets) return [];
    const totalScenes = scriptScenes.length;
    return scriptScenes.map((scene) => {
      const storyboardGridUrls = [
        scene.storyboard_1_url || null,
        scene.storyboard_2_url || null,
        scene.storyboard_3_url || null,
        scene.storyboard_4_url || null,
        scene.storyboard_5_url || null,
      ];
      const storyboardBeats = parseStoryboardPromptBlocks(scene.storyboard_prompts).map((beat) => ({
        ...beat,
        gridUrl: storyboardGridUrls[beat.beatNumber - 1] || null,
      }));

      return {
        sceneNumber: scene.scene || 0,
        actNumber: Math.ceil((scene.scene || 1) / Math.ceil(totalScenes / 6)),
        narrationText: scene.scene_text || "",
        duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
        voiceOverUrl: scene.voice_over_url || null,
        storyboardPrompt: scene.storyboard_prompts || null,
        storyboardBeats,
        storyboardStatus: scene.storyboard_status || null,
        storyboardBeatCount: scene.storyboard_beat_count ?? (storyboardBeats.length || null),
        storyboardGridCount: storyboardGridUrls.filter(Boolean).length,
        hasStoryboardPrompt: !!scene.storyboard_prompts,
        hasStoryboardData: !!(
          scene.storyboard_prompts ||
          scene.storyboard_status ||
          scene.storyboard_beat_count != null ||
          scene.storyboard_1_url ||
          scene.storyboard_2_url ||
          scene.storyboard_3_url
        ),
        segments: assets
          .filter((a) => a.scene === scene.scene)
          .sort((a, b) => (a.image_index || 0) - (b.image_index || 0))
          .map((asset) => ({
            id: asset.id,
            segmentId: `S-${String(asset.scene || 0).padStart(2, "0")}.${asset.image_index || 0}`,
            sentenceText: asset.sentence_text || "",
            imagePrompt: asset.image_prompt || "",
            imageUrl: asset.image_url || undefined,
            status: (asset.status === "approved" || asset.status === "Done" || asset.image_url)
              ? ("done" as const)
              : ("pending" as const),
            sceneNumber: asset.scene || 0,
            imageIndex: asset.image_index || 0,
          })),
      };
    });
  }, [scriptScenes, assets]);

  const [scenes, setScenes] = useState<SceneGroup[]>([]);
  const [regeneratingSegment, setRegeneratingSegment] = useState<string | null>(null);
  const [variantsSegment, setVariantsSegment] = useState<string | null>(null);
  const [generatingAll, setGeneratingAll] = useState(false);
  const [generatingPrompts, setGeneratingPrompts] = useState(false);
  const [model, setModel] = useState(video.image_model_override || "nano-banana-2");
  const [savingModel, setSavingModel] = useState(false);
  const [taskRunning, setTaskRunning] = useState(false);
  const [generatingScene, setGeneratingScene] = useState<number | null>(null);
  const [clearingScene, setClearingScene] = useState<number | null>(null);
  const [clearingAllStoryboards, setClearingAllStoryboards] = useState(false);
  const [clearingExtracted, setClearingExtracted] = useState(false);
  const [uploadingGrid, setUploadingGrid] = useState<string | null>(null); // "scene-beat"
  const [dragOver, setDragOver] = useState<string | null>(null);

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onProgress: () => {
      // Refresh assets on every poll tick so extracted panels appear live
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onComplete: () => {
      setTaskRunning(false);
      setGeneratingAll(false);
      setGeneratingPrompts(false);
      setGeneratingScene(null);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setGeneratingAll(false);
      setGeneratingPrompts(false);
      setGeneratingScene(null);
      toast.error(`Generation failed: ${error}`);
    },
  });

  useEffect(() => {
    if (computedScenes.length === 0) {
      setScenes([]);
      return;
    }

    setScenes((prev) =>
      computedScenes.map((scene) => {
        const existingScene = prev.find((s) => s.sceneNumber === scene.sceneNumber);
        if (!existingScene) return scene;

        return {
          ...scene,
          segments: scene.segments.map((seg) => {
            const existingSeg = existingScene.segments.find((s) => s.id === seg.id);
            return existingSeg
              ? { ...seg, imagePrompt: existingSeg.imagePrompt }
              : seg;
          }),
        };
      }),
    );
  }, [computedScenes]);

  useEffect(() => {
    setModel(video.image_model_override || "nano-banana-2");
  }, [video.image_model_override]);

  const totalSegments = scenes.reduce((sum, s) => sum + s.segments.length, 0);
  const doneSegments = scenes.reduce(
    (sum, s) => sum + s.segments.filter((seg) => seg.status === "done").length,
    0,
  );
  const promptReadySegments = scenes.reduce(
    (sum, s) => sum + s.segments.filter((seg) => seg.imagePrompt.trim().length > 0).length,
    0,
  );
  const storyboardPromptScenes = scenes.filter((s) => s.hasStoryboardPrompt).length;
  const storyboardReadyScenes = scenes.filter((s) => !!s.storyboardStatus).length;
  const storyboardGridsDone = scenes.length > 0 && scenes.every((s) => s.storyboardGridCount >= (s.storyboardBeatCount || 1));
  const storyboardScenesWithData = scenes.filter((s) => s.hasStoryboardData).length;
  const extractedSegments = scenes.reduce(
    (sum, s) => sum + s.segments.filter((seg) => !!seg.imageUrl).length,
    0,
  );
  const upscaledSegments = scenes.reduce(
    (sum, s) => sum + s.segments.filter((seg) => seg.imageUrl?.includes("_hd")).length,
    0,
  );
  const needsUpscale = extractedSegments > 0 && (extractedSegments - upscaledSegments) > 2;
  const pendingSegments = totalSegments - doneSegments;
  const missingPromptSegments = totalSegments - promptReadySegments;
  const hasStoryBible = !!(video.story_bible && video.story_bible.trim().length > 0);
  const storyboardPrereqsMet = totalSegments > 0 && missingPromptSegments === 0;
  const estimatedCostDone = doneSegments * 0.025;
  const estimatedCostTotal = totalSegments * 0.025;

  const updatePrompt = (segId: string, newPrompt: string) => {
    setScenes((prev) =>
      prev.map((scene) => ({
        ...scene,
        segments: scene.segments.map((seg) =>
          seg.id === segId ? { ...seg, imagePrompt: newPrompt } : seg,
        ),
      })),
    );
  };

  const persistSegment = useCallback(async (segId: string) => {
    const scene = scenes.find((s) => s.segments.some((seg) => seg.id === segId));
    if (!scene) return;
    const updatedSegments = scene.segments.map((seg) => ({
      image_index: seg.imageIndex,
      sentence_text: seg.sentenceText,
    }));
    try {
      await updateSceneSegments(video.id, scene.sceneNumber, updatedSegments);
    } catch {
      // silent
    }
  }, [scenes, video.id]);

  const handleRegenerate = useCallback(async (seg: VisualSegment) => {
    setRegeneratingSegment(seg.id);
    try {
      await runImageForSegment(video.id, seg.sceneNumber, seg.imageIndex);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setRegeneratingSegment(null);
    }
  }, [video.id, queryClient]);

  const handleGenerateVariants = useCallback(async (seg: VisualSegment) => {
    setVariantsSegment(seg.id);
    try {
      await runImageVariants(video.id, seg.sceneNumber, seg.imageIndex, 3);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setVariantsSegment(null);
    }
  }, [video.id, queryClient]);

  const handleClearSceneStoryboard = useCallback(async (sceneNumber: number) => {
    const confirmed = window.confirm(`Clear storyboard prompts and storyboard grids for Scene ${sceneNumber}?`);
    if (!confirmed) return;

    setClearingScene(sceneNumber);
    try {
      await clearSceneStoryboard(video.id, sceneNumber);
      setScenes((prev) =>
        prev.map((scene) =>
          scene.sceneNumber === sceneNumber
            ? {
                ...scene,
                storyboardPrompt: null,
                storyboardStatus: null,
                storyboardBeatCount: null,
                storyboardGridCount: 0,
                hasStoryboardPrompt: false,
                hasStoryboardData: false,
              }
            : scene,
        ),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-script", video.id] }),
        queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
      ]);
    } finally {
      setClearingScene(null);
    }
  }, [video.id, queryClient]);

  const handleClearAllStoryboards = useCallback(async () => {
    const confirmed = window.confirm(
      "Clear all storyboard prompts and storyboard grids for this video? This will keep your sentence image prompts intact.",
    );
    if (!confirmed) return;

    setClearingAllStoryboards(true);
    try {
      await clearAllStoryboards(video.id);
      setScenes((prev) =>
        prev.map((scene) => ({
          ...scene,
          storyboardPrompt: null,
          storyboardStatus: null,
          storyboardBeatCount: null,
          storyboardGridCount: 0,
          hasStoryboardPrompt: false,
          hasStoryboardData: false,
        })),
      );
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-script", video.id] }),
        queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
      ]);
    } finally {
      setClearingAllStoryboards(false);
    }
  }, [video.id, queryClient]);

  const handleClearAllExtracted = useCallback(async () => {
    const confirmed = window.confirm("Clear all extracted panel images? The segment rows and prompts will be preserved.");
    if (!confirmed) return;

    setClearingExtracted(true);
    try {
      await clearAllExtractedPanels(video.id);
      setScenes((prev) =>
        prev.map((scene) => ({
          ...scene,
          segments: scene.segments.map((seg) =>
            seg.status === "done" ? { ...seg, imageUrl: undefined, status: "pending" } : seg,
          ),
        })),
      );
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setClearingExtracted(false);
    }
  }, [video.id, queryClient]);

  const handleGridDrop = useCallback(async (sceneNumber: number, beatNumber: number, file: File) => {
    const key = `${sceneNumber}-${beatNumber}`;
    setUploadingGrid(key);
    try {
      const result = await uploadStoryboardGrid(video.id, sceneNumber, beatNumber, file);
      // Update local state with new grid URL
      setScenes((prev) =>
        prev.map((scene) => {
          if (scene.sceneNumber !== sceneNumber) return scene;
          return {
            ...scene,
            storyboardGridCount: scene.storyboardGridCount + 1,
            hasStoryboardData: true,
            storyboardStatus: result.all_grids_complete ? "grids_generated" : scene.storyboardStatus,
            storyboardBeats: scene.storyboardBeats.map((b) =>
              b.beatNumber === beatNumber ? { ...b, gridUrl: result.url } : b,
            ),
          };
        }),
      );
      await queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch {
      // silent
    } finally {
      setUploadingGrid(null);
      setDragOver(null);
    }
  }, [video.id, queryClient]);

  const handleClearExtractedPanel = useCallback(async (assetId: string) => {
    try {
      await clearExtractedPanel(video.id, assetId);
      setScenes((prev) =>
        prev.map((scene) => ({
          ...scene,
          segments: scene.segments.map((seg) =>
            seg.id === assetId ? { ...seg, imageUrl: undefined, status: "pending" } : seg,
          ),
        })),
      );
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch {
      // silent
    }
  }, [video.id, queryClient]);

  const runStageWith409Retry = useCallback(async (stage: string, params?: Record<string, string | number>) => {
    try {
      await runPipelineStage(video.id, stage, params);
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, stage, params);
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          throw retryErr;
        }
      }
      throw err;
    }
  }, [video.id]);

  const handleGenerateAllPrompts = useCallback(async () => {
    setGeneratingPrompts(true);
    const stage = storyboardMode
      ? (!hasStoryBible ? "story-bible" : (storyboardPrereqsMet ? "storyboards" : "prompts"))
      : "prompts";
    const label =
      stage === "story-bible"
        ? "Story Bible generation"
        : stage === "storyboards"
          ? "Storyboard prompt generation"
          : "Image prompt generation";
    try {
      await runStageWith409Retry(stage);
    } catch (err: unknown) {
      toast.error(`${label} failed: ${(err as Error).message}`);
      setGeneratingPrompts(false);
    }
  }, [runStageWith409Retry, storyboardMode, storyboardPrereqsMet, hasStoryBible]);

  const handleGenerateAllImages = useCallback(async () => {
    setGeneratingAll(true);
    const stage = storyboardMode ? "storyboard-images" : "images";
    const label = storyboardMode ? "Storyboard grid generation" : "Image generation";
    try {
      await runStageWith409Retry(stage);
    } catch (err: unknown) {
      toast.error(`${label} failed: ${(err as Error).message}`);
      setGeneratingAll(false);
    }
  }, [runStageWith409Retry, storyboardMode]);

  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const handleExtractPanels = useCallback(async () => {
    setExtracting(true);
    setExtractError(null);
    try {
      // Clear any stale task first
      try { await clearStaleTask(video.id); } catch { /* ok if no stale task */ }
      await runPipelineStage(video.id, "storyboard-extract");
      setTaskRunning(true);
    } catch (err: unknown) {
      const msg = (err as Error).message || "Unknown error";
      console.error("Extract panels failed:", msg);
      setExtractError(msg);
      setExtracting(false);
    }
  }, [video.id]);

  const handleUpscalePanels = useCallback(async () => {
    setExtracting(true);
    setExtractError(null);
    try {
      try { await clearStaleTask(video.id); } catch { /* ok */ }
      await runPipelineStage(video.id, "upscale-panels");
      setTaskRunning(true);
    } catch (err: unknown) {
      const msg = (err as Error).message || "Unknown error";
      console.error("Upscale panels failed:", msg);
      setExtractError(msg);
      setExtracting(false);
    }
  }, [video.id]);

  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

  const handleGenerateScenePrompts = useCallback(async (sceneNumber: number) => {
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboards", { scene: sceneNumber });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Scene ${sceneNumber} prompt generation failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry]);

  const handleGenerateSceneGrids = useCallback(async (sceneNumber: number) => {
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Scene ${sceneNumber} grid generation failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry]);

  const handleModelChange = useCallback(async (nextModel: string) => {
    setModel(nextModel);
    setSavingModel(true);
    try {
      await updateVideoStyles(video.id, { image_model_override: nextModel });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error(`Failed to update image model: ${(err as Error).message}`);
      setModel(video.image_model_override || "nano-banana-2");
    } finally {
      setSavingModel(false);
    }
  }, [queryClient, video.id, video.image_model_override]);

  // Group by act
  const actGroups = scenes.reduce<Record<number, SceneGroup[]>>((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {});

  // --- Loading state ---
  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--purple)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading visuals...</span>
      </div>
    );
  }

  // --- Voice guard rail ---
  if (!hasVoice) {
    return (
      <GlassCard className="p-10 text-center max-w-lg mx-auto">
        <div
          className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4"
          style={{ background: "rgba(255, 165, 0, 0.12)", border: "1px solid rgba(255, 165, 0, 0.25)" }}
        >
          <Lock size={20} style={{ color: "var(--orange)" }} />
        </div>
        <h3
          className="text-lg font-display font-semibold mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          Voice Required
        </h3>
        <p
          className="text-sm leading-relaxed mb-6"
          style={{ color: "var(--text-secondary)" }}
        >
          Voice must be generated before visuals. Voice audio timing drives image
          segmentation — without it, images will be incorrectly timed.
        </p>
        {onGoToScriptVoice && (
          <button
            onClick={onGoToScriptVoice}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
            style={{
              background: "var(--purple)",
              color: "var(--bg-void)",
            }}
          >
            <ArrowLeft size={14} />
            Go to Script &amp; Voice
          </button>
        )}
      </GlassCard>
    );
  }

  // --- Empty state ---
  if (scenes.length === 0) {
    return (
      <div className="space-y-4">
        {/* Storyboard toggle even in empty state */}
        <StoryboardToggle
          enabled={storyboardMode}
          toggling={togglingStoryboard}
          onToggle={handleToggleStoryboard}
        />
        <GlassCard className="p-12 text-center">
          <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
          <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>No Visual Segments Yet</p>
          <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
            Generate image prompts first, then generate images. Current stage: <span style={{ color: "var(--purple)" }}>{(video.status || "").replace(/_/g, " ")}</span>
          </p>
          <div className="flex items-center justify-center gap-3">
            <button
              onClick={handleGenerateAllPrompts}
              disabled={generatingPrompts || taskRunning}
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-base font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
              style={{ background: "var(--purple)", color: "var(--bg-void)" }}
            >
              {(generatingPrompts || taskRunning) ? <Loader2 size={18} className="animate-spin" /> : <Pencil size={18} />}
              {taskRunning
                ? (taskMessage || "Generating Prompts...")
                : generatingPrompts
                  ? "Starting..."
                  : storyboardMode
                    ? (!hasStoryBible ? "Generate Story Bible First" : (storyboardPrereqsMet ? "Generate Storyboard Prompts" : "Generate Image Prompts First"))
                    : "Generate All Image Prompts"}
            </button>
            <button
              onClick={handleGenerateAllImages}
              disabled={generatingAll || taskRunning || (storyboardMode ? (!storyboardPrereqsMet || storyboardPromptScenes === 0) : false)}
              className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-base font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}
            >
              {(generatingAll || taskRunning) ? <Loader2 size={18} className="animate-spin" /> : <ImageIcon size={18} />}
              {taskRunning ? (taskMessage || (storyboardMode ? "Generating Storyboard Grids..." : "Generating Images...")) : generatingAll ? "Starting..." : (storyboardMode ? "Generate Storyboard Grids" : "Generate All Images")}
            </button>
          </div>
        </GlassCard>
      </div>
    );
  }

  // --- Full visuals workflow ---
  return (
    <div className="space-y-4">
      {/* Storyboard mode toggle */}
      <StoryboardToggle
        enabled={storyboardMode}
        toggling={togglingStoryboard}
        onToggle={handleToggleStoryboard}
      />

      {/* Top action bar — all controls visible without scrolling */}
      {scenes.length > 0 && (
        <div
          className="rounded-xl px-4 py-3"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
        >
          {/* Status row */}
          <div className="flex items-center gap-4 text-[10px] font-mono mb-3" style={{ color: "var(--text-tertiary)" }}>
            <span>Prompts <strong style={{ color: promptReadySegments >= totalSegments ? "var(--green)" : "var(--text-secondary)" }}>{promptReadySegments}/{totalSegments}</strong></span>
            {storyboardMode && <>
              <span>Grids <strong style={{ color: storyboardGridsDone ? "var(--green)" : "var(--text-secondary)" }}>{storyboardReadyScenes}/{scenes.length}</strong></span>
              <span>Extracted <strong style={{ color: extractedSegments >= totalSegments && totalSegments > 0 ? "var(--green)" : "var(--text-secondary)" }}>{extractedSegments}/{totalSegments}</strong></span>
              {upscaledSegments > 0 && (
                <span>Upscaled <strong style={{ color: "var(--text-secondary)" }}>{upscaledSegments}/{extractedSegments}</strong></span>
              )}
            </>}
            <span>Cost <strong style={{ color: "var(--gold)" }}>${estimatedCostDone.toFixed(2)}</strong></span>
            <span>Bible <strong style={{ color: hasStoryBible ? "var(--green)" : "var(--orange)" }}>{hasStoryBible ? "Ready" : "Missing"}</strong></span>
            <span>Style <strong style={{ color: "var(--text-secondary)" }}>{video.visual_style || "default"}</strong></span>
            <span>
              <select
                value={model}
                onChange={(e) => handleModelChange(e.target.value)}
                disabled={savingModel}
                className="bg-transparent text-[10px] font-mono border rounded px-1 py-0.5 cursor-pointer"
                style={{ color: "var(--text-secondary)", borderColor: "rgba(255,255,255,0.1)" }}
              >
                <option value="nano-banana-2">Nano Banana 2</option>
                <option value="z-image">Z Image</option>
              </select>
            </span>
          </div>
          {/* Action buttons row */}
          <div className="flex items-center gap-2 flex-wrap">
            <button onClick={handleGenerateAllPrompts}
              disabled={generatingPrompts || generatingAll || taskRunning}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
              style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
              {(generatingPrompts || taskRunning) ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Pencil size={12} className="inline mr-1" />}
              {storyboardMode
                ? (!hasStoryBible ? "Story Bible" : (storyboardPrereqsMet ? "Storyboard Prompts" : "Image Prompts"))
                : "Image Prompts"}
            </button>
            <button onClick={handleGenerateAllImages}
              disabled={generatingAll || generatingPrompts || taskRunning || (storyboardMode ? (!hasStoryBible || !storyboardPrereqsMet || storyboardPromptScenes === 0) : pendingSegments === 0)}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
              style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
              {(generatingAll || taskRunning) ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <ImageIcon size={12} className="inline mr-1" />}
              {storyboardMode ? "Storyboard Grids" : `Images (${pendingSegments})`}
            </button>
            {storyboardMode && (
              <>
                <button onClick={handleExtractPanels}
                  disabled={extracting || taskRunning || (extractedSegments >= totalSegments && totalSegments > 0)}
                  className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
                  style={{ background: "var(--green)", color: "var(--bg-void)" }}>
                  {(extracting || taskRunning) ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Scissors size={12} className="inline mr-1" />}
                  Extract
                </button>
                {extractedSegments > 0 && (
                  <button onClick={handleUpscalePanels}
                    disabled={extracting || taskRunning || !needsUpscale}
                    className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
                    style={{ background: "var(--amber, #D4A844)", color: "var(--bg-void)" }}>
                    Upscale ({upscaledSegments}/{extractedSegments})
                  </button>
                )}
              </>
            )}
            <button onClick={handleClearAllStoryboards}
              disabled={taskRunning || clearingAllStoryboards || storyboardScenesWithData === 0}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold disabled:opacity-40 transition-all hover:brightness-110"
              style={{ background: "rgba(255,107,71,0.15)", color: "#FF8A65", border: "1px solid rgba(255,107,71,0.25)" }}>
              {clearingAllStoryboards ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Trash2 size={12} className="inline mr-1" />}
              Reset
            </button>
            <div className="flex-1" />
            <button
              onClick={handleAdvanceStage}
              disabled={advancing}
              className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
              Advance Stage <ChevronRight size={12} />
            </button>
          </div>
        </div>
      )}

      {/* Storyboard pipeline steps */}
      {storyboardMode && (
        <div
          className="rounded-xl p-4"
          style={{ background: "rgba(168, 85, 247, 0.04)", border: "1px solid rgba(168, 85, 247, 0.12)" }}
        >
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--purple)" }}>
              Storyboard Pipeline
            </span>
          </div>
          <div className="flex items-center gap-0">
            {(() => {
              // Derive step completion from downstream state — if grids exist, prompts must be done
              const sbPromptsDone = storyboardPromptScenes >= scenes.length && scenes.length > 0;
              const sbGridsComplete = storyboardGridsDone;
              const extractionDone = totalSegments > 0 && extractedSegments >= totalSegments;
              const promptsDone = (promptReadySegments >= totalSegments && totalSegments > 0) || sbPromptsDone;
              return [
                { label: "Image Prompts", done: promptsDone, count: `${promptReadySegments}/${totalSegments}` },
                { label: "Storyboard Prompts", done: sbPromptsDone, count: `${storyboardPromptScenes}/${scenes.length}` },
                { label: "Storyboard Grids", done: sbGridsComplete, count: `${storyboardReadyScenes}/${scenes.length}` },
                { label: "Extract Panels", done: extractionDone, count: `${extractedSegments}/${totalSegments}` },
            ];
            })().map((step, i, arr) => {
              const isNext = !step.done && (i === 0 || arr[i - 1].done);
              return (
                <div key={step.label} className="flex items-center gap-0 flex-1">
                  <div className="flex flex-col items-center flex-1">
                    <div
                      className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold mb-1"
                      style={{
                        background: step.done ? "var(--green)" : isNext ? "var(--purple)" : "rgba(255,255,255,0.06)",
                        color: step.done || isNext ? "var(--bg-void)" : "var(--text-tertiary)",
                        border: isNext ? "2px solid var(--purple)" : "none",
                      }}
                    >
                      {step.done ? "✓" : i + 1}
                    </div>
                    <span className="text-[9px] font-medium" style={{ color: step.done ? "var(--green)" : isNext ? "var(--purple)" : "var(--text-tertiary)" }}>
                      {step.label}
                    </span>
                    <span className="text-[8px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                      {step.count}
                    </span>
                  </div>
                  {i < arr.length - 1 && (
                    <div className="w-8 h-px mx-1" style={{ background: step.done ? "var(--green)" : "rgba(255,255,255,0.1)" }} />
                  )}
                </div>
              );
            })}
          </div>
          {/* Next action CTA */}
          {(() => {
            // Derive from storyboard state — if grids exist, earlier steps are done
            const sbPromptsDone = storyboardPromptScenes >= scenes.length && scenes.length > 0;
            const sbGridsAllDone = storyboardGridsDone;
            const promptsDone = (promptReadySegments >= totalSegments && totalSegments > 0) || sbPromptsDone;
            const extractionDone = totalSegments > 0 && extractedSegments >= totalSegments;

            if (!promptsDone) return (
              <button
                onClick={handleGenerateAllPrompts}
                disabled={generatingPrompts || taskRunning}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--purple)", color: "var(--bg-void)" }}
              >
                {(generatingPrompts || taskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                Step 1: Generate Image Prompts
              </button>
            );
            if (!sbPromptsDone) return (
              <button
                onClick={handleGenerateAllPrompts}
                disabled={generatingPrompts || taskRunning}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--purple)", color: "var(--bg-void)" }}
              >
                {(generatingPrompts || taskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                Step 2: Generate Storyboard Prompts
              </button>
            );
            if (!sbGridsAllDone) return (
              <button
                onClick={handleGenerateAllImages}
                disabled={generatingAll || taskRunning}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--purple)", color: "var(--bg-void)" }}
              >
                {(generatingAll || taskRunning) ? <Loader2 size={14} className="animate-spin" /> : <ImageIcon size={14} />}
                Step 3: Generate Storyboard Grids
              </button>
            );
            if (extractionDone && needsUpscale) return (
              <div className="mt-3 space-y-2">
                <button
                  onClick={handleUpscalePanels}
                  disabled={extracting || taskRunning}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                  style={{ background: "var(--amber, #D4A844)", color: "var(--bg-void)" }}
                >
                  {(extracting || taskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />}
                  Upscale &amp; Remove KF Labels ({upscaledSegments}/{extractedSegments})
                </button>
                <button
                  onClick={handleAdvanceStage}
                  disabled={advancing}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all disabled:opacity-50"
                  style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.1)" }}
                >
                  {advancing ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                  Skip Upscale — Advance Stage
                </button>
                {extractError && (
                  <p className="text-[10px] text-center" style={{ color: "var(--orange)" }}>{extractError}</p>
                )}
              </div>
            );
            if (extractionDone) return (
              <div className="mt-3 text-center space-y-2">
                <p className="text-[10px]" style={{ color: "var(--green)" }}>
                  ✓ Panels extracted{upscaledSegments > 0 ? ` &amp; ${upscaledSegments} upscaled` : ""}
                  {upscaledSegments < extractedSegments && upscaledSegments > 0 ? ` (${extractedSegments - upscaledSegments} skipped)` : ""}
                </p>
                <button
                  onClick={handleAdvanceStage}
                  disabled={advancing}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                  style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                >
                  {advancing ? <Loader2 size={14} className="animate-spin" /> : <ChevronRight size={14} />}
                  Advance Stage
                </button>
              </div>
            );
            return (
              <div className="mt-3 space-y-2">
                <button
                  onClick={handleExtractPanels}
                  disabled={extracting || taskRunning}
                  className="w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                  style={{ background: "var(--green)", color: "var(--bg-void)" }}
                >
                  {(extracting || taskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Scissors size={14} />}
                  Step 4: Extract &amp; Upscale Panels ({extractedSegments}/{totalSegments})
                </button>
                {extractError && (
                  <p className="text-[10px] text-center" style={{ color: "var(--orange)" }}>
                    {extractError}
                  </p>
                )}
              </div>
            );
          })()}
        </div>
      )}

      {/* Live progress banner */}
      {taskRunning && (
        <div
          className="rounded-xl px-4 py-3 space-y-2"
          style={{
            background: "rgba(212, 168, 68, 0.08)",
            border: "1px solid rgba(212, 168, 68, 0.25)",
          }}
        >
          <div className="flex items-center gap-3">
            <Loader2 size={16} className="animate-spin flex-shrink-0" style={{ color: "var(--amber)" }} />
            <span className="text-sm font-medium" style={{ color: "var(--amber)" }}>
              {(() => {
                if (!taskMessage) return generatingPrompts ? "Generating storyboard prompts..." : "Generating storyboard grids...";
                const sceneMatch = taskMessage.match(/Scene\s+(\d+)\s+\((\d+)\/(\d+)\)/);
                const beatMatch = taskMessage.match(/Beat\s+(\d+)\/(\d+)/);
                if (sceneMatch) {
                  return (
                    <>
                      Generating Scene {sceneMatch[1]} ({sceneMatch[2]}/{sceneMatch[3]})
                      {beatMatch && (
                        <span style={{ color: "var(--text-secondary)", fontWeight: 400 }}>
                          {" "}— Beat {beatMatch[1]}/{beatMatch[2]}
                        </span>
                      )}
                    </>
                  );
                }
                return taskMessage.replace(/[*_]/g, "").replace(/\n/g, " · ");
              })()}
            </span>
          </div>
          {/* Progress bar */}
          {taskMessage && (() => {
            const sceneMatch = taskMessage.match(/Scene\s+\d+\s+\((\d+)\/(\d+)\)/);
            if (!sceneMatch) return null;
            const pct = Math.round((parseInt(sceneMatch[1]) / parseInt(sceneMatch[2])) * 100);
            return (
              <div className="h-1.5 rounded-full overflow-hidden" style={{ background: "rgba(212, 168, 68, 0.15)" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{ background: "var(--amber)", width: `${Math.max(pct, 5)}%` }}
                />
              </div>
            );
          })()}
        </div>
      )}

      {/* Filmstrip — horizontal scroll of all extracted images */}
      {storyboardMode && (() => {
        const allExtracted = scenes.flatMap(s => s.segments.filter(seg => seg.imageUrl)).sort((a, b) => a.sceneNumber === b.sceneNumber ? a.imageIndex - b.imageIndex : a.sceneNumber - b.sceneNumber);
        if (allExtracted.length === 0) return null;
        return (
          <div className="rounded-xl p-3" style={{ background: "rgba(80, 227, 194, 0.04)", border: "1px solid rgba(80, 227, 194, 0.12)" }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--green)" }}>
                Extracted Panels
              </span>
              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {allExtracted.length} images
              </span>
              <button
                className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded text-[9px] font-medium transition-colors"
                style={{
                  background: "rgba(239, 68, 68, 0.1)",
                  color: "rgba(239, 68, 68, 0.8)",
                  border: "1px solid rgba(239, 68, 68, 0.2)",
                }}
                disabled={clearingExtracted}
                onClick={handleClearAllExtracted}
              >
                {clearingExtracted ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                Clear All
              </button>
            </div>
            <div className="flex gap-2.5 overflow-x-auto pb-2" style={{ scrollbarWidth: "thin" }}>
              {allExtracted.map((seg) => (
                <div key={seg.id} className="flex-shrink-0 group cursor-pointer relative" onClick={() => { const el = document.getElementById(`scene-${seg.sceneNumber}`); if (el) el.scrollIntoView({ behavior: "smooth", block: "start" }); }}>
                  <div className="w-[220px] h-[124px] rounded-lg overflow-hidden" style={{ border: "1px solid rgba(255,255,255,0.08)" }}>
                    <img src={seg.imageUrl!} alt={seg.segmentId} className="w-full h-full object-cover group-hover:scale-105 transition-transform" loading="lazy" />
                  </div>
                  <button
                    className="absolute top-1 right-1 opacity-0 group-hover:opacity-100 transition-opacity rounded-full p-0.5"
                    style={{ background: "rgba(0,0,0,0.7)", color: "rgba(239, 68, 68, 0.9)" }}
                    onClick={(e) => { e.stopPropagation(); handleClearExtractedPanel(seg.id); }}
                  >
                    <X size={12} />
                  </button>
                  <span className="text-[9px] font-mono block text-center mt-1" style={{ color: "var(--text-tertiary)" }}>{seg.segmentId}</span>
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      <div className="grid grid-cols-1 gap-6">
        {/* Main content */}
        <div className="space-y-6">
          {Object.entries(actGroups).map(([actNum, actScenes]) => (
            <div key={actNum}>
              <div className="flex items-center gap-4 mb-4">
                <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
                <span
                  className="text-xs font-semibold uppercase tracking-wider"
                  style={{ color: "var(--purple)" }}
                >
                  Act {actNum}
                </span>
                <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
              </div>

              <div className="space-y-4">
                {actScenes.map((scene) => (
                  <GlassCard key={scene.sceneNumber} id={`scene-${scene.sceneNumber}`} className="p-5">
                    {/* Scene badge + duration (compact header) */}
                    <div className="flex items-center gap-2 mb-3">
                      <SegmentBadge label={`Scene ${scene.sceneNumber}`} color="var(--purple)" />
                      <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                        {scene.duration}
                      </span>
                      {/* Per-scene action buttons */}
                      <div className="ml-auto flex items-center gap-1.5">
                        {storyboardMode && scene.storyboardStatus && (
                          <span className="text-[8px] font-mono px-1.5 py-0.5 rounded" style={{
                            background: scene.storyboardStatus === "prompts_ready" || scene.storyboardStatus === "grids_generated"
                              ? "rgba(0, 230, 138, 0.1)"
                              : "rgba(168, 85, 247, 0.1)",
                            color: scene.storyboardStatus === "prompts_ready" || scene.storyboardStatus === "grids_generated"
                              ? "var(--green)"
                              : "var(--purple)",
                          }}>
                            {scene.storyboardStatus.replace(/_/g, " ")}
                          </span>
                        )}
                        {storyboardMode && !scene.hasStoryboardPrompt && (
                          <button
                            onClick={() => handleGenerateScenePrompts(scene.sceneNumber)}
                            disabled={taskRunning || generatingPrompts}
                            className="inline-flex items-center gap-1 text-[9px] font-medium px-2 py-1 rounded-md transition-all disabled:opacity-30"
                            style={{ background: "var(--purple)", color: "var(--bg-void)" }}
                          >
                            <Pencil size={9} /> Gen Prompts
                          </button>
                        )}
                        {storyboardMode && scene.hasStoryboardPrompt && scene.storyboardGridCount === 0 && (
                          <button
                            onClick={() => handleGenerateSceneGrids(scene.sceneNumber)}
                            disabled={taskRunning || generatingAll}
                            className="inline-flex items-center gap-1 text-[9px] font-medium px-2 py-1 rounded-md transition-all disabled:opacity-30"
                            style={{ background: "var(--orange)", color: "var(--bg-void)" }}
                          >
                            <ImageIcon size={9} /> Gen Grids
                          </button>
                        )}
                        {(scene.hasStoryboardData) && (
                          <button
                            onClick={() => handleClearSceneStoryboard(scene.sceneNumber)}
                            disabled={taskRunning || clearingAllStoryboards || clearingScene === scene.sceneNumber || !scene.hasStoryboardData}
                            className="inline-flex items-center gap-1 text-[9px] uppercase tracking-wider font-medium px-2 py-1 rounded-md transition-all disabled:opacity-30"
                            style={{ color: "#FF8A65", background: "rgba(255, 138, 101, 0.08)", border: "1px solid rgba(255, 138, 101, 0.25)" }}
                          >
                            {clearingScene === scene.sceneNumber ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={10} />}
                            Clear
                          </button>
                        )}
                      </div>
                    </div>

                    {/* ★ STORYBOARD GRIDS — PRIMARY FOCAL POINT */}
                    {(scene.storyboardBeats.length > 0 || scene.hasStoryboardData) && (
                      <div className="mb-3">
                        <div className="flex gap-4 overflow-x-auto pb-2" style={{ scrollbarWidth: "thin" }}>
                          {scene.storyboardBeats.map((beat) => (
                            <div key={`grid-${scene.sceneNumber}-${beat.beatNumber}`} className="flex-shrink-0">
                              <div
                                className="rounded-lg overflow-hidden cursor-pointer transition-all hover:ring-2 hover:ring-[var(--purple)]"
                                style={{
                                  width: 340,
                                  height: 200,
                                  background: "var(--bg-elevated)",
                                  border: dragOver === `${scene.sceneNumber}-${beat.beatNumber}`
                                    ? "2px solid var(--green)"
                                    : beat.gridUrl
                                      ? "1px solid rgba(0, 230, 138, 0.25)"
                                      : "1px dashed rgba(255,255,255,0.1)",
                                }}
                                onClick={() => {
                                  if (beat.gridUrl) {
                                    window.open(beat.gridUrl, "_blank");
                                  } else if (!taskRunning && !generatingAll) {
                                    handleGenerateSceneGrids(scene.sceneNumber);
                                  }
                                }}
                                onDragOver={(e) => { e.preventDefault(); setDragOver(`${scene.sceneNumber}-${beat.beatNumber}`); }}
                                onDragLeave={() => setDragOver(null)}
                                onDrop={(e) => {
                                  e.preventDefault();
                                  setDragOver(null);
                                  const file = e.dataTransfer.files[0];
                                  if (file && file.type.startsWith("image/")) {
                                    handleGridDrop(scene.sceneNumber, beat.beatNumber, file);
                                  }
                                }}
                                title={beat.gridUrl ? "Click to open full size" : "Click to generate or drag & drop an image"}
                              >
                                {beat.gridUrl ? (
                                  <img
                                    src={beat.gridUrl}
                                    alt={`S${scene.sceneNumber}.${beat.beatNumber}`}
                                    className="w-full h-full object-cover"
                                  />
                                ) : (
                                  <div className="w-full h-full flex flex-col items-center justify-center gap-2 transition-colors hover:bg-[rgba(168,85,247,0.08)]">
                                    {uploadingGrid === `${scene.sceneNumber}-${beat.beatNumber}` ? (
                                      <>
                                        <Loader2 size={20} className="animate-spin" style={{ color: "var(--green)" }} />
                                        <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>
                                          Uploading...
                                        </span>
                                      </>
                                    ) : dragOver === `${scene.sceneNumber}-${beat.beatNumber}` ? (
                                      <>
                                        <ImageIcon size={20} style={{ color: "var(--green)" }} />
                                        <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>
                                          Drop to Upload
                                        </span>
                                      </>
                                    ) : (generatingAll || generatingScene === scene.sceneNumber) ? (
                                      <>
                                        <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                                        <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>
                                          Generating...
                                        </span>
                                      </>
                                    ) : (
                                      <>
                                        <ImageIcon size={20} style={{ color: "var(--purple)", opacity: 0.6 }} />
                                        <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>
                                          Click or Drop Image
                                        </span>
                                      </>
                                    )}
                                  </div>
                                )}
                              </div>
                              <p className="text-center mt-1.5 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                                S{scene.sceneNumber}.{beat.beatNumber}
                              </p>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Voice player — uses short-lived audio token instead of session JWT */}
                    {scene.voiceOverUrl && (
                      <SecureAudioPlayer videoId={video.id} scene={scene.sceneNumber} />
                    )}
                    {!scene.voiceOverUrl && (
                      <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>No voice generated yet</p>
                    )}

                    {/* Narration text — collapsed, expandable */}
                    <details className="mb-3">
                      <summary className="text-[11px] cursor-pointer" style={{ color: "var(--text-secondary)" }}>
                        <span style={{ color: "var(--text-tertiary)" }}>
                          {scene.narrationText.slice(0, 80).trim()}{scene.narrationText.length > 80 ? "..." : ""}
                        </span>
                      </summary>
                      <p
                        className="text-sm leading-relaxed mt-2 pl-4"
                        style={{ color: "var(--text-primary)", borderLeft: "2px solid var(--border-subtle)" }}
                      >
                        {scene.narrationText}
                      </p>
                    </details>

                    {/* Beat prompts (expandable) */}
                    {scene.storyboardBeats.length > 0 && (
                      <details className="mb-3">
                        <summary className="text-[10px] cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
                          {scene.storyboardBeats.length} beat prompt{scene.storyboardBeats.length !== 1 ? "s" : ""}
                        </summary>
                        <div className="space-y-2 mt-2">
                          {scene.storyboardBeats.map((beat) => (
                            <PromptExpander
                              key={`prompt-${scene.sceneNumber}-${beat.beatNumber}`}
                              prompt={beat.prompt}
                              label={`Beat ${beat.beatNumber}`}
                              previewLength={120}
                            />
                          ))}
                        </div>
                      </details>
                    )}

                    {/* Segment cards — collapsed by default */}
                    <details>
                      <summary className="text-[11px] cursor-pointer py-1" style={{ color: "var(--text-secondary)" }}>
                        <span style={{ color: "var(--text-tertiary)" }}>
                          {scene.segments.length} image segment{scene.segments.length !== 1 ? "s" : ""}
                        </span>
                        {" · "}
                        <span style={{ color: "var(--green)" }}>
                          {scene.segments.filter((s) => s.status === "done").length} generated
                        </span>
                        {scene.segments.filter((s) => s.status !== "done").length > 0 && (
                          <>
                            {" · "}
                            <span style={{ color: "var(--orange)" }}>
                              {scene.segments.filter((s) => s.status !== "done").length} pending
                            </span>
                          </>
                        )}
                      </summary>
                    <div className="space-y-3 mt-3">
                      {scene.segments.map((seg) => {
                        const statusInfo = STATUS_ICON[seg.status];
                        const isRegenerating = regeneratingSegment === seg.id;
                        const isGeneratingVariants = variantsSegment === seg.id;

                        return (
                          <div
                            key={seg.id}
                            className="rounded-xl p-3 transition-all"
                            style={{
                              background: "rgba(255,255,255,0.02)",
                              border: `1px solid ${
                                seg.status === "done"
                                  ? "rgba(0, 230, 138, 0.15)"
                                  : "rgba(255,255,255,0.05)"
                              }`,
                            }}
                          >
                            <div className="flex items-start gap-3">
                              <SegmentBadge
                                label={seg.segmentId}
                                color={seg.status === "done" ? "var(--green)" : undefined}
                              />
                              <div className="flex-1 min-w-0 space-y-2">
                                {/* Sentence text */}
                                <div>
                                  <label
                                    className="text-[9px] uppercase tracking-wider font-medium"
                                    style={{ color: "var(--text-tertiary)" }}
                                  >
                                    Sentence
                                  </label>
                                  <p
                                    className="text-sm mt-0.5"
                                    style={{ color: "var(--text-primary)" }}
                                  >
                                    {seg.sentenceText || "\u2014"}
                                  </p>
                                  <span
                                    className="text-[9px] font-mono"
                                    style={{ color: "var(--text-tertiary)" }}
                                  >
                                    {seg.sentenceText
                                      ? `${seg.sentenceText.split(/\s+/).length} words \u00B7 ${Math.round(seg.sentenceText.split(/\s+/).length / 2.5)}s`
                                      : ""}
                                  </span>
                                </div>

                                {/* Image prompt (expandable) */}
                                {seg.imagePrompt && (
                                  <PromptExpander
                                    prompt={seg.imagePrompt}
                                    label="Image Prompt"
                                    previewLength={60}
                                    onSave={(newPrompt) => updatePrompt(seg.id, newPrompt)}
                                  />
                                )}
                              </div>

                              {/* Thumbnail + status + regenerate */}
                              <div className="shrink-0 flex flex-col items-center gap-1.5">
                                <div
                                  className="w-24 h-[54px] rounded-lg relative flex items-center justify-center overflow-hidden"
                                  style={{
                                    background: "var(--bg-elevated)",
                                    border: "1px solid var(--border-subtle)",
                                    aspectRatio: "16/9",
                                  }}
                                >
                                  {seg.imageUrl ? (
                                    <img
                                      src={seg.imageUrl}
                                      alt={seg.segmentId}
                                      className="absolute inset-0 w-full h-full object-cover"
                                    />
                                  ) : (
                                    <svg className="absolute inset-0 w-full h-full opacity-15">
                                      <defs>
                                        <pattern
                                          id={`vg-${seg.id}`}
                                          width="12"
                                          height="12"
                                          patternUnits="userSpaceOnUse"
                                        >
                                          <path
                                            d="M 12 0 L 0 0 0 12"
                                            fill="none"
                                            stroke="var(--purple)"
                                            strokeWidth="0.3"
                                          />
                                        </pattern>
                                      </defs>
                                      <rect
                                        width="100%"
                                        height="100%"
                                        fill={`url(#vg-${seg.id})`}
                                      />
                                    </svg>
                                  )}
                                  {seg.status === "done" && (
                                    <div
                                      className="absolute top-1 right-1 w-4 h-4 rounded-full flex items-center justify-center"
                                      style={{ background: "var(--green)" }}
                                    >
                                      <Check size={8} style={{ color: "var(--bg-void)" }} />
                                    </div>
                                  )}
                                </div>
                                <span
                                  className="text-[9px] font-mono flex items-center gap-1"
                                  style={{ color: statusInfo.color }}
                                >
                                  {statusInfo.icon}
                                  {statusInfo.label}
                                </span>
                                {!storyboardMode && (
                                  <>
                                    <button
                                      onClick={() => handleRegenerate(seg)}
                                      disabled={isRegenerating}
                                      className="text-[9px] px-2 py-0.5 rounded transition-all disabled:opacity-50"
                                      style={{
                                        color: "var(--orange)",
                                        border: "1px solid var(--orange)",
                                      }}
                                    >
                                      {isRegenerating ? (
                                        <Loader2 size={8} className="animate-spin inline" />
                                      ) : (
                                        <RefreshCw size={8} className="inline" />
                                      )}{" "}
                                      {seg.status === "done" ? "Regen" : "Gen"}
                                    </button>
                                    {seg.status === "done" && (
                                      <button
                                        onClick={() => handleGenerateVariants(seg)}
                                        disabled={isGeneratingVariants}
                                        className="text-[9px] px-2 py-0.5 rounded transition-all disabled:opacity-50"
                                        style={{
                                          color: "var(--purple)",
                                          border: "1px solid var(--purple)",
                                        }}
                                      >
                                        {isGeneratingVariants ? (
                                          <Loader2 size={8} className="animate-spin inline" />
                                        ) : (
                                          <Layers size={8} className="inline" />
                                        )}{" "}
                                        Variants
                                      </button>
                                    )}
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    </details>
                  </GlassCard>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Sidebar removed — all controls moved to top bar */}
      </div>
    </div>
  );
}

// --- Storyboard toggle sub-component ---

function StoryboardToggle({
  enabled,
  toggling,
  onToggle,
}: {
  enabled: boolean;
  toggling: boolean;
  onToggle: () => void;
}) {
  return (
    <GlassCard className="p-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span
            className="text-xs font-semibold uppercase tracking-wider"
            style={{ color: "var(--text-secondary)" }}
          >
            Storyboard Mode
          </span>
          <span
            className="text-[10px] font-mono px-2 py-0.5 rounded-full"
            style={{
              color: enabled ? "var(--green)" : "var(--text-tertiary)",
              background: enabled ? "rgba(0, 230, 138, 0.1)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${enabled ? "rgba(0, 230, 138, 0.2)" : "rgba(255,255,255,0.06)"}`,
            }}
          >
            {enabled ? "ON" : "OFF"}
          </span>
        </div>
        <button
          onClick={onToggle}
          disabled={toggling}
          className="transition-all disabled:opacity-50"
          style={{ color: enabled ? "var(--green)" : "var(--text-tertiary)" }}
        >
          {toggling ? (
            <Loader2 size={20} className="animate-spin" />
          ) : enabled ? (
            <ToggleRight size={28} />
          ) : (
            <ToggleLeft size={28} />
          )}
        </button>
      </div>
      <p className="text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
        When on, storyboard grids are generated before individual images for visual consistency.
      </p>
    </GlassCard>
  );
}
