"use client";

import { useState, useMemo, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown, ChevronRight, Merge, Trash2, Plus, Volume2,
  Library, Wand2, Play, Pause, Layers, Mic, Pencil, Loader2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { getVideoScript } from "@/lib/api";
import type { ScriptScene as ApiScriptScene } from "@/lib/api";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { StatusPill } from "@/components/ui/StatusPill";

interface ScriptTabProps {
  video: any;
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
];

// Split narration into sentences
function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?—])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

interface SentenceState {
  text: string;
  sfxMode: "none" | "library" | "elevenlabs" | "custom";
  sfxLibraryValue: string;
  sfxCustomPrompt: string;
}

interface SceneState {
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  visualStyle: string;
  composition: string;
  sources?: string[];
  imageGenerated?: boolean;
  voiceOverUrl?: string | null;
  voiceStatus?: string | null;
  scriptStatus?: string | null;
  tone?: string | null;
  sentences: SentenceState[];
}

function initFromApi(apiScenes: ApiScriptScene[]): SceneState[] {
  const total = apiScenes.length;
  const actsCount = Math.min(total, 6);
  return apiScenes.map((s) => ({
    sceneNumber: s.scene || 0,
    actNumber: Math.ceil((s.scene || 1) / Math.ceil(total / actsCount)),
    narrationText: s.scene_text || "",
    visualStyle: "dossier",
    composition: "wide",
    sources: s.sources ? (() => { try { return JSON.parse(s.sources!); } catch { return []; } })() : [],
    imageGenerated: false,
    voiceOverUrl: s.voice_over_url,
    voiceStatus: s.voice_status,
    scriptStatus: s.script_status,
    tone: s.tone,
    sentences: splitSentences(s.scene_text || "").map((text) => ({
      text,
      sfxMode: "none" as const,
      sfxLibraryValue: "",
      sfxCustomPrompt: "",
    })),
  }));
}

