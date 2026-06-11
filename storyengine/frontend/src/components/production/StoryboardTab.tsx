"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { Check, Loader2, Image as ImageIcon, RefreshCw } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { StatusPill } from "@/components/ui/StatusPill";
import { getVideoScript, runPipelineStage, advanceVideo, clearStaleTask, approveStoryboard, rejectStoryboard, bulkApproveStoryboards } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import type { ScriptScene } from "@/lib/api";
import { PromptExpander } from "@/components/video-detail/prompt-expander";
import { toDisplayImageUrl } from "@/lib/utils";

interface StoryboardTabProps {
  video: any;
}

interface StoryboardSceneData {
  sceneNumber: number;
  narrationText: string;
  storyboardPrompt: string | null;
  panels: { id: string; url: string | null }[];
  selectedPanel: number;
  approved: boolean;
  hasAnyPanels: boolean;
  hasPrompt: boolean;
}

function buildScenes(scriptScenes: ScriptScene[]): StoryboardSceneData[] {
  return scriptScenes.map((s) => {
    const panels = [
      { id: `s${s.scene}-p1`, url: s.storyboard_1_url },
      { id: `s${s.scene}-p2`, url: s.storyboard_2_url },
      { id: `s${s.scene}-p3`, url: s.storyboard_3_url },
    ];
    const hasAnyPanels = panels.some((p) => !!p.url);
    return {
      sceneNumber: s.scene || 0,
      narrationText: s.scene_text || "",
      storyboardPrompt: s.storyboard_prompts,
      panels,
      selectedPanel: 0,
      approved: false,
      hasAnyPanels,
      hasPrompt: !!s.storyboard_prompts,
    };
  });
}

