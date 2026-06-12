"use client";

import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { Check, Loader2, Play, Pause, Sparkles, Film, RotateCcw, X, MoreHorizontal, MessageCircle, AlertTriangle } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { getVideoAssets, getDialogueMap, runPipelineStage, clearStaleTask, updateVideoStyles, getDefaultVideoMotionPrompt, updateVideo, deleteClip } from "@/lib/api";
import { clipCost } from "@/lib/next-action";
import { toDisplayImageUrl } from "@/lib/utils";
import { useTaskWatcher } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import type { VideoDetail, Asset } from "@/lib/api";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";

/** Models with a live generation path. Everything else in the registry is
 * visible but disabled — the old dropdown silently ignored the choice. */
const WIRED_MODELS: { id: string; label: string }[] = [
  { id: "grok-imagine", label: "Grok Imagine — $0.10/clip" },
  { id: "veo-3.1-fast", label: "Veo 3.1 Fast — $0.30/clip" },
  { id: "veo-3.1-quality", label: "Veo 3.1 Quality — $1.25/clip" },
];
const COMING_SOON_MODELS = ["Kling 3.0 Pro", "Runway Gen-4 Turbo", "Hailuo 2.3"];

/** Loose containment match: dialogue segment words (kept verbatim by the
 * tagger) appear inside the card's sentence text. */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

interface VideoClipsTabProps {
  video: VideoDetail & { id: string };
  onAdvanced?: () => void;
}

