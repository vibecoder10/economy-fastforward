"use client";

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, Loader2, Pencil, Image as ImageIcon, RefreshCw, Trash2,
  Lock, Unlock, ArrowLeft, Layers, X, MoreHorizontal,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { PromptExpander } from "@/components/video-detail/prompt-expander";
import { VoicePlayer } from "@/components/video-detail/voice-player";
import {
  getVideoScript, getVideoAssets, updateStoryboardMode, clearSceneStoryboard, clearAllStoryboards,
  clearStoryboardSlot, clearAllExtractedPanels, clearExtractedPanel, uploadStoryboardGrid,
  runPipelineStage, updateSceneSegments, runImageForSegment, runImageVariants, clearStaleTask, updateVideoStyles,
  getAudioToken, advanceVideo, unlockStory,
} from "@/lib/api";
import { useTaskWatcher } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { VideoDetail } from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { API_URL } from "@/lib/env";
import { AnimaticPlayer } from "@/components/production/AnimaticPlayer";

/** Fetches a short-lived audio token, then renders VoicePlayer with scoped URL */
function SecureAudioPlayer({ videoId, scene }: { videoId: string; scene: number }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getAudioToken(videoId).then(({ token }) => {
      // API_URL, not window.location:8001 — the old guess produced
      // https://storyengine.dev:8001 in prod, a port the browser can't reach,
      // so every voice player rendered dead at 0:00/0:00.
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

  // Storyboarding is MANDATORY (Creator Control Run, phase 3): boards are the
  // only path to image spend. Persist mode=On so the backend scripts rows agree.
  const storyboardMode = true;
  useEffect(() => {
    if (scriptScenes && scriptScenes.length > 0) {
      const anyOff = scriptScenes.some((s) => s.storyboard_on_off !== "On");
      if (anyOff) {
        updateStoryboardMode(video.id, true).catch(() => { /* best-effort */ });
      }
    }
  }, [scriptScenes, video.id]);

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
  const [model, setModel] = useState(video.image_model_override || "nano-banana-2");
  const [savingModel, setSavingModel] = useState(false);
  const [generatingScene, setGeneratingScene] = useState<number | null>(null);
  const [clearingScene, setClearingScene] = useState<number | null>(null);
  const [clearingAllStoryboards, setClearingAllStoryboards] = useState(false);
  const [clearingExtracted, setClearingExtracted] = useState(false);
  const [uploadingGrid, setUploadingGrid] = useState<string | null>(null); // "scene-beat"
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [clearingSlot, setClearingSlot] = useState<string | null>(null); // "scene-beat"
  const [showAdvanced, setShowAdvanced] = useState(false);
  // Replacing a board reuses the same Drive file (same URL) — bump a cache
  // key per slot so the <img> actually refetches the new pixels.
  const [gridBust, setGridBust] = useState<Record<string, number>>({});

  // Per-scene auto-chain: "rewrite & redraw" needs two stages back-to-back
  // (storyboards → storyboard-images). The watcher fires the next stage when
  // the previous one completes, so one click does the whole scene.
  const chainRef = useRef<{ scene: number; stages: string[] } | null>(null);

  const refreshAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  }, [queryClient, video.id]);

  const { running: taskRunning, message: taskMessage, markStarted } = useTaskWatcher({
    videoId: video.id,
    onProgress: () => {
      // Refresh assets on every poll tick so extracted panels appear live
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onComplete: async () => {
      const chain = chainRef.current;
      if (chain && chain.stages.length > 0) {
        const nextStage = chain.stages.shift()!;
        try {
          queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
          try {
            await runPipelineStage(video.id, nextStage, { scene: chain.scene });
          } catch (err) {
            if (!((err as Error).message || "").includes("409")) throw err;
            await clearStaleTask(video.id);
            await runPipelineStage(video.id, nextStage, { scene: chain.scene });
          }
          markStarted();
          return;
        } catch (err) {
          chainRef.current = null;
          toast.error(`Scene ${chain.scene} couldn't continue: ${(err as Error).message}`);
        }
      }
      chainRef.current = null;
      setGeneratingScene(null);
      refreshAll();
    },
    onFailed: () => {
      // The page banner shows the persistent failure card — no duplicate toast.
      chainRef.current = null;
      setGeneratingScene(null);
      refreshAll();
    },
  });

  // Stop must also stand down any queued chain stage: a cancelled task reads
  // as "completed" to pollers, which would otherwise fire the next stage.
  useEffect(() => {
    const onStop = (e: Event) => {
      if ((e as CustomEvent).detail?.videoId === video.id) {
        chainRef.current = null;
        setGeneratingScene(null);
      }
    };
    window.addEventListener("se:stop-requested", onStop);
    return () => window.removeEventListener("se:stop-requested", onStop);
  }, [video.id]);

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

  // "Start scene over": wipe the scene's plan + pictures, then automatically
  // rebuild both (plan → pictures) in one click. Before this existed, clearing
  // left the scene with no prompts and a confusing dead end.
  const handleRedoSceneFromScratch = useCallback(async (sceneNumber: number) => {
    const confirmed = window.confirm(
      `Start Scene ${sceneNumber} over? We'll throw away its plan and pictures, write a fresh plan, and draw new pictures (≈ $0.08 each).\n\nTo redo just the pictures, use "Redo pictures". To remove one picture, hover it and click the X.`
    );
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
                storyboardBeats: [],
              }
            : scene,
        ),
      );
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      // Plan first, pictures chained after it completes.
      chainRef.current = { scene: sceneNumber, stages: ["storyboard-images"] };
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("storyboards", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't restart Scene ${sceneNumber}: ${(err as Error).message}`);
    } finally {
      setClearingScene(null);
    }
  }, [video.id, queryClient, toast, runStageWith409Retry]);

  // "Redo pictures": keep the scene's plan, replace its pictures.
  const handleRedoScenePictures = useCallback(async (sceneNumber: number) => {
    const scene = scenes.find((s) => s.sceneNumber === sceneNumber);
    const boardCount = scene?.storyboardBeats.filter((b) => b.gridUrl).length || 0;
    const confirmed = window.confirm(
      `Redo Scene ${sceneNumber}'s pictures? The current ${boardCount === 1 ? "picture" : `${boardCount} pictures`} will be replaced (≈ $0.08 each). The scene's plan stays the same.`
    );
    if (!confirmed) return;

    setGeneratingScene(sceneNumber);
    try {
      for (const beat of scene?.storyboardBeats || []) {
        if (beat.gridUrl) {
          await clearStoryboardSlot(video.id, sceneNumber, beat.beatNumber);
        }
      }
      setScenes((prev) =>
        prev.map((s) =>
          s.sceneNumber === sceneNumber
            ? {
                ...s,
                storyboardGridCount: 0,
                storyboardBeats: s.storyboardBeats.map((b) => ({ ...b, gridUrl: null })),
              }
            : s,
        ),
      );
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err) {
      setGeneratingScene(null);
      toast.error(`Couldn't redo Scene ${sceneNumber}'s pictures: ${(err as Error).message}`);
    }
  }, [video.id, scenes, toast, runStageWith409Retry]);

  const handleClearAllStoryboards = useCallback(async () => {
    const confirmed = window.confirm(
      "Start the storyboard over? Every board and every scene plan gets thrown away. Your script and voice stay. You\u2019ll rebuild from the big button at the top.",
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
    const confirmed = window.confirm("Delete all the final pictures? Your storyboards stay \u2014 you can create the final pictures again afterwards.");
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
          const wasEmpty = !scene.storyboardBeats.find((b) => b.beatNumber === beatNumber)?.gridUrl;
          return {
            ...scene,
            storyboardGridCount: scene.storyboardGridCount + (wasEmpty ? 1 : 0),
            hasStoryboardData: true,
            storyboardStatus: result.all_grids_complete ? "grids_generated" : scene.storyboardStatus,
            storyboardBeats: scene.storyboardBeats.map((b) =>
              b.beatNumber === beatNumber ? { ...b, gridUrl: result.url } : b,
            ),
          };
        }),
      );
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
      setScenes((prev) =>
        prev.map((scene) => {
          if (scene.sceneNumber !== sceneNumber) return scene;
          return {
            ...scene,
            storyboardGridCount: Math.max(0, scene.storyboardGridCount - 1),
            storyboardStatus: scene.storyboardStatus === "grids_generated" ? "prompts_ready" : scene.storyboardStatus,
            storyboardBeats: scene.storyboardBeats.map((b) =>
              b.beatNumber === beatNumber ? { ...b, gridUrl: null } : b,
            ),
          };
        }),
      );
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

  // --- Story lock (mandatory storyboard gate) ---
  const storyLocked = !!video.story_locked_at;
  const [locking, setLocking] = useState(false);
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

  // --- Empty state: no scenes yet — the big banner button above drives everything ---
  if (scenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Your storyboard will appear here
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          {taskRunning
            ? (taskMessage || "Working on it…")
            : "Use the big button at the top of the page — it always knows the next step."}
        </p>
      </GlassCard>
    );
  }

  // --- Full visuals workflow ---
  return (
    <div className="space-y-4">
      {/* One quiet status line + everything power-user behind one menu.
          The page banner above is the ONLY primary button — this tab is the
          workspace: look at boards, fix scenes, drag in replacements. */}
      <div
        className="rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}
      >
        <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{scenes.length} scenes</strong>
          {" · "}
          <strong style={{ color: storyboardGridsDone ? "var(--green)" : "var(--text-primary)" }}>
            {scenes.reduce((n, s) => n + s.storyboardGridCount, 0)} of {scenes.reduce((n, s) => n + (s.storyboardBeatCount || 1), 0)} boards
          </strong>
          {extractedSegments > 0 && (
            <>
              {" · "}
              <strong style={{ color: "var(--green)" }}>{extractedSegments}/{totalSegments} final pictures</strong>
            </>
          )}
          {storyLocked && (
            <span className="ml-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
              <Lock size={11} className="inline mr-0.5 -mt-0.5" /> Story locked
            </span>
          )}
        </p>
        {taskRunning && (
          <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--turquoise)" }}>
            <Loader2 size={12} className="animate-spin" />
            {(taskMessage || "Working…").replace(/[*_]/g, "").slice(0, 80)}
          </span>
        )}
        <div className="flex-1" />
        {storyLocked && (
          <button
            onClick={handleUnlockStory}
            disabled={locking || taskRunning}
            className="text-xs font-medium px-3 py-1.5 rounded-lg transition-all disabled:opacity-40"
            style={{ color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.12)" }}
            title="Unlock to keep editing boards"
          >
            {locking ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Unlock size={12} className="inline mr-1" />}
            Unlock
          </button>
        )}
        <div className="relative">
          <button
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="p-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)]"
            style={{ color: "var(--text-tertiary)" }}
            title="Advanced options"
          >
            <MoreHorizontal size={18} />
          </button>
          {showAdvanced && (
            <>
            <div className="fixed inset-0 z-40" onClick={() => setShowAdvanced(false)} />
            <div
              className="absolute right-0 top-full mt-2 z-50 w-72 rounded-xl p-2 space-y-0.5"
              style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}
            >
              <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>Advanced</p>
              <div className="flex items-center justify-between px-3 py-2">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>Picture model</span>
                <select
                  value={model}
                  onChange={(e) => handleModelChange(e.target.value)}
                  disabled={savingModel}
                  className="bg-transparent text-xs border rounded px-1.5 py-1 cursor-pointer"
                  style={{ color: "var(--text-secondary)", borderColor: "rgba(255,255,255,0.15)" }}
                >
                  <option value="nano-banana-2">Nano Banana 2</option>
                  <option value="z-image">Z Image</option>
                </select>
              </div>
              {extractedSegments > 0 && needsUpscale && (
                <button
                  onClick={() => { setShowAdvanced(false); handleUpscalePanels(); }}
                  disabled={taskRunning}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Upscale final pictures <span style={{ color: "var(--text-tertiary)" }}>({upscaledSegments}/{extractedSegments} done)</span>
                </button>
              )}
              {extractedSegments > 0 && (
                <button
                  onClick={() => { setShowAdvanced(false); handleClearAllExtracted(); }}
                  disabled={taskRunning || clearingExtracted}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--orange)" }}
                >
                  Delete all final pictures <span style={{ color: "var(--text-tertiary)" }}>— boards stay</span>
                </button>
              )}
              <button
                onClick={() => { setShowAdvanced(false); handleClearAllStoryboards(); }}
                disabled={taskRunning || clearingAllStoryboards || storyboardScenesWithData === 0 || storyLocked}
                title={storyLocked ? "Unlock the story first" : undefined}
                className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                style={{ color: "var(--orange)" }}
              >
                Start storyboard over <span style={{ color: "var(--text-tertiary)" }}>— deletes every board + plan</span>
              </button>
              {storyLocked && totalSegments > 0 && extractedSegments < totalSegments && (
                <button
                  onClick={() => { setShowAdvanced(false); handleReExtract(); }}
                  disabled={taskRunning}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--text-secondary)" }}
                >
                  Create missing final pictures <span style={{ color: "var(--text-tertiary)" }}>({totalSegments - extractedSegments} to make)</span>
                </button>
              )}
              <button
                onClick={() => { setShowAdvanced(false); handleAdvanceStage(); }}
                disabled={advancing}
                className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                style={{ color: "var(--text-secondary)" }}
              >
                Skip ahead to the next stage
              </button>
            </div>
            </>
          )}
        </div>
      </div>

      {/* Filmstrip — horizontal scroll of all extracted images */}
      {storyboardMode && (() => {
        const allExtracted = scenes.flatMap(s => s.segments.filter(seg => seg.imageUrl)).sort((a, b) => a.sceneNumber === b.sceneNumber ? a.imageIndex - b.imageIndex : a.sceneNumber - b.sceneNumber);
        if (allExtracted.length === 0) return null;
        return (
          <div className="rounded-xl p-3" style={{ background: "rgba(80, 227, 194, 0.04)", border: "1px solid rgba(80, 227, 194, 0.12)" }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--green)" }}>
                Final pictures
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
                disabled={clearingExtracted || taskRunning}
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
                    <img src={toDisplayImageUrl(seg.imageUrl)} alt={seg.segmentId} className="w-full h-full object-cover group-hover:scale-105 transition-transform" loading="lazy" />
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
                      {/* Per-scene controls — readable buttons, one obvious verb each */}
                      <div className="ml-auto flex items-center gap-2">
                        {generatingScene === scene.sceneNumber ? (
                          <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--purple)" }}>
                            <Loader2 size={13} className="animate-spin" /> Redoing this scene…
                          </span>
                        ) : (
                          <>
                            {!scene.hasStoryboardPrompt && (
                              <button
                                onClick={() => handleGenerateScenePrompts(scene.sceneNumber)}
                                disabled={taskRunning}
                                className="inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                                style={{ background: "var(--purple)", color: "var(--bg-void)" }}
                              >
                                <Pencil size={13} /> Plan this scene
                              </button>
                            )}
                            {scene.hasStoryboardPrompt && scene.storyboardGridCount === 0 && (
                              <button
                                onClick={() => handleGenerateSceneGrids(scene.sceneNumber)}
                                disabled={taskRunning}
                                className="inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                                style={{ background: "var(--purple)", color: "var(--bg-void)" }}
                              >
                                <ImageIcon size={13} /> Draw the pictures
                              </button>
                            )}
                            {scene.hasStoryboardPrompt && scene.storyboardGridCount > 0 && (
                              <button
                                onClick={() => handleRedoScenePictures(scene.sceneNumber)}
                                disabled={taskRunning || storyLocked}
                                title={storyLocked ? "Unlock the story first (top right)" : "Replace this scene's pictures — the plan stays"}
                                className="inline-flex items-center gap-1.5 text-xs font-semibold px-3.5 py-2 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                                style={{ background: "rgba(168, 85, 247, 0.15)", color: "var(--purple)", border: "1px solid rgba(168, 85, 247, 0.4)" }}
                              >
                                <RefreshCw size={13} /> Redo pictures
                              </button>
                            )}
                            {scene.hasStoryboardData && (
                              <button
                                onClick={() => handleRedoSceneFromScratch(scene.sceneNumber)}
                                disabled={taskRunning || storyLocked || clearingScene === scene.sceneNumber}
                                title={storyLocked ? "Unlock the story first (top right)" : "New plan AND new pictures for this scene"}
                                className="text-xs font-medium px-3 py-2 rounded-lg transition-all disabled:opacity-40 hover:bg-[rgba(255,255,255,0.05)]"
                                style={{ color: "var(--text-tertiary)" }}
                              >
                                {clearingScene === scene.sceneNumber ? <Loader2 size={12} className="animate-spin inline mr-1" /> : null}
                                Start scene over
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </div>

                    {/* ★ STORYBOARD GRIDS — PRIMARY FOCAL POINT */}
                    {(scene.storyboardBeats.length > 0 || scene.hasStoryboardData) && (
                      <div className="mb-3">
                        <div className="flex gap-4 overflow-x-auto pb-2" style={{ scrollbarWidth: "thin" }}>
                          {scene.storyboardBeats.map((beat) => {
                            const slotKey = `${scene.sceneNumber}-${beat.beatNumber}`;
                            const bust = gridBust[slotKey];
                            const displayUrl = beat.gridUrl
                              ? `${toDisplayImageUrl(beat.gridUrl)}${bust ? `?cb=${bust}` : ""}`
                              : undefined;
                            return (
                            <div key={`grid-${slotKey}`} className="flex-shrink-0 relative group/board">
                              <div
                                className="relative rounded-lg overflow-hidden cursor-pointer transition-all hover:ring-2 hover:ring-[var(--purple)]"
                                style={{
                                  width: 340,
                                  height: 200,
                                  background: "var(--bg-elevated)",
                                  border: dragOver === slotKey
                                    ? "2px solid var(--green)"
                                    : beat.gridUrl
                                      ? "1px solid rgba(0, 230, 138, 0.25)"
                                      : "1px dashed rgba(255,255,255,0.1)",
                                }}
                                onClick={() => {
                                  if (beat.gridUrl) {
                                    window.open(beat.gridUrl, "_blank");
                                  } else if (!taskRunning) {
                                    handleGenerateSceneGrids(scene.sceneNumber);
                                  }
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
                                    <img
                                      src={displayUrl}
                                      alt={`S${scene.sceneNumber}.${beat.beatNumber}`}
                                      className="w-full h-full object-cover"
                                    />
                                    {(dragOver === slotKey || uploadingGrid === slotKey || clearingSlot === slotKey) && (
                                      <div
                                        className="absolute inset-0 flex flex-col items-center justify-center gap-2"
                                        style={{ background: "rgba(0,0,0,0.65)" }}
                                      >
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
                                              Drop to replace this picture
                                            </span>
                                          </>
                                        )}
                                      </div>
                                    )}
                                  </>
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
                                    ) : (generatingScene === scene.sceneNumber) ? (
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
                              {beat.gridUrl && clearingSlot !== slotKey && uploadingGrid !== slotKey && (
                                <button
                                  onClick={(e) => { e.stopPropagation(); handleClearGridSlot(scene.sceneNumber, beat.beatNumber); }}
                                  disabled={taskRunning}
                                  title="Remove just this picture (prompts stay)"
                                  className="absolute top-1.5 right-1.5 rounded-full p-1 opacity-0 group-hover/board:opacity-100 transition-opacity disabled:opacity-0"
                                  style={{ background: "rgba(0,0,0,0.75)", color: "rgba(239, 68, 68, 0.95)" }}
                                >
                                  <X size={14} />
                                </button>
                              )}
                              <p className="text-center mt-1.5 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                                S{scene.sceneNumber}.{beat.beatNumber}
                              </p>
                            </div>
                          );
                          })}
                        </div>
                      </div>
                    )}

                    {/* Animatic: pictures + narration = the scene as a film, $0.
                        Falls back to the plain voice player until the final
                        pictures exist (they're made automatically after lock). */}
                    {(() => {
                      const panels = scene.segments
                        .filter((seg) => seg.imageUrl)
                        .map((seg) => ({ url: toDisplayImageUrl(seg.imageUrl)!, text: seg.sentenceText }));
                      if (panels.length > 0) {
                        return <AnimaticPlayer videoId={video.id} scene={scene.sceneNumber} panels={panels} />;
                      }
                      return scene.voiceOverUrl
                        ? <SecureAudioPlayer videoId={video.id} scene={scene.sceneNumber} />
                        : <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>No voice generated yet</p>;
                    })()}

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
                          {scene.storyboardBeats.length} picture plan{scene.storyboardBeats.length !== 1 ? "s" : ""}
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
                          {scene.segments.length} final picture slot{scene.segments.length !== 1 ? "s" : ""}
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
                                      src={toDisplayImageUrl(seg.imageUrl)}
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