export function StoryboardTab({ video }: StoryboardTabProps) {
  const queryClient = useQueryClient();
  const [taskRunning, setTaskRunning] = useState(false);
  const [generating, setGenerating] = useState(false);

  const { data: scriptScenes, isLoading } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const { message: taskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: taskRunning,
    interval: 3000,
    onComplete: () => {
      setTaskRunning(false);
      setGenerating(false);
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setGenerating(false);
      alert(`Storyboard generation failed: ${error}`);
    },
  });

  const computed = useMemo(
    () => (scriptScenes ? buildScenes(scriptScenes) : []),
    [scriptScenes]
  );

  const [scenes, setScenes] = useState<StoryboardSceneData[]>([]);

  useEffect(() => {
    if (computed.length === 0) {
      setScenes([]);
      return;
    }

    setScenes((prev) =>
      computed.map((scene) => {
        const existing = prev.find((s) => s.sceneNumber === scene.sceneNumber);
        return existing
          ? {
              ...scene,
              selectedPanel: existing.selectedPanel,
              approved: existing.approved,
            }
          : scene;
      })
    );
  }, [computed]);

  const selectPanel = (sceneIdx: number, panelIdx: number) => {
    setScenes((prev) =>
      prev.map((s, i) => (i === sceneIdx ? { ...s, selectedPanel: panelIdx } : s))
    );
  };

  const approveScene = async (sceneIdx: number) => {
    const scene = scenes[sceneIdx];
    if (!scene || !scriptScenes) return;
    const scriptScene = scriptScenes.find((s) => s.scene === scene.sceneNumber);
    if (scriptScene?.id) {
      try {
        await approveStoryboard(scriptScene.id);
        queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      } catch (err) {
        alert(`Failed to approve: ${(err as Error).message}`);
        return;
      }
    }
    setScenes((prev) =>
      prev.map((s, i) => (i === sceneIdx ? { ...s, approved: true } : s))
    );
  };

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    try {
      await runPipelineStage(video.id, "storyboards");
      setTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "storyboards");
          setTaskRunning(true);
          return;
        } catch (retryErr) {
          alert(`Failed: ${(retryErr as Error).message}`);
        }
      } else {
        alert(`Failed: ${message}`);
      }
      setGenerating(false);
    }
  }, [video.id]);

  const handleApproveAll = useCallback(async () => {
    try {
      // Bulk-approve all storyboard scenes via API
      if (scriptScenes && scriptScenes.length > 0) {
        const scriptIds = scriptScenes.map((s) => s.id).filter(Boolean);
        if (scriptIds.length > 0) {
          await bulkApproveStoryboards(scriptIds);
        }
      }
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      setScenes((prev) => prev.map((s) => ({ ...s, approved: true })));
    } catch (err) {
      alert(`Failed to approve: ${(err as Error).message}`);
    }
  }, [video.id, queryClient, scriptScenes]);

  const approvedCount = scenes.filter((s) => s.approved).length;
  const totalWithPanels = scenes.filter((s) => s.hasAnyPanels).length;
  const totalWithPrompts = scenes.filter((s) => s.hasPrompt).length;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--turquoise)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading storyboards...</span>
      </div>
    );
  }

  if (!scriptScenes || scriptScenes.length === 0) {
    return (
      <GlassCard className="p-8 text-center">
        <ImageIcon size={24} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)" }} />
        <p className="text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
          No scenes available
        </p>
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Generate a script first to enable storyboard generation.
        </p>
      </GlassCard>
    );
  }

  // No storyboard prompt/image output generated yet
  if (totalWithPanels === 0 && totalWithPrompts === 0) {
    return (
      <GlassCard className="p-8 text-center">
        <ImageIcon size={24} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)" }} />
        <p className="text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
          Storyboards not generated yet
        </p>
        <p className="text-xs mb-5" style={{ color: "var(--text-tertiary)" }}>
          {scriptScenes.length} scenes ready for storyboard generation.
        </p>
        <button
          onClick={handleGenerate}
          disabled={generating || taskRunning}
          className="inline-flex items-center justify-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {(generating || taskRunning) ? <Loader2 size={16} className="animate-spin" /> : <ImageIcon size={16} />}
          {taskRunning ? (taskMessage || "Generating...") : generating ? "Starting..." : "Generate Storyboards"}
        </button>
      </GlassCard>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Approved: {approvedCount}/{scenes.length}
          </span>
          {totalWithPrompts > 0 && totalWithPanels === 0 && (
            <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
              Storyboard prompts generated. Generate storyboard images next to create grids.
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleGenerate}
            disabled={generating || taskRunning}
            className="px-4 py-2 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 disabled:opacity-50"
            style={{ background: "rgba(255, 120, 73, 0.15)", color: "var(--orange)", border: "1px solid var(--orange)" }}
          >
            {(generating || taskRunning) ? <Loader2 size={14} className="animate-spin inline mr-1" /> : <RefreshCw size={14} className="inline mr-1" />}
            {taskRunning ? (taskMessage || "Regenerating...") : "Regenerate"}
          </button>
          <button
            onClick={handleApproveAll}
            className="px-4 py-2 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            Approve All & Continue
          </button>
        </div>
      </div>

      {scenes.map((scene, sceneIdx) => (
        <GlassCard key={scene.sceneNumber} className="p-5">
          <div className="flex items-start gap-6 flex-col md:flex-row">
            <div className="flex items-start gap-3 md:w-2/5">
              <div
                className="w-3 h-3 rounded-full mt-1 shrink-0"
                style={{
                  background: scene.approved ? "var(--turquoise)" : "var(--bg-elevated)",
                  border: `2px solid ${scene.approved ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                }}
              />
              <div>
                <StatusPill label={`Scene ${scene.sceneNumber}`} color={scene.approved ? "green" : "turquoise"} size="sm" />
                <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--text-primary)" }}>
                  {scene.narrationText}
                </p>
              </div>
            </div>

            <div className="flex-1">
              {scene.storyboardPrompt && (
                <div className="mb-3">
                  <PromptExpander prompt={scene.storyboardPrompt} label="Storyboard Prompt" previewLength={120} />
                </div>
              )}
              <div className="grid grid-cols-3 gap-2">
                {scene.panels.map((panel, panelIdx) => {
                  const isSelected = scene.selectedPanel === panelIdx;
                  const isApprovedPanel = scene.approved && isSelected;
                  return (
                    <button
                      key={panel.id}
                      onClick={() => selectPanel(sceneIdx, panelIdx)}
                      className="aspect-video rounded-lg relative overflow-hidden transition-all"
                      style={{
                        background: "var(--bg-elevated)",
                        border: isSelected ? "2px solid var(--turquoise)" : "1px solid var(--border-subtle)",
                        opacity: scene.approved && !isSelected ? 0.3 : 1,
                      }}
                    >
                      {panel.url ? (
                        <img
                          src={toDisplayImageUrl(panel.url)}
                          alt={`Scene ${scene.sceneNumber} panel ${panelIdx + 1}`}
                          className="absolute inset-0 w-full h-full object-cover"
                        />
                      ) : (
                        <svg className="absolute inset-0 w-full h-full opacity-20">
                          <defs>
                            <pattern id={`sb-${panel.id}`} width="16" height="16" patternUnits="userSpaceOnUse">
                              <path d="M 16 0 L 0 0 0 16" fill="none" stroke="var(--turquoise)" strokeWidth="0.5" />
                            </pattern>
                          </defs>
                          <rect width="100%" height="100%" fill={`url(#sb-${panel.id})`} />
                        </svg>
                      )}
                      {isApprovedPanel && (
                        <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                          <div className="w-8 h-8 rounded-full flex items-center justify-center" style={{ background: "var(--turquoise)" }}>
                            <Check size={16} style={{ color: "var(--bg-void)" }} />
                          </div>
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>

              <div className="flex items-center justify-between mt-3">
                <div className="flex items-center gap-3">
                  {scene.panels.map((_, panelIdx) => (
                    <button
                      key={panelIdx}
                      onClick={() => selectPanel(sceneIdx, panelIdx)}
                      className="w-3 h-3 rounded-full transition-all"
                      style={{
                        background: scene.selectedPanel === panelIdx ? "var(--turquoise)" : "transparent",
                        border: `2px solid ${scene.selectedPanel === panelIdx ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                      }}
                    />
                  ))}
                </div>
                <button
                  onClick={() => approveScene(sceneIdx)}
                  disabled={scene.approved}
                  className="text-xs px-3 py-1 rounded-lg transition-all disabled:opacity-50"
                  style={{ border: "1px solid var(--turquoise)", color: "var(--turquoise)", background: scene.approved ? "var(--turquoise-dim)" : "transparent" }}
                >
                  {scene.approved ? "Approved" : "Approve"}
                </button>
              </div>
            </div>
          </div>
        </GlassCard>
      ))}
    </div>
  );
}
