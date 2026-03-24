"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getVideoScript, acceptSuggestion, rejectSuggestion } from "@/lib/api";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface ScriptTabProps {
  videoId: string;
  video: any;
}

export function ScriptTab({ videoId, video }: ScriptTabProps) {
  const [currentScene, setCurrentScene] = useState(0);
  const queryClient = useQueryClient();

  const acceptMutation = useMutation({
    mutationFn: () => acceptSuggestion(videoId, ["script"]),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      queryClient.invalidateQueries({ queryKey: ["video-script", videoId] });
    },
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectSuggestion(videoId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    },
  });

  const { data: scenes, isLoading } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  const sortedScenes = (scenes || [])
    .filter((s: any) => s.scene_text)
    .sort((a: any, b: any) => (a.scene || 0) - (b.scene || 0));

  if (sortedScenes.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No script scenes yet. Script will appear after the scripting stage.
      </div>
    );
  }

  const totalWords = sortedScenes.reduce((sum: number, s: any) => {
    return sum + (s.scene_text?.split(/\s+/).length || 0);
  }, 0);

  const scene = sortedScenes[currentScene];
  const sceneWords = scene?.scene_text?.split(/\s+/).length || 0;

  return (
    <div className="space-y-4">
      {/* Suggestion diff */}
      {video.suggested_script && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid rgba(212, 168, 68, 0.3)" }}
        >
          <div className="p-4" style={{ background: "rgba(212, 168, 68, 0.1)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--amber)" }}>
              Agent suggests script improvements
              {video.suggestion_source && ` based on ${video.suggestion_source} pattern`}
              {video.suggestion_scores?.hook && ` (hook score: ${video.suggestion_scores.hook})`}
            </p>
          </div>

          {/* Side-by-side on desktop, stacked on mobile */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
            <div className="p-4" style={{ borderRight: "1px solid var(--border)" }}>
              <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Current Script
              </h4>
              <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {video.script?.slice(0, 500)}{video.script && video.script.length > 500 ? "..." : ""}
              </p>
            </div>
            <div className="p-4">
              <h4 className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--amber)" }}>
                Suggested Script
              </h4>
              <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
                {video.suggested_script.slice(0, 500)}{video.suggested_script.length > 500 ? "..." : ""}
              </p>
            </div>
          </div>

          <div className="flex gap-3 p-4" style={{ borderTop: "1px solid var(--border)" }}>
            <button
              onClick={() => acceptMutation.mutate()}
              disabled={acceptMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
            >
              {acceptMutation.isPending ? "Accepting..." : "Accept Script"}
            </button>
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
            >
              {rejectMutation.isPending ? "Rejecting..." : "Keep Original"}
            </button>
          </div>
        </div>
      )}

      {/* Script stats */}
      <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-muted)" }}>
        <span>{totalWords.toLocaleString()} words</span>
        <span>~{Math.round(totalWords / 150)} min</span>
        <span>{sortedScenes.length} scenes</span>
      </div>

      {/* Mobile: single scene view */}
      <div className="md:hidden">
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Scene {scene?.scene || currentScene + 1} of {sortedScenes.length}
            </span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {sceneWords}w
            </span>
          </div>
          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
            {scene?.scene_text}
          </p>
          {scene?.sources && currentScene === 0 && (
            <div className="mt-4 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Sources: {scene.sources}
              </p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setCurrentScene(Math.max(0, currentScene - 1))}
            disabled={currentScene === 0}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={16} /> Prev
          </button>
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            {currentScene + 1} / {sortedScenes.length}
          </span>
          <button
            onClick={() => setCurrentScene(Math.min(sortedScenes.length - 1, currentScene + 1))}
            disabled={currentScene === sortedScenes.length - 1}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Desktop: scrollable list */}
      <div className="hidden md:block space-y-3">
        {sortedScenes.map((s: any, i: number) => (
          <div
            key={s.id}
            className="rounded-xl p-4"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Scene {s.scene || i + 1}
              </span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {s.scene_text?.split(/\s+/).length || 0}w
              </span>
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
              {s.scene_text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
