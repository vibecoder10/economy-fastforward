"use client";

/**
 * ScenesWorkspaceTab — ONE workspace per scene: boards → final pictures →
 * clips, redo at any level in place (Ryan's answer 1, 2026-06-12). The
 * separate Storyboard and Video Clips tabs collapsed into this.
 *
 * Design bar (decisions.md): the page banner is the ONLY primary CTA;
 * everything here is a per-item contextual control or lives behind ⋯.
 * Clips follow the trust-ladder contract: tap a card = animate (~$0.09,
 * no confirm), "Animate this scene" per group, "Animate the rest" in the
 * strip; confirms only above $0.50. Bad crops wear a red badge with a
 * one-tap Re-crop that also re-animates stale clips server-side.
 */

import { useState, useMemo, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check, Loader2, Image as ImageIcon, RefreshCw,
  Lock, Unlock, ArrowLeft, X, MoreHorizontal, Play, Pause,
  MessageCircle, AlertTriangle, Film, Sparkles, RotateCcw, Scissors, MapPin, Volume2, LayoutGrid, Download, Ratio,
  Camera,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { PromptExpander } from "@/components/video-detail/prompt-expander";
import { VoicePlayer } from "@/components/video-detail/voice-player";
import {
  getVideoScript, getVideoAssets, getDialogueMap, updateStoryboardMode,
  clearSceneStoryboard, clearAllStoryboards, clearStoryboardSlot,
  clearAllExtractedPanels, clearExtractedPanel, uploadStoryboardGrid,
  runPipelineStage, clearStaleTask, updateVideoStyles, updateVideo,
  getDefaultVideoMotionPrompt, getAudioToken, advanceVideo, unlockStory,
  deleteClip, recropAsset, getEnvironments, getVideoCharacters, updateVideoPrompt, updateImagePrompt, improvePrompt,
  getModels, getVideoActions, updateAssetModelOverride, approveScene,
  getCameraPresets, updateAssetCameraPreset,
} from "@/lib/api";
import type { VideoModelInfo, CameraPresetInfo, StoryboardBoardError } from "@/lib/api";
import { clipCost, CLIP_COST_PER_MODEL } from "@/lib/next-action";
import { useSharedTaskWatcher, type TaskWatcherBridge } from "@/hooks/use-task-poller";
import { useClipTrustLadder } from "@/hooks/use-clip-trust-ladder";
import { useToast } from "@/components/ui/toast";
import { Modal } from "@/components/ui/modal";
import type { VideoDetail, Asset } from "@/lib/api";
import { toDisplayImageUrl, toDisplayVideoUrl, appendQueryParam } from "@/lib/utils";
import { API_URL } from "@/lib/env";
import { AnimaticPlayer } from "@/components/production/AnimaticPlayer";
import { StopGenerationButton } from "@/components/production/StopGenerationButton";

/** Network-failure safety net ONLY — if GET /api/models can't be reached, the
 * clip-model selector still needs something selectable instead of rendering
 * empty. This is NOT the source of truth (that's the `wiredVideoModels`
 * derivation below, backed by the `["models"]` query); it exists so a
 * dropped request never breaks the UI. */
const FALLBACK_WIRED_MODELS: { id: string; label: string }[] = [
  // TODO: source from API — this is the offline-only safety net, so it can't
  // read modelsData. $0.09 = grok-imagine's 6s tier (channel_profile.py,
  // C09a); keep in sync by hand if that price ever moves.
  { id: "grok-imagine", label: "Grok Imagine — $0.09/clip" },
];

/** Short labels for the picture-model badge (asset.image_model — the model that
 * ACTUALLY drew this panel, from shared/clients/image_model_router.py). Matches
 * the Pictures selector's 3 values (ScenesWorkspaceTab L1121-1126). */
const IMAGE_MODEL_BADGE: Record<string, string> = {
  "gpt-image-2": "GPT",
  "nano-banana-2": "Nano",
  "z-image": "Z",
};

/** Human labels for a failed board slot's chip — mirrors the backend's OWN
 * copy in scripts/coverage_to_app.py's _SHEET_FAIL_LABELS (that one feeds
 * the scene-summary progress line; this one feeds the badge on the empty
 * slot itself). Same 5 class strings from ScriptScene.storyboard_errors
 * (migration 113), capitalized for UI display. */
const SHEET_FAIL_LABELS: Record<StoryboardBoardError["class"], string> = {
  moderation: "Blocked by OpenAI moderation",
  sensitive: "Flagged as sensitive",
  kie_transient: "Kie server error (transient)",
  ref_fetch: "Reference image fetch failed (transient)",
  unknown: "Failed",
};

/** Loose containment match for the 💬 badge — mirrors backend match_lines. */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();
}

/** Humanize a camera_moves.py catalog id ("crash_zoom_in" -> "Crash Zoom
 * In") — the chip's fallback label when a move isn't in the curated preset
 * list fetched from GET /api/camera-presets (e.g. the auto pick landed on
 * a full-catalog move outside the curated dozen). */
function humanizeCameraId(id: string): string {
  return id.split("_").map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
}

/** The camera-move chip's display text + whether it's a manual (vs auto)
 * pick (checklist §2.2/C23). Reads `camera_preset_id` (the creator's
 * manual override) first; falls back to `camera_movement` (the AUTO/
 * "earned" pick camera_selector.py stamps at shot-plan time — raw shape
 * "move_id|PURPOSE" or "static"); "Auto" when neither exists. Fail-safe by
 * construction — every branch returns a label, so a shot with no camera
 * data at all still renders an "Auto" chip, never a broken one. */
function describeCameraMove(asset: Asset, presets: CameraPresetInfo[]): { label: string; isManual: boolean } {
  if (asset.camera_preset_id) {
    const preset = presets.find((p) => p.id === asset.camera_preset_id);
    return { label: preset?.name ?? humanizeCameraId(asset.camera_preset_id), isManual: true };
  }
  const raw = (asset.camera_movement || "").trim();
  if (!raw) return { label: "Auto", isManual: false };
  if (raw === "static") return { label: "Static", isManual: false };
  const moveId = raw.split("|")[0];
  const preset = presets.find((p) => p.id === moveId);
  return { label: preset?.name ?? humanizeCameraId(moveId), isManual: false };
}

/** Fetches a short-lived audio token, then renders VoicePlayer with scoped URL */
function SecureAudioPlayer({ videoId, scene }: { videoId: string; scene: number }) {
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    getAudioToken(videoId).then(({ token }) => {
      // API_URL, not window.location:8001 — the old guess produced an
      // unreachable port in prod and every player rendered dead at 0:00.
      if (!cancelled) setAudioUrl(`${API_URL}/api/videos/${videoId}/audio/${scene}?token=${token}`);
    }).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => { cancelled = true; };
  }, [videoId, scene]);
  if (failed) return null;
  if (!audioUrl) return <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>Loading audio...</p>;
  return <div className="mb-3"><VoicePlayer audioUrl={audioUrl} /></div>;
}

interface SceneGroup {
  sceneNumber: number;
  narrationText: string;
  duration: string;
  voiceOverUrl: string | null;
  sceneVideoUrl: string | null;
  storyboardBeats: Array<{
    beatNumber: number; prompt: string; gridUrl: string | null;
    errorEntry: StoryboardBoardError | null;
  }>;
  coverageDirective: string | null;
  storyboardPromptsRaw: string | null;
  storyboardStatus: string | null;
  storyboardBeatCount: number | null;
  storyboardGridCount: number;
  hasStoryboardPrompt: boolean;
  hasStoryboardData: boolean;
  /** Cache-bust key — boards update in place at the same URL, so the <img>
   *  must change its src when the scene's row changes or the browser/CDN
   *  serves a stale grid. */
  gridVersion: number;
  assets: Asset[];
}

function parseStoryboardPromptBlocks(promptText: string | null | undefined) {
  const prompt = (promptText || "").trim();
  if (!prompt) return [];
  const beatRegex = /--- BEAT (\d+) ---\s*\n([\s\S]*?)(?=\n--- BEAT \d+ ---|$)/g;
  const beats = Array.from(prompt.matchAll(beatRegex)).map((match) => ({
    beatNumber: Number(match[1]),
    prompt: match[2].trim(),
  }));
  if (beats.length > 0) return beats;
  return [{ beatNumber: 1, prompt }];
}

/** Parse the saved coverage directive (the shot plan) into a clean structure:
 * the [SET | ...] geography/props line plus one row per SHOT with its global
 * panel number (masters then angles, in order — the SAME numbering the board
 * sheets use, so row 13 here IS panel 13 on the boards). */
