"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { acceptSuggestion, rejectSuggestion } from "@/lib/api";

interface ThumbnailTabProps {
  video: any;
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
  const queryClient = useQueryClient();

  const acceptMutation = useMutation({
    mutationFn: () => acceptSuggestion(video.id, ["thumbnail"]),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectSuggestion(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });
  return (
    <div className="space-y-6">
      {/* Current thumbnail */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <div className="p-4 pb-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Current Thumbnail
          </h3>
        </div>
        <div className="px-4 pb-4">
          {video.thumbnail_url ? (
            <img
              src={video.thumbnail_url}
              alt="Current thumbnail"
              className="w-full rounded-lg aspect-video object-cover"
            />
          ) : (
            <div
              className="w-full rounded-lg aspect-video flex items-center justify-center"
              style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
            >
              <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                No thumbnail generated
              </span>
            </div>
          )}
        </div>

        {/* CTR indicator */}
        {video.ctr != null && (
          <div className="px-4 pb-4">
            <div className="flex items-center gap-2">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                CTR:
              </span>
              <span
                className="text-sm font-bold"
                style={{
                  color: video.ctr >= 3 ? "var(--green)" : video.ctr >= 2 ? "var(--amber)" : "var(--red)",
                }}
              >
                {video.ctr.toFixed(1)}%
              </span>
              {video.ctr < 3 && (
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  (below 3% threshold)
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Suggested thumbnail variants */}
      {video.suggested_thumbnail_urls && video.suggested_thumbnail_urls.length > 0 && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid rgba(212, 168, 68, 0.3)" }}
        >
          <div className="p-4" style={{ background: "rgba(212, 168, 68, 0.1)" }}>
            <p className="text-sm font-semibold" style={{ color: "var(--amber)" }}>
              Agent suggests thumbnail improvements
              {video.suggestion_source && ` — ${video.suggestion_source} pattern`}
            </p>
            {video.suggestion_scores?.reasoning && (
              <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
                {video.suggestion_scores.reasoning}
              </p>
            )}
          </div>

          {/* Title comparison */}
          {video.suggested_title && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-0 px-4 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
              <div>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>Current Title</span>
                <p className="text-sm font-medium" style={{ color: "var(--text-secondary)" }}>{video.video_title}</p>
              </div>
              <div>
                <span className="text-xs" style={{ color: "var(--amber)" }}>Suggested Title</span>
                <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{video.suggested_title}</p>
              </div>
            </div>
          )}

          {/* Variant images */}
          <div className="p-4">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {video.suggested_thumbnail_urls.map((variant: any, i: number) => (
                <div key={i} className="space-y-2">
                  <img
                    src={variant.url}
                    alt={`Variant ${i + 1}`}
                    className="w-full rounded-lg aspect-video object-cover"
                  />
                  {variant.approach && (
                    <span
                      className="text-xs px-2 py-0.5 rounded inline-block"
                      style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}
                    >
                      {variant.approach}
                    </span>
                  )}
                  <button
                    onClick={() => acceptMutation.mutate()}
                    disabled={acceptMutation.isPending}
                    className="w-full px-3 py-1.5 rounded-lg text-xs font-medium"
                    style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                  >
                    Use This
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="flex gap-3 px-4 pb-4">
            <button
              onClick={() => rejectMutation.mutate()}
              disabled={rejectMutation.isPending}
              className="px-4 py-2 rounded-lg text-sm font-medium"
              style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
            >
              Keep Current
            </button>
          </div>
        </div>
      )}

      {/* Prompt */}
      {video.thumbnail_prompt && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
            Prompt
          </h3>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
            {video.thumbnail_prompt}
          </p>
        </div>
      )}

      {/* Style override */}
      {video.thumbnail_style_override && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
            Style Override
          </h3>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
            {video.thumbnail_style_override}
          </p>
        </div>
      )}
    </div>
  );
}
