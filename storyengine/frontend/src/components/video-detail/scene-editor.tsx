"use client";

import { useState, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  ScriptScene,
  updateSceneText,
  updateSceneTone,
} from "@/lib/api";
import { SegmentList } from "./segment-list";

interface SceneEditorProps {
  scene: ScriptScene;
  sceneIndex: number;
  videoId: string;
  videoStatus: string;
  onRefresh: () => void;
}

const TONE_OPTIONS = ["serious", "conversational", "urgent", "concise"] as const;

export function SceneEditor({ scene, sceneIndex, videoId, onRefresh }: SceneEditorProps) {
  const queryClient = useQueryClient();
  const sceneNum = scene.scene ?? (sceneIndex + 1);

  const [collapsed, setCollapsed] = useState(true);
  const [editing, setEditing] = useState(false);
  const [localText, setLocalText] = useState(scene.scene_text || "");

  const textMutation = useMutation({
    mutationFn: (text: string) => updateSceneText(videoId, sceneNum, text),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    },
  });

  const toneMutation = useMutation({
    mutationFn: (tone: string) => updateSceneTone(videoId, sceneNum, tone),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
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
      {/* Header — clickable to expand/collapse */}
      <div
        className="flex items-center justify-between px-4 py-3 cursor-pointer select-none"
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
            {wordCount}w · ~{estimatedDuration}s · ~{estimatedImages} img
          </span>
        </div>

        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
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
        </div>
      </div>

      {/* Expanded content */}
      {!collapsed && (
        <>
          {/* Script text — click to edit */}
          <div className="px-4 py-3">
            {editing ? (
              <textarea
                value={localText}
                onChange={(e) => setLocalText(e.target.value)}
                onBlur={handleBlur}
                autoFocus
                className="w-full text-sm leading-relaxed resize-none rounded-lg p-3"
                style={{
                  background: "var(--bg-card-hover)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                  outline: "none",
                  minHeight: 150,
                }}
              />
            ) : (
              <div
                onClick={() => {
                  setLocalText(scene.scene_text || "");
                  setEditing(true);
                }}
                className="text-sm leading-relaxed whitespace-pre-wrap cursor-text rounded-lg p-3 transition-colors"
                style={{ color: "var(--text-primary)" }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-card-hover)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                {scene.scene_text || "Click to add script text..."}
              </div>
            )}
            {textMutation.isPending && (
              <span className="text-xs mt-1 block" style={{ color: "var(--text-muted)" }}>
                Saving...
              </span>
            )}
          </div>

          {/* Sentence segments — image breakout */}
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
