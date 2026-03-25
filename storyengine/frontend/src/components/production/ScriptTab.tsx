"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Merge, Trash2, Plus, Volume2, Library, Wand2, Play, Pause } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { FilterSelect } from "@/components/ui/FilterSelect";
import { MOCK_SCRIPT_SCENES } from "@/lib/mock-data";
import type { Video, ScriptScene } from "@/lib/types";

interface ScriptTabProps {
  video: Video;
}

// SFX library presets
const SFX_LIBRARY = [
  { value: "", label: "— No SFX —" },
  { value: "ambient-tension", label: "Ambient Tension" },
  { value: "war-drums", label: "War Drums (distant)" },
  { value: "paper-shuffle", label: "Paper Shuffle" },
  { value: "door-close", label: "Heavy Door Close" },
  { value: "crowd-murmur", label: "Crowd Murmur" },
  { value: "typing", label: "Keyboard Typing" },
  { value: "explosion-distant", label: "Distant Explosion" },
  { value: "clock-ticking", label: "Clock Ticking" },
  { value: "heartbeat", label: "Heartbeat" },
  { value: "wind", label: "Desert Wind" },
  { value: "helicopter", label: "Helicopter Flyover" },
  { value: "news-broadcast", label: "News Broadcast Chatter" },
  { value: "custom", label: "✦ Generate Custom..." },
];

interface SceneState extends ScriptScene {
  soundMode: "none" | "library" | "custom";
  soundLibraryValue: string;
  soundCustomPrompt: string;
}