export function ScriptTab({ video }: ScriptTabProps) {
  const { data: apiScenes, isLoading } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
    enabled: !!video.id,
  });

  const computed = useMemo(() => apiScenes ? initFromApi(apiScenes) : [], [apiScenes]);

  const [scenes, setScenes] = useState<SceneState[]>([]);
  const [collapsedActs, setCollapsedActs] = useState<Record<number, boolean>>({});
  const [expandedScenes, setExpandedScenes] = useState<Set<number>>(new Set());
  const [playingScene, setPlayingScene] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Sync API data into local state (once)
  useEffect(() => {
    if (computed.length > 0 && scenes.length === 0) {
      setScenes(computed);
    }
  }, [computed, scenes.length]);

  // Audio playback
  useEffect(() => {
    if (playingScene !== null) {
      const scene = scenes.find((s) => s.sceneNumber === playingScene);
      if (scene?.voiceOverUrl) {
        if (audioRef.current) audioRef.current.pause();
        audioRef.current = new Audio(scene.voiceOverUrl);
        audioRef.current.play().catch(() => {});
        audioRef.current.onended = () => setPlayingScene(null);
      }
    } else {
      if (audioRef.current) { audioRef.current.pause(); audioRef.current = null; }
    }
    return () => { if (audioRef.current) audioRef.current.pause(); };
  }, [playingScene, scenes]);

  // Group by act
  const actGroups = scenes.reduce((acc, scene) => {
    if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
    acc[scene.actNumber].push(scene);
    return acc;
  }, {} as Record<number, SceneState[]>);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--orange)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading script...</span>
      </div>
    );
  }

  const toggleAct = (actNum: number) => {
    setCollapsedActs((prev) => ({ ...prev, [actNum]: !prev[actNum] }));
  };

  const toggleExpand = (sceneNum: number) => {
    setExpandedScenes((prev) => {
      const next = new Set(prev);
      if (next.has(sceneNum)) next.delete(sceneNum);
      else next.add(sceneNum);
      return next;
    });
  };

  // Update unified narration text (collapsed view edit)
  const updateNarration = (sceneNum: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = splitSentences(text).map((t, i) => ({
          ...(s.sentences[i] || { sfxMode: "none" as const, sfxLibraryValue: "", sfxCustomPrompt: "" }),
          text: t,
        }));
        return { ...s, narrationText: text, sentences: newSentences };
      })
    );
  };

  // Update individual sentence text (expanded view edit)
  const updateSentence = (sceneNum: number, sentIdx: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, text } : sent
        );
        return {
          ...s,
          sentences: newSentences,
          narrationText: newSentences.map((sent) => sent.text).join(" "),
        };
      })
    );
  };

  // Merge sentence into previous
  const mergeSentenceUp = (sceneNum: number, sentIdx: number) => {
    if (sentIdx === 0) return;
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences[sentIdx - 1] = {
          ...newSentences[sentIdx - 1],
          text: newSentences[sentIdx - 1].text + " " + newSentences[sentIdx].text,
        };
        newSentences.splice(sentIdx, 1);
        return {
          ...s,
          sentences: newSentences,
          narrationText: newSentences.map((sent) => sent.text).join(" "),
        };
      })
    );
  };

  // Delete sentence
  const deleteSentence = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.filter((_, i) => i !== sentIdx);
        return {
          ...s,
          sentences: newSentences,
          narrationText: newSentences.map((sent) => sent.text).join(" "),
        };
      })
    );
  };

  // Add sentence after
  const addSentenceAfter = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences.splice(sentIdx + 1, 0, {
          text: "",
          sfxMode: "none",
          sfxLibraryValue: "",
          sfxCustomPrompt: "",
        });
        return {
          ...s,
          sentences: newSentences,
          narrationText: newSentences.map((sent) => sent.text).join(" "),
        };
      })
    );
  };

  // SFX controls per sentence
  const updateSfxMode = (sceneNum: number, sentIdx: number, mode: SentenceState["sfxMode"]) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, sfxMode: mode } : sent
        );
        return { ...s, sentences: newSentences };
      })
    );
  };

  const updateSfxLibrary = (sceneNum: number, sentIdx: number, value: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, sfxLibraryValue: value, sfxMode: (value ? "library" : "none") as SentenceState["sfxMode"] } : sent
        );
        return { ...s, sentences: newSentences };
      })
    );
  };

  const updateSfxPrompt = (sceneNum: number, sentIdx: number, prompt: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, sfxCustomPrompt: prompt } : sent
        );
        return { ...s, sentences: newSentences };
      })
    );
  };

  // Scene-level actions
  const mergeSceneUp = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      if (idx <= 0) return prev;
      const merged = [...prev];
      merged[idx - 1] = {
        ...merged[idx - 1],
        narrationText: merged[idx - 1].narrationText + " " + merged[idx].narrationText,
        sentences: [...merged[idx - 1].sentences, ...merged[idx].sentences],
      };
      merged.splice(idx, 1);
      return merged;
    });
  };

  const deleteScene = (sceneNum: number) => {
    setScenes((prev) => prev.filter((s) => s.sceneNumber !== sceneNum));
  };

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
        sentences: [{ text: "", sfxMode: "none", sfxLibraryValue: "", sfxCustomPrompt: "" }],
      };
      const result = [...prev];
      result.splice(idx + 1, 0, newScene);
      return result;
    });
  };

  const totalScenes = scenes.length;
  const totalSentences = scenes.reduce((sum, s) => sum + s.sentences.length, 0);
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
              {/* Act header */}
              <button onClick={() => toggleAct(Number(actNum))} className="flex items-center gap-3 w-full mb-3 group">
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                <div className="flex items-center gap-2 px-3 py-1 rounded-full transition-all"
                  style={{ background: isCollapsed ? "rgba(255, 120, 73, 0.1)" : "transparent" }}>
                  {isCollapsed ? <ChevronRight size={14} style={{ color: "var(--orange)" }} /> : <ChevronDown size={14} style={{ color: "var(--orange)" }} />}
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--orange)" }}>Act {actNum}</span>
                  <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{actScenes.length} scenes · {actWordCount} words</span>
                </div>
                <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
              </button>

              {!isCollapsed && (
                <div className="space-y-3">
                  {actScenes.map((scene) => {
                    const isExpanded = expandedScenes.has(scene.sceneNumber);

                    return (
                      <GlassCard
                        key={scene.sceneNumber}
                        className="p-4"
                        style={{
                          borderLeftWidth: 3,
                          borderLeftColor: scene.imageGenerated ? "var(--turquoise)" : "var(--orange)",
                        }}
                      >
                        {/* Scene header */}
                        <div className="flex items-center gap-2 mb-2">
                          <SegmentBadge label={`S-${String(scene.sceneNumber).padStart(2, "0")}`} color={scene.imageGenerated ? undefined : "var(--orange)"} />
                          <button
                            onClick={() => setPlayingScene(playingScene === scene.sceneNumber ? null : scene.sceneNumber)}
                            className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                            style={{ background: "var(--green)", color: "var(--bg-void)" }}
                          >
                            {playingScene === scene.sceneNumber ? <Pause size={10} /> : <Play size={10} className="ml-0.5" />}
                          </button>
                          <MiniWaveform color="var(--green)" width={60} height={16} bars={15} />

                          <div className="flex-1" />

                          {/* Expand/collapse toggle */}
                          <button
                            onClick={() => toggleExpand(scene.sceneNumber)}
                            title={isExpanded ? "Collapse to unified text" : "Expand into sentence cards"}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all"
                            style={{
                              background: isExpanded ? "var(--turquoise-dim)" : "transparent",
                              color: isExpanded ? "var(--turquoise)" : "var(--text-tertiary)",
                              border: `1px solid ${isExpanded ? "var(--turquoise-dim)" : "transparent"}`,
                            }}
                          >
                            <Layers size={11} />
                            {isExpanded ? "Collapse" : "Expand"}
                            <span className="font-mono">{scene.sentences.length}</span>
                          </button>

                          <button onClick={() => mergeSceneUp(scene.sceneNumber)} title="Merge into scene above" className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Merge size={12} /></button>
                          <button onClick={() => addSceneAfter(scene.sceneNumber)} title="Add scene below" className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Plus size={12} /></button>
                          <button onClick={() => deleteScene(scene.sceneNumber)} title="Delete scene" className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Trash2 size={12} /></button>
                        </div>

                        {/* === COLLAPSED: Unified text view === */}
                        {!isExpanded && (
                          <textarea
                            value={scene.narrationText}
                            onChange={(e) => updateNarration(scene.sceneNumber, e.target.value)}
                            rows={Math.max(2, Math.ceil(scene.narrationText.length / 100))}
                            className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-3 py-2 transition-all"
                            style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                            onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--orange)"; }}
                            onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                          />
                        )}

                        {/* === EXPANDED: Individual sentence cards === */}
                        <AnimatePresence>
                          {isExpanded && (
                            <motion.div
                              initial={{ opacity: 0, height: 0 }}
                              animate={{ opacity: 1, height: "auto" }}
                              exit={{ opacity: 0, height: 0 }}
                              transition={{ duration: 0.3 }}
                              className="space-y-2"
                            >
                              {scene.sentences.map((sent, sentIdx) => (
                                <div
                                  key={sentIdx}
                                  className="rounded-xl p-3 transition-all"
                                  style={{
                                    background: "rgba(255,255,255,0.02)",
                                    border: "1px solid rgba(255,255,255,0.05)",
                                  }}
                                >
                                  {/* Sentence header */}
                                  <div className="flex items-center gap-2 mb-1.5">
                                    <span className="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded"
                                      style={{ background: "var(--orange-dim)", color: "var(--orange)" }}>
                                      {sentIdx + 1}/{scene.sentences.length}
                                    </span>
                                    <div className="flex-1" />
                                    <button onClick={() => mergeSentenceUp(scene.sceneNumber, sentIdx)} title="Merge up" className="p-0.5 rounded hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Merge size={10} /></button>
                                    <button onClick={() => addSentenceAfter(scene.sceneNumber, sentIdx)} title="Add below" className="p-0.5 rounded hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Plus size={10} /></button>
                                    <button onClick={() => deleteSentence(scene.sceneNumber, sentIdx)} title="Delete" className="p-0.5 rounded hover:bg-[var(--bg-surface)]" style={{ color: "var(--text-tertiary)" }}><Trash2 size={10} /></button>
                                  </div>

                                  {/* Sentence text — editable */}
                                  <textarea
                                    value={sent.text}
                                    onChange={(e) => updateSentence(scene.sceneNumber, sentIdx, e.target.value)}
                                    rows={Math.max(1, Math.ceil(sent.text.length / 90))}
                                    className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                                    style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                                    onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                                    onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
                                  />

                                  {/* SFX per sentence */}
                                  <div className="flex items-center gap-2 mt-2 flex-wrap">
                                    <Volume2 size={10} style={{ color: "var(--gold)", opacity: 0.5 }} />

                                    {/* Mode selector pills */}
                                    {(["none", "library", "elevenlabs", "custom"] as const).map((mode) => {
                                      const labels = { none: "None", library: "Library", elevenlabs: "ElevenLabs", custom: "AI Prompt" };
                                      const icons = { none: null, library: <Library size={9} />, elevenlabs: <Mic size={9} />, custom: <Wand2 size={9} /> };
                                      const colors = { none: "var(--text-tertiary)", library: "var(--gold)", elevenlabs: "var(--green)", custom: "var(--purple)" };
                                      const isActive = sent.sfxMode === mode;
                                      return (
                                        <button
                                          key={mode}
                                          onClick={() => updateSfxMode(scene.sceneNumber, sentIdx, mode)}
                                          className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-medium transition-all"
                                          style={{
                                            background: isActive ? `${colors[mode]}15` : "transparent",
                                            color: isActive ? colors[mode] : "var(--text-tertiary)",
                                            border: `1px solid ${isActive ? `${colors[mode]}30` : "transparent"}`,
                                          }}
                                        >
                                          {icons[mode]}
                                          {labels[mode]}
                                        </button>
                                      );
                                    })}
                                  </div>

                                  {/* Library dropdown */}
                                  {sent.sfxMode === "library" && (
                                    <div className="flex items-center gap-2 mt-1.5">
                                      <select
                                        value={sent.sfxLibraryValue}
                                        onChange={(e) => updateSfxLibrary(scene.sceneNumber, sentIdx, e.target.value)}
                                        className="text-[10px] font-mono px-2 py-1 rounded-lg outline-none flex-1"
                                        style={{ background: "var(--bg-elevated)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
                                      >
                                        <option value="">Select sound...</option>
                                        {SFX_LIBRARY.map((sfx) => (
                                          <option key={sfx.value} value={sfx.value}>{sfx.label}</option>
                                        ))}
                                      </select>
                                      {sent.sfxLibraryValue && (
                                        <button className="w-5 h-5 rounded-full flex items-center justify-center" style={{ background: "var(--green)", color: "var(--bg-void)" }}>
                                          <Play size={8} className="ml-px" />
                                        </button>
                                      )}
                                    </div>
                                  )}

                                  {/* ElevenLabs SFX design */}
                                  {sent.sfxMode === "elevenlabs" && (
                                    <div className="mt-1.5 flex items-start gap-2">
                                      <Mic size={11} style={{ color: "var(--green)", marginTop: 5 }} />
                                      <div className="flex-1">
                                        <textarea
                                          value={sent.sfxCustomPrompt}
                                          onChange={(e) => updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)}
                                          placeholder="Describe the sound for ElevenLabs to generate (e.g. 'distant thunder rolling across mountains')..."
                                          rows={2}
                                          className="w-full text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                          style={{ color: "var(--text-secondary)", background: "var(--bg-elevated)", border: "1px solid rgba(0, 230, 138, 0.15)" }}
                                          onFocus={(e) => { e.target.style.borderColor = "var(--green)"; }}
                                          onBlur={(e) => { e.target.style.borderColor = "rgba(0, 230, 138, 0.15)"; }}
                                        />
                                        <div className="flex items-center gap-2 mt-1">
                                          <button className="text-[9px] font-medium px-2 py-0.5 rounded-lg" style={{ background: "var(--green)", color: "var(--bg-void)" }}>
                                            Generate SFX
                                          </button>
                                          <span className="text-[9px] font-mono" style={{ color: "var(--text-tertiary)" }}>~$0.03</span>
                                        </div>
                                      </div>
                                    </div>
                                  )}

                                  {/* AI custom prompt */}
                                  {sent.sfxMode === "custom" && (
                                    <div className="mt-1.5 flex items-start gap-2">
                                      <Wand2 size={11} style={{ color: "var(--purple)", marginTop: 5 }} />
                                      <textarea
                                        value={sent.sfxCustomPrompt}
                                        onChange={(e) => updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)}
                                        placeholder="Describe the SFX for AI generation..."
                                        rows={2}
                                        className="flex-1 text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                        style={{ color: "var(--text-secondary)", background: "var(--bg-elevated)", border: "1px solid var(--purple-dim)" }}
                                        onFocus={(e) => { e.target.style.borderColor = "var(--purple)"; }}
                                        onBlur={(e) => { e.target.style.borderColor = "var(--purple-dim)"; }}
                                      />
                                    </div>
                                  )}
                                </div>
                              ))}
                            </motion.div>
                          )}
                        </AnimatePresence>

                        {/* Sources + metadata (always visible) */}
                        <div className="flex items-center gap-2 mt-2 flex-wrap">
                          {scene.sources?.map((src, srcIdx) => (
                            <span key={srcIdx} className="text-[10px] font-mono px-2 py-0.5 rounded" style={{ background: "var(--yellow-dim)", color: "var(--yellow)" }}>
                              [{src}]
                            </span>
                          ))}
                          <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{scene.visualStyle}</span>
                          <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>{scene.composition}</span>
                        </div>
                      </GlassCard>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Sidebar */}
      <div className="space-y-4">
        <GlassCard className="p-5">
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>Script Details</h3>
          <div className="space-y-3">
            {[
              { label: "Framework", value: video.framework || "—" },
              { label: "Word Count", value: String(wordCount) },
              { label: "Scenes", value: String(totalScenes) },
              { label: "Sentences", value: String(totalSentences) },
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
          <h3 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--gold)" }}>Sound Design</h3>
          <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>
            Expand a scene, then choose per-sentence:
          </p>
          <div className="space-y-1.5">
            {[
              { icon: <Library size={10} />, label: "Library", desc: "Free presets", color: "var(--gold)" },
              { icon: <Mic size={10} />, label: "ElevenLabs", desc: "Design your own SFX", color: "var(--green)" },
              { icon: <Wand2 size={10} />, label: "AI Prompt", desc: "Text-to-sound", color: "var(--purple)" },
            ].map((opt) => (
              <div key={opt.label} className="flex items-center gap-2 text-[10px]">
                <span style={{ color: opt.color }}>{opt.icon}</span>
                <span className="font-medium" style={{ color: opt.color }}>{opt.label}</span>
                <span style={{ color: "var(--text-tertiary)" }}>— {opt.desc}</span>
              </div>
            ))}
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
