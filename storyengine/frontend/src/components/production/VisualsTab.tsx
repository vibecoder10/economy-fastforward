"use client";

import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Play, Pause, Check, Loader2, Pencil, Image as ImageIcon } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { StatusPill } from "@/components/ui/StatusPill";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { getVideoScript, getVideoAssets } from "@/lib/api";
import type { ScriptScene as ApiScriptScene, Asset } from "@/lib/api";
import type { Video, SceneVisualGroup } from "@/lib/types";

interface VisualsTabProps {
  video: Video;
}

const STATUS_ICON: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  done: { icon: <Check size={10} />, color: "var(--green)", label: "Generated" },
  generating: { icon: <Loader2 size={10} className="animate-spin" />, color: "var(--purple)", label: "Generating" },
  pending: { icon: <ImageIcon size={10} />, color: "var(--text-tertiary)", label: "Pending" },
};

export function VisualsTab({ video }: VisualsTabProps) {
  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });
  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });

  const computedScenes = useMemo<SceneVisualGroup[]>(() => {
    if (!scriptScenes || !assets) return [];
    const totalScenes = scriptScenes.length;
    return scriptScenes.map((scene) => ({
      sceneNumber: scene.scene || 0,
      actNumber: Math.ceil((scene.scene || 1) / Math.ceil(totalScenes / 6)),
      narrationText: scene.scene_text || "",
      visualStyle: "dossier",
      composition: "wide",
      duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
      segments: assets
        .filter((a) => a.scene === scene.scene)
        .sort((a, b) => (a.image_index || 0) - (b.image_index || 0))
        .map((asset) => ({
          id: asset.id,
          segmentId: `S-${String(asset.image_index || 0).padStart(2, "0")}`,
          sentenceText: asset.sentence_text || "",
          imagePrompt: asset.image_prompt || "",
          imageUrl: asset.image_url || undefined,
          status: (asset.status === "approved" || asset.status === "Done" || asset.image_url)
            ? ("done" as const)
            : ("pending" as const),
        })),
      storyboardPanels: [scene.storyboard_1_url, scene.storyboard_2_url, scene.storyboard_3_url]
        .filter(Boolean)
        .map((url, i) => ({ id: `sb-${scene.scene}-${i}`, imageUrl: url as string })),
      storyboardApproved: false,
      selectedStoryboardPanel: undefined,
    }));
  }, [scriptScenes, assets]);

  const [scenes, setScenes] = useState<SceneVisualGroup[]>([]);
  const [storyboardOn, setStoryboardOn] = useState(false);
  const [model, setModel] = useState("nano-banana-2");
  const [styleProfile, setStyleProfile] = useState("holographic-hud");
  const [playingScene, setPlayingScene] = useState<number | null>(null);
  const [editingPrompt, setEditingPrompt] = useState<string | null>(null);

  // Sync computed scenes into local state (for edits)
  useEffect(() => {
    if (computedScenes.length > 0 && scenes.length === 0) {
      setScenes(computedScenes);
    }
  }, [computedScenes, scenes.length]);

  // Initialize storyboardOn from first scene
  useEffect(() => {
    if (scriptScenes && scriptScenes.length > 0) {
      setStoryboardOn(scriptScenes[0].storyboard_on_off === "On");
    }
  }, [scriptScenes]);

  const totalSegments = scenes.reduce((sum, s) => sum + s.segments.length, 0);
  const doneSegments = scenes.reduce((sum, s) => sum + s.segments.filter((seg) => seg.status === "done").length, 0);

  const updatePrompt = (segId: string, newPrompt: string) => {
    setScenes((prev) =>
      prev.map((scene) => ({
        ...scene,
        segments: scene.segments.map((seg) =>
          seg.id === segId ? { ...seg, imagePrompt: newPrompt } : seg
        ),
      }))
    );
  };

  const updateSentence = (segId: string, newText: string) => {
    setScenes((prev) =>
      prev.map((scene) => ({
        ...scene,
        segments: scene.segments.map((seg) =>
          seg.id === segId ? { ...seg, sentenceText: newText } : seg
        ),
      }))
    );
  };

  const updateNarration = (sceneNum: number, newText: string) => {
    setScenes((prev) =>
      prev.map((scene) =>
        scene.sceneNumber === sceneNum ? { ...scene, narrationText: newText } : scene
      )
    );
  };

  const selectStoryboardPanel = (sceneNum: number, panelIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, selectedStoryboardPanel: panelIdx } : s))
    );
  };

  const approveStoryboard = (sceneNum: number) => {
    setScenes((prev) =>
      prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, storyboardApproved: true } : s))
    );
  };

  // Group by act
  const actGroups = scenes.reduce((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {} as Record<number, SceneVisualGroup[]>);

  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--purple)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading visuals...</span>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_260px] gap-6">
      {/* Main content */}
      <div className="space-y-6">
        {/* Controls bar */}
        <div className="flex items-center justify-between flex-wrap gap-3">
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium" style={{ color: "var(--text-secondary)" }}>
              Storyboard
            </span>
            <button
              onClick={() => setStoryboardOn(!storyboardOn)}
              className="relative w-12 h-6 rounded-full transition-all"
              style={{ background: storyboardOn ? "var(--turquoise)" : "var(--bg-surface)" }}
            >
              <div
                className="w-5 h-5 rounded-full absolute top-0.5 transition-all"
                style={{
                  background: storyboardOn ? "var(--bg-void)" : "var(--text-tertiary)",
                  left: storyboardOn ? "calc(100% - 22px)" : "2px",
                }}
              />
            </button>
            <span className="text-[10px] font-mono" style={{ color: storyboardOn ? "var(--turquoise)" : "var(--text-tertiary)" }}>
              {storyboardOn ? "ON" : "OFF"}
            </span>
          </div>
        </div>

        {/* Scenes grouped by act */}
        {Object.entries(actGroups).map(([actNum, actScenes]) => (
          <div key={actNum}>
            <div className="flex items-center gap-4 mb-4">
              <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--purple)" }}>
                Act {actNum}
              </span>
              <div className="flex-1 h-px" style={{ background: "var(--purple)", opacity: 0.3 }} />
            </div>

            <div className="space-y-4">
              {actScenes.map((scene) => (
                <GlassCard key={scene.sceneNumber} className="p-5">
                  {/* Scene header */}
                  <div className="flex items-start gap-3 mb-4">
                    <SegmentBadge label={`Scene ${scene.sceneNumber}`} color="var(--purple)" />
                    <div className="flex-1">
                      <textarea
                        value={scene.narrationText}
                        onChange={(e) => updateNarration(scene.sceneNumber, e.target.value)}
                        rows={2}
                        className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                        style={{
                          color: "var(--text-primary)",
                          background: "transparent",
                          border: "1px solid transparent",
                        }}
                        onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--purple)"; }}
                        onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                      />
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{scene.visualStyle}</span>
                        <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{scene.composition}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => setPlayingScene(playingScene === scene.sceneNumber ? null : scene.sceneNumber)}
                        className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
                        style={{ background: "var(--green)", color: "var(--bg-void)" }}
                      >
                        {playingScene === scene.sceneNumber ? <Pause size={12} /> : <Play size={12} className="ml-0.5" />}
                      </button>
                      <MiniWaveform color="var(--green)" width={100} height={20} bars={25} />
                      <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{scene.duration}</span>
                    </div>
                  </div>

                  {/* Segment cards */}
                  <div className="space-y-3">
                    {scene.segments.map((seg) => {
                      const statusInfo = STATUS_ICON[seg.status];
                      const isEditing = editingPrompt === seg.id;
                      return (
                        <div
                          key={seg.id}
                          className="rounded-xl p-3 transition-all"
                          style={{
                            background: "rgba(255,255,255,0.02)",
                            border: `1px solid ${seg.status === "done" ? "rgba(0, 230, 138, 0.15)" : seg.status === "generating" ? "rgba(139, 92, 246, 0.2)" : "rgba(255,255,255,0.05)"}`,
                          }}
                        >
                          <div className="flex items-start gap-3">
                            <SegmentBadge label={seg.segmentId} color={seg.status === "done" ? "var(--green)" : seg.status === "generating" ? "var(--purple)" : undefined} />
                            <div className="flex-1 min-w-0 space-y-2">
                              <div>
                                <label className="text-[9px] uppercase tracking-wider font-medium" style={{ color: "var(--text-tertiary)" }}>
                                  Sentence Text
                                </label>
                                <input
                                  type="text"
                                  value={seg.sentenceText}
                                  onChange={(e) => updateSentence(seg.id, e.target.value)}
                                  className="w-full text-sm outline-none rounded-lg px-2 py-1 mt-0.5 transition-all"
                                  style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                                  onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                                  onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                                />
                              </div>
                              <div>
                                <div className="flex items-center gap-1.5">
                                  <label className="text-[9px] uppercase tracking-wider font-medium" style={{ color: "var(--purple)" }}>
                                    Image Prompt
                                  </label>
                                  <Pencil size={8} style={{ color: "var(--purple)", opacity: 0.5 }} />
                                </div>
                                <textarea
                                  value={seg.imagePrompt}
                                  onChange={(e) => updatePrompt(seg.id, e.target.value)}
                                  rows={isEditing ? 4 : 2}
                                  className="w-full text-[12px] font-mono outline-none rounded-lg px-2 py-1 mt-0.5 resize-none transition-all"
                                  style={{ color: "var(--text-secondary)", background: "transparent", border: "1px solid transparent" }}
                                  onFocus={(e) => {
                                    setEditingPrompt(seg.id);
                                    e.target.style.background = "var(--bg-elevated)";
                                    e.target.style.borderColor = "var(--purple)";
                                  }}
                                  onBlur={(e) => {
                                    setEditingPrompt(null);
                                    e.target.style.background = "transparent";
                                    e.target.style.borderColor = "transparent";
                                  }}
                                />
                              </div>
                            </div>
                            <div className="shrink-0 flex flex-col items-center gap-1.5">
                              <div
                                className="w-20 h-14 rounded-lg relative flex items-center justify-center overflow-hidden"
                                style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)" }}
                              >
                                {seg.imageUrl ? (
                                  <img src={seg.imageUrl} alt={seg.segmentId} className="absolute inset-0 w-full h-full object-cover" />
                                ) : (
                                  <svg className="absolute inset-0 w-full h-full opacity-15">
                                    <defs>
                                      <pattern id={`vg-${seg.id}`} width="12" height="12" patternUnits="userSpaceOnUse">
                                        <path d="M 12 0 L 0 0 0 12" fill="none" stroke="var(--purple)" strokeWidth="0.3" />
                                      </pattern>
                                    </defs>
                                    <rect width="100%" height="100%" fill={`url(#vg-${seg.id})`} />
                                  </svg>
                                )}
                                {seg.status === "done" && (
                                  <div className="absolute top-1 right-1 w-4 h-4 rounded-full flex items-center justify-center" style={{ background: "var(--green)" }}>
                                    <Check size={8} style={{ color: "var(--bg-void)" }} />
                                  </div>
                                )}
                                {seg.status === "generating" && (
                                  <Loader2 size={14} className="animate-spin" style={{ color: "var(--purple)" }} />
                                )}
                              </div>
                              <span className="text-[9px] font-mono flex items-center gap-1" style={{ color: statusInfo.color }}>
                                {statusInfo.icon}
                                {statusInfo.label}
                              </span>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Storyboard section (conditional) */}
                  {storyboardOn && scene.storyboardPanels && scene.storyboardPanels.length > 0 && (
                    <motion.div
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.3 }}
                      className="mt-4 pt-4"
                      style={{ borderTop: "1px solid var(--border-subtle)" }}
                    >
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <StatusPill label="Storyboard" color={scene.storyboardApproved ? "green" : "turquoise"} size="sm" />
                          {scene.storyboardApproved && (
                            <span className="text-[10px] font-mono" style={{ color: "var(--green)" }}>Approved</span>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <button
                            onClick={() => approveStoryboard(scene.sceneNumber)}
                            disabled={scene.storyboardApproved}
                            className="text-[10px] px-2.5 py-1 rounded-lg transition-all disabled:opacity-40"
                            style={{ border: "1px solid var(--turquoise)", color: "var(--turquoise)" }}
                          >
                            {scene.storyboardApproved ? "Approved" : "Approve"}
                          </button>
                          <button
                            className="text-[10px] px-2.5 py-1 rounded-lg"
                            style={{ border: "1px solid var(--border)", color: "var(--text-secondary)" }}
                          >
                            Regenerate
                          </button>
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-1.5">
                        {scene.storyboardPanels.map((panel, panelIdx) => {
                          const isSelected = scene.selectedStoryboardPanel === panelIdx;
                          const isApproved = scene.storyboardApproved && isSelected;
                          return (
                            <button
                              key={panel.id}
                              onClick={() => selectStoryboardPanel(scene.sceneNumber, panelIdx)}
                              className="aspect-video rounded relative overflow-hidden transition-all"
                              style={{
                                background: "var(--bg-elevated)",
                                border: isSelected ? "2px solid var(--turquoise)" : "1px solid var(--border-subtle)",
                                opacity: scene.storyboardApproved && !isSelected ? 0.3 : 1,
                              }}
                            >
                              {panel.imageUrl ? (
                                <img src={panel.imageUrl} alt={`Storyboard ${panelIdx + 1}`} className="absolute inset-0 w-full h-full object-cover" />
                              ) : (
                                <svg className="absolute inset-0 w-full h-full opacity-15">
                                  <defs>
                                    <pattern id={`sb-${panel.id}`} width="10" height="10" patternUnits="userSpaceOnUse">
                                      <path d="M 10 0 L 0 0 0 10" fill="none" stroke="var(--turquoise)" strokeWidth="0.3" />
                                    </pattern>
                                  </defs>
                                  <rect width="100%" height="100%" fill={`url(#sb-${panel.id})`} />
                                </svg>
                              )}
                              {isApproved && (
                                <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                                  <div className="w-6 h-6 rounded-full flex items-center justify-center" style={{ background: "var(--turquoise)" }}>
                                    <Check size={12} style={{ color: "var(--bg-void)" }} />
                                  </div>
                                </div>
                              )}
                            </button>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-1 mt-2">
                        {scene.storyboardPanels.map((_, panelIdx) => (
                          <button
                            key={panelIdx}
                            onClick={() => selectStoryboardPanel(scene.sceneNumber, panelIdx)}
                            className="flex items-center justify-center text-[9px] font-mono transition-all"
                            style={{
                              width: 18, height: 18, borderRadius: "50%",
                              background: scene.selectedStoryboardPanel === panelIdx ? "var(--turquoise)" : "transparent",
                              color: scene.selectedStoryboardPanel === panelIdx ? "var(--bg-void)" : "var(--text-tertiary)",
                              border: `1.5px solid ${scene.selectedStoryboardPanel === panelIdx ? "var(--turquoise)" : "var(--text-tertiary)"}`,
                            }}
                          >
                            {panelIdx + 1}
                          </button>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </GlassCard>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Right sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-4" style={{ color: "var(--text-secondary)" }}>
            Generation Stats
          </h3>
          <div className="flex justify-center mb-4">
            <ProgressRing value={totalSegments > 0 ? (doneSegments / totalSegments) * 100 : 0} size={90} color="var(--purple)" strokeWidth={7}>
              <span className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>{doneSegments}</span>
              <span className="text-[8px] uppercase" style={{ color: "var(--text-secondary)" }}>/ {totalSegments}</span>
            </ProgressRing>
          </div>
          <FilterSelect label="Model" options={[{ value: "nano-banana-2", label: "Nano Banana 2" }, { value: "seed-dream-4.5", label: "Seed Dream 4.5" }]} value={model} onChange={setModel} className="mb-3" />
          <FilterSelect label="Style Profile" options={[{ value: "holographic-hud", label: "Holographic HUD" }, { value: "cinematic-illustration", label: "Cinematic Illustration" }, { value: "cinematic-dossier", label: "Cinematic Dossier" }, { value: "clay-mannequin", label: "Clay Mannequin" }]} value={styleProfile} onChange={setStyleProfile} className="mb-3" />
          <div className="pt-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <p className="text-xs font-semibold mb-1" style={{ color: "var(--text-secondary)" }}>Cost Tracker</p>
            <p className="text-lg font-mono" style={{ color: "var(--gold)" }}>
              ${(doneSegments * 0.025).toFixed(3)} <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>/ ${(totalSegments * 0.025).toFixed(2)}</span>
            </p>
          </div>
        </GlassCard>
      </div>
    </div>
  );
}
