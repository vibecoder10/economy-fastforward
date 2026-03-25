"use client";

import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Loader2, Mic } from "lucide-react";
import {
  ScriptScene,
  updateSceneText,
  updateSceneTone,
  runVoiceForScene,
  runPipelineStage,
} from "@/lib/api";
import { VoicePlayer } from "./voice-player";
import { SegmentList } from "./segment-list";
import { useTaskPoller } from "@/hooks/use-task-poller";

interface SceneEditorProps {
  scene: ScriptScene;
  videoId: string;
  videoStatus: string;
  onRefresh: () => void;
}

const TONE_OPTIONS = ["serious", "conversational", "urgent", "concise"] as const;

export function SceneEditor({ scene, videoId, videoStatus, onRefresh }: SceneEditorProps) {
  const queryClient = useQueryClient();
  const sceneNum = scene.scene ?? 0;

  const [editing, setEditing] = useState(false);
  const [localText, setLocalText] = useState(scene.scene_text || "");
  const [voiceGenerating, setVoiceGenerating] = useState(false);
  const [showRegenWarning, setShowRegenWarning] = useState(false);

  // Optimistic text update
  const textMutation = useMutation({
    mutationFn: (text: string) => updateSceneText(videoId, sceneNum, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    },
  });

  // Tone update
  const toneMutation = useMutation({
    mutationFn: (tone: string) => updateSceneTone(videoId, sceneNum, tone),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    },
  });

  // Regenerate full script
  const regenMutation = useMutation({
    mutationFn: () => runPipelineStage(videoId, "script"),
    onSuccess: () => {
      setShowRegenWarning(false);
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      onRefresh();
    },
  });

  // Voice generation polling
  const voicePoller = useTaskPoller({
    videoId,
    enabled: voiceGenerating,
    onComplete: () => {
      setVoiceGenerating(false);
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
      onRefresh();
    },
    onFailed: () => {
      setVoiceGenerating(false);
    },
  });

  const handleBlur = useCallback(() => {
    setEditing(false);
    if (localText !== scene.scene_text) {
      textMutation.mutate(localText);
    }
  }, [localText, scene.scene_text, textMutation]);

  const handleVoiceGenerate = async () => {
    setVoiceGenerating(true);
    try {
      await runVoiceForScene(videoId, sceneNum);
    } catch {
      setVoiceGenerating(false);
    }
  };

  const handleRedoVoice = async () => {
    setVoiceGenerating(true);
    try {
      await runVoiceForScene(videoId, sceneNum);
    } catch {
      setVoiceGenerating(false);
    }
  };

  const wordCount = localText.split(/\s+/).filter(Boolean).length;

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3"
        style={{ borderBottom: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-3">
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded"
            style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
          >
            Scene {sceneNum}
          </span>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {wordCount}w
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Tone dropdown */}
          <select
            value={scene.tone || "serious"}
            onChange={(e) => toneMutation.mutate(e.target.value)}
            disabled={toneMutation.isPending}
            className="text-xs rounded px-2 py-1 cursor-pointer"
            style={{
              background: "var(--bg-card-hover)",
              border: "1px solid var(--border)",
              color: "var(--text-secondary)",
              outline: "none",
            }}
          >
            {TONE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t.charAt(0).toUpperCase() + t.slice(1)}
              </option>
            ))}
          </select>

          {/* Regenerate button */}
          {!showRegenWarning ? (
            <button
              onClick={() => setShowRegenWarning(true)}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded"
              style={{
                background: "var(--bg-card-hover)",
                border: "1px solid var(--border)",
                color: "var(--text-muted)",
              }}
            >
              <RefreshCw size={10} /> Regen
            </button>
          ) : (
            <div className="flex items-center gap-1">
              <button
                onClick={() => regenMutation.mutate()}
                disabled={regenMutation.isPending}
                className="text-xs px-2 py-1 rounded font-medium"
                style={{ background: "#C44545", color: "#fff", border: "none" }}
              >
                {regenMutation.isPending ? "..." : "Confirm"}
              </button>
              <button
                onClick={() => setShowRegenWarning(false)}
                className="text-xs px-2 py-1 rounded"
                style={{ color: "var(--text-muted)", background: "none", border: "none" }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Script text */}
      <div className="px-4 py-3">
        {editing ? (
          <textarea
            value={localText}
            onChange={(e) => setLocalText(e.target.value)}
            onBlur={handleBlur}
            autoFocus
            className="w-full text-sm leading-relaxed resize-none rounded-lg p-2"
            style={{
              background: "var(--bg-card-hover)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
              outline: "none",
              minHeight: 120,
            }}
          />
        ) : (
          <p
            onClick={() => {
              setLocalText(scene.scene_text || "");
              setEditing(true);
            }}
            className="text-sm leading-relaxed whitespace-pre-wrap cursor-text rounded-lg p-2 transition-colors"
            style={{ color: "var(--text-primary)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-card-hover)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
          >
            {scene.scene_text || "Click to add script text..."}
          </p>
        )}
        {textMutation.isPending && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>Saving...</span>
        )}
      </div>

      {/* Voice section */}
      <div className="px-4 pb-3">
        {voiceGenerating ? (
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-lg"
            style={{ background: "var(--bg-card-hover)", border: "1px solid var(--border)" }}
          >
            <Loader2 size={14} className="animate-spin" style={{ color: "#1A8A7A" }} />
            <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
              Generating voice... {voicePoller.message || ""}
            </span>
          </div>
        ) : scene.voice_over_url ? (
          <VoicePlayer audioUrl={scene.voice_over_url} onRedo={handleRedoVoice} />
        ) : (
          <button
            onClick={handleVoiceGenerate}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg font-medium"
            style={{
              background: "rgba(26, 138, 122, 0.1)",
              border: "1px solid rgba(26, 138, 122, 0.3)",
              color: "#1A8A7A",
            }}
          >
            <Mic size={12} /> Generate Voice
          </button>
        )}
      </div>

      {/* Segments */}
      <div
        className="px-4 pb-3"
        style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}
      >
        <SegmentList videoId={videoId} scene={sceneNum} />
      </div>
    </div>
  );
}
