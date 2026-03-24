"use client";

import { motion } from "framer-motion";
import { CheckCircle, Loader2, RefreshCw, ImageOff } from "lucide-react";
import { cn } from "@/lib/utils";

export interface StoryboardPanel {
  index: number;
  url: string | null;
  prompt?: string;
}

export interface SceneData {
  sceneNumber: number;
  title: string;
  narration: string;
  panels: StoryboardPanel[];
  status: "approved" | "pending" | "generating";
}

interface SceneGridProps {
  scene: SceneData;
  onPanelClick: (panelIndex: number) => void;
  onApprove: () => void;
  onRegenerate: () => void;
  isApproving?: boolean;
  isRegenerating?: boolean;
}

const statusConfig = {
  approved: {
    icon: CheckCircle,
    color: "text-green-500",
    bgColor: "bg-green-500/10",
    label: "Approved",
  },
  pending: {
    icon: RefreshCw,
    color: "text-[var(--accent)]",
    bgColor: "bg-[var(--accent)]/10",
    label: "Pending Review",
  },
  generating: {
    icon: Loader2,
    color: "text-[var(--text-secondary)]",
    bgColor: "bg-[var(--surface-elevated)]",
    label: "Generating...",
  },
};

export function SceneGrid({
  scene,
  onPanelClick,
  onApprove,
  onRegenerate,
  isApproving = false,
  isRegenerating = false,
}: SceneGridProps) {
  const config = statusConfig[scene.status];
  const StatusIcon = config.icon;
  const isGenerating = scene.status === "generating";
  const isApproved = scene.status === "approved";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-xl border border-[var(--border)] bg-[var(--surface)] overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[var(--border)] px-4 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold">Scene {scene.sceneNumber}</span>
          {scene.title && (
            <>
              <span className="text-[var(--border)]">|</span>
              <span className="text-sm text-[var(--text-secondary)]">{scene.title}</span>
            </>
          )}
        </div>
        <div className={cn("flex items-center gap-1.5 rounded-full px-2.5 py-1", config.bgColor)}>
          <StatusIcon
            size={14}
            className={cn(config.color, isGenerating && "animate-spin")}
          />
          <span className={cn("text-xs font-medium", config.color)}>{config.label}</span>
        </div>
      </div>

      {/* 3x3 Grid */}
      <div className="p-3">
        <div className="grid grid-cols-3 gap-1.5">
          {scene.panels.map((panel, idx) => (
            <button
              key={idx}
              onClick={() => panel.url && onPanelClick(idx)}
              disabled={!panel.url || isGenerating}
              className={cn(
                "relative aspect-square overflow-hidden rounded-lg transition-all",
                panel.url
                  ? "hover:ring-2 hover:ring-[var(--accent)] hover:ring-offset-2 hover:ring-offset-[var(--surface)]"
                  : "cursor-not-allowed"
              )}
            >
              {panel.url ? (
                <img
                  src={panel.url}
                  alt={`Panel ${idx + 1}`}
                  className="h-full w-full object-cover"
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center bg-[var(--surface-elevated)]">
                  {isGenerating ? (
                    <Loader2 size={20} className="animate-spin text-[var(--text-secondary)]" />
                  ) : (
                    <ImageOff size={20} className="text-[var(--text-secondary)]" />
                  )}
                </div>
              )}
              {/* Panel number badge */}
              <span className="absolute bottom-1 left-1 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-medium text-white">
                {idx + 1}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Narration */}
      <div className="border-t border-[var(--border)] px-4 py-3">
        <p className="text-sm leading-relaxed text-[var(--text-secondary)]">
          {scene.narration}
        </p>
      </div>

      {/* Actions */}
      {!isApproved && !isGenerating && (
        <div className="flex gap-2 border-t border-[var(--border)] p-3">
          <button
            onClick={onApprove}
            disabled={isApproving}
            className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-green-500 py-2.5 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {isApproving ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <CheckCircle size={16} />
            )}
            Approve
          </button>
          <button
            onClick={onRegenerate}
            disabled={isRegenerating}
            className="flex items-center justify-center gap-2 rounded-lg bg-[var(--surface-elevated)] px-4 py-2.5 text-sm font-medium text-[var(--text-secondary)] transition-colors hover:text-[var(--text-primary)] disabled:opacity-50"
          >
            {isRegenerating ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <RefreshCw size={16} />
            )}
            Regenerate
          </button>
        </div>
      )}
    </motion.div>
  );
}
