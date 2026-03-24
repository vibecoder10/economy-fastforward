"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Lock } from "lucide-react";

export interface ThumbnailVersion {
  prompt: string;
  imageUrl: string | null;
}

interface ThumbnailWorkshopProps {
  initialPrompt: string;
  versions: ThumbnailVersion[];
  onGenerate: (prompt: string) => void;
  onLock: (version: ThumbnailVersion) => void;
  isGenerating?: boolean;
}

export function ThumbnailWorkshop({
  initialPrompt,
  versions,
  onGenerate,
  onLock,
  isGenerating,
}: ThumbnailWorkshopProps) {
  const [currentIndex, setCurrentIndex] = useState(versions.length > 0 ? versions.length - 1 : 0);
  const [editPrompt, setEditPrompt] = useState(
    versions.length > 0 ? versions[versions.length - 1].prompt : initialPrompt
  );

  const hasVersions = versions.length > 0;
  const currentVersion = hasVersions ? versions[currentIndex] : null;
  const costPerGen = 0.075;
  const totalSpent = versions.filter((v) => v.imageUrl).length * costPerGen;

  const goNext = () => setCurrentIndex(Math.min(versions.length - 1, currentIndex + 1));
  const goPrev = () => setCurrentIndex(Math.max(0, currentIndex - 1));

  return (
    <div className="space-y-4">
      <h4
        className="text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        Thumbnail Workshop
      </h4>

      {/* Carousel */}
      {hasVersions && (
        <div>
          {/* Image with arrows */}
          <div className="relative">
            {currentVersion?.imageUrl ? (
              <img
                src={currentVersion.imageUrl}
                alt={`Version ${currentIndex + 1}`}
                className="w-full rounded-lg aspect-video object-cover"
              />
            ) : (
              <div
                className="w-full rounded-lg aspect-video flex items-center justify-center"
                style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
              >
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                  {isGenerating ? "Generating..." : "Not generated"}
                </span>
              </div>
            )}

            {/* Navigation arrows */}
            {versions.length > 1 && (
              <>
                <button
                  onClick={goPrev}
                  disabled={currentIndex === 0}
                  className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center disabled:opacity-20"
                  style={{ background: "rgba(0,0,0,0.6)" }}
                >
                  <ChevronLeft size={16} style={{ color: "var(--text-primary)" }} />
                </button>
                <button
                  onClick={goNext}
                  disabled={currentIndex === versions.length - 1}
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center disabled:opacity-20"
                  style={{ background: "rgba(0,0,0,0.6)" }}
                >
                  <ChevronRight size={16} style={{ color: "var(--text-primary)" }} />
                </button>
              </>
            )}
          </div>

          {/* Dot indicators */}
          {versions.length > 1 && (
            <div className="flex items-center justify-center gap-1.5 mt-2">
              {versions.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setCurrentIndex(i)}
                  className="w-2 h-2 rounded-full transition-colors"
                  style={{
                    background: i === currentIndex ? "var(--amber)" : "var(--text-muted)",
                  }}
                />
              ))}
              <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>
                v{currentIndex + 1} of {versions.length}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Prompt editor */}
      <textarea
        value={editPrompt}
        onChange={(e) => setEditPrompt(e.target.value)}
        rows={3}
        className="w-full rounded-lg px-3 py-2 text-xs outline-none resize-none"
        style={{
          background: "var(--bg-card-hover)",
          border: "1px solid var(--border)",
          color: "var(--text-primary)",
        }}
      />

      {/* Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => onGenerate(editPrompt)}
          disabled={isGenerating || !editPrompt.trim()}
          className="px-4 py-2 rounded-lg text-xs font-medium disabled:opacity-40"
          style={{
            background: "var(--bg-card-hover)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
          }}
        >
          {isGenerating ? "Generating..." : `Generate $${costPerGen.toFixed(3)}`}
        </button>

        {totalSpent > 0 && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {versions.filter((v) => v.imageUrl).length} versions · ${totalSpent.toFixed(3)}
          </span>
        )}
      </div>

      {/* Lock button */}
      {currentVersion?.imageUrl && (
        <button
          onClick={() => onLock(currentVersion)}
          className="w-full py-2.5 rounded-lg text-sm font-semibold flex items-center justify-center gap-2"
          style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        >
          <Lock size={14} />
          Lock This Version
        </button>
      )}
    </div>
  );
}
