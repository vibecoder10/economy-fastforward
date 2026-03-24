"use client";

import { useState, useMemo } from "react";
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
import { getVideo, getVideoScript, type ScriptScene } from "@/lib/api";

// Mock function to get storyboard data - will be replaced with real API
function getStoryboardsForVideo(
  videoId: string,
  scripts: ScriptScene[]
): SceneData[] {
  // Generate mock scene data from scripts
  return scripts
    .filter((s) => s.scene !== null)
    .slice(0, 6) // Limit to 6 scenes for demo
    .map((script, idx) => {
      // Check if storyboards exist
      const hasStoryboards = !!(
        script.storyboard_on_off === "On" ||
        idx < 3 // First 3 scenes have storyboards for demo
      );

      return {
        sceneNumber: script.scene || idx + 1,
        title: `Scene ${script.scene || idx + 1}`,
        narration: script.scene_text || "Narration text...",
        status: hasStoryboards
          ? idx < 2
            ? "approved"
            : "pending"
          : "generating",
        panels: Array.from({ length: 9 }, (_, panelIdx) => ({
          index: panelIdx,
          url: hasStoryboards
            ? `https://picsum.photos/seed/${videoId}-${idx}-${panelIdx}/400/400`
            : null,
          prompt: `Panel ${panelIdx + 1} prompt for scene ${idx + 1}`,
        })),
      } as SceneData;
    });
}

export default function StoryboardsPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const videoId = params.videoId as string;

  // Panel detail state
  const [selectedScene, setSelectedScene] = useState<number | null>(null);
  const [selectedPanel, setSelectedPanel] = useState<number>(0);

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

  // Generate storyboard scenes from script data
  const scenes = useMemo(() => {
    if (!scripts.length) return [];
    return getStoryboardsForVideo(videoId, scripts);
  }, [videoId, scripts]);

  // Calculate progress
  const approvedCount = scenes.filter((s) => s.status === "approved").length;
  const totalCount = scenes.length;

  // Approve mutation (mock)
  const approveMutation = useMutation({
    mutationFn: async (sceneNumber: number) => {
      // TODO: Implement actual API call
      await new Promise((resolve) => setTimeout(resolve, 500));
      return { sceneNumber };
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    },
  });

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
              onApprove={() => approveMutation.mutate(scene.sceneNumber)}
              onRegenerate={() => {
                // TODO: Implement regenerate
                console.log("Regenerate scene", scene.sceneNumber);
              }}
              isApproving={
                approveMutation.isPending &&
                approveMutation.variables === scene.sceneNumber
              }
            />
          </motion.div>
        ))}
      </div>

      {/* Extract All FAB */}
      {approvedCount > 0 && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="fixed bottom-20 left-4 right-4 md:bottom-8 md:left-auto md:right-8"
        >
          <button
            onClick={() => {
              // TODO: Implement extract all
              console.log("Extract all approved scenes");
            }}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-[var(--accent)] py-4 text-sm font-medium text-black shadow-lg md:w-auto md:px-6"
          >
            <CheckCircle size={18} />
            Extract All ({approvedCount} scenes)
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
            // TODO: Implement panel regeneration
            console.log("Regenerate panel", selectedScene, panelIndex);
          }}
          onUseThis={(panelIndex) => {
            // TODO: Implement use this panel
            console.log("Use panel", selectedScene, panelIndex);
            setSelectedScene(null);
          }}
        />
      )}
    </div>
  );
}
