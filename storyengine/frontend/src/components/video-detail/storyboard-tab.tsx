"use client";

import { useQuery } from "@tanstack/react-query";
import { getVideoScript } from "@/lib/api";

interface StoryboardTabProps {
  videoId: string;
}

export function StoryboardTab({ videoId }: StoryboardTabProps) {
  const { data: scenes, isLoading } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2].map((i) => (
          <div key={i} className="h-64 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  // Find scenes with storyboard data
  const storyboardScenes = (scenes || []).filter(
    (s: any) => s.storyboard_on_off === "On" || s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
  );

  // Collect all storyboard grid URLs
  const grids: { sceneNum: number; gridNum: number; url: string; narration: string }[] = [];
  storyboardScenes.forEach((s: any) => {
    const urls = [s.storyboard_1_url, s.storyboard_2_url, s.storyboard_3_url];
    urls.forEach((url, i) => {
      if (url) {
        grids.push({
          sceneNum: s.scene || 0,
          gridNum: i + 1,
          url,
          narration: s.scene_text || "",
        });
      }
    });
  });

  if (grids.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No storyboards yet. Storyboards will appear after the storyboard generation stage.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="text-sm" style={{ color: "var(--text-muted)" }}>
        {grids.length} storyboard grid{grids.length !== 1 ? "s" : ""}
      </div>

      {grids.map((grid) => (
        <div
          key={`${grid.sceneNum}-${grid.gridNum}`}
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div className="p-4 pb-2">
            <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Grid {grid.gridNum} (Scene {grid.sceneNum})
            </h3>
          </div>
          <div className="px-4 pb-4">
            <img
              src={grid.url}
              alt={`Storyboard grid ${grid.gridNum} for scene ${grid.sceneNum}`}
              className="w-full rounded-lg"
            />
          </div>
          {grid.narration && (
            <div className="px-4 pb-4">
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {grid.narration.length > 200
                  ? grid.narration.slice(0, 200) + "..."
                  : grid.narration}
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
