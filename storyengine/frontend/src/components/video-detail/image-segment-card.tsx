"use client";

import { useState } from "react";
import { Loader2, RefreshCw, Image as ImageIcon, Star } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Asset, getImageVariants, runImageForSegment, runImageVariants } from "@/lib/api";
import { PromptExpander } from "./prompt-expander";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { toDisplayImageUrl } from "@/lib/utils";

interface ImageSegmentCardProps {
  asset: Asset;
  videoId: string;
  onRefresh: () => void;
}

export function ImageSegmentCard({ asset, videoId, onRefresh }: ImageSegmentCardProps) {
  const [generating, setGenerating] = useState(false);
  const queryClient = useQueryClient();
  const scene = asset.scene;
  const imageIndex = asset.image_index;

  const { data: variants = [] } = useQuery({
    queryKey: ["image-variants", videoId, scene, imageIndex],
    queryFn: () => getImageVariants(videoId, scene as number, imageIndex as number),
    enabled: scene != null && imageIndex != null,
  });

  useTaskPoller({
    videoId,
    enabled: generating,
    onComplete: () => {
      setGenerating(false);
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
      queryClient.invalidateQueries({ queryKey: ["image-variants", videoId, scene, imageIndex] });
      onRefresh();
    },
    onFailed: () => {
      setGenerating(false);
    },
  });

  const handleGenerate = async () => {
    if (scene == null || imageIndex == null) return;
    try {
      await runImageForSegment(videoId, scene, imageIndex);
      setGenerating(true);
    } catch (err) {
      console.error("Failed to start image generation", err);
    }
  };

  const handleVariants = async () => {
    if (scene == null || imageIndex == null) return;
    try {
      await runImageVariants(videoId, scene, imageIndex);
      setGenerating(true);
    } catch (err) {
      console.error("Failed to start variants generation", err);
    }
  };

  const hasImage = !!asset.image_url;

  return (
    <div
      className="flex gap-3 rounded-lg p-3"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
    >
      {/* Image area — 160x90px */}
      <div
        className="relative flex-shrink-0 rounded overflow-hidden"
        style={{ width: 160, height: 90 }}
      >
        {hasImage ? (
          <img
            src={toDisplayImageUrl(asset.image_url)}
            alt={asset.sentence_text || "Scene image"}
            className="w-full h-full object-cover"
          />
        ) : (
          <div
            className="w-full h-full flex flex-col items-center justify-center gap-1"
            style={{
              border: "1px dashed var(--border)",
              borderRadius: 6,
              background: "var(--bg-card-hover)",
            }}
          >
            <ImageIcon size={20} style={{ color: "var(--text-muted)" }} />
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              Not generated
            </span>
          </div>
        )}

        {/* Spinner overlay while generating */}
        {generating && (
          <div
            className="absolute inset-0 flex items-center justify-center"
            style={{ background: "rgba(10,10,11,0.7)" }}
          >
            <Loader2 size={20} className="animate-spin" style={{ color: "var(--amber)" }} />
          </div>
        )}

        {/* image_index badge — amber, top-left */}
        {asset.image_index != null && (
          <span
            className="absolute top-1 left-1 text-xs font-mono font-semibold px-1 rounded"
            style={{
              background: "rgba(212,168,68,0.85)",
              color: "#0A0A0B",
              fontSize: 10,
              lineHeight: "18px",
            }}
          >
            {asset.image_index}
          </span>
        )}

        {/* shot_type badge — teal, top-right */}
        {asset.shot_type && (
          <span
            className="absolute top-1 right-1 text-xs px-1 rounded"
            style={{
              background: "rgba(26,138,122,0.85)",
              color: "#E8E8EA",
              fontSize: 10,
              lineHeight: "18px",
            }}
          >
            {asset.shot_type}
          </span>
        )}

        {/* hero_shot star — bottom-right */}
        {asset.hero_shot && (
          <span
            className="absolute bottom-1 right-1"
            title="Hero shot"
          >
            <Star size={12} fill="#D4A844" style={{ color: "#D4A844" }} />
          </span>
        )}
      </div>

      {/* Content area */}
      <div className="flex flex-col gap-2 flex-1 min-w-0">
        {/* Sentence text */}
        {asset.sentence_text && (
          <p
            className="text-xs leading-relaxed"
            style={{ color: "var(--text-primary)", fontSize: 12 }}
          >
            {asset.sentence_text}
          </p>
        )}

        {/* Collapsible prompt */}
        <PromptExpander
          prompt={asset.image_prompt || ""}
          label="Prompt"
        />

        {/* Action buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          {!hasImage ? (
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
              style={{
                background: "var(--amber)",
                color: "#0A0A0B",
              }}
            >
              {generating ? (
                <Loader2 size={11} className="animate-spin" />
              ) : (
                <ImageIcon size={11} />
              )}
              Generate · $0.025
            </button>
          ) : (
            <>
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded disabled:opacity-50"
                style={{
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                  background: "var(--bg-card-hover)",
                }}
              >
                <RefreshCw size={11} />
                Regenerate
              </button>
              <button
                onClick={handleVariants}
                disabled={generating}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded disabled:opacity-50"
                style={{
                  border: "1px solid var(--border)",
                  color: "var(--text-secondary)",
                  background: "var(--bg-card-hover)",
                }}
              >
                <Star size={11} />
                3 Variants · $0.075
              </button>
            </>
          )}
        </div>

        {variants.length > 0 && (
          <div className="flex gap-2 flex-wrap pt-1">
            {variants.map((variant) => (
              <a
                key={variant.id}
                href={variant.drive_image_url || variant.image_url || "#"}
                target="_blank"
                rel="noreferrer"
                className="block rounded overflow-hidden"
                style={{
                  width: 72,
                  height: 40,
                  border: "1px solid var(--border)",
                  background: "var(--bg-card-hover)",
                }}
                title={`Variant ${variant.panel_position || "?"}`}
              >
                {variant.image_url ? (
                  <img
                    src={toDisplayImageUrl(variant.image_url)}
                    alt={`Variant ${variant.panel_position || ""}`}
                    className="w-full h-full object-cover"
                  />
                ) : null}
              </a>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
