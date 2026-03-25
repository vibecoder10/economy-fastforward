"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getVideo } from "@/lib/api";
import { ArrowLeft } from "lucide-react";
import { InfoTab } from "@/components/video-detail/info-tab";
import { ScriptTab } from "@/components/video-detail/script-tab";
import { VisualsTab } from "@/components/video-detail/visuals-tab";
import { ThumbnailTab } from "@/components/video-detail/thumbnail-tab";
import { PerformanceTab } from "@/components/video-detail/performance-tab";
import { PipelineActionBar } from "@/components/video-detail/pipeline-action-bar";

const TABS = [
  { id: "info", label: "Info" },
  { id: "script", label: "Script" },
  { id: "visuals", label: "Visuals" },
  { id: "thumbnail", label: "Thumb" },
  { id: "performance", label: "Perf" },
];

export default function VideoDetailPage({
  params,
}: {
  params: Promise<{ videoId: string }>;
}) {
  const { videoId } = use(params);
  const [activeTab, setActiveTab] = useState("info");

  const { data: video, isLoading } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="h-4 w-32 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="h-64 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
      </div>
    );
  }

  if (!video) {
    return (
      <div className="text-center py-20" style={{ color: "var(--text-muted)" }}>
        Video not found
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Back + Title */}
      <div>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-1 text-sm mb-3 transition-colors hover:opacity-80"
          style={{ color: "var(--text-muted)" }}
        >
          <ArrowLeft size={16} />
          Back
        </Link>
        <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
          {video.video_title}
        </h1>
      </div>

      {/* Pipeline progress + action — unified component */}
      <PipelineActionBar videoId={videoId} status={video.status || ""} />

      {/* Tab bar */}
      <div
        className="flex gap-1 p-1 rounded-xl overflow-x-auto scrollbar-hide"
        style={{ background: "var(--bg-card)" }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="px-4 py-2 text-sm font-medium rounded-lg whitespace-nowrap transition-colors"
            style={{
              background: activeTab === tab.id ? "var(--bg-card-hover)" : "transparent",
              color: activeTab === tab.id ? "var(--text-primary)" : "var(--text-muted)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "info" && <InfoTab video={video} />}
        {activeTab === "script" && <ScriptTab videoId={videoId} video={video} />}
        {activeTab === "visuals" && <VisualsTab videoId={videoId} videoStatus={video.status || ""} />}
        {activeTab === "thumbnail" && <ThumbnailTab video={video} />}
        {activeTab === "performance" && <PerformanceTab video={video} />}
      </div>
    </div>
  );
}
