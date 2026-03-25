"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getVideoScript,
  ScriptScene,
  VideoDetail,
  acceptSuggestion,
  rejectSuggestion,
} from "@/lib/api";
import { SceneEditor } from "./scene-editor";
import { StageAdvancer } from "./stage-advancer";

interface ScriptTabProps {
  videoId: string;
  video: VideoDetail;
}

export function ScriptTab({ videoId, video }: ScriptTabProps) {
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
    .filter((s) => s.scene_text)
    .sort((a, b) => (a.scene || 0) - (b.scene || 0));

  if (sortedScenes.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No script scenes yet. Script will appear after the scripting stage.
      </div>
    );
  }

  const totalWords = sortedScenes.reduce((sum, s) => {
    return sum + (s.scene_text?.split(/\s+/).filter(Boolean).length || 0);
  }, 0);

  const estimatedMinutes = Math.round(totalWords / 150);

  const hasPendingSuggestion =
    video.suggested_script && video.suggestion_status === "pending";

  const hasEmptyScene = sortedScenes.some((s) => !s.scene_text?.trim());
  const allVoicesReady = sortedScenes.every((s) => s.voice_over_url);

  const status = video.status || "";

  // Determine which StageAdvancer to show
  const showVoiceAdvancer =
    status !== "ready_for_scripting" &&
    status !== "idea_logged" &&
    !allVoicesReady;

  const showPromptsAdvancer = allVoicesReady;

  return (
    <div className="space-y-4">
      {/* Suggestion banner */}
      {video.suggested_script && video.suggestion_status === "pending" && (
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

      {/* Stats bar + Stage advancer */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-muted)" }}>
          <span>{sortedScenes.length} scenes</span>
          <span>{totalWords.toLocaleString()} words</span>
          <span>~{estimatedMinutes} min</span>
        </div>

        {showPromptsAdvancer ? (
          <StageAdvancer
            videoId={videoId}
            stage="prompts"
            label="All Voices Ready — Prompts"
            nextLabel="Prompts started"
          />
        ) : showVoiceAdvancer ? (
          <StageAdvancer
            videoId={videoId}
            stage="voice"
            label="Approve Script — Generate Voice"
            nextLabel="Voice generation started"
            disabled={hasEmptyScene}
            disabledReason={hasEmptyScene ? "All scenes must have text before generating voice" : undefined}
          />
        ) : null}
      </div>

      {/* Scene editor cards */}
      <div className="space-y-3">
        {sortedScenes.map((scene) => (
          <SceneEditor
            key={scene.id}
            scene={scene}
            videoId={videoId}
            videoStatus={status}
            onRefresh={() => queryClient.invalidateQueries({ queryKey: ["video-script", videoId] })}
          />
        ))}
      </div>
    </div>
  );
}