export function ScriptTab({ video }: ScriptTabProps) {
  const [scenes, setScenes] = useState<SceneState[]>(
    MOCK_SCRIPT_SCENES.map((s) => ({
      ...s,
      soundMode: "none",
      soundLibraryValue: "",
      soundCustomPrompt: "",
    }))
  );
  const [collapsedActs, setCollapsedActs] = useState<Record<number, boolean>>({});
  const [playingScene, setPlayingScene] = useState<number | null>(null);

  // Group scenes by act
  const actGroups = scenes.reduce((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {} as Record<number, SceneState[]>);

  const toggleAct = (actNum: number) => {
    setCollapsedActs((prev) => ({ ...prev, [actNum]: !prev[actNum] }));
  };

  const updateNarration = (sceneNum: number, text: string) => {
    setScenes((prev) => prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, narrationText: text } : s)));
  };

  const updateSource = (sceneNum: number, srcIdx: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum || !s.sources) return s;
        const newSources = [...s.sources];
        newSources[srcIdx] = text;
        return { ...s, sources: newSources };
      })
    );
  };

  const updateVisualStyle = (sceneNum: number, style: string) => {
    setScenes((prev) => prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, visualStyle: style } : s)));
  };

  const updateComposition = (sceneNum: number, comp: string) => {
    setScenes((prev) => prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, composition: comp } : s)));
  };

  // Merge scene into the one above (append text, delete this scene)
  const mergeUp = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      if (idx <= 0) return prev;
      const merged = [...prev];
      merged[idx - 1] = {
        ...merged[idx - 1],
        narrationText: merged[idx - 1].narrationText + " " + merged[idx].narrationText,
      };
      merged.splice(idx, 1);
      return merged;
    });
  };

  // Delete a scene
  const deleteScene = (sceneNum: number) => {
    setScenes((prev) => prev.filter((s) => s.sceneNumber !== sceneNum));
  };

  // Add a new scene after the given one
  const addSceneAfter = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      const actNum = prev[idx]?.actNumber || 1;
      const newScene: SceneState = {
        sceneNumber: Math.max(...prev.map((s) => s.sceneNumber)) + 1,
        actNumber: actNum,
        narrationText: "",
        visualStyle: "dossier",
        composition: "medium",
        sources: [],
        imageGenerated: false,
        soundMode: "none",
        soundLibraryValue: "",
        soundCustomPrompt: "",
      };
      const result = [...prev];
      result.splice(idx + 1, 0, newScene);
      return result;
    });
  };

  // Sound controls
  const updateSoundMode = (sceneNum: number, mode: "none" | "library" | "custom") => {
    setScenes((prev) => prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, soundMode: mode } : s)));
  };

  const updateSoundLibrary = (sceneNum: number, value: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        if (value === "custom") return { ...s, soundMode: "custom", soundLibraryValue: "" };
        return { ...s, soundLibraryValue: value, soundMode: value ? "library" : "none" };
      })
    );
  };

  const updateSoundPrompt = (sceneNum: number, prompt: string) => {
    setScenes((prev) => prev.map((s) => (s.sceneNumber === sceneNum ? { ...s, soundCustomPrompt: prompt } : s)));
  };

  const totalScenes = scenes.length;
  const wordCount = scenes.reduce((sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length, 0);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
      {/* Script scenes */}
      <div className="space-y-4">
        {Object.entries(actGroups).map(([actNum, actScenes]) => {
          const isCollapsed = collapsedActs[Number(actNum)];
          const actWordCount = actScenes.reduce((sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length, 0);

          return (
            <div key={actNum}>
              {/* Act header — clickable to collapse */}
              <button
                onClick={() => toggleAct(Number(actNum))}
                className="flex items-center gap-3 w-full mb-3 group"
              >
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                <div className="flex items-center gap-2 px-3 py-1 rounded-full transition-all"
                  style={{ background: isCollapsed ? "rgba(255, 120, 73, 0.1)" : "transparent" }}>
                  {isCollapsed ? (
                    <ChevronRight size={14} style={{ color: "var(--orange)" }} />
                  ) : (
                    <ChevronDown size={14} style={{ color: "var(--orange)" }} />
                  )}
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--orange)" }}>
                    Act {actNum}
                  </span>
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                    {actScenes.length} scenes · {actWordCount} words
                  </span>
                </div>
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
              </button>

              {/* Scenes (collapsible) */}
              {!isCollapsed && (
                <div className="space-y-3">
                  {actScenes.map((scene, sceneIdx) => (
                    <GlassCard
                      key={scene.sceneNumber}
                      className="p-4"
                      style={{
                        borderLeftWidth: 3,
                        borderLeftColor: scene.imageGenerated ? "var(--turquoise)" : "var(--orange)",
                      }}
                    >
                      {/* Scene header row */}
                      <div className="flex items-center gap-2 mb-2">
                        <SegmentBadge
                          label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                          color={scene.imageGenerated ? undefined : "var(--orange)"}
                        />
                        {/* Play button */}
                        <button
                          onClick={() => setPlayingScene(playingScene === scene.sceneNumber ? null : scene.sceneNumber)}
                          className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                          style={{ background: "var(--green)", color: "var(--bg-void)" }}
                        >
                          {playingScene === scene.sceneNumber ? <Pause size={10} /> : <Play size={10} className="ml-0.5" />}
                        </button>
                        <MiniWaveform color="var(--green)" width={60} height={16} bars={15} />

                        <div className="flex-1" />

                        {/* Scene actions */}
                        <button
                          onClick={() => mergeUp(scene.sceneNumber)}
                          title="Merge into scene above"
                          className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          <Merge size={12} />
                        </button>
                        <button
                          onClick={() => addSceneAfter(scene.sceneNumber)}
                          title="Add scene below"
                          className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          <Plus size={12} />
                        </button>
                        <button
                          onClick={() => deleteScene(scene.sceneNumber)}
                          title="Delete scene"
                          className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                          style={{ color: "var(--text-tertiary)" }}
                        >
                          <Trash2 size={12} />
                        </button>
                      </div>

                      {/* Narration text — editable */}
                      <textarea
                        value={scene.narrationText}
                        onChange={(e) => updateNarration(scene.sceneNumber, e.target.value)}
                        rows={Math.max(2, Math.ceil(scene.narrationText.length / 100))}
                        className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-3 py-2 transition-all"
                        style={{
                          color: "var(--text-primary)",
                          background: "transparent",
                          border: "1px solid transparent",
                        }}
                        onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--orange)"; }}
                        onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                      />

                      {/* Sources — editable */}
                      {scene.sources && scene.sources.length > 0 && (
                        <div className="flex gap-2 mt-1 flex-wrap items-center">
                          {scene.sources.map((src, srcIdx) => (
                            <input
                              key={srcIdx}
                              type="text"
                              value={src}
                              onChange={(e) => updateSource(scene.sceneNumber, srcIdx, e.target.value)}
                              className="text-[10px] font-mono px-2 py-0.5 rounded outline-none w-auto"
                              style={{
                                background: "var(--yellow-dim)",
                                color: "var(--yellow)",
                                border: "1px solid transparent",
                                width: `${Math.max(src.length * 7 + 20, 60)}px`,
                              }}
                              onFocus={(e) => { e.target.style.borderColor = "var(--yellow)"; }}
                              onBlur={(e) => { e.target.style.borderColor = "transparent"; }}
                            />
                          ))}
                        </div>
                      )}

                      {/* Visual style + composition — editable */}
                      <div className="flex items-center gap-2 mt-2">
                        <input
                          type="text"
                          value={scene.visualStyle}
                          onChange={(e) => updateVisualStyle(scene.sceneNumber, e.target.value)}
                          className="text-[10px] font-mono px-2 py-0.5 rounded outline-none w-20"
                          style={{ color: "var(--text-tertiary)", background: "transparent", border: "1px solid transparent" }}
                          onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                          onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                        />
                        <input
                          type="text"
                          value={scene.composition}
                          onChange={(e) => updateComposition(scene.sceneNumber, e.target.value)}
                          className="text-[10px] font-mono px-2 py-0.5 rounded outline-none w-24"
                          style={{ color: "var(--text-tertiary)", background: "transparent", border: "1px solid transparent" }}
                          onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                          onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                        />
                      </div>

                      {/* Sound FX section — inline */}
                      <div className="mt-3 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                        <div className="flex items-center gap-2 flex-wrap">
                          <Volume2 size={12} style={{ color: "var(--gold)", opacity: 0.6 }} />
                          <span className="text-[9px] uppercase tracking-wider font-medium" style={{ color: "var(--gold)" }}>
                            SFX
                          </span>

                          {/* Library selector */}
                          <select
                            value={scene.soundMode === "library" ? scene.soundLibraryValue : scene.soundMode === "custom" ? "custom" : ""}
                            onChange={(e) => updateSoundLibrary(scene.sceneNumber, e.target.value)}
                            className="text-[11px] font-mono px-2 py-1 rounded-lg outline-none flex-1 max-w-[200px]"
                            style={{
                              background: "var(--bg-elevated)",
                              color: "var(--text-secondary)",
                              border: "1px solid var(--border-subtle)",
                            }}
                          >
                            {SFX_LIBRARY.map((sfx) => (
                              <option key={sfx.value} value={sfx.value}>{sfx.label}</option>
                            ))}
                          </select>

                          {scene.soundMode === "library" && scene.soundLibraryValue && (
                            <button
                              className="w-5 h-5 rounded-full flex items-center justify-center"
                              style={{ background: "var(--green)", color: "var(--bg-void)" }}
                              title="Preview sound"
                            >
                              <Play size={8} className="ml-px" />
                            </button>
                          )}
                        </div>

                        {/* Custom prompt — only when "Generate Custom" selected */}
                        {scene.soundMode === "custom" && (
                          <div className="mt-2 flex items-start gap-2">
                            <Wand2 size={12} style={{ color: "var(--purple)", marginTop: 6 }} />
                            <textarea
                              value={scene.soundCustomPrompt}
                              onChange={(e) => updateSoundPrompt(scene.sceneNumber, e.target.value)}
                              placeholder="Describe the sound effect you want AI to generate..."
                              rows={2}
                              className="flex-1 text-[11px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                              style={{
                                color: "var(--text-secondary)",
                                background: "var(--bg-elevated)",
                                border: "1px solid var(--purple-dim)",
                              }}
                              onFocus={(e) => { e.target.style.borderColor = "var(--purple)"; }}
                              onBlur={(e) => { e.target.style.borderColor = "var(--purple-dim)"; }}
                            />
                          </div>
                        )}
                      </div>
                    </GlassCard>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Metadata sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
            Script Details
          </h3>
          <div className="space-y-3">
            {[
              { label: "Framework", value: video.framework || "—" },
              { label: "Word Count", value: String(wordCount) },
              { label: "Scene Count", value: String(totalScenes) },
              { label: "Target Length", value: `${video.videoLengthMin || 0} min` },
              { label: "Est. Cost", value: `$${(video.estimatedCost || 0).toFixed(2)}` },
            ].map((row) => (
              <div key={row.label} className="flex items-center justify-between">
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{row.label}</span>
                <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>{row.value}</span>
              </div>
            ))}
          </div>
        </GlassCard>

        <GlassCard className="p-4">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--gold)" }}>
            SFX Library
          </h3>
          <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>
            Select from presets or generate custom SFX per scene. Library sounds are free, custom generation costs ~$0.02 each.
          </p>
          <div className="flex items-center gap-2 text-[10px] font-mono">
            <Library size={12} style={{ color: "var(--gold)" }} />
            <span style={{ color: "var(--text-secondary)" }}>{SFX_LIBRARY.length - 2} presets</span>
          </div>
        </GlassCard>

        <div className="space-y-2">
          <ActionButton variant="filled" className="w-full">Approve Script</ActionButton>
          <ActionButton variant="outline" className="w-full">Request Revision</ActionButton>
          <ActionButton variant="warning" className="w-full">Regenerate</ActionButton>
        </div>
      </div>
    </div>
  );
}
