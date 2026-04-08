"use client";

import { useState, useMemo, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, CheckCircle, Loader2 } from "lucide-react";
import Link from "next/link";
import {
  SceneGrid,
  PanelDetail,
  StoryboardProgressBar,
  type SceneData,
} from "@/components/storyboard";
import {
  getVideo,
  getVideoScript,
  advanceVideo,
  clearSceneStoryboard,
  runPipelineStage,
  clearStaleTask,
  type ScriptScene,
} from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";

/**
 * Transform script scenes into storyboard scene data.
 * Each script scene has up to 3 storyboard grid URLs (3x3 contact sheets).
 */
function buildSceneData(scripts: ScriptScene[]): SceneData[] {
  return scripts
    .filter((s) => s.scene !== null)
    .map((script) => {
      const gridUrls = [
        script.storyboard_1_url,
        script.storyboard_2_url,
        script.storyboard_3_url,
      ].filter(Boolean) as string[];

      const hasBoards = gridUrls.length > 0;

      // Determine status from script data
      let status: SceneData["status"] = "generating";
      if (hasBoards) {
        status = script.storyboard_status === "approved" ? "approved" : "pending";
      }

      // Build panels from the 3x3 grids — each grid is one panel in our view
      // (panels here represent the grid options to pick from)
      const panels = gridUrls.length > 0
        ? gridUrls.map((url, idx) => ({
            index: idx,
            url,
            prompt: script.storyboard_prompts
              ? `Grid ${idx + 1} — ${(script.storyboard_prompts || "").slice(0, 100)}`
              : `Storyboard grid ${idx + 1}`,
          }))
        : Array.from({ length: 3 }, (_, idx) => ({
            index: idx,
            url: null,
            prompt: `Grid ${idx + 1} — awaiting generation`,
          }));

      return {
        sceneNumber: script.scene || 0,
        title: `Scene ${script.scene || 0}`,
        narration: script.scene_text || "Narration text...",
        panels,
        status,
      };
    });
}

