"use client";

import { useState, useMemo, useCallback } from "react";
import { Play, Pause, Volume2, Zap, SkipForward, Loader2, ChevronRight } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { ActionButton } from "@/components/ui/ActionButton";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { getVideoScript, getVideoAssets, runPipelineStage, advanceVideo, clearStaleTask, getDefaultSoundCurationPrompt, updateVideo } from "@/lib/api";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { ScriptScene, Asset } from "@/lib/api";

interface SoundTabProps {
  video: any;
  onAdvanced?: () => void;
  /** The ONE page-level task watcher (S9-1/C19a). */
  taskWatcher: TaskWatcherBridge;
}

interface SoundScene {
  sceneNumber: number;
  narrationText: string;
  soundPrompt: string;
  sfxStatus: "generated" | "pending" | "skipped";
  soundUrl: string | null;
  volume: number;
}

const SFX_STATUS_MAP: Record<string, { label: string; color: string }> = {
  generated: { label: "Generated", color: "green" },
  pending: { label: "Pending", color: "orange" },
  skipped: { label: "Skipped", color: "purple" },
};

function buildSoundScenes(scripts: ScriptScene[], assets: Asset[]): SoundScene[] {
  return scripts.map((s) => {
    // Find first asset for this scene that has sound data
    const sceneAssets = assets.filter((a) => a.scene === s.scene);
    const withSound = sceneAssets.find((a) => a.sound_prompt);

    const prompt = withSound?.sound_prompt || "";
    const isSkip = !prompt || prompt === "SKIP" || prompt === "SILENCE";
    const hasUrl = !!withSound?.sound_effect_url;

    return {
      sceneNumber: s.scene || 0,
      narrationText: s.scene_text || "",
      soundPrompt: prompt || "No prompt",
      sfxStatus: isSkip ? "skipped" : hasUrl ? "generated" : "pending",
      soundUrl: withSound?.sound_effect_url || null,
      volume: withSound?.sound_volume ?? 15,
    };
  });
}