export function VideoClipsTab({ video }: VideoClipsTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const model = video.video_model || "grok-imagine";
  const perClip = clipCost(model, 1);

  const [generatingIds, setGeneratingIds] = useState<Set<string>>(new Set());
  const [failedIds, setFailedIds] = useState<Set<string>>(new Set());
  const [confirmKey, setConfirmKey] = useState<string | null>(null); // "scene-3" | "all"
  const [menuOpen, setMenuOpen] = useState(false);
  const [showMotionPrompt, setShowMotionPrompt] = useState(false);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const promptsAutoRan = useRef(false);
  const menuRef = useRef<HTMLDivElement>(null);

  // ALWAYS-ON watcher (the pt-3 lesson): the strip must show whatever holds
  // the video's task slot — the silent prompt auto-run, the banner, another
  // browser tab — not just work this component started. A caller-armed
  // poller here made taps bounce off an invisible task with a bare 409.
  const { running, message: taskMessage, markStarted } = useTaskWatcher({
    videoId: video.id,
    onComplete: () => {
      setGeneratingIds(new Set());
      setConfirmKey(null);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onFailed: (error) => {
      // Cards that were in flight when the task died show Try Again in place.
      setFailedIds((prev) => new Set([...prev, ...generatingIds]));
      setGeneratingIds(new Set());
      setConfirmKey(null);
      toast.error(error || "Clip generation hit a problem — tap the card to try again.");
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
  });

  const { data: assets = [] } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
    refetchInterval: running ? 4000 : false,
  });
  const { data: dialogueMap } = useQuery({
    queryKey: ["dialogue-map", video.id],
    queryFn: () => getDialogueMap(video.id),
    staleTime: 60_000,
  });

  // Cards = every segment with a final picture (the contract: ALL get clips).
  const cards = useMemo(
    () => assets.filter((a) => a.image_url).slice().sort((a, b) =>
      (a.scene ?? 0) - (b.scene ?? 0) || (a.image_index ?? 0) - (b.image_index ?? 0)),
    [assets],
  );
  const doneCount = cards.filter((a) => a.video_clip_url).length;
  const pendingCount = cards.length - doneCount;
  const promptlessCount = cards.filter((a) => !a.video_prompt && !a.video_clip_url).length;

  // Scene → speakers map for the 💬 badge (matched per-card below).
  const dialogueByScene = useMemo(() => {
    const map = new Map<number, { speaker: string; text: string }[]>();
    for (const sc of dialogueMap?.scenes ?? []) {
      map.set(sc.scene, sc.segments
        .filter((s) => s.type === "dialogue" && s.speaker && s.text)
        .map((s) => ({ speaker: s.speaker as string, text: norm(s.text) })));
    }
    return map;
  }, [dialogueMap]);

  const speakerFor = useCallback((asset: Asset): string | null => {
    const lines = dialogueByScene.get(asset.scene ?? -1);
    if (!lines?.length || !asset.sentence_text) return null;
    const text = norm(asset.sentence_text);
    return lines.find((l) => text.includes(l.text) || l.text.includes(text))?.speaker ?? null;
  }, [dialogueByScene]);

  const sceneGroups = useMemo(() => {
    const groups = new Map<number, Asset[]>();
    for (const a of cards) {
      const s = a.scene ?? 0;
      if (!groups.has(s)) groups.set(s, []);
      groups.get(s)!.push(a);
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0]);
  }, [cards]);

  // Motion prompts are plumbing, not a decision: write them silently the
  // moment the tab sees cards without one. Failures surface via the banner's
  // task watcher; the strip shows quiet progress meanwhile.
  useEffect(() => {
    if (promptsAutoRan.current || running || cards.length === 0 || promptlessCount === 0) return;
    promptsAutoRan.current = true;
    (async () => {
      try {
        await runPipelineStage(video.id, "video-scripts");
        markStarted();
      } catch {
        promptsAutoRan.current = false; // 409 etc. — retry on next mount
      }
    })();
  }, [cards.length, promptlessCount, running, video.id, markStarted]);

  useEffect(() => {
    if (!menuOpen) return;
    const close = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [menuOpen]);

  const startClipTask = useCallback(async (params: Record<string, string | number>, ids: string[]) => {
    if (running) {
      // Say WHAT is running — a bare "already running" reads as a bug.
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}. This card will be tappable the moment it's done.`);
      return;
    }
    setFailedIds((prev) => {
      const next = new Set(prev);
      ids.forEach((id) => next.delete(id));
      return next;
    });
    setGeneratingIds(new Set(ids));
    try {
      await runPipelineStage(video.id, "clip", params);
      markStarted();
    } catch (err) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "clip", params);
          markStarted();
          return;
        } catch (retryErr) {
          toast.error((retryErr as Error).message);
        }
      } else {
        toast.error(message || "Couldn't start the clip.");
      }
      setGeneratingIds(new Set());
    }
  }, [running, taskMessage, video.id, toast, markStarted]);

  const animateOne = (asset: Asset, force = false) =>
    startClipTask(force ? { asset_id: asset.id, force: "true" } : { asset_id: asset.id }, [asset.id]);

  const animateScene = (scene: number, pendingIds: string[]) =>
    startClipTask({ scene }, pendingIds);

  const animateAll = () =>
    startClipTask({}, cards.filter((a) => !a.video_clip_url).map((a) => a.id));

  const removeClip = useCallback(async (asset: Asset) => {
    try {
      await deleteClip(video.id, asset.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  const handleModelChange = useCallback(async (next: string) => {
    try {
      await updateVideoStyles(video.id, { video_model: next });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  /** Confirm-then-run for anything over $0.50; cheaper actions just go. */
  const confirmable = (key: string, dollars: number, run: () => void) => {
    if (dollars <= 0.5 || confirmKey === key) {
      setConfirmKey(null);
      run();
    } else {
      setConfirmKey(key);
    }
  };

  if (cards.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Film size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Nothing to animate yet
        </p>
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          Clips bring your final pictures to life — finish the storyboard first and they&apos;ll appear here.
        </p>
      </GlassCard>
    );
  }

  const remainingCost = clipCost(model, pendingCount);
  const modelLabel = WIRED_MODELS.find((m) => m.id === model)?.label.split(" — ")[0]
    ?? model;

  return (
    <div className="space-y-5">
      {/* ── Status strip — the only chrome ── */}
      <div className="flex items-center gap-3 rounded-xl px-4 py-3"
        style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: doneCount === cards.length ? "var(--green)" : "var(--text-primary)" }}>
            {doneCount} of {cards.length}
          </strong>{" "}
          pictures animated
          {pendingCount > 0 && (
            <span style={{ color: "var(--text-tertiary)" }}> · ≈ ${remainingCost.toFixed(2)} to finish · {modelLabel}</span>
          )}
        </span>
        {running && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            style={{ background: "rgba(139, 92, 246, 0.15)", color: "var(--purple)", border: "1px solid rgba(139, 92, 246, 0.35)" }}>
            <Loader2 size={12} className="animate-spin" />
            {taskMessage || "Working…"}
          </span>
        )}
        <div className="flex-1" />
        {doneCount > 0 && pendingCount > 0 && (
          <button
            onClick={() => confirmable("all", remainingCost, animateAll)}
            disabled={running}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-40 transition-all hover:brightness-110"
            style={{ background: confirmKey === "all" ? "var(--gold)" : "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {confirmKey === "all" ? `Confirm — $${remainingCost.toFixed(2)}` : "Animate the rest"}
          </button>
        )}
        {confirmKey === "all" && (
          <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            Cancel
          </button>
        )}
        <StopGenerationButton videoId={video.id} running={running} />
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((v) => !v)}
            aria-label="Advanced options"
            className="p-1.5 rounded-lg transition-colors hover:bg-white/5"
            style={{ color: "var(--text-tertiary)" }}
          >
            <MoreHorizontal size={16} />
          </button>
          {menuOpen && (
            <div className="absolute right-0 top-8 z-30 w-64 rounded-xl p-2 space-y-1"
              style={{ background: "var(--bg-elevated)", border: "1px solid rgba(255,255,255,0.1)", boxShadow: "0 12px 32px rgba(0,0,0,0.5)" }}>
              <p className="px-2 pt-1 text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                Clip model
              </p>
              {WIRED_MODELS.map((m) => (
                <button key={m.id}
                  onClick={() => { handleModelChange(m.id); setMenuOpen(false); }}
                  className="w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 flex items-center gap-2"
                  style={{ color: model === m.id ? "var(--turquoise)" : "var(--text-secondary)" }}>
                  {model === m.id ? <Check size={12} /> : <span className="w-3" />}
                  {m.label}
                </button>
              ))}
              {COMING_SOON_MODELS.map((label) => (
                <div key={label} className="px-2 py-1.5 text-xs flex items-center gap-2 opacity-40 cursor-not-allowed"
                  style={{ color: "var(--text-tertiary)" }}>
                  <span className="w-3" />{label} — coming soon
                </div>
              ))}
              <div className="border-t my-1" style={{ borderColor: "rgba(255,255,255,0.08)" }} />
              <button
                onClick={() => {
                  setMenuOpen(false);
                  runPipelineStage(video.id, "video-scripts").then(() => markStarted())
                    .catch((e) => toast.error((e as Error).message));
                }}
                disabled={running}
                className="w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 disabled:opacity-40 flex items-center gap-2"
                style={{ color: "var(--text-secondary)" }}>
                <Sparkles size={12} /> Re-write motion directions
              </button>
              <button
                onClick={() => { setShowMotionPrompt((v) => !v); setMenuOpen(false); }}
                className="w-full text-left px-2 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 flex items-center gap-2"
                style={{ color: "var(--text-secondary)" }}>
                <Film size={12} /> {showMotionPrompt ? "Hide" : "Edit"} motion instructions
              </button>
            </div>
          )}
        </div>
      </div>

      {showMotionPrompt && (
        <SystemPromptEditor
          label="Video Motion System Prompt"
          currentValue={video.video_motion_system_prompt}
          onSave={async (text) => {
            await updateVideo(video.id, { video_motion_system_prompt: text || null });
            queryClient.invalidateQueries({ queryKey: ["video", video.id] });
          }}
          onReset={async () => {
            const res = await getDefaultVideoMotionPrompt();
            await updateVideo(video.id, { video_motion_system_prompt: null });
            queryClient.invalidateQueries({ queryKey: ["video", video.id] });
            return res.prompt;
          }}
        />
      )}

      {/* ── Scene groups ── */}
      {sceneGroups.map(([scene, sceneAssets]) => {
        const scenePending = sceneAssets.filter((a) => !a.video_clip_url);
        const sceneCost = clipCost(model, scenePending.length);
        const sceneKey = `scene-${scene}`;
        return (
          <section key={scene}>
            <div className="flex items-center gap-3 mb-3">
              <h3 className="text-sm font-display" style={{ color: "var(--text-primary)" }}>
                Scene {scene}
              </h3>
              <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                {sceneAssets.length - scenePending.length} of {sceneAssets.length} animated
              </span>
              <div className="flex-1" />
              {scenePending.length > 0 && (
                <>
                  {confirmKey === sceneKey && (
                    <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                      Cancel
                    </button>
                  )}
                  <button
                    onClick={() => confirmable(sceneKey, sceneCost, () => animateScene(scene, scenePending.map((a) => a.id)))}
                    disabled={running}
                    className="px-2.5 py-1 rounded-lg text-xs font-medium disabled:opacity-40 transition-all hover:bg-white/5"
                    style={confirmKey === sceneKey
                      ? { background: "var(--gold)", color: "var(--bg-void)" }
                      : { border: "1px solid rgba(255,255,255,0.15)", color: "var(--text-secondary)" }}
                  >
                    {confirmKey === sceneKey
                      ? `Confirm — $${sceneCost.toFixed(2)}`
                      : `Animate this scene · $${sceneCost.toFixed(2)}`}
                  </button>
                </>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
              {sceneAssets.map((asset) => (
                <ClipCard
                  key={asset.id}
                  asset={asset}
                  speaker={speakerFor(asset)}
                  perClip={perClip}
                  isGenerating={generatingIds.has(asset.id) && running}
                  isFailed={failedIds.has(asset.id)}
                  isPlaying={playingId === asset.id}
                  onTap={() => {
                    if (asset.video_clip_url) setPlayingId((p) => (p === asset.id ? null : asset.id));
                    else animateOne(asset);
                  }}
                  onRedo={() => animateOne(asset, true)}
                  onDelete={() => removeClip(asset)}
                />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function ClipCard({ asset, speaker, perClip, isGenerating, isFailed, isPlaying, onTap, onRedo, onDelete }: {
  asset: Asset;
  speaker: string | null;
  perClip: number;
  isGenerating: boolean;
  isFailed: boolean;
  isPlaying: boolean;
  onTap: () => void;
  onRedo: () => void;
  onDelete: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const done = Boolean(asset.video_clip_url);
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;
    if (isPlaying) v.play().catch(() => undefined);
    else { v.pause(); v.currentTime = 0; }
  }, [isPlaying]);

  return (
    <GlassCard
      className="p-0 overflow-hidden group cursor-pointer"
      style={isFailed ? { border: "1px solid rgba(255,90,90,0.5)" } : undefined}
      onClick={onTap}
    >
      <div className="aspect-video relative flex items-center justify-center" style={{ background: "var(--bg-elevated)" }}>
        {done ? (
          <video
            ref={videoRef}
            src={toDisplayImageUrl(asset.video_clip_url) ?? undefined}
            poster={toDisplayImageUrl(asset.image_url) ?? undefined}
            preload="none"
            playsInline
            loop
            className="absolute inset-0 w-full h-full object-cover"
            onEnded={() => undefined}
          />
        ) : (
          asset.image_url && (
            <img
              src={toDisplayImageUrl(asset.image_url)}
              alt={label}
              loading="lazy"
              className="absolute inset-0 w-full h-full object-cover"
              style={{ opacity: isGenerating ? 0.4 : 0.85 }}
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

        {/* State overlays */}
        {isGenerating && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2">
            <Loader2 size={22} className="animate-spin" style={{ color: "var(--purple)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>Bringing it to life…</span>
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
        {!done && !isGenerating && !isFailed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.45)" }}>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
              <Play size={12} /> Animate · ${perClip.toFixed(2)}
            </span>
          </div>
        )}
        {done && !isPlaying && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.35)" }}>
            <Play size={28} style={{ color: "white" }} />
          </div>
        )}
        {done && isPlaying && (
          <div className="absolute bottom-2 left-2 z-10">
            <Pause size={16} style={{ color: "white", opacity: 0.8 }} />
          </div>
        )}

        {/* Done check + hover actions (same pattern as storyboard cards) */}
        {done && !isGenerating && (
          <>
            <div className="absolute top-2 right-2 z-20 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
              <button
                onClick={(e) => { e.stopPropagation(); onRedo(); }}
                title={`Redo this clip · $${perClip.toFixed(2)}`}
                className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                style={{ background: "rgba(0,0,0,0.6)", color: "var(--text-secondary)" }}
              >
                <RotateCcw size={13} />
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onDelete(); }}
                title="Remove this clip (keeps the picture)"
                className="w-7 h-7 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
                style={{ background: "rgba(0,0,0,0.6)", color: "rgb(255,120,120)" }}
              >
                <X size={13} />
              </button>
            </div>
            <div className="absolute top-2 right-2 z-10 w-7 h-7 rounded-full flex items-center justify-center group-hover:opacity-0 transition-opacity"
              style={{ background: "rgba(0, 230, 138, 0.2)", color: "var(--green)" }}>
              <Check size={14} />
            </div>
          </>
        )}
      </div>

      <div className="p-3">
        <div className="flex items-center gap-2 mb-1.5">
          <SegmentBadge label={label} />
        </div>
        <p className="text-[11px] leading-relaxed line-clamp-2" style={{ color: "var(--text-secondary)" }}>
          {asset.sentence_text || asset.video_prompt || "—"}
        </p>
      </div>
    </GlassCard>
  );
}