export default function StoryboardsPage() {
  const params = useParams();
  const toast = useToast();
  const router = useRouter();
  const queryClient = useQueryClient();
  const videoId = params.videoId as string;

  // Panel detail state
  const [selectedScene, setSelectedScene] = useState<number | null>(null);
  const [selectedPanel, setSelectedPanel] = useState<number>(0);
  const [taskRunning, setTaskRunning] = useState(false);
  const [taskAction, setTaskAction] = useState<"extract" | "regenerate">("extract");

  const { message: taskMessage } = useTaskPoller({
    videoId,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video", videoId, "script"] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      toast.error(`${taskAction === "extract" ? "Extraction" : "Regeneration"} failed: ${error}`);
    },
  });

  // Fetch video data
  const { data: video, isLoading: videoLoading } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
    enabled: !!videoId,
  });

  // Fetch script data
  const { data: scripts = [], isLoading: scriptsLoading } = useQuery({
    queryKey: ["video", videoId, "script"],
    queryFn: () => getVideoScript(videoId),
    enabled: !!videoId,
  });

  // Build storyboard scenes from real script data
  const scenes = useMemo(() => {
    if (!scripts.length) return [];
    return buildSceneData(scripts);
  }, [scripts]);

  // Calculate progress
  const approvedCount = scenes.filter((s) => s.status === "approved").length;
  const totalCount = scenes.length;

  // Advance (approve) video past storyboard stage
  const approveMutation = useMutation({
    mutationFn: () => advanceVideo(videoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video", videoId, "script"] });
    },
    onError: (err) => {
      toast.error(`Advance failed: ${(err as Error).message}`);
    },
  });

  // Extract all approved storyboard panels
  const handleExtractAll = useCallback(async () => {
    setTaskAction("extract");
    try {
      await runPipelineStage(videoId, "storyboard-extract");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(videoId);
          await runPipelineStage(videoId, "storyboard-extract");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Extraction failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Extraction failed: ${message}`);
      }
    }
  }, [videoId]);

  // Regenerate storyboard for a specific scene
  const handleRegenerate = useCallback(
    async (sceneNumber: number) => {
      setTaskAction("regenerate");
      try {
        await clearSceneStoryboard(videoId, sceneNumber);
        await runPipelineStage(videoId, "storyboard-images");
        setTaskRunning(true);
      } catch (err: unknown) {
        const message = (err as Error).message || "";
        if (message.includes("409")) {
          try {
            await clearStaleTask(videoId);
            await runPipelineStage(videoId, "storyboard-images");
            setTaskRunning(true);
            return;
          } catch (retryErr) {
            toast.error(`Regeneration failed: ${(retryErr as Error).message}`);
          }
        } else {
          toast.error(`Regeneration failed: ${message}`);
        }
      }
    },
    [videoId]
  );

  // Handle panel click
  const handlePanelClick = (sceneIndex: number, panelIndex: number) => {
    setSelectedScene(sceneIndex);
    setSelectedPanel(panelIndex);
  };

  // Loading state
  if (videoLoading || scriptsLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Loader2 size={32} className="animate-spin text-[var(--accent)]" />
      </div>
    );
  }

  // No video found
  if (!video) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <p className="text-[var(--text-secondary)]">Video not found</p>
        <Link
          href="/pipeline"
          className="text-sm font-medium text-[var(--accent)]"
        >
          Back to Pipeline
        </Link>
      </div>
    );
  }

  // No storyboards
  if (scenes.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.back()}
            className="rounded-lg p-2 hover:bg-[var(--surface)]"
          >
            <ArrowLeft size={20} />
          </button>
          <h1 className="text-xl font-bold">Storyboards</h1>
        </div>
        <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 rounded-xl border border-[var(--border)] bg-[var(--surface)]">
          <p className="text-[var(--text-secondary)]">
            No storyboards generated yet
          </p>
          <p className="text-sm text-[var(--text-secondary)]">
            Run the prompts stage to generate storyboard grids
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4 pb-20">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => router.back()}
          className="rounded-lg p-2 hover:bg-[var(--surface)]"
        >
          <ArrowLeft size={20} />
        </button>
        <div className="min-w-0 flex-1">
          <h1 className="text-lg font-bold">Storyboards</h1>
          <p className="line-clamp-1 text-sm text-[var(--text-secondary)]">
            {video.video_title || "Untitled"}
          </p>
        </div>
        {approvedCount === totalCount && totalCount > 0 && (
          <div className="flex items-center gap-1.5 rounded-full bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-500">
            <CheckCircle size={14} />
            All Approved
          </div>
        )}
      </div>

      {/* Task status banner */}
      {taskRunning && (
        <div
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-sm"
          style={{ background: "var(--bg-elevated)", color: "var(--turquoise)" }}
        >
          <Loader2 size={14} className="animate-spin" />
          {taskMessage || (taskAction === "extract" ? "Extracting storyboard panels..." : "Regenerating storyboard grids...")}
        </div>
      )}

      {/* Progress bar */}
      <div className="sticky top-0 z-10 -mx-4 bg-[var(--background)] px-4 py-2">
        <StoryboardProgressBar current={approvedCount} total={totalCount} />
      </div>

      {/* Scene list */}
      <div className="space-y-4">
        {scenes.map((scene, sceneIndex) => (
          <motion.div
            key={scene.sceneNumber}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: sceneIndex * 0.1 }}
          >
            <SceneGrid
              scene={scene}
              onPanelClick={(panelIndex) => handlePanelClick(sceneIndex, panelIndex)}
              onApprove={() => approveMutation.mutate()}
              onRegenerate={() => handleRegenerate(scene.sceneNumber)}
              isApproving={approveMutation.isPending}
            />
          </motion.div>
        ))}
      </div>

      {/* Extract All FAB */}
      {totalCount > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed bottom-20 left-4 right-4 md:bottom-8 md:left-auto md:right-8"
        >
          <button
            onClick={handleExtractAll}
            disabled={taskRunning}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] py-4 text-sm font-medium text-black shadow-lg disabled:opacity-50 md:w-auto md:px-6"
          >
            {taskRunning && taskAction === "extract" ? (
              <Loader2 size={18} className="animate-spin" />
            ) : (
              <CheckCircle size={18} />
            )}
            {taskRunning && taskAction === "extract"
              ? "Extracting..."
              : `Extract All (${totalCount} scenes)`}
          </button>
        </motion.div>
      )}

      {/* Panel detail modal */}
      {selectedScene !== null && (
        <PanelDetail
          panels={scenes[selectedScene].panels}
          initialIndex={selectedPanel}
          sceneNumber={scenes[selectedScene].sceneNumber}
          narration={scenes[selectedScene].narration}
          open={selectedScene !== null}
          onClose={() => setSelectedScene(null)}
          onRegenerate={(panelIndex) => {
            handleRegenerate(scenes[selectedScene].sceneNumber);
            void panelIndex; // panel-level regen not available, regenerates whole scene
          }}
          onUseThis={() => {
            setSelectedScene(null);
          }}
        />
      )}
    </div>
  );
}