export function SoundTab({ video, onAdvanced, taskWatcher }: SoundTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [taskRunning, setTaskRunning] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [playingScene, setPlayingScene] = useState<number | null>(null);

  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });

  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const { message: taskMessage } = useSharedTaskWatcher({
    bridge: taskWatcher,
    enabled: taskRunning,
    onComplete: () => {
      setTaskRunning(false);
      setGenerating(false);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    },
    onFailed: (error) => {
      setTaskRunning(false);
      setGenerating(false);
      toast.error(`Sound generation failed: ${error}`);
    },
  });

  const scenes = useMemo(
    () => (scriptScenes && assets ? buildSoundScenes(scriptScenes, assets) : []),
    [scriptScenes, assets]
  );

  const [volumes, setVolumes] = useState<Record<number, number>>({});
  const getVolume = (sceneNum: number, defaultVol: number) =>
    volumes[sceneNum] ?? defaultVol;

  const handleVolumeChange = (sceneNum: number, value: number) => {
    setVolumes((prev) => ({ ...prev, [sceneNum]: value }));
  };

  const handleGenerate = useCallback(async (stage: string) => {
    setGenerating(true);
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
          toast.error(`Failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Failed: ${message}`);
      }
      setGenerating(false);
    }
  }, [video.id]);

  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, queryClient, onAdvanced]);

  const handleApproveAndContinue = useCallback(async () => {
    try {
      await advanceVideo(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    }
  }, [video.id, queryClient, onAdvanced]);

  const isLoading = loadingScripts || loadingAssets;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--gold)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading sound data...</span>
      </div>
    );
  }

  if (!scriptScenes || scriptScenes.length === 0) {
    return (
      <GlassCard className="p-8 text-center">
        <Volume2 size={24} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)" }} />
        <p className="text-sm font-medium mb-1" style={{ color: "var(--text-secondary)" }}>
          No scenes available
        </p>
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Generate a script first to enable sound design.
        </p>
      </GlassCard>
    );
  }

  const generatedCount = scenes.filter((s) => s.sfxStatus === "generated").length;
  const skippedCount = scenes.filter((s) => s.sfxStatus === "skipped").length;
  const pendingCount = scenes.filter((s) => s.sfxStatus === "pending").length;
  const estimatedCost = (generatedCount + pendingCount) * 0.05;

  // No prompts generated yet
  const hasAnyPrompts = scenes.some((s) => s.sfxStatus !== "skipped" && s.soundPrompt !== "No prompt");

  return (
    <>
    <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
          <span>{generatedCount}/{scenes.length} prompts</span>
          <span>{scenes.filter((s) => s.sfxStatus === "generated").length} effects</span>
        </div>
        <button onClick={handleAdvanceStage} disabled={advancing}
          className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
          {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
          Advance Stage <ChevronRight size={12} />
        </button>
      </div>
    </div>
    {/* Sound System Prompt */}
    <SystemPromptEditor
      label="Sound System Prompt"
      currentValue={video.sound_system_prompt}
      onSave={async (text) => {
        await updateVideo(video.id, { sound_system_prompt: text || null });
        queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      }}
      onReset={async () => {
        const res = await getDefaultSoundCurationPrompt();
        await updateVideo(video.id, { sound_system_prompt: null });
        queryClient.invalidateQueries({ queryKey: ["video", video.id] });
        return res.prompt;
      }}
    />

    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Scene list */}
      <div className="space-y-3">
        {scenes.map((scene) => {
          const sfx = SFX_STATUS_MAP[scene.sfxStatus];
          const vol = getVolume(scene.sceneNumber, scene.volume);
          const isPlaying = playingScene === scene.sceneNumber;
          return (
            <GlassCard
              key={scene.sceneNumber}
              className="p-4"
              style={{
                borderLeftWidth: 3,
                borderLeftColor:
                  scene.sfxStatus === "generated"
                    ? "var(--green)"
                    : scene.sfxStatus === "pending"
                      ? "var(--orange)"
                      : "var(--border-subtle)",
              }}
            >
              <div className="flex items-start gap-3">
                <SegmentBadge
                  label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                />
                <div className="flex-1 min-w-0">
                  <p
                    className="text-sm leading-relaxed mb-2 line-clamp-2"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {scene.narrationText}
                  </p>

                  {/* Sound prompt */}
                  <div
                    className="flex items-center gap-2 px-3 py-2 rounded-lg mb-2"
                    style={{ background: "var(--bg-elevated)" }}
                  >
                    <Volume2
                      size={12}
                      style={{
                        color:
                          scene.sfxStatus === "skipped"
                            ? "var(--text-tertiary)"
                            : "var(--gold)",
                      }}
                    />
                    <span
                      className="text-xs font-mono flex-1"
                      style={{
                        color:
                          scene.sfxStatus === "skipped"
                            ? "var(--text-tertiary)"
                            : "var(--text-secondary)",
                        fontStyle:
                          scene.sfxStatus === "skipped"
                            ? "italic"
                            : "normal",
                      }}
                    >
                      {scene.soundPrompt}
                    </span>
                  </div>

                  <div className="flex items-center gap-3">
                    <StatusPill label={sfx.label} color={sfx.color} />

                    {scene.sfxStatus !== "skipped" && (
                      <div className="flex items-center gap-2 flex-1">
                        <span
                          className="text-[10px] font-mono"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          Vol
                        </span>
                        <input
                          type="range"
                          min={0}
                          max={100}
                          value={vol}
                          onChange={(e) =>
                            handleVolumeChange(scene.sceneNumber, Number(e.target.value))
                          }
                          className="flex-1 h-1 appearance-none rounded-full"
                          style={{ accentColor: "var(--turquoise)" }}
                        />
                        <span
                          className="text-[10px] font-mono w-8 text-right"
                          style={{ color: "var(--text-secondary)" }}
                        >
                          {vol}%
                        </span>
                      </div>
                    )}

                    {scene.sfxStatus === "generated" && scene.soundUrl && (
                      <button
                        onClick={() => setPlayingScene(isPlaying ? null : scene.sceneNumber)}
                        className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
                        style={{
                          background: "var(--turquoise-dim)",
                          color: "var(--turquoise)",
                        }}
                      >
                        {isPlaying ? <Pause size={10} /> : <Play size={10} />}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </GlassCard>
          );
        })}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3
            className="text-xs font-semibold uppercase tracking-wider mb-3"
            style={{ color: "var(--text-secondary)" }}
          >
            Sound Stats
          </h3>
          <div className="space-y-3">
            {[
              { label: "Total Scenes", value: String(scenes.length) },
              { label: "SFX Generated", value: String(generatedCount), color: "var(--green)" },
              { label: "Skipped", value: String(skippedCount), color: "var(--text-tertiary)" },
              { label: "Pending", value: String(pendingCount), color: "var(--orange)" },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {row.label}
                </span>
                <span
                  className="text-sm font-mono font-medium"
                  style={{ color: row.color || "var(--text-primary)" }}
                >
                  {row.value}
                </span>
              </div>
            ))}
          </div>

          <div
            className="pt-3 mt-3"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            <p
              className="text-xs font-semibold mb-1"
              style={{ color: "var(--text-secondary)" }}
            >
              Estimated Cost
            </p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${estimatedCost.toFixed(2)}
            </p>
          </div>
        </GlassCard>

        <div className="space-y-2">
          {!hasAnyPrompts ? (
            <ActionButton
              startsGeneration
              variant="filled"
              icon={generating || taskRunning ? Loader2 : Zap}
              className="w-full"
              onClick={() => handleGenerate("sound-prompts")}
              disabled={generating || taskRunning}
            >
              {taskRunning ? (taskMessage || "Generating...") : "Generate Sound Prompts"}
            </ActionButton>
          ) : (
            <>
              <ActionButton
                startsGeneration
                variant="filled"
                icon={generating || taskRunning ? Loader2 : Zap}
                className="w-full"
                onClick={() => handleGenerate("sound-effects")}
                disabled={generating || taskRunning}
              >
                {taskRunning ? (taskMessage || "Generating...") : "Generate All SFX"}
              </ActionButton>
              <ActionButton
                variant="outline"
                icon={SkipForward}
                className="w-full"
                onClick={handleApproveAndContinue}
              >
                Approve & Continue
              </ActionButton>
            </>
          )}
        </div>
      </div>
    </div>
    </>
  );
}
