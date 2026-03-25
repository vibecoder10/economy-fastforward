"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getSceneSegments, Segment } from "@/lib/api";

interface SegmentListProps {
  videoId: string;
  scene: number;
}

export function SegmentList({ videoId, scene }: SegmentListProps) {
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ["segments", videoId, scene],
    queryFn: () => getSceneSegments(videoId, scene),
  });

  const segments = data?.segments || [];

  if (isLoading) {
    return (
      <div
        className="h-8 rounded-lg animate-pulse"
        style={{ background: "var(--bg-card-hover)" }}
      />
    );
  }

  if (segments.length === 0) {
    return (
      <div className="text-xs py-2" style={{ color: "var(--text-muted)" }}>
        No segments
      </div>
    );
  }

  const totalWords = segments.reduce((sum, s) => sum + s.word_count, 0);
  const totalDuration = segments.reduce((sum, s) => sum + s.duration_seconds, 0);

  return (
    <div>
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs py-1.5 w-full text-left"
        style={{ color: "var(--text-secondary)", background: "none", border: "none" }}
      >
        <span style={{ fontSize: 10, display: "inline-block", transform: expanded ? "rotate(90deg)" : "none", transition: "transform 0.15s" }}>
          &#9654;
        </span>
        <span>
          {segments.length} segment{segments.length !== 1 ? "s" : ""}
          {" \u00b7 "}
          {totalWords}w
          {" \u00b7 "}
          {Math.round(totalDuration)}s
        </span>
      </button>

      {expanded && (
        <div
          className="rounded-lg overflow-hidden mt-1"
          style={{ border: "1px solid var(--border)" }}
        >
          {segments.map((seg: Segment, i: number) => (
            <div
              key={seg.id}
              className="flex items-start gap-3 px-3 py-2"
              style={{
                borderTop: i > 0 ? "1px solid var(--border)" : undefined,
                background: "var(--bg-card)",
              }}
            >
              <span
                className="text-xs font-mono font-semibold flex-shrink-0 pt-0.5"
                style={{ color: "var(--amber)", minWidth: 18, textAlign: "right" }}
              >
                {seg.image_index}
              </span>
              <p
                className="text-xs leading-relaxed flex-1"
                style={{ color: "var(--text-primary)" }}
              >
                {seg.sentence_text}
              </p>
              <div className="flex items-center gap-2 flex-shrink-0 pt-0.5">
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {seg.word_count}w
                </span>
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  {Math.round(seg.duration_seconds)}s
                </span>
                {seg.shot_type && (
                  <span
                    className="text-xs px-1.5 py-0.5 rounded"
                    style={{
                      color: "#1A8A7A",
                      background: "rgba(26, 138, 122, 0.1)",
                      fontSize: 10,
                    }}
                  >
                    {seg.shot_type}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