function parseShotPlan(directive: string | null | undefined) {
  const text = (directive || "").trim();
  if (!text) return null;
  const setMatch = text.match(/\[SET\s*\|\s*([^\]]+)\]/i);
  const momentRe = /\[MOMENT\s+(\d+)\s*\|\s*([^\]]*)\]/gi;
  const heads = Array.from(text.matchAll(momentRe));
  let panel = 0;
  const shots: Array<{ panel: number; moment: number; summary: string; role: string;
    shotType: string; speaker: string | null; line: string | null; desc: string }> = [];
  heads.forEach((h, i) => {
    const block = text.slice((h.index || 0) + h[0].length,
      i + 1 < heads.length ? heads[i + 1].index : text.length);
    const lineMatch = block.match(/^\s*\*{0,2}\s*LINE\s*:\s*([^|"\n]+?)\s*\|\s*"([^"]+)"/im);
    const shotRe = /-\s*\*{0,2}\s*(MASTER|ANGLE)\s*\[?\s*([A-Za-z][\w /-]*?)\s*\]?\s*\*{0,2}\s*:\s*([\s\S]*?)(?=\n\s*-\s*\*{0,2}\s*(?:MASTER|ANGLE)\b|$)/gi;
    let first = true;
    for (const m of Array.from(block.matchAll(shotRe))) {
      panel += 1;
      shots.push({
        panel,
        moment: Number(h[1]),
        summary: h[2].trim(),
        role: m[1].toUpperCase(),
        shotType: m[2].trim().toUpperCase(),
        speaker: first && lineMatch ? lineMatch[1].trim() : null,
        line: first && lineMatch ? lineMatch[2].trim() : null,
        desc: m[3].trim().replace(/\s+/g, " "),
      });
      first = false;
    }
  });
  if (!shots.length) return null;
  return { set: setMatch ? setMatch[1].trim() : null, shots };
}

/** Parse the ENFORCED plan out of the persisted BEAT blocks — the exact
 * numbered panel briefs the board sheets draw ([13] M13 MS — desc SPEAKING …),
 * grouped per board. The raw directive can contain MORE shots than the budget
 * allows (planner overshoot), so parsing it showed "40 shots" while the boards
 * draw 27 — the BEAT blocks are post-budget and match the boards 1:1. */
function parseEnforcedPlan(promptText: string | null | undefined) {
  const beats = parseStoryboardPromptBlocks(promptText);
  if (!beats.length || !beats[0].prompt.includes("[1]")) return null;
  const shots: Array<{ panel: number; moment: number; board: number; role: string;
    shotType: string; speaker: string | null; line: string | null; desc: string }> = [];
  const lineRe = /\[(\d+)\]\s+M(\d+)\s+(ANGLE\s+)?([A-Za-z][\w /-]*?)\s+—\s+([^\n]*)/g;
  for (const b of beats) {
    for (const m of Array.from(b.prompt.matchAll(lineRe))) {
      let desc = m[5].trim();
      let speaker: string | null = null, line: string | null = null;
      const sp = desc.match(/\sSPEAKING\s+([^:]+):\s*"([^"]*)"?\s*$/);
      if (sp) { speaker = sp[1].trim(); line = sp[2].trim(); desc = desc.slice(0, sp.index).trim(); }
      shots.push({ panel: Number(m[1]), moment: Number(m[2]), board: b.beatNumber,
        role: m[3] ? "ANGLE" : "MASTER", shotType: m[4].trim().toUpperCase(), speaker, line, desc });
    }
  }
  return shots.length ? shots : null;
}

/** Read-the-plan-before-you-pay viewer: the scene's saved shot plan, formatted —
 * the fixed SET/blocking line up top, then one row per panel grouped by board.
 * Panel numbers match the board sheets 1:1. */
function ShotPlanViewer({ directive, storyboardPrompts, sceneNumber }: { directive: string | null; storyboardPrompts: string | null; sceneNumber: number }) {
  const plan = useMemo(() => {
    const enforced = parseEnforcedPlan(storyboardPrompts);
    const raw = parseShotPlan(directive);
    if (enforced) return { set: raw?.set ?? null, shots: enforced, enforced: true };
    if (raw) return { set: raw.set, shots: raw.shots.map((s) => ({ ...s, board: Math.ceil(s.panel / 12) })), enforced: false };
    return null;
  }, [directive, storyboardPrompts]);
  if (!plan) return null;
  return (
    <details className="mb-3">
      <summary className="cursor-pointer text-xs font-semibold inline-flex items-center gap-1.5"
        style={{ color: "var(--purple)" }}>
        <LayoutGrid size={12} /> Shot plan · {plan.shots.length} shots — read it before you draw
      </summary>
      <div className="mt-2 rounded-lg p-3 space-y-2" style={{ background: "var(--bg-elevated)", border: "1px solid rgba(255,255,255,0.06)" }}>
        {plan.set && (
          <div className="text-[11px] leading-relaxed rounded-md p-2"
            style={{ background: "rgba(168,85,247,0.08)", border: "1px solid rgba(168,85,247,0.25)", color: "var(--text-secondary)" }}>
            <span className="font-bold uppercase tracking-wide mr-1.5" style={{ color: "var(--purple)" }}>Set & blocking — every shot</span>
            {plan.set}
          </div>
        )}
        <div className="space-y-1.5 max-h-80 overflow-y-auto pr-1" style={{ scrollbarWidth: "thin" }}>
          {plan.shots.map((s, i) => (
            <div key={s.panel}>
              {(i === 0 || plan.shots[i - 1].board !== s.board) && (
                <p className="text-[10px] font-mono font-bold uppercase tracking-wider mt-2 mb-1"
                  style={{ color: "var(--text-tertiary)" }}>
                  Board S{sceneNumber}.{s.board}
                </p>
              )}
              <div className="flex gap-2 items-baseline text-[11px] leading-snug">
              <span className="flex-shrink-0 font-mono font-bold w-6 text-right" style={{ color: "var(--text-tertiary)" }}>{s.panel}</span>
              <span className="flex-shrink-0 font-semibold px-1.5 py-0.5 rounded" style={{
                background: s.role === "MASTER" ? "rgba(168,85,247,0.15)" : "rgba(255,255,255,0.06)",
                color: s.role === "MASTER" ? "var(--purple)" : "var(--text-tertiary)",
              }}>
                M{s.moment} {s.role === "ANGLE" ? "· angle " : "· "}{s.shotType}
              </span>
              <span className="min-w-0" style={{ color: "var(--text-secondary)" }}>
                {s.speaker && s.line && (
                  <span className="font-medium mr-1" style={{ color: "var(--turquoise)" }}>
                    {s.speaker}: “{s.line.length > 90 ? `${s.line.slice(0, 90)}…` : s.line}”
                  </span>
                )}
                {s.desc.length > 220 ? `${s.desc.slice(0, 220)}…` : s.desc}
              </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </details>
  );
}

interface ScenesWorkspaceTabProps {
  video: VideoDetail & { id: string };
  onGoToScriptVoice?: () => void;
  onGoToEnvironments?: () => void;
  onGoToCharacters?: () => void;
  onAdvanced?: () => void;
  /** The ONE page-level task watcher (S9-1/C19a) — replaces this tab's own
   * useTaskWatcher so it doesn't duplicate-poll against TaskFailureBanner. */
  taskWatcher: TaskWatcherBridge;
  /** Declutter (2026-07-22): the progress summary + bulk-generate button used
   * to live in a full-width green banner between the stage rail and the
   * model-settings row. Ryan asked to move it up into the StageRail card's
   * empty right-hand side instead of deleting it — this ref points at the
   * slot div StageRail renders for exactly that, and stays undefined for any
   * caller that doesn't have one (portal simply doesn't render). */
  stageRailSlot?: React.RefObject<HTMLDivElement | null>;
}

export function ScenesWorkspaceTab({ video, onGoToScriptVoice, onGoToEnvironments, onGoToCharacters, onAdvanced, taskWatcher, stageRailSlot }: ScenesWorkspaceTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();
  // Portal target for the command-bar controls (progress text + bulk button +
  // overflow menu) — StageRail mounts its slot div in the SAME commit as this
  // component (both render from page.tsx's tree), but a ref write doesn't
  // trigger a re-render, so this runs on every render (cheap: one ref read)
  // until it catches the node, then stops. Guards the productionGuide-still-
  // loading edge case where StageRail hasn't mounted its slot yet.
  const [commandBarSlot, setCommandBarSlot] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!commandBarSlot && stageRailSlot?.current) setCommandBarSlot(stageRailSlot.current);
  });
  const model = video.video_model || "grok-imagine";
  // Clip-model registry (GET /api/models) — queried early so every per-clip
  // price computed below can read it directly on the SAME render it arrives,
  // instead of going through the mutable CLIP_COST_PER_MODEL cache (which a
  // later effect populates one render too late — see priceForModel below).
  const { data: modelsData } = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    staleTime: 5 * 60_000,
  });
  // Camera-move presets (checklist §2.2, C23) — the curated catalog subset
  // for the per-shot chip's preset sheet. Global/rarely-changing, same
  // long staleTime as the model registry above. A failed/empty fetch just
  // means the sheet has nothing to list yet — the chip itself still reads
  // straight off the asset (camera_movement/camera_preset_id), never blocked
  // on this query (fail-safe: no camera data -> "Auto" chip, never broken).
  const { data: cameraPresetsData } = useQuery({
    queryKey: ["camera-presets"],
    queryFn: getCameraPresets,
    staleTime: 5 * 60_000,
  });
  const cameraPresets = cameraPresetsData?.presets ?? [];
  const priceByModel = useMemo(() => {
    const m: Record<string, number> = {};
    for (const mm of modelsData?.models ?? []) {
      if (mm.cost_per_clip != null) m[mm.id] = mm.cost_per_clip;
    }
    return m;
  }, [modelsData]);
  // Sync the shared clip-price cache too, for clipCost() callers elsewhere
  // (this file's own model-picker labels, and other components).
  useEffect(() => {
    for (const [id, price] of Object.entries(priceByModel)) CLIP_COST_PER_MODEL[id] = price;
  }, [priceByModel]);
  /** Real per-clip price for a model, reactive on THIS render (not the
   * mutable-cache side channel) — checklist §0.3c/C09. */
  const priceForModel = useCallback(
    (id: string | null | undefined) => priceByModel[id || "grok-imagine"] ?? clipCost(id, 1),
    [priceByModel],
  );
  const perClip = priceForModel(model);

  // Same "video-actions" query the video page runs (page.tsx) — same query
  // key, so React Query serves this from the shared cache instead of firing
  // a second request. Gives us the live picture price (prices.picture) for
  // toasts/tooltips below, mirroring how perClip above reads modelsData.
  const { data: videoActions } = useQuery({
    queryKey: ["video-actions", video.id],
    queryFn: () => getVideoActions(video.id),
    staleTime: 30_000,
  });
  // Loading-gap fallback only (C09a: GPT Image 2 2K default) — real value
  // always wins once the query above resolves.
  const picturePrice = videoActions?.prices?.picture ?? 0.05;

  // The "video" (animation) stage can be switched OFF at creation (an images-
  // only plan). When it is, keep the picture workspace but hide every animate/
  // clip affordance — the backend refuses those triggers too. Full-pipeline
  // videos (no plan) and any plan that includes "video" keep everything.
  const videoStageEnabled = useMemo(() => {
    const plan = video.pipeline_stages;
    if (!Array.isArray(plan) || plan.length === 0) return true;
    return plan.includes("video");
  }, [video.pipeline_stages]);

  // ── Data ──
  const { data: scriptScenes, isLoading: loadingScripts } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
  });
  const { data: assets, isLoading: loadingAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
  });
  const { data: dialogueMap } = useQuery({
    queryKey: ["dialogue-map", video.id],
    queryFn: () => getDialogueMap(video.id),
    staleTime: 60_000,
  });

  // Storyboards require the environments step to be done (approved OR skipped) —
  // the backend enforces this; we mirror it here so the creator sees a clear
  // banner and we never fire a generation that will just fail.
  const { data: environmentsData } = useQuery({
    queryKey: ["video-environments", video.id],
    queryFn: () => getEnvironments(video.id),
    staleTime: 30_000,
  });
  const environmentsReady = !!environmentsData?.approved_at;

  // Cast gate mirror: a designed-but-unapproved cast parks storyboard
  // generation server-side with no visible cue — the stage strip jumps here
  // and it LOOKS like characters got skipped. Surface the parked cast with a
  // banner (like the environments one) so the creator knows where to go.
  const { data: charactersData } = useQuery({
    queryKey: ["video-characters-gate", video.id],
    queryFn: () => getVideoCharacters(video.id),
    staleTime: 30_000,
  });
  const castDrafted = (charactersData?.characters?.length ?? 0) > 0;
  const castReady = !castDrafted || !!charactersData?.approved_at;

  // Clip-model options: derived from the backend registry (GET /api/models,
  // queried above as `modelsData`) — never hand-copied, see
  // storyengine-wiring-fix-checklist.md §0.2.
  const wiredVideoModels = useMemo((): { id: string; label: string }[] => {
    const wired = (modelsData?.models ?? []).filter((m) => m.kind === "video" && m.wired);
    if (!wired.length) {
      // Endpoint unreachable, still loading, or (shouldn't happen) came back
      // empty — never render a broken/empty dropdown; fall back to the one
      // model we know is always live.
      return FALLBACK_WIRED_MODELS;
    }
    return wired.map((m: VideoModelInfo) => ({
      id: m.id,
      // Read cost_per_clip straight off THIS row (priceByModel derives from
      // the exact same modelsData) — real on the first render it arrives.
      label: `${m.name} — $${(m.cost_per_clip ?? priceForModel(m.id)).toFixed(2)}/clip`,
    }));
  }, [modelsData, priceForModel]);

  // Short display name for a model id, for the C14 per-scene badge — reads
  // straight off GET /api/models (the same registry wiredVideoModels
  // derives from), so a name change on the backend never needs a matching
  // frontend edit. Falls back to the raw id (never blank) for a stale/
  // unwired id (e.g. an old model_used value the registry has since dropped).
  const modelDisplayName = useCallback(
    (id: string | null | undefined) => {
      if (!id) return "";
      return (modelsData?.models ?? []).find((m) => m.id === id)?.name ?? id;
    },
    [modelsData],
  );

  // Guard every storyboard-generating action: bounce with a clear message
  // (and a pointer to the Environments tab) instead of firing a doomed task.
  const requireEnvironments = useCallback(() => {
    if (!castReady) {
      toast.error("Approve your cast first — your characters are designed and waiting in the Characters tab.");
      return false;
    }
    if (environmentsReady) return true;
    toast.error('Design your environments first — open the Environments tab (or hit "No locations — skip" there) before generating storyboards.');
    return false;
  }, [castReady, environmentsReady, toast]);

  // Voice exists when a narrator MP3 does, OR when a character-dialogue
  // scene's per-segment performance track is fully voiced (the pure couple
  // format never writes voice_over_url — the gate locked a fully-voiced
  // video out of its own Scenes tab, found live), OR when the video is
  // grok-native dialogue: the clips CARRY their voices, no narrator or TTS
  // exists by design.
  const hasVoice = useMemo(() => {
    if ((scriptScenes ?? []).some((s) => !!s.voice_over_url)) return true;
    if (dialogueMap?.dialogue_mode !== "character_dialogue") return false;
    if ((video as { dialogue_audio?: string | null }).dialogue_audio === "grok_native") return true;
    const dscenes = dialogueMap.scenes ?? [];
    return dscenes.length > 0 && dscenes.some(
      (sc) => (sc.segments ?? []).length > 0 && sc.segments.every((g) => g.voiced));
  }, [scriptScenes, dialogueMap, video]);

  // Voice is optional. When AI voice-over is off (skip_voice / no "voice" stage),
  // image segmentation is timed from word count instead (the backend's
  // deterministic splitter falls back to a default words-per-second), so the
  // Scenes step must NOT hard-block on voice.
  const voiceSkipped = useMemo(() => {
    if (video.skip_voice) return true;
    const plan = video.pipeline_stages;
    return Array.isArray(plan) && plan.length > 0 && !plan.includes("voice");
  }, [video.skip_voice, video.pipeline_stages]);

  // C36 (checklist §3.3 item 1): the chat auto-build's "pictures" target
  // deliberately DEFERS voice to the finish phase (actions.make_autobuild_step
  // skips run_voice on the way to ready_for_images — voice is the slowest paid
  // step and isn't needed to review pictures) — so a video can genuinely have
  // real pictures with hasVoice=false and voiceSkipped=false at the exact
  // moment the chat checkpoint says "Your pictures are ready — review them."
  // Before this fix the gate below couldn't tell that state apart from "no
  // pictures exist yet, voice hasn't run, go do that first" and showed the
  // SAME hard "Voice Required" block either way — the review checkpoint the
  // chat had just pointed the creator to was unreachable. Distinguish by
  // whether pictures already exist: only pre-generation (no pictures) blocks;
  // post-generation-without-voice shows an inline advisory instead (below).
  const hasPictures = useMemo(
    () => (assets ?? []).some((a) => !!a.image_url),
    [assets],
  );

  // Storyboarding is MANDATORY: boards are the only path to image spend.
  useEffect(() => {
    if (scriptScenes && scriptScenes.length > 0) {
      const anyOff = scriptScenes.some((s) => s.storyboard_on_off !== "On");
      if (anyOff) updateStoryboardMode(video.id, true).catch(() => { /* best-effort */ });
    }
  }, [scriptScenes, video.id]);

  // ── Scene groups: boards + the scene's full asset rows ──
  const scenes = useMemo<SceneGroup[]>(() => {
    if (!scriptScenes || !assets) return [];
    return scriptScenes.map((scene) => {
      const gridUrls = [
        scene.storyboard_1_url || null,
        scene.storyboard_2_url || null,
        scene.storyboard_3_url || null,
        scene.storyboard_4_url || null,
        scene.storyboard_5_url || null,
      ];
      // storyboard_errors is keyed by beat number as a STRING (JSON object
      // keys). Only relevant for a slot with no image — the backend clears
      // a beat's entry the moment it lands, and the render below re-gates
      // on `!beat.gridUrl` too, so a stale entry can never show alongside
      // a real picture either way.
      const errorsByBeat = scene.storyboard_errors || {};
      const errorFor = (beatNumber: number): StoryboardBoardError | null =>
        errorsByBeat[String(beatNumber)] || null;
      const parsedBeats = parseStoryboardPromptBlocks(scene.storyboard_prompts).map((beat) => ({
        ...beat,
        gridUrl: gridUrls[beat.beatNumber - 1] || null,
        errorEntry: errorFor(beat.beatNumber),
      }));
      // The cheap one-image storyboard writes only storyboard_N_url (no prompts → no
      // parsed beats). Synthesize a board per filled slot so the sheet stays visible.
      // Real-picture burger boards can also fill MORE slots than the gate had prompt
      // blocks — append those so every filled slot displays.
      const extraBoards = gridUrls.flatMap((url, i) =>
        (url && i >= parsedBeats.length
          ? [{ beatNumber: i + 1, prompt: "", gridUrl: url, errorEntry: errorFor(i + 1) }]
          : []));
      let storyboardBeats = parsedBeats.length > 0
        ? [...parsedBeats, ...extraBoards]
        : gridUrls.flatMap((url, i) =>
          (url ? [{ beatNumber: i + 1, prompt: "", gridUrl: url, errorEntry: errorFor(i + 1) }] : []));
      // A saved shot plan ALWAYS shows its board slots — even with zero boards
      // drawn yet (the plan gate) and even for plans saved before the gate
      // persisted prompts/beat_count. One placeholder per coming board, each
      // clickable to draw JUST that board.
      if (storyboardBeats.length === 0 && scene.coverage_directive) {
        const plan = parseShotPlan(scene.coverage_directive);
        const expected = scene.storyboard_beat_count
          ?? (plan ? Math.min(5, Math.ceil(plan.shots.length / 12)) : 0);
        storyboardBeats = Array.from({ length: expected }, (_, i) => ({
          beatNumber: i + 1, prompt: "(planned)", gridUrl: gridUrls[i] || null,
          errorEntry: errorFor(i + 1),
        }));
      }
      return {
        sceneNumber: scene.scene || 0,
        narrationText: scene.scene_text || "",
        duration: `${Math.round((scene.scene_text || "").split(/\s+/).length / 2.5)}s`,
        voiceOverUrl: scene.voice_over_url || null,
        sceneVideoUrl: scene.scene_video_url || null,
        storyboardBeats,
        coverageDirective: scene.coverage_directive || null,
        storyboardPromptsRaw: scene.storyboard_prompts || null,
        storyboardStatus: scene.storyboard_status || null,
        storyboardBeatCount: scene.storyboard_beat_count ?? (storyboardBeats.length || null),
        storyboardGridCount: gridUrls.filter(Boolean).length,
        hasStoryboardPrompt: !!scene.storyboard_prompts,
        hasStoryboardData: !!(
          scene.storyboard_prompts || scene.storyboard_status ||
          scene.storyboard_beat_count != null || gridUrls.some(Boolean) ||
          scene.coverage_directive
        ),
        gridVersion: scene.updated_at ? Date.parse(scene.updated_at) || 0 : 0,
        assets: assets
          .filter((a) => a.scene === scene.scene)
          .sort((a, b) => (a.image_index || 0) - (b.image_index || 0)),
      };
    });
  }, [scriptScenes, assets]);

  // ── Local state ──
  // generatingClipIds/failedClipIds/confirmKey now live in useClipTrustLadder
  // (S9-7 extraction) — see the hook call below, after taskWatcher/refreshAll.
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [recropping, setRecropping] = useState<string | null>(null);
  const [generatingScene, setGeneratingScene] = useState<number | null>(null);
  const [clearingScene, setClearingScene] = useState<number | null>(null);
  // C18: which scene's Approve tick is mid-flight (free/instant, so this is
  // only ever set for the width of one request).
  const [approvingScene, setApprovingScene] = useState<number | null>(null);
  const [clearingAllStoryboards, setClearingAllStoryboards] = useState(false);
  const [clearingExtracted, setClearingExtracted] = useState(false);
  const [uploadingGrid, setUploadingGrid] = useState<string | null>(null); // "scene-beat"
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [clearingSlot, setClearingSlot] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showMotionPrompt, setShowMotionPrompt] = useState(false);
  const [imageModel, setImageModel] = useState(video.image_model_override || "gpt-image-2");
  const [savingModel, setSavingModel] = useState(false);
  // C14 per-scene clip-model override sheet — the asset id whose sheet is open.
  const [overrideAssetId, setOverrideAssetId] = useState<string | null>(null);
  const [savingOverride, setSavingOverride] = useState(false);
  // C23 per-shot camera-move preset sheet — the asset id whose sheet is open.
  const [cameraAssetId, setCameraAssetId] = useState<string | null>(null);
  const [savingCameraPreset, setSavingCameraPreset] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [locking, setLocking] = useState(false);
  // Replace-in-place uploads keep the same URL — bump a cache key per slot
  // so the <img> refetches the new pixels.
  const [gridBust, setGridBust] = useState<Record<string, number>>({});
  // Full-screen board viewer — clicking a board must NEVER leave the app
  // (the raw storage URL serves as a download).
  const [lightbox, setLightbox] = useState<{ items: { url: string; label: string }[]; index: number } | null>(null);
  const promptsAutoRan = useRef(false);

  // Per-scene auto-chain: "Start scene over" runs plan → pictures back to back.
  // A queue of remaining pipeline steps to run sequentially (one task at a time).
  // Each step is a (stage, scene) pair; bulk "Generate all scenes" enqueues a
  // plan+draw pair per scene. Per-scene calls bypass the global stage gate, so
  // this works at any storyboard sub-stage.
  const chainRef = useRef<{ queue: Array<{ stage: string; scene?: number }> } | null>(null);
  // Clip auto-resume ref + prevRunningRef now live inside useClipTrustLadder.

  const refreshAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  }, [queryClient, video.id]);

  // ALWAYS-ON watcher (lessons, twice): the strip must show whatever holds
  // the video's task slot — banner runs, silent prompt auto-run, recrop
  // chains — not just work this component started.
  const { message: taskMessage } = useSharedTaskWatcher({
    bridge: taskWatcher,
    onProgress: () => {
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    },
    onComplete: async () => {
      const chain = chainRef.current;
      if (chain && chain.queue.length > 0) {
        const step = chain.queue.shift()!;
        const stageParams = step.scene != null ? { scene: step.scene } : undefined;
        try {
          queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
          try {
            await runPipelineStage(video.id, step.stage, stageParams);
          } catch (err) {
            if (!((err as Error).message || "").includes("409")) throw err;
            await clearStaleTask(video.id);
            await runPipelineStage(video.id, step.stage, stageParams);
          }
          setGeneratingScene(step.scene ?? null);
          markStarted();
          return;
        } catch (err) {
          chainRef.current = null;
          toast.error(
            `${step.scene != null ? `Scene ${step.scene}` : "Storyboards"} couldn't continue: ${(err as Error).message}`,
          );
        }
      }
      chainRef.current = null;
      setGeneratingScene(null);
      setGeneratingClipIds(new Set());
      setConfirmKey(null);
      setRecropping(null);
      refreshAll();
    },
    onFailed: (error) => {
      chainRef.current = null;
      setGeneratingScene(null);
      setFailedClipIds((prev) => new Set([...prev, ...generatingClipIds]));
      setGeneratingClipIds(new Set());
      setConfirmKey(null);
      setRecropping(null);
      if (generatingClipIds.size > 0) {
        toast.error(error || "Clip generation hit a problem — tap the card to try again.");
      }
      refreshAll();
    },
  });
  const { running, markStarted } = taskWatcher;

  // S9-7: clip animate/confirm/auto-resume state machine, extracted to its
  // own hook (hooks/use-clip-trust-ladder.ts) so this file stops growing
  // before C23's camera-move chip lands here. onComplete/onFailed above and
  // the Stop effect below still reach into it directly — those handlers
  // serve the storyboard chain too, so they weren't moved wholesale.
  const {
    generatingClipIds, setGeneratingClipIds,
    failedClipIds, setFailedClipIds,
    confirmKey, setConfirmKey,
    animateOne, animateScene, animateAll,
    confirmable, cancelResume,
  } = useClipTrustLadder({
    videoId: video.id,
    running,
    taskMessage,
    markStarted,
    toast,
    refreshAll,
  });

  // Stop must stand down any queued chain stage: a cancelled task reads as
  // "completed" to pollers, which would otherwise fire the next paid stage.
  useEffect(() => {
    const onStop = (e: Event) => {
      if ((e as CustomEvent).detail?.videoId === video.id) {
        chainRef.current = null;
        cancelResume();  // Stop halts the clip auto-resume loop too
        setGeneratingScene(null);
        setGeneratingClipIds(new Set());
      }
    };
    window.addEventListener("se:stop-requested", onStop);
    return () => window.removeEventListener("se:stop-requested", onStop);
  }, [video.id, cancelResume, setGeneratingClipIds]);

  useEffect(() => {
    setImageModel(video.image_model_override || "gpt-image-2");
  }, [video.image_model_override]);

  // ── Derived counts ──
  const allAssets = useMemo(() => scenes.flatMap((s) => s.assets), [scenes]);
  // C14 override sheet's target asset — looked up live off allAssets so the
  // sheet's "currently routed to" line stays correct across invalidations.
  const overrideAsset = overrideAssetId ? allAssets.find((a) => a.id === overrideAssetId) ?? null : null;
  // C23 camera-move sheet's target asset — same live-lookup pattern as overrideAsset.
  const cameraAsset = cameraAssetId ? allAssets.find((a) => a.id === cameraAssetId) ?? null : null;
  const totalSegments = allAssets.length;
  const extractedCount = allAssets.filter((a) => a.image_url).length;
  const clipCards = useMemo(() => allAssets.filter((a) => a.image_url), [allAssets]);
  const clipsDone = clipCards.filter((a) => a.video_clip_url).length;
  const clipsPending = clipCards.length - clipsDone;
  const promptlessCount = clipCards.filter((a) => !a.video_prompt && !a.video_clip_url).length;
  const badCropCount = allAssets.filter((a) => (a.extraction_flags?.length ?? 0) > 0).length;
  const upscaledCount = allAssets.filter((a) => a.image_url?.includes("_hd")).length;
  const needsUpscale = extractedCount > 0 && extractedCount - upscaledCount > 2;
  const boardsDone = scenes.reduce((n, s) => n + s.storyboardGridCount, 0);
  const boardsTotal = scenes.reduce((n, s) => n + (s.storyboardBeatCount || 1), 0);
  const remainingCost = priceForModel(model) * clipsPending;
  // ONE stage-aware bulk action: run the step the most scenes need next. Driven by
  // the SAME lists the button acts on, so it can never show-but-no-op (the old bug).
  const needStoryboard = scenes.filter((s) => s.storyboardGridCount === 0);
  const needPictures = scenes.filter((s) => s.storyboardGridCount > 0 && !s.assets.some((a) => a.image_url));
  const picturesMissing = totalSegments - extractedCount;
  const bulk: { kind: "gen"; stage: string; label: string; scenes: typeof scenes } | { kind: "finish"; label: string } | { kind: "animate"; label: string } | null =
    needStoryboard.length ? { kind: "gen", stage: "storyboard-images", label: `Generate all storyboards (${needStoryboard.length})`, scenes: needStoryboard }
    : needPictures.length ? { kind: "gen", stage: "coverage-images", label: `Generate all pictures (${needPictures.length})`, scenes: needPictures }
    // Never offer animation while pictures are missing — a partially-drawn set
    // used to fall through to "Animate everything" and read as ready-to-go.
    : (extractedCount > 0 && picturesMissing > 0) ? { kind: "finish", label: `Finish pictures (${picturesMissing} missing)` }
    : (videoStageEnabled && clipsPending > 0) ? { kind: "animate", label: `Animate everything · $${remainingCost.toFixed(2)}` }
    : null;
  const modelLabel = wiredVideoModels.find((m) => m.id === model)?.label.split(" — ")[0] ?? model;
  const storyLocked = !!video.story_locked_at;

  // Scene → dialogue lines for the 💬 badge.
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

  // Motion prompts are plumbing, not a decision: write them silently the
  // moment the workspace sees animatable cards without one.
  useEffect(() => {
    if (!videoStageEnabled || promptsAutoRan.current || running || clipCards.length === 0 || promptlessCount === 0) return;
    promptsAutoRan.current = true;
    (async () => {
      try {
        await runPipelineStage(video.id, "video-scripts");
        markStarted();
      } catch {
        promptsAutoRan.current = false; // 409 etc. — retry on next mount
      }
    })();
  }, [videoStageEnabled, clipCards.length, promptlessCount, running, video.id, markStarted]);

  // ── Stage helpers (storyboard side) ──
  const runStageWith409Retry = useCallback(async (stage: string, params?: Record<string, string | number>) => {
    try {
      await runPipelineStage(video.id, stage, params);
      markStarted();
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        await clearStaleTask(video.id);
        await runPipelineStage(video.id, stage, params);
        markStarted();
        return;
      }
      throw err;
    }
  }, [video.id, markStarted]);

  const handleRedoSceneFromScratch = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    const confirmed = window.confirm(
      `Redo Scene ${sceneNumber}'s pictures? We'll draw fresh per-shot pictures, replacing the current ones (≈ $${picturePrice.toFixed(2)} each).\n\nTo remove just one picture, hover it and click the X.`
    );
    if (!confirmed) return;
    setClearingScene(sceneNumber);
    try {
      await clearSceneStoryboard(video.id, sceneNumber);
      queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("coverage-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't redo Scene ${sceneNumber}: ${(err as Error).message}`);
    } finally {
      setClearingScene(null);
    }
  }, [video.id, queryClient, toast, runStageWith409Retry, requireEnvironments, picturePrice]);

  // Draw a scene's grids only (no re-plan) — used by empty-slot clicks on a
  // scene that already has a plan.
  const handleGenerateSceneGrids = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    chainRef.current = null;
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Scene ${sceneNumber} failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // PLAN GATE: write the shot plan + board placeholders, draw NOTHING. The
  // creator reads the formatted plan, then draws boards one at a time.
  const handlePlanShots = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    chainRef.current = null;
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber, plan_only: 1 });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Scene ${sceneNumber} planning failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // Redraw ONE board slot from the scene's saved plan (the plan is untouched,
  // so the other boards' panels can't shift). Ryan drives boards one at a time.
  const handleGenerateSingleBoard = useCallback(async (sceneNumber: number, beatNumber: number) => {
    if (!requireEnvironments()) return;
    chainRef.current = null;
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber, beat: beatNumber });
    } catch (err: unknown) {
      setGeneratingScene(null);
      toast.error(`Board S${sceneNumber}.${beatNumber} failed: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // One per-scene action: PLAN then DRAW as two chained tasks (the draw runs
  // from onComplete, after the plan task finishes — separate tasks so the draw
  // reads the freshly-written plan; an in-process plan+draw can't see its own
  // new prompts). Always plans first, so a draw never fires without a plan.
  // Step 1 — the CHEAP one-image storyboard (a quick "do I like the direction?"
  // preview). storyboard-images → generate_storyboard_sheet_for_scene.
  const handleGenerateScene = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    try {
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("storyboard-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't generate Scene ${sceneNumber} storyboard: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // Step 2 — draw the REAL per-shot pictures (coverage), after the storyboard
  // preview. coverage-images → generate_coverage_for_video; replaces any pictures.
  const handleGenerateRealImages = useCallback(async (sceneNumber: number) => {
    if (!requireEnvironments()) return;
    try {
      chainRef.current = null;
      setGeneratingScene(sceneNumber);
      await runStageWith409Retry("coverage-images", { scene: sceneNumber });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't generate Scene ${sceneNumber} pictures: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments]);

  // Manual per-scene stitch — FFmpeg-concats the scene's clips into one video.
  // Auto-stitch already covers the animate paths; this is the explicit button +
  // re-stitch on demand (shown once every clip in the scene is animated).
  const handleStitchScene = useCallback(async (sceneNumber: number) => {
    setGeneratingScene(sceneNumber);
    try {
      await runStageWith409Retry("stitch-scene", { scene: sceneNumber });
    } catch (err) {
      setGeneratingScene(null);
      toast.error(`Couldn't stitch Scene ${sceneNumber}: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast]);

  // Bulk: run ONE stage for every scene in the list, one task at a time (the
  // onComplete chain runs the queue in order). Used by the stage-aware header
  // button — storyboards for all, or pictures for all, never both.
  const handleBulkGen = useCallback(async (stage: string, list: typeof scenes) => {
    if (!requireEnvironments()) return;
    if (list.length === 0) return;
    const what = stage === "coverage-images" ? "pictures" : "storyboards";
    if (!window.confirm(
      `Generate ${what} for ${list.length} scene${list.length === 1 ? "" : "s"} (≈ $${picturePrice.toFixed(2)} each). You can Stop anytime.`,
    )) return;
    const steps = list.map((s) => ({ stage, scene: s.sceneNumber }));
    const [first, ...rest] = steps;
    try {
      chainRef.current = { queue: rest };
      setGeneratingScene(first.scene ?? null);
      await runStageWith409Retry(first.stage, { scene: first.scene });
    } catch (err) {
      chainRef.current = null;
      setGeneratingScene(null);
      toast.error(`Couldn't start generating all ${what}: ${(err as Error).message}`);
    }
  }, [runStageWith409Retry, toast, requireEnvironments, picturePrice]);

  const handleClearAllStoryboards = useCallback(async () => {
    if (!window.confirm(
      "Start the storyboard over? Every board and every scene plan gets thrown away. Your script and voice stay. You’ll rebuild from the big button at the top.",
    )) return;
    setClearingAllStoryboards(true);
    try {
      await clearAllStoryboards(video.id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["video-script", video.id] }),
        queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
      ]);
    } finally {
      setClearingAllStoryboards(false);
    }
  }, [video.id, queryClient]);

  const handleClearAllExtracted = useCallback(async () => {
    if (!window.confirm("Delete all the final pictures? Your storyboards stay — you can create the final pictures again afterwards.")) return;
    setClearingExtracted(true);
    try {
      await clearAllExtractedPanels(video.id);
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } finally {
      setClearingExtracted(false);
    }
  }, [video.id, queryClient]);

  const handleGridDrop = useCallback(async (sceneNumber: number, beatNumber: number, file: File) => {
    const key = `${sceneNumber}-${beatNumber}`;
    setUploadingGrid(key);
    try {
      await uploadStoryboardGrid(video.id, sceneNumber, beatNumber, file);
      setGridBust((prev) => ({ ...prev, [key]: Date.now() }));
      toast.success(`Your image is now storyboard S${sceneNumber}.${beatNumber}.`);
      await queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch (err) {
      toast.error(`Upload failed: ${(err as Error).message || "please try again."}`);
    } finally {
      setUploadingGrid(null);
      setDragOver(null);
    }
  }, [video.id, queryClient, toast]);

  const handleClearGridSlot = useCallback(async (sceneNumber: number, beatNumber: number) => {
    if (!window.confirm(
      `Remove storyboard picture S${sceneNumber}.${beatNumber}? Your scene descriptions and prompts stay — only this image goes. You can regenerate it or drop in your own.`
    )) return;
    const key = `${sceneNumber}-${beatNumber}`;
    setClearingSlot(key);
    try {
      await clearStoryboardSlot(video.id, sceneNumber, beatNumber);
      await queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    } catch (err) {
      toast.error(`Couldn't remove that picture: ${(err as Error).message || "please try again."}`);
    } finally {
      setClearingSlot(null);
    }
  }, [video.id, queryClient, toast]);

  const handleClearExtractedPanel = useCallback(async (assetId: string) => {
    try {
      await clearExtractedPanel(video.id, assetId);
      await queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch { /* silent */ }
  }, [video.id, queryClient]);

  const handleUnlockStory = useCallback(async () => {
    setLocking(true);
    try {
      await unlockStory(video.id);
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
      toast.info("Story unlocked — keep iterating on the boards.");
    } catch (err) {
      toast.error((err as Error).message || "Couldn't unlock the story.");
    } finally {
      setLocking(false);
    }
  }, [video.id, queryClient, toast]);

  const handleReExtract = useCallback(async () => {
    try {
      try { await clearStaleTask(video.id); } catch { /* ok */ }
      await runPipelineStage(video.id, "storyboard-extract");
      markStarted();
    } catch (err: unknown) {
      toast.error(`Couldn't start: ${(err as Error).message || "Unknown error"}`);
    }
  }, [video.id, markStarted, toast]);

  const handleUpscalePanels = useCallback(async () => {
    try {
      try { await clearStaleTask(video.id); } catch { /* ok */ }
      await runPipelineStage(video.id, "upscale-panels");
      markStarted();
    } catch (err: unknown) {
      toast.error(`Upscale failed: ${(err as Error).message || "Unknown error"}`);
    }
  }, [video.id, markStarted, toast]);

  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      refreshAll();
      onAdvanced?.();
    } catch (err) {
      toast.error(`Failed to advance: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, refreshAll, onAdvanced, toast]);

  const handleImageModelChange = useCallback(async (next: string) => {
    setImageModel(next);
    setSavingModel(true);
    try {
      await updateVideoStyles(video.id, { image_model_override: next });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error(`Failed to update image model: ${(err as Error).message}`);
      setImageModel(video.image_model_override || "gpt-image-2");
    } finally {
      setSavingModel(false);
    }
  }, [queryClient, video.id, video.image_model_override, toast]);

  const handleClipModelChange = useCallback(async (next: string) => {
    try {
      await updateVideoStyles(video.id, { video_model: next });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  // C14: set (or clear, with null = "Use recommendation") one scene's manual
  // clip-model override. Wins over routed_model at both quote and generation
  // time (shared.model_router.resolve_clip_model's scene_override param) —
  // invalidate video-assets so the badge/cost refresh immediately.
  const handleSetModelOverride = useCallback(async (assetId: string, next: string | null) => {
    setSavingOverride(true);
    try {
      await updateAssetModelOverride(assetId, next);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      setOverrideAssetId(null);
    } catch (err) {
      toast.error((err as Error).message || "Couldn't save that override.");
    } finally {
      setSavingOverride(false);
    }
  }, [video.id, queryClient, toast]);

  // C23 (checklist §2.2): set (or clear, with null = "Auto") one shot's
  // manual camera-move override. Same write path the copilot's "use a
  // crash zoom on scene 12" calls (actions.py's camera_preset runner) —
  // wins over the auto/"earned" camera_movement at clip-generation time
  // (pipeline_executor._apply_camera_preset_override). Invalidate
  // video-assets so the chip refreshes immediately.
  const handleSetCameraPreset = useCallback(async (assetId: string, next: string | null) => {
    setSavingCameraPreset(true);
    try {
      await updateAssetCameraPreset(assetId, next);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      setCameraAssetId(null);
    } catch (err) {
      toast.error((err as Error).message || "Couldn't save that camera move.");
    } finally {
      setSavingCameraPreset(false);
    }
  }, [video.id, queryClient, toast]);

  // C18 (checklist §1.3 [U]): the clickable door for the 'approve_scene' verb
  // (C15b shipped chat-only). Free + reversible server-side — invalidate
  // video-actions too, since finalize's quote/N reads _approved_scenes.
  const handleApproveScene = useCallback(async (sceneNumber: number) => {
    setApprovingScene(sceneNumber);
    try {
      await approveScene(video.id, sceneNumber);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
      queryClient.invalidateQueries({ queryKey: ["video-actions", video.id] });
    } catch (err) {
      toast.error((err as Error).message || "Couldn't approve that scene.");
    } finally {
      setApprovingScene(null);
    }
  }, [video.id, queryClient, toast]);

  const handleRenderStyleChange = useCallback(async (next: string) => {
    try {
      await updateVideo(video.id, { render_style: next || null });
      queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  // ── Clip actions (trust-ladder contract) ──
  // startClipTask/animateOne/animateScene/animateAll/maybeResumeClips + the
  // resume-trigger effect now live in useClipTrustLadder (S9-7 extraction,
  // called above alongside taskWatcher/refreshAll).

  const removeClip = useCallback(async (asset: Asset) => {
    try {
      await deleteClip(video.id, asset.id);
      queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
    } catch (err) {
      toast.error((err as Error).message);
    }
  }, [video.id, queryClient, toast]);

  // One-tap bad-crop fix: free re-crop of the whole beat; the backend
  // re-animates any clips the new pictures made stale (per-clip price, same as perClip below).
  const recropOne = useCallback(async (asset: Asset) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}.`);
      return;
    }
    setRecropping(asset.id);
    try {
      await recropAsset(video.id, asset.id);
      markStarted();
      toast.info(`Re-cropping this picture's storyboard — clips that go stale re-animate automatically (~$${perClip.toFixed(2)} each).`);
    } catch (err) {
      setRecropping(null);
      toast.error((err as Error).message || "Couldn't start the re-crop.");
    }
  }, [video.id, running, taskMessage, markStarted, toast, perClip]);

  const redrawOne = useCallback(async (asset: Asset) => {
    if (running) {
      toast.info(`Hang on — still working: ${taskMessage || "finishing the current step"}.`);
      return;
    }
    setRecropping(asset.id);  // reuse the per-card "working" dim until onComplete clears it
    try {
      await runStageWith409Retry("redraw-image", { asset_id: asset.id });
      toast.info(`Redrawing this picture from your prompt (~$${picturePrice.toFixed(2)}), anchored on the locked cast. Re-animate after.`);
    } catch (err) {
      setRecropping(null);
      toast.error((err as Error).message || "Couldn't start the redraw.");
    }
  }, [running, taskMessage, toast, runStageWith409Retry, picturePrice]);

  // confirmable() now lives in useClipTrustLadder too.

  // ── Guards ──
  if (loadingScripts || loadingAssets) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--purple)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>Loading your scenes...</span>
      </div>
    );
  }

  if (!hasVoice && !voiceSkipped && !hasPictures) {
    return (
      <GlassCard className="p-10 text-center max-w-lg mx-auto">
        <div className="w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4"
          style={{ background: "rgba(255, 165, 0, 0.12)", border: "1px solid rgba(255, 165, 0, 0.25)" }}>
          <Lock size={20} style={{ color: "var(--orange)" }} />
        </div>
        <h3 className="text-lg font-display font-semibold mb-2" style={{ color: "var(--text-primary)" }}>
          Voice Required
        </h3>
        <p className="text-sm leading-relaxed mb-6" style={{ color: "var(--text-secondary)" }}>
          Voice must be generated before visuals. Voice audio timing drives image
          segmentation — without it, images will be incorrectly timed.
        </p>
        {onGoToScriptVoice && (
          <button onClick={onGoToScriptVoice}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
            <ArrowLeft size={14} />
            Go to Script &amp; Voice
          </button>
        )}
      </GlassCard>
    );
  }

  if (scenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <ImageIcon size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Your scenes will appear here
        </p>
        <p className="text-sm max-w-md mx-auto" style={{ color: "var(--text-tertiary)" }}>
          {running
            ? (taskMessage || "Working on it…")
            : "Use the big button at the top of the page — it always knows the next step."}
        </p>
      </GlassCard>
    );
  }

  // ── Render ──
  return (
    <div className="flex flex-col gap-4">
      {/* C36 (checklist §3.3 item 1): set the expectation instead of implying
          audio exists — this is the exact "pictures are ready, review them"
          checkpoint the auto-build chat message points to, and at this point
          in the pipeline voice genuinely hasn't run yet (deferred to the
          finish phase on purpose). Advisory, not a block — hasPictures
          already cleared the gate above. */}
      {!hasVoice && !voiceSkipped && hasPictures && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap"
          style={{ background: "rgba(255, 165, 0, 0.08)", border: "1px solid rgba(255, 165, 0, 0.30)" }}>
          <Volume2 size={16} style={{ color: "var(--orange)" }} className="shrink-0" />
          <p className="text-sm flex-1 min-w-[12rem]" style={{ color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>No voice yet — that&apos;s expected here.</strong>{" "}
            These pictures were timed from the script text. Voice-over generates in the finish step,
            right before rendering — review the visuals now, audio comes next.
          </p>
        </div>
      )}
      {/* Cast gate: characters were DESIGNED (often by the chat auto-build)
          but not approved — without this banner the stage strip lands here
          and the step looks silently skipped. */}
      {!castReady && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap"
          style={{ background: "rgba(64, 224, 208, 0.08)", border: "1px solid rgba(64, 224, 208, 0.30)" }}>
          <Sparkles size={16} style={{ color: "var(--turquoise)" }} className="shrink-0" />
          <p className="text-sm flex-1 min-w-[12rem]" style={{ color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>Your cast is designed and waiting.</strong>{" "}
            {charactersData?.characters?.length === 1
              ? `${charactersData.characters[0].name} was created from the script — `
              : `${charactersData?.characters?.length ?? 0} characters were created from the script — `}
            review and approve them so every storyboard keeps the same faces.
          </p>
          {onGoToCharacters && (
            <button
              onClick={onGoToCharacters}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110 shrink-0"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
              <Sparkles size={13} /> Review the cast
            </button>
          )}
        </div>
      )}
      {/* Environments gate: storyboards need locations locked (or skipped)
          first — guide the creator there instead of generating drifting
          backgrounds. The generation handlers are guarded too. */}
      {!environmentsReady && (
        <div className="rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap"
          style={{ background: "rgba(245, 158, 11, 0.10)", border: "1px solid rgba(245, 158, 11, 0.35)" }}>
          <MapPin size={16} style={{ color: "var(--gold)" }} className="shrink-0" />
          <p className="text-sm flex-1 min-w-[12rem]" style={{ color: "var(--text-secondary)" }}>
            <strong style={{ color: "var(--text-primary)" }}>Design your environments first.</strong>{" "}
            Storyboards lock each location so backgrounds stay consistent. Approve them in the
            Environments tab — or mark “No locations” there if this video has none.
          </p>
          {onGoToEnvironments && (
            <button
              onClick={onGoToEnvironments}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all hover:brightness-110 shrink-0"
              style={{ background: "var(--gold)", color: "var(--bg-void)" }}>
              <MapPin size={13} /> Design environments
            </button>
          )}
        </div>
      )}
      {/* Model controls — always visible at the top (no longer buried in the Advanced menu). */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <ImageIcon size={13} style={{ color: "var(--text-tertiary)" }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Pictures</span>
          <select value={imageModel} onChange={(e) => handleImageModelChange(e.target.value)} disabled={savingModel}
            className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
            <option value="nano-banana-2">Nano Banana 2</option>
            <option value="gpt-image-2">GPT Image 2</option>
            <option value="z-image">Z Image</option>
          </select>
        </div>
        {videoStageEnabled && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <Film size={13} style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Clips</span>
            <select value={model} onChange={(e) => handleClipModelChange(e.target.value)}
              className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
              {wiredVideoModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </div>
        )}
        {videoStageEnabled && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
            title="Gates which clip models the per-scene router is allowed to recommend. Animated channels stay on Grok — no premium (realistic-only) upgrades. Auto = undeclared, router leaves your current model alone."
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <Sparkles size={13} style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Channel look</span>
            <select value={video.render_style || ""} onChange={(e) => handleRenderStyleChange(e.target.value)}
              className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
              <option value="">Auto</option>
              <option value="animated">Animated</option>
              <option value="realistic">Realistic</option>
            </select>
          </div>
        )}
        {videoStageEnabled && (
          <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
            style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
            <Volume2 size={13} style={{ color: "var(--text-tertiary)" }} />
            <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Voice</span>
            <select value={video.dialogue_audio || "voice_over"}
              onChange={async (e) => {
                try {
                  await updateVideo(video.id, { dialogue_audio: e.target.value });
                  queryClient.invalidateQueries({ queryKey: ["video", video.id] });
                } catch (err) { toast.error((err as Error).message); }
              }}
              className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
              <option value="voice_over">Character voice-over</option>
              <option value="grok_native">Grok native</option>
            </select>
          </div>
        )}
        <div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg"
          style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
          <Ratio size={13} style={{ color: "var(--text-tertiary)" }} />
          <span className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Aspect</span>
          <select value={video.aspect_ratio || "16:9"}
            onChange={async (e) => {
              try {
                await updateVideo(video.id, { aspect_ratio: e.target.value });
                queryClient.invalidateQueries({ queryKey: ["video", video.id] });
              } catch (err) { toast.error((err as Error).message); }
            }}
            className="bg-transparent text-xs cursor-pointer outline-none" style={{ color: "var(--text-primary)" }}>
            <option value="16:9">16:9 wide</option>
            <option value="9:16">9:16 tall</option>
            <option value="1:1">1:1 square</option>
          </select>
        </div>
      </div>
      {videoStageEnabled && video.render_style && (
        <p className="text-[10px] -mt-2" style={{ color: "var(--text-tertiary)" }}>
          {video.render_style === "animated"
            ? "Animated channels stay on Grok — no premium upgrades."
            : "Realistic channels can route hero/reveal scenes to a premium model when it earns it."}
        </p>
      )}

      {/* Command bar — progress at a glance + the one big bulk action. Used to
          be a full-width green banner between the stage rail and the model-
          settings row; Ryan asked to declutter (2026-07-22) by moving it up
          into the StageRail card's empty right-hand side instead, via a
          portal into the slot div StageRail renders for it. Same conditional
          as before governs whether it renders at all: this whole block only
          exists in the tree while ScenesWorkspaceTab is mounted, i.e. the
          Scenes stage is active — it never leaks into other stages. */}
      {commandBarSlot && createPortal(
        <div className="flex items-center gap-3 flex-wrap justify-end">
        <p className="text-sm font-medium text-right" style={{ color: "var(--text-secondary)" }}>
          <strong style={{ color: "var(--text-primary)" }}>{scenes.length} scenes</strong>
          {" · "}
          <strong style={{ color: boardsDone >= boardsTotal ? "var(--green)" : "var(--text-primary)" }}>
            {boardsDone}/{boardsTotal} boards
          </strong>
          {extractedCount > 0 && (
            <>
              {" · "}
              <strong style={{ color: "var(--green)" }}>{extractedCount}/{totalSegments} pictures</strong>
              {videoStageEnabled && (
                <>
                  {" · "}
                  <strong style={{ color: clipsDone === clipCards.length ? "var(--green)" : "var(--text-primary)" }}>
                    {clipsDone}/{clipCards.length} animated
                  </strong>
                  {clipsPending > 0 && (
                    <span style={{ color: "var(--text-tertiary)" }}> · ≈ ${remainingCost.toFixed(2)} to finish · {modelLabel}</span>
                  )}
                </>
              )}
            </>
          )}
          {badCropCount > 0 && (
            <span className="ml-2 text-xs font-semibold" style={{ color: "rgb(255,110,110)" }}>
              <AlertTriangle size={11} className="inline mr-0.5 -mt-0.5" /> {badCropCount} bad crop{badCropCount === 1 ? "" : "s"}
            </span>
          )}
          {storyLocked && (
            <span className="ml-2 text-xs font-semibold" style={{ color: "var(--green)" }}>
              <Lock size={11} className="inline mr-0.5 -mt-0.5" /> Story locked
            </span>
          )}
        </p>
        {running && (
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
            style={{ background: "rgba(139, 92, 246, 0.15)", color: "var(--purple)", border: "1px solid rgba(139, 92, 246, 0.35)" }}>
            <Loader2 size={12} className="animate-spin" />
            {(taskMessage || "Working…").replace(/[*_]/g, "").slice(0, 80)}
          </span>
        )}
        <div className="flex-1" />
        {/* ONE stage-aware bulk button: storyboards → pictures → animate everything. */}
        {!running && !storyLocked && environmentsReady && bulk && (
          bulk.kind === "animate" ? (
            <button
              onClick={() => confirmable("all", remainingCost, () => animateAll(clipCards.filter((a) => !a.video_clip_url).map((a) => a.id)))}
              disabled={running}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold disabled:opacity-40 transition-all hover:brightness-110"
              style={{ background: confirmKey === "all" ? "var(--gold)" : "var(--green)", color: "var(--bg-void)" }}>
              <Play size={16} /> {confirmKey === "all" ? `Confirm — $${remainingCost.toFixed(2)}` : bulk.label}
            </button>
          ) : bulk.kind === "finish" ? (
            <button
              onClick={handleReExtract}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}
              title="Some pictures never finished — draw only the missing ones">
              <ImageIcon size={16} /> {bulk.label}
            </button>
          ) : (
            <button
              onClick={() => handleBulkGen(bulk.stage, bulk.scenes)}
              className="inline-flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-semibold transition-all hover:brightness-110"
              style={{ background: bulk.stage === "coverage-images" ? "var(--orange)" : "var(--purple)", color: "var(--bg-void)" }}
              title="Run this step for every scene that needs it">
              <ImageIcon size={16} /> {bulk.label}
            </button>
          )
        )}
        {confirmKey === "all" && (
          <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
            Cancel
          </button>
        )}
        <StopGenerationButton videoId={video.id} running={running} />
        {storyLocked && (
          <button onClick={handleUnlockStory} disabled={locking || running}
            className="text-xs font-medium px-3 py-1.5 rounded-lg transition-all disabled:opacity-40"
            style={{ color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.12)" }}
            title="Unlock to keep editing boards">
            {locking ? <Loader2 size={12} className="animate-spin inline mr-1" /> : <Unlock size={12} className="inline mr-1" />}
            Unlock
          </button>
        )}
        <div className="relative">
          <button onClick={() => setShowAdvanced(!showAdvanced)}
            className="p-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)]"
            style={{ color: "var(--text-tertiary)" }} aria-label="Advanced options" title="Advanced options">
            <MoreHorizontal size={18} />
          </button>
          {showAdvanced && (
            <>
              <div className="fixed inset-0 z-40" onClick={() => setShowAdvanced(false)} />
              <div className="absolute right-0 top-full mt-2 z-50 w-72 rounded-xl p-2 space-y-0.5"
                style={{ background: "var(--bg-deep)", border: "1px solid var(--border)", boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }}>
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>
                  Pictures
                </p>
                {extractedCount > 0 && needsUpscale && (
                  <button onClick={() => { setShowAdvanced(false); handleUpscalePanels(); }} disabled={running}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--text-secondary)" }}>
                    Upscale final pictures <span style={{ color: "var(--text-tertiary)" }}>({upscaledCount}/{extractedCount} done)</span>
                  </button>
                )}
                {storyLocked && totalSegments > 0 && extractedCount < totalSegments && (
                  <button onClick={() => { setShowAdvanced(false); handleReExtract(); }} disabled={running}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--text-secondary)" }}>
                    Create missing final pictures <span style={{ color: "var(--text-tertiary)" }}>({totalSegments - extractedCount} to make)</span>
                  </button>
                )}
                {videoStageEnabled && (
                <>
                <p className="text-[10px] uppercase tracking-wider font-semibold px-3 pt-2 pb-1" style={{ color: "var(--text-tertiary)" }}>
                  Clips
                </p>
                <button
                  onClick={() => {
                    setShowAdvanced(false);
                    runPipelineStage(video.id, "video-scripts").then(() => markStarted())
                      .catch((e) => toast.error((e as Error).message));
                  }}
                  disabled={running}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 disabled:opacity-40 flex items-center gap-2"
                  style={{ color: "var(--text-secondary)" }}>
                  <Sparkles size={12} /> Re-write motion directions
                </button>
                <button onClick={() => { setShowMotionPrompt((v) => !v); setShowAdvanced(false); }}
                  className="w-full text-left px-3 py-1.5 rounded-lg text-xs transition-colors hover:bg-white/5 flex items-center gap-2"
                  style={{ color: "var(--text-secondary)" }}>
                  <Film size={12} /> {showMotionPrompt ? "Hide" : "Edit"} motion instructions
                </button>
                <div className="border-t my-1" style={{ borderColor: "rgba(255,255,255,0.08)" }} />
                </>
                )}
                {extractedCount > 0 && (
                  <button onClick={() => { setShowAdvanced(false); handleClearAllExtracted(); }}
                    disabled={running || clearingExtracted}
                    className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                    style={{ color: "var(--orange)" }}>
                    Delete all final pictures <span style={{ color: "var(--text-tertiary)" }}>— boards stay</span>
                  </button>
                )}
                <button onClick={() => { setShowAdvanced(false); handleClearAllStoryboards(); }}
                  disabled={running || clearingAllStoryboards || storyLocked}
                  title={storyLocked ? "Unlock the story first" : undefined}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--orange)" }}>
                  Clear ALL storyboards <span style={{ color: "var(--text-tertiary)" }}>— deletes every board + plan</span>
                </button>
                <button onClick={() => { setShowAdvanced(false); handleAdvanceStage(); }} disabled={advancing}
                  className="w-full text-left text-xs px-3 py-2 rounded-lg transition-all hover:bg-[rgba(255,255,255,0.06)] disabled:opacity-40"
                  style={{ color: "var(--text-secondary)" }}>
                  Skip ahead to the next stage
                </button>
              </div>
            </>
          )}
        </div>
        </div>,
        commandBarSlot
      )}

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

      {/* ── Scene cards: boards → pictures+clips, one card per scene ── */}
      {scenes.map((scene) => {
        const sceneCards = scene.assets.filter((a) => a.image_url);
        const scenePending = sceneCards.filter((a) => !a.video_clip_url);
        const sceneMissing = scene.assets.length - sceneCards.length;
        const sceneCost = priceForModel(model) * scenePending.length;
        const sceneKey = `scene-${scene.sceneNumber}`;
        // C18 (checklist §1.3 [U]): approve_scene (C15b) sets status='approved'
        // on EVERY row in the scene in one UPDATE, so any approved row means
        // the whole scene counts as approved — same reading _approved_scenes
        // (backend/actions.py) uses to build finalize's scene set.
        const sceneApproved = sceneCards.some((a) => a.status === "approved");
        return (
          <GlassCard key={scene.sceneNumber} id={sceneKey} className="p-5">
            {/* Scene header: identity + per-scene verbs */}
            <div className="flex items-center gap-2 mb-3 flex-wrap">
              <SegmentBadge label={`Scene ${scene.sceneNumber}`} color="var(--purple)" />
              <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                {scene.duration}
              </span>
              {sceneCards.length > 0 && (
                <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                  {sceneCards.length - scenePending.length} of {sceneCards.length} animated
                </span>
              )}
              {/* Approve tick (checklist §1.3/C18 — C15b noted this tab had NO
                  approve affordance at all, chat-only). Finalize only touches
                  approved scenes, so this is the gate a creator taps before
                  "Finalize N approved scenes" does anything. Free + reversible
                  server-side; re-approving is a no-op, so no unapprove control. */}
              {sceneCards.length > 0 && (
                sceneApproved ? (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold"
                    style={{ background: "rgba(0, 230, 138, 0.15)", color: "var(--green)", border: "1px solid rgba(0, 230, 138, 0.35)" }}>
                    <Check size={11} /> Approved
                  </span>
                ) : (
                  <button
                    onClick={() => handleApproveScene(scene.sceneNumber)}
                    disabled={approvingScene === scene.sceneNumber}
                    title="Lock in this scene's pictures — free. Finalize only regenerates approved scenes."
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold transition-all hover:brightness-110 disabled:opacity-40"
                    style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.14)" }}>
                    {approvingScene === scene.sceneNumber ? <Loader2 size={11} className="animate-spin" /> : <Check size={11} />}
                    {approvingScene === scene.sceneNumber ? "Approving…" : "Approve"}
                  </button>
                )
              )}
              <div className="ml-auto flex items-center gap-2 flex-wrap">
                {generatingScene === scene.sceneNumber ? (
                  <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--purple)" }}>
                    <Loader2 size={13} className="animate-spin" /> Generating this scene…
                  </span>
                ) : (
                  <>
                    {/* ONE big primary = this scene's next step. Stage colour:
                        1 storyboard (purple) → 2 pictures (orange) → 3 animate (green).
                        Redo is a small secondary once pictures exist. */}
                    {sceneCards.length === 0 && scene.storyboardGridCount === 0 ? (
                      <>
                        <button onClick={() => handlePlanShots(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Plan the shots only (a few cents, nothing drawn) — read the plan, then draw boards one at a time"}
                          className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "transparent", border: "1px solid var(--purple)", color: "var(--purple)" }}>
                          <LayoutGrid size={15} /> {scene.coverageDirective ? "Re-plan shots" : "Plan shots"}
                        </button>
                        <button onClick={() => handleGenerateScene(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Plan the shots AND draw every board in one go"}
                          className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "var(--purple)", color: "var(--bg-void)" }}>
                          <LayoutGrid size={15} /> Generate storyboard
                        </button>
                      </>
                    ) : sceneCards.length === 0 ? (
                      <>
                        {/* Storyboard exists but no pictures yet: let them REDO the board
                            (e.g. after changing the cast or environments) OR move to pictures. */}
                        <button onClick={() => handleGenerateScene(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Redraw this scene's storyboard (after changing the cast, environments, or script)"}
                          className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "transparent", border: "1px solid var(--purple)", color: "var(--purple)" }}>
                          <LayoutGrid size={15} /> Regenerate storyboard
                        </button>
                        <button onClick={() => handleGenerateRealImages(scene.sceneNumber)}
                          disabled={running || storyLocked}
                          title={storyLocked ? "Unlock the story first (top right)" : "Draw the real per-shot pictures for this scene"}
                          className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                          style={{ background: "var(--orange)", color: "var(--bg-void)" }}>
                          <ImageIcon size={15} /> Generate pictures
                        </button>
                      </>
                    ) : (
                      <>
                        {videoStageEnabled && sceneMissing > 0 && (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full"
                            style={{ background: "rgba(251, 146, 60, 0.15)", color: "var(--orange)", border: "1px solid rgba(251, 146, 60, 0.35)" }}
                            title="Some of this scene's pictures never finished — animate after they exist">
                            {sceneMissing} picture{sceneMissing === 1 ? "" : "s"} missing
                          </span>
                        )}
                        {videoStageEnabled && scenePending.length > 0 && sceneMissing === 0 && (
                          <>
                            {confirmKey === sceneKey && (
                              <button onClick={() => setConfirmKey(null)} className="text-xs" style={{ color: "var(--text-tertiary)" }}>
                                Cancel
                              </button>
                            )}
                            <button
                              onClick={() => confirmable(sceneKey, sceneCost, () => animateScene(scene.sceneNumber, scenePending.map((a) => a.id)))}
                              disabled={running}
                              className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg disabled:opacity-40 transition-all hover:brightness-110"
                              style={confirmKey === sceneKey
                                ? { background: "var(--gold)", color: "var(--bg-void)" }
                                : { background: "var(--green)", color: "var(--bg-void)" }}>
                              <Play size={15} />
                              {confirmKey === sceneKey ? `Confirm — $${sceneCost.toFixed(2)}` : `Animate scene · $${sceneCost.toFixed(2)}`}
                            </button>
                          </>
                        )}
                        {videoStageEnabled && scenePending.length === 0 && (
                          <button onClick={() => handleStitchScene(scene.sceneNumber)}
                            disabled={running}
                            title="Stitch this scene's clips into one video you can watch"
                            className="inline-flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
                            <Film size={15} /> {scene.sceneVideoUrl ? "Re-stitch scene" : "Stitch scene"}
                          </button>
                        )}
                        {/* Named by what it redraws — a bare "Redo" was ambiguous
                            next to the per-clip redo and per-picture redraw
                            (Ryan, 2026-07-02). */}
                        <button onClick={() => handleRedoSceneFromScratch(scene.sceneNumber)}
                          disabled={running || storyLocked || clearingScene === scene.sceneNumber}
                          title={storyLocked ? "Unlock the story first (top right)" : "Re-plan this scene's shots and draw fresh pictures, replacing the current ones (storyboard refreshes too)"}
                          className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg transition-all hover:bg-white/5 disabled:opacity-40"
                          style={{ color: "var(--text-secondary)", border: "1px solid rgba(255,255,255,0.15)" }}>
                          {clearingScene === scene.sceneNumber ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={13} />} Redraw pictures
                        </button>
                      </>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Board + animatic side by side — equal halves, same line. */}
            <div className="flex flex-col lg:flex-row gap-4 mb-3 lg:items-stretch">
            {(scene.storyboardBeats.length > 0 || scene.hasStoryboardData) && (
              <div className="lg:flex-1 min-w-0">
                <ShotPlanViewer directive={scene.coverageDirective}
                  storyboardPrompts={scene.storyboardPromptsRaw}
                  sceneNumber={scene.sceneNumber} />
                <div className={`flex gap-4 pb-2 ${scene.storyboardBeats.length === 1 ? "" : "overflow-x-auto"}`} style={{ scrollbarWidth: "thin" }}>
                  {scene.storyboardBeats.map((beat) => {
                    const slotKey = `${scene.sceneNumber}-${beat.beatNumber}`;
                    // Boards update in place at the same URL — cache-bust by the
                    // scene's updated_at (changes on every regen) so the browser/
                    // CDN never shows a stale grid. A manual upload bumps gridBust
                    // for that one slot and takes precedence.
                    const bust = gridBust[slotKey] || scene.gridVersion;
                    const displayUrl = beat.gridUrl
                      ? (bust ? appendQueryParam(toDisplayImageUrl(beat.gridUrl)!, "cb", String(bust)) : toDisplayImageUrl(beat.gridUrl))
                      : undefined;
                    return (
                      <div key={`grid-${slotKey}`} className={`relative group/board ${scene.storyboardBeats.length === 1 ? "w-full" : "flex-shrink-0"}`}>
                        <div
                          className="relative rounded-lg overflow-hidden cursor-pointer transition-all hover:ring-2 hover:ring-[var(--purple)]"
                          style={{
                            ...(scene.storyboardBeats.length === 1
                              ? { width: "100%", aspectRatio: "16 / 9" }
                              : { width: 300, height: 176 }),
                            background: "var(--bg-elevated)",
                            border: dragOver === slotKey
                              ? "2px solid var(--green)"
                              : beat.gridUrl
                                ? "1px solid rgba(0, 230, 138, 0.25)"
                                : "1px dashed rgba(255,255,255,0.1)",
                          }}
                          onClick={() => {
                            if (beat.gridUrl) {
                              // Open the in-app viewer with every board of this
                              // scene, starting at the one that was clicked.
                              const withUrls = scene.storyboardBeats.filter((b) => b.gridUrl);
                              const items = withUrls.map((b) => {
                                const k = `${scene.sceneNumber}-${b.beatNumber}`;
                                const bv = gridBust[k] || scene.gridVersion;
                                return {
                                  url: bv
                                    ? appendQueryParam(toDisplayImageUrl(b.gridUrl!)!, "cb", String(bv))
                                    : toDisplayImageUrl(b.gridUrl!)!,
                                  label: `Board S${scene.sceneNumber}.${b.beatNumber}`,
                                };
                              });
                              const start = withUrls.findIndex((b) => b.beatNumber === beat.beatNumber);
                              setLightbox({ items, index: Math.max(0, start) });
                            } else if (!running) {
                              // A planned-but-empty slot draws JUST this board;
                              // no plan yet → plan + draw the whole scene.
                              if (beat.prompt.trim()) handleGenerateSingleBoard(scene.sceneNumber, beat.beatNumber);
                              else handleGenerateSceneGrids(scene.sceneNumber);
                            }
                          }}
                          onDragOver={(e) => { e.preventDefault(); setDragOver(slotKey); }}
                          onDragLeave={() => setDragOver(null)}
                          onDrop={(e) => {
                            e.preventDefault();
                            setDragOver(null);
                            const file = e.dataTransfer.files[0];
                            if (file && file.type.startsWith("image/")) {
                              handleGridDrop(scene.sceneNumber, beat.beatNumber, file);
                            }
                          }}
                          title={beat.gridUrl
                            ? "Click to view full-screen · drop an image here to replace it"
                            : beat.errorEntry
                              ? `${SHEET_FAIL_LABELS[beat.errorEntry.class]} (${beat.errorEntry.attempts} attempt${beat.errorEntry.attempts === 1 ? "" : "s"}) — ${beat.errorEntry.msg || "no details"} · click to try again`
                              : beat.prompt.trim()
                                ? "Click to draw just this board from the saved plan · or drag & drop an image"
                                : "Click to plan + draw this scene's boards · or drag & drop an image"}
                        >
                          {beat.gridUrl ? (
                            <>
                              <img src={displayUrl} alt={`S${scene.sceneNumber} board ${beat.beatNumber}`} className="w-full h-full object-cover" />
                              {(dragOver === slotKey || uploadingGrid === slotKey || clearingSlot === slotKey) && (
                                <div className="absolute inset-0 flex flex-col items-center justify-center gap-2" style={{ background: "rgba(0,0,0,0.65)" }}>
                                  {uploadingGrid === slotKey || clearingSlot === slotKey ? (
                                    <>
                                      <Loader2 size={22} className="animate-spin" style={{ color: "var(--green)" }} />
                                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                                        {uploadingGrid === slotKey ? "Saving your image..." : "Removing..."}
                                      </span>
                                    </>
                                  ) : (
                                    <>
                                      <ImageIcon size={22} style={{ color: "var(--green)" }} />
                                      <span className="text-xs font-semibold" style={{ color: "var(--green)" }}>
                                        Drop to replace this board
                                      </span>
                                    </>
                                  )}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="w-full h-full flex flex-col items-center justify-center gap-2 transition-colors hover:bg-[rgba(168,85,247,0.08)]">
                              {uploadingGrid === slotKey ? (
                                <>
                                  <Loader2 size={20} className="animate-spin" style={{ color: "var(--green)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>Uploading...</span>
                                </>
                              ) : dragOver === slotKey ? (
                                <>
                                  <ImageIcon size={20} style={{ color: "var(--green)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>Drop to Upload</span>
                                </>
                              ) : generatingScene === scene.sceneNumber ? (
                                <>
                                  <Loader2 size={20} className="animate-spin" style={{ color: "var(--purple)" }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>Generating...</span>
                                </>
                              ) : beat.prompt.trim() ? (
                                <>
                                  <span className="w-9 h-9 rounded-full flex items-center justify-center"
                                    style={{ background: "rgba(168,85,247,0.18)", border: "1px solid var(--purple)" }}>
                                    <Play size={16} style={{ color: "var(--purple)" }} />
                                  </span>
                                  <span className="text-[11px] font-semibold" style={{ color: "var(--purple)" }}>
                                    Draw board S{scene.sceneNumber}.{beat.beatNumber}
                                  </span>
                                </>
                              ) : (
                                <>
                                  <ImageIcon size={20} style={{ color: "var(--purple)", opacity: 0.6 }} />
                                  <span className="text-[11px] font-medium" style={{ color: "var(--purple)" }}>Click or Drop Image</span>
                                </>
                              )}
                            </div>
                          )}
                        </div>
                        {beat.gridUrl && clearingSlot !== slotKey && uploadingGrid !== slotKey && (
                          <button
                            onClick={(e) => { e.stopPropagation(); handleClearGridSlot(scene.sceneNumber, beat.beatNumber); }}
                            disabled={running}
                            title="Remove just this board (prompts stay)"
                            className="absolute top-1.5 right-1.5 rounded-full p-1 opacity-0 group-hover/board:opacity-100 transition-opacity disabled:opacity-0"
                            style={{ background: "rgba(0,0,0,0.75)", color: "rgba(239, 68, 68, 0.95)" }}>
                            <X size={14} />
                          </button>
                        )}
                        {/* Failed-board chip (migration 113 / storyboard_errors) — only
                            an empty slot with a known failure gets this; a landed image
                            always wins, and the backend clears the entry the moment a
                            board lands so this can't go stale on a slot that redrew fine. */}
                        {!beat.gridUrl && beat.errorEntry && (
                          <span
                            className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[9px] font-semibold"
                            style={{
                              background: "rgba(239, 68, 68, 0.15)", color: "rgb(255,110,110)",
                              border: "1px solid rgba(239, 68, 68, 0.35)",
                            }}
                            title={`${beat.errorEntry.msg || "No details"} (attempt${beat.errorEntry.attempts === 1 ? "" : "s"}: ${beat.errorEntry.attempts})`}>
                            <AlertTriangle size={10} />
                            {SHEET_FAIL_LABELS[beat.errorEntry.class]} · {beat.errorEntry.attempts}×
                          </span>
                        )}
                        <p className="text-center mt-1.5 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                          Board S{scene.sceneNumber}.{beat.beatNumber}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Animatic (right half): pictures + narration = the scene as a film, $0 */}
            <div className="lg:flex-1 min-w-0">
            {(() => {
              // Real stitched scene video (FFmpeg concat of the clips) wins over the
              // still-image animatic. Cache-bust by the scene's updated_at so a
              // re-stitch shows the new cut.
              if (scene.sceneVideoUrl) {
                // Drive-hosted stitches don't stream in <video> directly — route
                // through the media proxy (Supabase/other URLs pass through).
                const base = toDisplayVideoUrl(scene.sceneVideoUrl) ?? scene.sceneVideoUrl;
                const v = `${base}${scene.gridVersion ? `${base.includes("?") ? "&" : "?"}cb=${scene.gridVersion}` : ""}`;
                return (
                  <>
                    <p className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--turquoise)" }}>Watch this scene</p>
                    <video key={v} src={v} controls playsInline className="w-full rounded-xl"
                      style={{ aspectRatio: "16 / 9", background: "#000" }} />
                  </>
                );
              }
              const panels = scene.assets
                .filter((a) => a.image_url)
                .map((a) => ({ url: toDisplayImageUrl(a.image_url)!, text: a.sentence_text || "" }));
              if (panels.length > 0) {
                return <AnimaticPlayer videoId={video.id} scene={scene.sceneNumber} panels={panels} />;
              }
              return scene.voiceOverUrl
                ? <SecureAudioPlayer videoId={video.id} scene={scene.sceneNumber} />
                : <p className="text-[10px] mb-3" style={{ color: "var(--text-tertiary)" }}>No voice generated yet</p>;
            })()}
            </div>
            </div>

            {/* Narration text — collapsed */}
            <details className="mb-3">
              <summary className="text-[11px] cursor-pointer" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--text-tertiary)" }}>
                  {scene.narrationText.slice(0, 80).trim()}{scene.narrationText.length > 80 ? "..." : ""}
                </span>
              </summary>
              <p className="text-sm leading-relaxed mt-2 pl-4"
                style={{ color: "var(--text-primary)", borderLeft: "2px solid var(--border-subtle)" }}>
                {scene.narrationText}
              </p>
            </details>

            {/* Beat prompts — collapsed. Only for storyboards with a written plan;
                the cheap one-image storyboard has no per-beat text (the plan is the
                picture), so skip the empty accordion. */}
            {(() => {
              const planned = scene.storyboardBeats.filter((b) => b.prompt.trim());
              if (planned.length === 0) return null;
              return (
                <details className="mb-3">
                  <summary className="text-[10px] cursor-pointer" style={{ color: "var(--text-tertiary)" }}>
                    {planned.length} picture plan{planned.length !== 1 ? "s" : ""}
                  </summary>
                  <div className="space-y-2 mt-2">
                    {planned.map((beat) => (
                      <PromptExpander key={`prompt-${scene.sceneNumber}-${beat.beatNumber}`}
                        prompt={beat.prompt} label={`Beat ${beat.beatNumber}`} previewLength={120} />
                    ))}
                  </div>
                </details>
              );
            })()}

            {/* ── Pictures + clips: one card per story segment ── */}
            {sceneCards.length > 0 && (
              <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4 mt-1">
                {sceneCards.map((asset) => (
                  <SegmentCard
                    key={asset.id}
                    asset={asset}
                    speaker={speakerFor(asset)}
                    perClip={perClip}
                    picturePrice={picturePrice}
                    canAnimate={videoStageEnabled}
                    isGenerating={generatingClipIds.has(asset.id) && running}
                    isRecropping={recropping === asset.id && running}
                    isFailed={failedClipIds.has(asset.id)}
                    isPlaying={playingId === asset.id}
                    disabled={running}
                    videoDefaultModel={model}
                    modelDisplayName={modelDisplayName}
                    onTap={() => {
                      if (asset.video_clip_url) setPlayingId((p) => (p === asset.id ? null : asset.id));
                      else if (videoStageEnabled) animateOne(asset);
                    }}
                    onRedoClip={() => animateOne(asset, true)}
                    onDeleteClip={() => removeClip(asset)}
                    onDeletePicture={() => handleClearExtractedPanel(asset.id)}
                    onRecrop={() => recropOne(asset)}
                    onRedraw={() => redrawOne(asset)}
                    onOpenModelOverride={() => setOverrideAssetId(asset.id)}
                    cameraPresets={cameraPresets}
                    onOpenCameraPreset={() => setCameraAssetId(asset.id)}
                  />
                ))}
              </div>
            )}
          </GlassCard>
        );
      })}
      {lightbox && (
        <BoardLightbox
          items={lightbox.items}
          index={lightbox.index}
          onNavigate={(i) => setLightbox({ ...lightbox, index: i })}
          onClose={() => setLightbox(null)}
        />
      )}
      {overrideAsset && (
        <ModelOverrideSheet
          asset={overrideAsset}
          models={wiredVideoModels}
          videoDefaultModel={model}
          saving={savingOverride}
          onPick={(id) => handleSetModelOverride(overrideAsset.id, id)}
          onUseRecommendation={() => handleSetModelOverride(overrideAsset.id, null)}
          onClose={() => setOverrideAssetId(null)}
        />
      )}
      {cameraAsset && (
        <CameraPresetSheet
          asset={cameraAsset}
          presets={cameraPresets}
          saving={savingCameraPreset}
          onPick={(id) => handleSetCameraPreset(cameraAsset.id, id)}
          onUseAuto={() => handleSetCameraPreset(cameraAsset.id, null)}
          onClose={() => setCameraAssetId(null)}
        />
      )}
    </div>
  );
}

/** C14's one-tap override sheet: tapping a scene's model badge opens this —
 * pick any wired model (name + $/clip, straight off GET /api/models — no
 * hardcoded prices) to force that scene through it, or "Use recommendation"
 * to clear back to the automatic router/video default. */
function ModelOverrideSheet({ asset, models, videoDefaultModel, saving, onPick, onUseRecommendation, onClose }: {
  asset: Asset;
  models: { id: string; label: string }[];
  videoDefaultModel: string;
  saving: boolean;
  onPick: (modelId: string) => void;
  onUseRecommendation: () => void;
  onClose: () => void;
}) {
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  const activeId = asset.model_override || asset.routed_model || videoDefaultModel;
  const reason = asset.model_override
    ? "Manually overridden"
    : asset.routing_reason || "Channel default — no per-scene routing yet";
  return (
    <Modal open onClose={onClose} title={`Clip model — ${label}`} size="sm">
      <p className="text-xs mb-3" style={{ color: "var(--text-tertiary)" }}>{reason}</p>
      <div className="flex flex-col gap-1.5">
        {models.map((m) => {
          const isActive = m.id === activeId;
          return (
            <button
              key={m.id}
              disabled={saving}
              onClick={() => onPick(m.id)}
              className="text-left px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110 disabled:opacity-50"
              style={{
                background: isActive ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.04)",
                border: isActive ? "1px solid rgba(139, 92, 246, 0.4)" : "1px solid rgba(255,255,255,0.08)",
                color: "var(--text-primary)",
              }}>
              {m.label}{isActive && asset.model_override ? " · manual" : isActive ? " · current" : ""}
            </button>
          );
        })}
      </div>
      {asset.model_override && (
        <button
          onClick={onUseRecommendation}
          disabled={saving}
          className="mt-3 w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
          {saving ? "Saving…" : "Use recommendation"}
        </button>
      )}
    </Modal>
  );
}

/** C23's one-tap camera-move sheet (checklist §2.2, UX map §4): tapping a
 * shot's camera chip opens this — pick from the curated catalog (name +
 * "best for" one-liner, straight off GET /api/camera-presets — no
 * hardcoded list here) to force that ONE shot's motion, or "Auto" to clear
 * back to camera_selector.py's earn-the-move system. Reuses the C14
 * ModelOverrideSheet pattern (same Modal, same active/manual highlight,
 * same "clear" button shape) — grouped by purpose per the UX map ("Reveal
 * / Scale / Establish / Isolation / Payoff"), `static_locked`'s empty
 * best_for gets its own "Other" group at the end. */
const _CAMERA_PURPOSE_ORDER = ["REVEAL", "SCALE", "ESTABLISH", "ISOLATION", "PAYOFF"];
function CameraPresetSheet({ asset, presets, saving, onPick, onUseAuto, onClose }: {
  asset: Asset;
  presets: CameraPresetInfo[];
  saving: boolean;
  onPick: (presetId: string) => void;
  onUseAuto: () => void;
  onClose: () => void;
}) {
  const label = `S-${String(asset.scene ?? 0).padStart(2, "0")}.${asset.image_index ?? 0}`;
  const current = describeCameraMove(asset, presets);
  const groups = useMemo(() => {
    const byPurpose = new Map<string, CameraPresetInfo[]>();
    const other: CameraPresetInfo[] = [];
    for (const p of presets) {
      const purpose = _CAMERA_PURPOSE_ORDER.find((pp) => p.best_for.includes(pp));
      if (purpose) {
        if (!byPurpose.has(purpose)) byPurpose.set(purpose, []);
        byPurpose.get(purpose)!.push(p);
      } else {
        other.push(p);
      }
    }
    const ordered: { title: string; items: CameraPresetInfo[] }[] = _CAMERA_PURPOSE_ORDER
      .filter((p) => byPurpose.has(p))
      .map((p) => ({ title: p.charAt(0) + p.slice(1).toLowerCase(), items: byPurpose.get(p)! }));
    if (other.length) ordered.push({ title: "Other", items: other });
    return ordered;
  }, [presets]);
  return (
    <Modal open onClose={onClose} title={`Camera move — ${label}`} size="sm">
      <p className="text-xs mb-3" style={{ color: "var(--text-tertiary)" }}>
        {current.isManual ? "Manually picked" : `Auto (earn-the-move): ${current.label}`}
      </p>
      {presets.length === 0 && (
        <p className="text-xs" style={{ color: "var(--text-tertiary)" }}>
          Couldn&apos;t load the preset list — try again in a moment.
        </p>
      )}
      <div className="flex flex-col gap-3 max-h-96 overflow-y-auto pr-1">
        {groups.map((g) => (
          <div key={g.title}>
            <p className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: "var(--text-tertiary)" }}>
              {g.title}
            </p>
            <div className="flex flex-col gap-1.5">
              {g.items.map((p) => {
                const isActive = asset.camera_preset_id === p.id;
                return (
                  <button
                    key={p.id}
                    disabled={saving}
                    onClick={() => onPick(p.id)}
                    title={p.preview || undefined}
                    className="text-left px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110 disabled:opacity-50"
                    style={{
                      background: isActive ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.04)",
                      border: isActive ? "1px solid rgba(139, 92, 246, 0.4)" : "1px solid rgba(255,255,255,0.08)",
                      color: "var(--text-primary)",
                    }}>
                    <span className="block">{p.name}{isActive ? " · manual" : ""}</span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      {asset.camera_preset_id && (
        <button
          onClick={onUseAuto}
          disabled={saving}
          className="mt-3 w-full text-center px-3 py-2 rounded-lg text-xs font-semibold transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: "var(--bg-elevated)", color: "var(--turquoise)", border: "1px solid var(--border-subtle)" }}>
          {saving ? "Saving…" : "Use Auto (earn the move)"}
        </button>
      )}
    </Modal>
  );
}

/** Full-screen in-app board viewer. Esc or backdrop closes; ←/→ move between
 * the scene's boards. Exists because the raw storage URL downloads instead of
 * displaying — the user should never leave the page to look at a board. */
function BoardLightbox({ items, index, onNavigate, onClose }: {
  items: { url: string; label: string }[];
  index: number;
  onNavigate: (i: number) => void;
  onClose: () => void;
}) {
  const item = items[Math.min(index, items.length - 1)];
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" && index < items.length - 1) onNavigate(index + 1);
      else if (e.key === "ArrowLeft" && index > 0) onNavigate(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, items.length, onNavigate, onClose]);
  if (!item) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center"
      style={{ background: "rgba(0,0,0,0.92)" }}
      onClick={onClose}
    >
      <button
        onClick={onClose}
        title="Close (Esc)"
        className="absolute top-4 right-4 w-9 h-9 rounded-full flex items-center justify-center transition-colors hover:brightness-125"
        style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
        <X size={18} />
      </button>
      {index > 0 && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(index - 1); }}
          title="Previous board (←)"
          className="absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center text-xl transition-colors hover:brightness-125"
          style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
          ‹
        </button>
      )}
      {index < items.length - 1 && (
        <button
          onClick={(e) => { e.stopPropagation(); onNavigate(index + 1); }}
          title="Next board (→)"
          className="absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full flex items-center justify-center text-xl transition-colors hover:brightness-125"
          style={{ background: "rgba(255,255,255,0.12)", color: "white" }}>
          ›
        </button>
      )}
      <img
        src={item.url}
        alt={item.label}
        onClick={(e) => e.stopPropagation()}
        className="max-w-[94vw] max-h-[88vh] object-contain rounded-lg"
      />
      <p className="mt-3 text-sm font-mono" style={{ color: "rgba(255,255,255,0.75)" }}>
        {item.label}{items.length > 1 ? ` · ${index + 1}/${items.length}` : ""}
      </p>
    </div>
  );
}

/** One story segment: shows the clip when it exists (tap = play), else the
 * final picture (tap = animate, ~$0.09). Bad crops wear a red badge whose
 * one-tap Re-crop is free and re-animates stale clips automatically. */
function SegmentCard({ asset, speaker, perClip, picturePrice, canAnimate, isGenerating, isRecropping, isFailed, isPlaying, disabled, videoDefaultModel, modelDisplayName, onTap, onRedoClip, onDeleteClip, onDeletePicture, onRecrop, onRedraw, onOpenModelOverride, cameraPresets, onOpenCameraPreset }: {
  asset: Asset;
  speaker: string | null;
  perClip: number;
  picturePrice: number;
  canAnimate: boolean;
  isGenerating: boolean;
  isRecropping: boolean;
  isFailed: boolean;
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
      className={`p-0 overflow-hidden group ${hasClip || canAnimate ? "cursor-pointer" : "cursor-default"}`}
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
              style={{ opacity: isGenerating || isRecropping ? 0.4 : 0.85 }}
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

        {/* Bad crop badge — one tap fixes it for free */}
        {badCrop && !isGenerating && !isRecropping && (
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
        {(isGenerating || isRecropping) && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-2">
            <Loader2 size={22} className="animate-spin" style={{ color: "var(--purple)" }} />
            <span className="text-[10px]" style={{ color: "var(--text-secondary)" }}>
              {isRecropping ? "Re-cropping…" : "Bringing it to life…"}
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
        {canAnimate && !hasClip && !isGenerating && !isRecropping && !isFailed && (
          <div className="absolute inset-0 z-10 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ background: "rgba(0,0,0,0.45)" }}>
            <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
              <Play size={12} /> Animate · ${perClip.toFixed(2)}
            </span>
          </div>
        )}
        {hasClip && !isPlaying && (
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

        {/* Hover actions: clip level when a clip exists, picture level otherwise */}
        {!isGenerating && !isRecropping && (
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
              {hasClip ? (
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
              )}
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
          {/* C14 per-scene model badge — tap opens the override sheet. Gated on
              canAnimate: an images-only plan has no clip model to show. */}
          {canAnimate && (
            <button
              onClick={(e) => { e.stopPropagation(); onOpenModelOverride(); }}
              title={`${modelDisplayName(effectiveModelId) || effectiveModelId} — ${modelReason}. Tap to change this scene's clip model.`}
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-mono font-medium transition-all hover:brightness-125"
              style={{
                background: modelOverridden ? "rgba(139, 92, 246, 0.16)" : "rgba(255,255,255,0.05)",
                color: modelOverridden ? "var(--purple)" : "var(--text-tertiary)",
                border: modelOverridden ? "1px solid rgba(139, 92, 246, 0.35)" : "1px solid rgba(255,255,255,0.08)",
              }}>
              <Film size={9} />
              {modelDisplayName(effectiveModelId) || effectiveModelId}
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
        {/* Image prompt — edit + redraw just this picture (anchored on the locked cast). */}
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
              disabled={imgState === "saving"}
              className="inline-flex items-center gap-1 text-[10px] font-semibold px-2.5 py-1 rounded-md transition-all hover:brightness-110 disabled:opacity-40"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}>
              <RotateCcw size={11} /> {imgState === "saving" ? "Starting…" : imgState === "error" ? "Failed — retry" : `Redraw picture · ~$${picturePrice.toFixed(2)}`}
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
        {/* Motion prompt — click to fine-tune how this shot moves before animating.
            stopPropagation so editing never triggers the card's tap-to-animate. */}
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
      </div>
    </GlassCard>
  );
}
