"use client";

import { useState, useCallback } from "react";
import { motion, AnimatePresence, useMotionValue, useTransform } from "framer-motion";
import { X, ChevronLeft, ChevronRight, RefreshCw, Check, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import type { StoryboardPanel } from "./scene-grid";

interface PanelDetailProps {
  panels: StoryboardPanel[];
  initialIndex: number;
  sceneNumber: number;
  narration?: string;
  open: boolean;
  onClose: () => void;
  onRegenerate?: (panelIndex: number) => void;
  onUseThis?: (panelIndex: number) => void;
  isRegenerating?: boolean;
}

export function PanelDetail({
  panels,
  initialIndex,
  sceneNumber,
  narration,
  open,
  onClose,
  onRegenerate,
  onUseThis,
  isRegenerating = false,
}: PanelDetailProps) {
  const [currentIndex, setCurrentIndex] = useState(initialIndex);
  const currentPanel = panels[currentIndex];

  // Swipe handling
  const x = useMotionValue(0);
  const opacity = useTransform(x, [-100, 0, 100], [0.5, 1, 0.5]);

  const goToNext = useCallback(() => {
    if (currentIndex < panels.length - 1) {
      setCurrentIndex((prev) => prev + 1);
    }
  }, [currentIndex, panels.length]);

  const goToPrev = useCallback(() => {
    if (currentIndex > 0) {
      setCurrentIndex((prev) => prev - 1);
    }
  }, [currentIndex]);

  const handleDragEnd = useCallback(
    (_: unknown, info: { offset: { x: number }; velocity: { x: number } }) => {
      const threshold = 50;
      const velocity = info.velocity.x;
      const offset = info.offset.x;

      if (offset > threshold || velocity > 500) {
        goToPrev();
      } else if (offset < -threshold || velocity < -500) {
        goToNext();
      }
    },
    [goToNext, goToPrev]
  );

  // Reset index when opening
  if (!open) {
    return null;
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/90"
            onClick={onClose}
          />

          {/* Content */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            className="fixed inset-0 z-50 flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3">
              <div className="flex items-center gap-2">
                <button
                  onClick={goToPrev}
                  disabled={currentIndex === 0}
                  className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white disabled:opacity-30"
                >
                  <ChevronLeft size={20} />
                </button>
                <span className="text-sm font-medium text-white">
                  Panel {currentIndex + 1} of {panels.length}
                </span>
                <button
                  onClick={goToNext}
                  disabled={currentIndex === panels.length - 1}
                  className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white disabled:opacity-30"
                >
                  <ChevronRight size={20} />
                </button>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-white/50">Scene {sceneNumber}</span>
                <button
                  onClick={onClose}
                  className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white"
                >
                  <X size={20} />
                </button>
              </div>
            </div>

            {/* Image with swipe */}
            <div className="relative flex flex-1 items-center justify-center overflow-hidden px-4">
              <motion.div
                key={currentIndex}
                drag="x"
                dragConstraints={{ left: 0, right: 0 }}
                dragElastic={0.2}
                onDragEnd={handleDragEnd}
                style={{ x, opacity }}
                className="relative max-h-full max-w-full cursor-grab active:cursor-grabbing"
              >
                {currentPanel?.url ? (
                  <img
                    src={currentPanel.url}
                    alt={`Panel ${currentIndex + 1}`}
                    className="max-h-[60vh] rounded-lg object-contain"
                    draggable={false}
                  />
                ) : (
                  <div className="flex h-64 w-64 items-center justify-center rounded-lg bg-[var(--surface)]">
                    <span className="text-[var(--text-secondary)]">No image</span>
                  </div>
                )}
              </motion.div>

              {/* Navigation hints */}
              {currentIndex > 0 && (
                <div className="absolute left-8 top-1/2 -translate-y-1/2 text-white/30">
                  <ChevronLeft size={40} />
                </div>
              )}
              {currentIndex < panels.length - 1 && (
                <div className="absolute right-8 top-1/2 -translate-y-1/2 text-white/30">
                  <ChevronRight size={40} />
                </div>
              )}
            </div>

            {/* Panel dots */}
            <div className="flex justify-center gap-1.5 py-3">
              {panels.map((_, idx) => (
                <button
                  key={idx}
                  onClick={() => setCurrentIndex(idx)}
                  className={cn(
                    "h-2 rounded-full transition-all",
                    idx === currentIndex
                      ? "w-6 bg-white"
                      : "w-2 bg-white/30 hover:bg-white/50"
                  )}
                />
              ))}
            </div>

            {/* Prompt/Narration */}
            {(currentPanel?.prompt || narration) && (
              <div className="mx-4 mb-4 rounded-lg bg-white/10 p-3">
                <p className="text-sm leading-relaxed text-white/80">
                  {currentPanel?.prompt || narration}
                </p>
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 p-4 pb-8">
              {onRegenerate && (
                <button
                  onClick={() => onRegenerate(currentIndex)}
                  disabled={isRegenerating}
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-white/10 py-3 text-sm font-medium text-white transition-colors hover:bg-white/20 disabled:opacity-50"
                >
                  {isRegenerating ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <RefreshCw size={16} />
                  )}
                  Regenerate
                </button>
              )}
              {onUseThis && (
                <button
                  onClick={() => onUseThis(currentIndex)}
                  className="flex flex-1 items-center justify-center gap-2 rounded-lg bg-[var(--accent)] py-3 text-sm font-medium text-black transition-opacity hover:opacity-90"
                >
                  <Check size={16} />
                  Use This
                </button>
              )}
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
