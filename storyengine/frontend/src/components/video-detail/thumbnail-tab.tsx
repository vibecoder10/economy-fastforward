"use client";

interface ThumbnailTabProps {
  video: any;
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
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
