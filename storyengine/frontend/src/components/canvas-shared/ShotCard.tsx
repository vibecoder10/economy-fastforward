"use client";

import { useState, useEffect, useRef } from "react";
import {
  Check, Loader2, Image as ImageIcon, RotateCcw, X, Play, Pause,
  MessageCircle, AlertTriangle, Film, Scissors, Clock, Download, Camera,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { updateImagePrompt, updateVideoPrompt, improvePrompt } from "@/lib/api";
import type { Asset, CameraPresetInfo } from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";
import { describeCameraMove } from "./camera-utils";

/** Short labels for the picture-model badge (asset.image_model — the model that
 * ACTUALLY drew this panel, from shared/clients/image_model_router.py). Matches
 * the Pictures selector's 3 values. */
const IMAGE_MODEL_BADGE: Record<string, string> = {
  "gpt-image-2": "GPT",
  "nano-banana-2": "Nano",
  "z-image": "Z",
};

/**
 * Harvested out of ScenesWorkspaceTab.tsx as `SegmentCard`, renamed
 * `ShotCard` (DIRECTOR-CHAT-PLAN.md Task 0.2).
 *
 * One story segment: shows the clip when it exists (tap = play), else the
 * final picture (tap = animate, ~$0.09). Bad crops wear a red badge whose
 * one-tap Re-crop is free and re-animates stale clips automatically.
 */
export function ShotCard({ asset, speaker, perClip, picturePrice, canAnimate, isGenerating, isRecropping, isFailed, isQueued, isRedrawing, isRedrawQueued, isRedrawFailed, isPlaying, disabled, videoDefaultModel, modelDisplayName, onTap, onRedoClip, onDeleteClip, onDeletePicture, onRecrop, onRedraw, onOpenModelOverride, cameraPresets, onOpenCameraPreset, showModelBadge = canAnimate, priceForModel, readOnly = false }: {
  asset: Asset;
  speaker: string | null;
  perClip: number;
  picturePrice: number;
  canAnimate: boolean;
  isGenerating: boolean;
  isRecropping: boolean;
  isFailed: boolean;
  /** C2: clicked but not yet dispatched — still inside the coalescing
   * debounce, or waiting for an in-flight batch to free up. */
  isQueued: boolean;
  /** C3: redraw's own three-state track — same shape as isGenerating/
   * isQueued/isFailed above, kept separate because a card's picture redraw
   * and its clip animate are independent actions that can each be mid-flight
   * (or queued, or failed) without the other. */
  isRedrawing: boolean;
  isRedrawQueued: boolean;
  isRedrawFailed: boolean;
  isPlaying: boolean;
  disabled: boolean;
  /** The video's own resolved clip model — the badge's last-resort fallback
   * when this scene has no per-scene routing/override/generation data yet. */
  videoDefaultModel: string;
  modelDisplayName: (id: string | null | undefined) => string;
  onTap: () => void;
  onRedoClip: () => void;
  onDeleteClip: () => void;
  onDeletePicture: () => void;
  onRecrop: () => void;
  onRedraw: () => void;
  onOpenModelOverride: () => void;
  /** C23 (checklist §2.2): curated catalog, for the chip's display-name
   * lookup and the sheet it opens — [] is a valid, fail-safe state (chip
   * still shows Auto/humanized-id, sheet just has nothing to list yet). */
  cameraPresets: CameraPresetInfo[];
  onOpenCameraPreset: () => void;
  /** Decouples the model-chip's VISIBILITY from `canAnimate` (Director
   * board's F4 fix — a view-only surface still wants to show the resolved
   * clip model even with canAnimate=false, since that flag there means "no
   * animate button", not "no clip model exists"). Optional and defaulted to
   * `canAnimate` so every existing caller (ScenesWorkspaceTab) that doesn't
   * pass this renders byte-identical to before this prop existed. */
  showModelBadge?: boolean;
  /** Optional: when provided, the model chip appends this model's real
   * $/clip (an approximate "cheapest tier" figure, same imprecision the
   * rest of the app already quotes — see docs/cost-awareness.md) next to
   * the model name. Omitted by ScenesWorkspaceTab on purpose — that surface
   * already prices per-action (Animate/Redo button labels), so a second
   * price in the chip would be new, un-asked-for UI there. */
  priceForModel?: (id: string | null | undefined) => number | null;
  /** Director board flavor (F-redraw-decision): hides every money-triggering
   * or destructive affordance (redo clip, delete clip/picture, bad-crop
   * re-crop, the image-prompt "edit & redraw" panel) instead of wiring them
   * to no-ops — a clickable control that silently does nothing is worse
   * than one that isn't there. Defaults to false so ScenesWorkspaceTab (the
   * only other caller) is unaffected. */
  readOnly?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hasClip = Boolean(asset.video_clip_url);
  const badCrop = (asset.extraction_flags?.length ?? 0) > 0;
  // C14 per-scene model badge: override > routed > video default before a
  // clip exists; model_used (whatever ACTUALLY generated it) once it does —
  // gated on canAnimate (the clip stage being enabled at all) per the
  // wiring checklist's fail-safe rule: no meaningful clip-model data on an
  // images-only plan, so no badge instead of a misleading one.
  const effectiveModelId = hasClip
    ? (asset.model_used || videoDefaultModel)
    : (asset.model_override || asset.routed_model || videoDefaultModel);
  const modelOverridden = Boolean(asset.model_override);
  // C23 camera-move chip (checklist §2.2) — gated on canAnimate too, same
  // reasoning as the model badge above: an images-only plan has no clip
  // to animate, so no camera move to show either.
  const cameraMove = describeCameraMove(asset, cameraPresets);
  const modelReason = asset.model_override
    ? "Manual override"
    : asset.routing_reason || "Channel default";
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  // Per-clip motion prompt: edit before animating. Saved to assets.video_prompt,
  // which the clip stage reads — so this override drives the next animate.
  const [prompt, setPrompt] = useState(asset.video_prompt || "");
  const [promptState, setPromptState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [imgPrompt, setImgPrompt] = useState(asset.image_prompt || "");
  const [imgState, setImgState] = useState<"idle" | "saving" | "error">("idle");
  // "✨ Improve": the prompt studio's model-aware rewrite fills the box — the
  // creator reviews and saves; nothing is applied automatically.
  const [improving, setImproving] = useState<"" | "image" | "motion">("");
  const improve = async (surface: "image" | "motion") => {
    setImproving(surface);
    try {
      const res = await improvePrompt(asset.video_id, surface, surface === "image" ? imgPrompt : prompt);
      if (surface === "image") { setImgPrompt(res.prompt); setImgState("idle"); }
      else { setPrompt(res.prompt); setPromptState("idle"); }
    } catch { /* leave the box as-is */ }
    setImproving("");
  };

  // useState only seeds on mount, so when the server value changes under an open
  // page (e.g. coverage just rewrote the motion prompt) the box kept showing its
  // stale/empty initial text. Re-sync from the asset when the SAVED value changes,
  // unless a save is mid-flight (don't clobber what the user is writing).
  const serverPrompt = asset.video_prompt || "";
  const serverImgPrompt = asset.image_prompt || "";
  useEffect(() => {
    if (promptState !== "saving") setPrompt(serverPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverPrompt]);
  useEffect(() => {
    if (imgState !== "saving") setImgPrompt(serverImgPrompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serverImgPrompt]);

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isPlaying) v.play().catch(() => undefined);
    else { v.pause(); v.currentTime = 0; }
  }, [isPlaying]);

  return (
    <GlassCard
      className={`p-0 overflow-hidden group ${hasClip || canAnimate || readOnly ? "cursor-pointer" : "cursor-default"}`}
      style={isFailed ? { border: "1px solid rgba(255,90,90,0.5)" }
        : badCrop ? { border: "1px solid rgba(255,110,110,0.45)" } : undefined}
      onClick={onTap}
    >
      <div className="aspect-video relative flex items-center justify-center" style={{ background: "var(--bg-elevated)" }}>
        {hasClip ? (
          <video
            ref={videoRef}
            src={toDisplayImageUrl(asset.video_clip_url) ?? undefined}
            poster={toDisplayImageUrl(asset.image_url) ?? undefined}
            preload="none"
            playsInline
            loop
            className="absolute inset-0 w-full h-full object-cover"
          />
        ) : (
          asset.image_url && (
            <img
              src={toDisplayImageUrl(asset.image_url)}
              alt={label}
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover"
              style={{ opacity: isGenerating || isRecropping || isRedrawing ? 0.4 : isQueued || isRedrawQueued ? 0.6 : 0.85 }}
            />
          )
        )}

        {/* Dialogue badge — this picture will SPEAK */}
        {speaker && (
          <span className="absolute top-2 left-2 z-10 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-medium"
            style={{ background: "rgba(0,0,0,0.55)", color: "var(--turquoise)", backdropFilter: "blur(4px)" }}>
            <MessageCircle size={10} /> {speaker}
          </span>
        )}

        {/* Picture-model badge — the model that ACTUALLY generated this panel, so a
            creator who picked one model but sees a stale/fallback badge can tell at
            a glance instead of the override silently lying (checklist §0.1). */}
        {asset.image_model && (
          <span
            className="absolute top-2 right-2 z-10 inline-flex items-center px-1.5 py-0.5 rounded-md text-[10px] font-mono font-medium"
            title={`Generated with ${asset.image_model}`}
            style={{ background: "rgba(0,0,0,0.55)", color: "var(--text-secondary)", backdropFilter: "blur(4px)" }}>
            {IMAGE_MODEL_BADGE[asset.image_model] ?? asset.image_model}
          </span>
        )}

        {/* Bad crop badge — one tap fixes it for free, EXCEPT a re-crop on a
            shot that already has a clip re-animates it automatically (paid),
            so it's part of readOnly's money-affordance gate too. */}
        {badCrop && !readOnly && !isGenerating && !isRecropping && !isRedrawing && (
          <button
            onClick={(e) => { e.stopPropagation(); onRecrop(); }}
            disabled={disabled}
            title={`This picture was cut wrong from its storyboard. Re-crop it for free — a clip on it re-animates automatically (~$${perClip.toFixed(2)}).`}
            className="absolute bottom-2 left-2 z-20 inline-flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-semibold transition-all hover:brightness-125 disabled:opacity-50"
            style={{ background: "rgba(220, 50, 50, 0.92)", color: "white" }}>
            <Scissors size={10} /> Bad crop — fix it
          </button>
        )}

        {/* State overlays */}
        {/* C2: queued — clicked but the coalescing debounce hasn't fired yet, or
            waiting on another in-flight batch to free up. No spinner (nothing's
            actually running for this card yet), just a held state.
            C3: isRedrawQueued shares this same visual — a card is only ever
            queued on ONE track at a time in practice (the two Redraw/Run
            buttons are separate affordances), so no separate label is needed. */}
        {(isQueued || isRedrawQueued) && !isGenerating && !isRecropping && !isRedrawing && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2" style={{ background: "rgba(0,0,0,0.25)" }}>
            <Clock size={20} style={{ color: "var(--text-secondary)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>Queued…</span>
          </div>
        )}
        {(isGenerating || isRecropping || isRedrawing) && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2">
            <Loader2 size={22} className="animate-spin" style={{ color: "var(--purple)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
              {isRecropping ? "Re-cropping…" : isRedrawing ? "Redrawing…" : "Bringing it to life…"}
            </span>
          </div>
        )}
        {isFailed && !isGenerating && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2" style={{ background: "rgba(40,0,0,0.45)" }}>
            <AlertTriangle size={18} style={{ color: "rgb(255,120,120)" }} />
            <span className="px-2 py-1 rounded-md text-[11px] font-semibold" style={{ background: "rgba(255,90,90,0.9)", color: "white" }}>
              Try again
            </span>
          </div>
        )}
        {/* C3: redraw's own "Try again" — a SEPARATE overlay (not folded into
            isFailed above) because its retry action is different: clicking
            anywhere on the card falls through to the GlassCard's onClick=
            {onTap}, which for a clip failure happens to BE the retry
            (animateOne, since !video_clip_url) — but for a redraw failure
            that would wrongly trigger a clip animate instead. This overlay
            stops that propagation and calls onRedraw() directly. */}
        {isRedrawFailed && !isFailed && !isGenerating && !isRecropping && !isRedrawing && (
          <div
            className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2"
            style={{ background: "rgba(40,0,0,0.45)" }}
            onClick={(e) => { e.stopPropagation(); onRedraw(); }}
          >
            <AlertTriangle size={18} style={{ color: "rgb(255,120,120)" }} />
            <span className="px-2 py-1 rounded-md text-[11px] font-semibold" style={{ background: "rgba(255,90,90,0.9)", color: "white" }}>
              Redraw failed — try again
            </span>
          </div>
        )}
        {canAnimate && !hasClip && !isGenerating && !isRecropping && !isRedrawing && !isFailed && !isQueued && !isRedrawQueued && !isRedrawFailed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.45)" }}>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
              <Play size={12} /> Animate · ${perClip.toFixed(2)}
            </span>
          </div>
        )}
        {/* readOnly's onTap does something else entirely (focus + switch
            altitude, not play/pause) — showing a "tap to play" hint would be
            misleading there, so this hover hint is part of readOnly's gate
            too (isPlaying is always false on a readOnly card regardless). */}
        {hasClip && !isPlaying && !readOnly && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.35)" }}>
            <Play size={28} style={{ color: "white" }} />
          </div>
        )}
        {hasClip && isPlaying && (
          <div className="absolute bottom-2 right-2 z-10">
            <Pause size={16} style={{ color: "white", opacity: 0.8 }} />
          </div>
        )}

        {/* Hover actions: clip level when a clip exists, picture level otherwise.
            Redo-clip is real spend (same $/clip as Animate); delete is
            destructive. readOnly (Director board) hides the whole cluster
            except the free download link, rather than wiring dead buttons. */}
        {!isGenerating && !isRecropping && !isRedrawing && (
          <>
            <div className="absolute top-2 right-2 z-20 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              {asset.image_url && (
                <a
                  href={`${asset.image_url}${asset.image_url.includes("?") ? "&" : "?"}download=${label}.png`}
                  download={`${label}.png`}
                  onClick={(e) => e.stopPropagation()}
                  title="Download this picture"
                  className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                  style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}>
                  <Download size={13} />
                </a>
              )}
              {!readOnly && (hasClip ? (
                <>
                  <button
                    onClick={(e) => { e.stopPropagation(); onRedoClip(); }}
                    title={`Redo this clip · $${perClip.toFixed(2)}`}
                    className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                    style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}>
                    <RotateCcw size={13} />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); onDeleteClip(); }}
                    title="Remove this clip (keeps the picture)"
                    className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                    style={{ background: "rgba(0,0,0,0.6)", color: "rgb(255,120,120)" }}>
                    <X size={13} />
                  </button>
                </>
              ) : (
                <button
                  onClick={(e) => { e.stopPropagation(); onDeletePicture(); }}
                  title="Remove this picture (the storyboard stays — re-extract to refill)"
                  className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                  style={{ background: "rgba(0,0,0,0.6)", color: "rgb(255,120,120)" }}>
                  <X size={13} />
                </button>
              ))}
            </div>
            {hasClip && (
              <div className="absolute top-2 right-2 z-10 w-7 h-7 rounded-full flex items-center justify-center group-hover:opacity-0 transition-opacity"
                style={{ background: "rgba(0, 230, 138, 0.2)", color: "var(--green)" }}>
                <Check size={14} />
              </div>
            )}
          </>
        )}
      </div>

      <div className="p-3">
        <div className="flex items-center gap-2 mb-1.5 flex-wrap">
          <SegmentBadge label={label} />
          {/* C14 per-scene model badge — tap opens the override sheet.
              Visibility is `showModelBadge` (defaults to canAnimate for
              backward compat — see the prop's doc comment); ScenesWorkspaceTab
              never passes it, so this renders exactly as before there. */}
          {showModelBadge && (
            <button
              onClick={(e) => { e.stopPropagation(); onOpenModelOverride(); }}
              title={`${modelDisplayName(effectiveModelId) || effectiveModelId} — ${modelReason}. Tap to change this scene's clip model.`}
              // `whitespace-nowrap` fixes a real board bug: without it, this
              // pill's text (extra-long once priceForModel adds a price)
              // soft-wrapped mid-word inside the board's narrower 3-col
              // canvas column and looked clipped/broken. If the whole pill
              // doesn't fit next to the S-XX.XXX label, it now wraps to the
              // NEXT ROW as one intact pill (flex-wrap on the parent row),
              // never mid-word.
              className="inline-flex items-center gap-1 whitespace-nowrap px-1.5 py-0.5 rounded-md text-[10px] font-mono font-medium transition-all hover:brightness-125"
              style={{
                // `priceForModel` is only ever passed by the Director board
                // (ScenesWorkspaceTab doesn't price per-card), so its presence
                // doubles as "this chip is the primary/only piece of model
                // info on this surface, not one detail among many" — reason
                // enough to read it clearly rather than dimmed, without
                // touching ScenesWorkspaceTab's unchanged default styling.
                background: modelOverridden ? "rgba(139, 92, 246, 0.16)" : priceForModel ? "rgba(255,255,255,0.09)" : "rgba(255,255,255,0.05)",
                color: modelOverridden ? "var(--purple)" : priceForModel ? "var(--text-secondary)" : "var(--text-tertiary)",
                border: modelOverridden ? "1px solid rgba(139, 92, 246, 0.35)" : priceForModel ? "1px solid rgba(255,255,255,0.18)" : "1px solid rgba(255,255,255,0.08)",
              }}>
              <Film size={9} />
              {modelDisplayName(effectiveModelId) || effectiveModelId}
              {/* Real $/clip for the resolved model, only when the caller
                  passes priceForModel (ScenesWorkspaceTab doesn't — it
                  already prices per-action elsewhere, so it keeps its exact
                  prior appearance). Cheapest-tier estimate, same imprecision
                  as the rest of the app (docs/cost-awareness.md) — the `~`
                  labels it as approximate rather than exact. No opacity dip
                  on this span — it needs to read as clearly as the model
                  name next to it, not fade into the background. */}
              {priceForModel && (() => {
                const price = priceForModel(effectiveModelId);
                return price != null ? <span>· ~${price.toFixed(2)}</span> : null;
              })()}
              {modelOverridden && (
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: "var(--purple)" }} />
              )}
            </button>
          )}
          {/* C23 per-shot camera-move chip (checklist §2.2, UX map §4) — tap
              opens the preset sheet. Shows the auto-selected value from
              camera_movement when present, else "Auto"; a manual pick gets
              the same purple "manual" dot the model badge uses. Gated on
              canAnimate: no clip stage, no camera move to show. */}
          {canAnimate && (
            <button
              onClick={(e) => { e.stopPropagation(); onOpenCameraPreset(); }}
              title={`Camera move: ${cameraMove.label}${cameraMove.isManual ? " (manual)" : ""}. Tap to change.`}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-mono font-medium transition-all hover:brightness-125"
              style={{
                background: cameraMove.isManual ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.05)",
                color: cameraMove.isManual ? "var(--purple)" : "var(--text-tertiary)",
                border: cameraMove.isManual ? "1px solid rgba(139, 92, 246, 0.35)" : "1px solid rgba(255,255,255,0.08)",
              }}>
              <Camera size={9} />
              {cameraMove.label}
              {cameraMove.isManual && (
                <span className="w-1 h-1 rounded-full shrink-0" style={{ background: "var(--purple)" }} />
              )}
            </button>
          )}
        </div>
        <p className="text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--text-secondary)" }}>
          {asset.sentence_text || asset.video_prompt || "—"}
        </p>
        {/* Image prompt — edit + redraw just this picture (anchored on the
            locked cast). Redraw is real spend (~$picturePrice), so this
            whole panel is part of readOnly's money-affordance gate. */}
        {!readOnly && (
        <details className="mt-2" onClick={(e) => e.stopPropagation()}>
          <summary className="text-[10px] cursor-pointer select-none inline-flex items-center gap-1" style={{ color: "var(--text-tertiary)" }}>
            <ImageIcon size={10} /> Image prompt — edit &amp; redraw
          </summary>
          <textarea
            value={imgPrompt}
            onChange={(e) => { setImgPrompt(e.target.value); setImgState("idle"); }}
            onClick={(e) => e.stopPropagation()}
            rows={4}
            placeholder="Describe this picture. Redraw keeps your locked characters."
            className="w-full mt-1.5 text-[11px] rounded-lg p-2 outline-none resize-y"
            style={{ background: "var(--bg-void)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,0.12)" }}
          />
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              onClick={async (e) => {
                e.stopPropagation();
                setImgState("saving");
                try { await updateImagePrompt(asset.id, imgPrompt); onRedraw(); setImgState("idle"); }
                catch { setImgState("error"); }
              }}
              disabled={imgState === "saving" || isRedrawing}
              title={isRedrawQueued ? "Queued — will fire as soon as the current batch clears, coalesced with any other cards you've clicked." : undefined}
              className="inline-flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}>
              <RotateCcw size={11} />{" "}
              {
                // C3: the button's own label now also reflects the ASYNC
                // redraw state (isRedrawing/isRedrawQueued/isRedrawFailed come
                // from the parent's hook-backed track), not just this card's
                // local `imgState` (which only covers the prompt-save call
                // that fires just before onRedraw()).
                imgState === "saving" ? "Starting…"
                  : isRedrawQueued ? "Queued…"
                  : isRedrawing ? "Redrawing…"
                  : isRedrawFailed ? "Redraw failed — try again"
                  : imgState === "error" ? "Failed — retry"
                  : `Redraw picture · ~$${picturePrice.toFixed(2)}`
              }
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); improve("image"); }}
              disabled={improving !== ""}
              title="AI rewrites this prompt to be stronger — review it, then redraw."
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
              {improving === "image" ? "Improving…" : "✨ Improve"}
            </button>
          </div>
        </details>
        )}
        {/* A static/photo plan has no clip stage, so it must not read as if a
            motion prompt is unfinished work. */}
        {canAnimate && (
        <details className="mt-2" onClick={(e) => e.stopPropagation()}>
          <summary className="text-[10px] cursor-pointer select-none inline-flex items-center gap-1" style={{ color: "var(--text-tertiary)" }}>
            <Film size={10} /> Motion prompt{hasClip ? "" : " — edit before animating"}
          </summary>
          <textarea
            value={prompt}
            onChange={(e) => { setPrompt(e.target.value); setPromptState("idle"); }}
            onClick={(e) => e.stopPropagation()}
            rows={4}
            placeholder="How should this shot move? Leave blank to auto-write it."
            className="w-full mt-1.5 text-[11px] rounded-lg p-2 outline-none resize-y"
            style={{ background: "var(--bg-void)", color: "var(--text-primary)", border: "1px solid rgba(255,255,255,0.12)" }}
          />
          <div className="mt-1.5 flex items-center gap-1.5">
            <button
              onClick={async (e) => {
                e.stopPropagation();
                setPromptState("saving");
                try { await updateVideoPrompt(asset.id, prompt); setPromptState("saved"); }
                catch { setPromptState("error"); }
              }}
              disabled={promptState === "saving"}
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
              {promptState === "saving" ? "Saving…" : promptState === "saved" ? "Saved ✓" : promptState === "error" ? "Failed — retry" : "Save prompt"}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); improve("motion"); }}
              disabled={improving !== ""}
              title="AI rewrites this motion prompt to be stronger — review it, then save."
              className="text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
              {improving === "motion" ? "Improving…" : "✨ Improve"}
            </button>
          </div>
        </details>
        )}
      </div>
    </GlassCard>
  );
}
