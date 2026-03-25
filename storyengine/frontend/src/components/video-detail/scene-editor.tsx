"use client";

import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, ChevronDown, ChevronRight } from "lucide-react";
import {
  ScriptScene,
  updateSceneText,
  updateSceneTone,
  runPipelineStage,
} from "@/lib/api";
import { SegmentList } from "./segment-list";

interface SceneEditorProps {
  scene: ScriptScene;
  sceneIndex: number; // 0-based index from parent, used as fallback when scene.scene is null
  videoId: string;
  videoStatus: string;
  onRefresh: () => void;
}

const TONE_OPTIONS = ["serious", "conversational", "urgent", "concise"] as const;

export function SceneEditor({ scene, sceneIndex, videoId, videoStatus, onRefresh }: SceneEditorProps) {
  const queryClient = useQueryClient();
  const sceneNum = scene.scene ?? (sceneIndex + 1);

  const [collapsed, setCollapsed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [localText, setLocalText] = useState(scene.scene_text || "");
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

  const handleBlur = useCallback(() => {
    setEditing(false);
    if (localText !== scene.scene_text) {
      textMutation.mutate(localText);
    }
  }, [localText, scene.scene_text, textMutation]);

  const wordCount = localText.split(/\s+/).filter(Boolean).length;
  const estimatedDuration = Math.round(wordCount / 2.5);
  const estimatedImages = Math.ceil(estimatedDuration / 9);

  return (
    <div
      className="rounded-xl overflow-hidden"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      {/* Header — always visible, clickable to collapse */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer"
        style={{ borderBottom: collapsed ? undefined : "1px solid var(--border)" }}
        onClick={() => setCollapsed(!collapsed)}
      >
        <div className="flex items-center gap-3">
          {collapsed ? (
            <ChevronRight size={14} style={{ color: "var(--text-muted)" }} />
          ) : (
            <ChevronDown size={14} style={{ color: "var(--text-muted)" }} />
          )}
          <span
            className="text-xs font-semibold px-2 py-0.5 rounded"
            style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
          >
            Scene {sceneNum}
          </span>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {wordCount}w · ~{estimatedDuration}s · ~{estimatedImages} images
          </span>
        </div>

        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
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

      {/* Collapsible content */}
      {!collapsed && (
        <>
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

          {/* Segments — sentence text breakout */}
          <div
            className="px-4 pb-3"
            style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }}
          >
            <SegmentList videoId={videoId} scene={sceneNum} />
          </div>
        </>
      )}
    </div>
  );
}
