"use client";

import { useState } from "react";
import { useToast } from "@/components/ui/toast";

/**
 * "Lock this as a style" save dialog (Chunk 1.E). Copy is verbatim from
 * storyengine/tasks/director-mockup/index.html `#styleScrim` (~L1340-1362).
 *
 * Presentational only — there is no save-style endpoint yet. Phase 4 wires
 * the real save; for now this just toasts and closes, exactly like the
 * mockup's own `saveStyle()` (toast, no persistence).
 */
export function SaveStyleModal({
  open,
  defaultName,
  onClose,
}: {
  open: boolean;
  defaultName: string;
  onClose: () => void;
}) {
  const [name, setName] = useState(defaultName);
  const toast = useToast();

  if (!open) return null;

  const handleSave = () => {
    const trimmed = name.trim() || "Untitled style";
    // Phase 4 wires the real save (a persisted style record + it showing up
    // on the home screen's "Your saved styles" section). This chunk is
    // presentational only — no backend call exists yet.
    toast.success(`Saved "${trimmed}" — it now shows on your home screen`);
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70 p-6 backdrop-blur-[3px]"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[470px] overflow-hidden rounded-[20px] border border-line bg-surface shadow-[0_30px_80px_rgba(0,0,0,0.75)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-line-soft px-[22px] pb-3.5 pt-5">
          <h3 className="mb-1 text-base font-semibold text-ink">★ Lock this as a style</h3>
          <p className="text-[12.5px] leading-relaxed text-dim">
            Saves how this video is put together so you can start a new one from it in one click.
          </p>
        </div>
        <div className="px-[22px] py-4">
          <label className="mb-1.5 block text-[11.5px] text-dim" htmlFor="style-name-input">
            Name this style
          </label>
          <input
            id="style-name-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            spellCheck={false}
            className="h-10 w-full rounded-[11px] border border-line-soft bg-deep px-3.5 text-sm text-ink outline-none focus:border-turquoise/50"
          />
          <div className="mt-3.5 rounded-[11px] border border-turquoise/20 bg-turquoise/[0.06] px-3.5 py-3 text-xs leading-relaxed text-dim">
            Saving how this one is <b className="text-ink">built</b>, how it&apos;s <b className="text-ink">written</b>,
            how it <b className="text-ink">looks</b>, the narrator&apos;s voice, and what you chose to spend (
            <b className="text-ink">cheap everywhere, expensive on the big moments</b>). It shows up on your home
            screen next to the four cards at the top.
          </div>
        </div>
        <div className="flex justify-end gap-2 border-t border-line-soft px-[22px] pb-[18px] pt-3.5">
          <button
            type="button"
            onClick={onClose}
            className="h-8 rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink transition-colors hover:border-line"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="h-8 rounded-[9px] border border-gold-director/45 bg-gold-director/[0.08] px-3.5 text-[13px] font-semibold text-gold-director transition-colors hover:border-gold-director/70 hover:bg-gold-director/[0.16]"
          >
            Save style
          </button>
        </div>
      </div>
    </div>
  );
}
