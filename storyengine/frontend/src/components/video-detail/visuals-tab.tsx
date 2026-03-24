"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getVideoAssets } from "@/lib/api";
import { ChevronLeft, ChevronRight, Star, Download } from "lucide-react";
import { formatCost } from "@/lib/utils";

interface VisualsTabProps {
  videoId: string;
}

export function VisualsTab({ videoId }: VisualsTabProps) {
  const [currentScene, setCurrentScene] = useState(1);

  const { data: assets, isLoading } = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-48 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  if (!assets || assets.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No images yet. Images will appear after the image prompts stage.
      </div>
    );
  }

  // Group assets by scene
  const scenes = new Map<number, any[]>();
  assets.forEach((a: any) => {
    const scene = a.scene || 1;
    if (!scenes.has(scene)) scenes.set(scene, []);
    scenes.get(scene)!.push(a);
  });

  const sceneNumbers = Array.from(scenes.keys()).sort((a, b) => a - b);
  const sceneAssets = scenes.get(currentScene) || [];
  const totalImages = assets.length;
  const generatedImages = assets.filter((a: any) => a.image_url).length;

  // Sort by image_index within scene
  sceneAssets.sort((a: any, b: any) => (a.image_index || 0) - (b.image_index || 0));

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-muted)" }}>
        <span>{generatedImages}/{totalImages} images generated</span>
        <span>{sceneNumbers.length} scenes</span>
        <span>~{formatCost(totalImages * 0.045)} estimated</span>
      </div>

      {/* Scene segments */}
      <div className="space-y-3">
        {sceneAssets.map((asset: any) => (
          <div
            key={asset.id}
            className="rounded-xl overflow-hidden"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            {/* Script text */}
            {asset.sentence_text && (
              <div className="p-4 pb-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                    Segment {asset.image_index || "?"}
                  </span>
                  {asset.shot_type && (
                    <span
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}
                    >
                      {asset.shot_type}
                    </span>
                  )}
                  {asset.hero_shot && (
                    <Star size={12} style={{ color: "var(--amber)" }} fill="var(--amber)" />
                  )}
                </div>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {asset.sentence_text}
                </p>
              </div>
            )}

            {/* Prompt */}
            {asset.image_prompt && (
              <div className="px-4 pb-2">
                <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
                  {asset.image_prompt.length > 150
                    ? asset.image_prompt.slice(0, 150) + "..."
                    : asset.image_prompt}
                </p>
              </div>
            )}

            {/* Image or placeholder */}
            <div className="px-4 pb-4">
              {asset.image_url ? (
                <div className="relative group">
                  <img
                    src={asset.image_url}
                    alt={asset.sentence_text || "Scene image"}
                    className="w-full rounded-lg aspect-video object-cover"
                  />
                  <div className="absolute bottom-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <a
                      href={asset.image_url}
                      target="_blank"
                      rel="noopener"
                      className="p-1.5 rounded-lg"
                      style={{ background: "rgba(0,0,0,0.7)" }}
                    >
                      <Download size={14} style={{ color: "var(--text-primary)" }} />
                    </a>
                  </div>
                </div>
              ) : (
                <div
                  className="w-full rounded-lg aspect-video flex items-center justify-center"
                  style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
                >
                  <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                    Not generated
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Scene navigation */}
      {sceneNumbers.length > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => {
              const idx = sceneNumbers.indexOf(currentScene);
              if (idx > 0) setCurrentScene(sceneNumbers[idx - 1]);
            }}
            disabled={sceneNumbers.indexOf(currentScene) === 0}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={16} /> Prev Scene
          </button>
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            Scene {currentScene} / {sceneNumbers.length}
          </span>
          <button
            onClick={() => {
              const idx = sceneNumbers.indexOf(currentScene);
              if (idx < sceneNumbers.length - 1) setCurrentScene(sceneNumbers[idx + 1]);
            }}
            disabled={sceneNumbers.indexOf(currentScene) === sceneNumbers.length - 1}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            Next Scene <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
