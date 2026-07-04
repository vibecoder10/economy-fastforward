"use client";

import { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown, ChevronRight, Merge, Trash2, Plus, Volume2,
  Library, Wand2, Play, Square, Layers, Mic, Pencil, Loader2,
  CheckCircle, Clock, AlertCircle, Save, ShieldCheck,
  Cloud, CloudUpload, RefreshCw, ExternalLink,
} from "lucide-react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  getVideoScript, getVideoAssets, advanceVideo, rejectVideo,
  runPipelineStage, updateSceneText, updateVideo, clearStaleTask,
  runVoiceForScene, runSplit, getSceneSegments, updateSceneSegments,
  getDefaultScriptPrompt,
  getDriveScriptStatus, pushScriptToDrive, syncScriptFromDrive,
  setApiKey, getApiKeyStatus, getDialogueMap, getAudioToken,
  getPipelineTaskStatus,
} from "@/lib/api";
import { API_URL } from "@/lib/env";
import type { ScriptScene as ApiScriptScene, Asset, Segment } from "@/lib/api";
import { useTaskPoller } from "@/hooks/use-task-poller";
import { useToast } from "@/components/ui/toast";
import { GlassCard } from "@/components/ui/GlassCard";
import { SegmentBadge } from "@/components/ui/SegmentBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { MiniWaveform } from "@/components/ui/MiniWaveform";
import { ProgressRing } from "@/components/ui/ProgressRing";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ScriptVoiceTabProps {
  video: any;
  onAdvanced?: () => void;
}

interface SentenceState {
  text: string;
  sfxMode: "none" | "library" | "elevenlabs" | "custom";
  sfxLibraryValue: string;
  sfxCustomPrompt: string;
  durationSeconds: number | null;
  cumulativeStart: number | null;
  imagePrompt: string | null;
  imageIndex: number | null;
}

interface SceneState {
  id: string;
  sceneNumber: number;
  actNumber: number;
  narrationText: string;
  displayText: string; // narrationText with style directives stripped
  visualStyle: string;
  composition: string;
  sources?: string[];
  imageGenerated?: boolean;
  voiceOverUrl: string | null;
  voiceStatus: string | null;
  scriptStatus: string | null;
  tone: string | null;
  sentences: SentenceState[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SFX_LIBRARY = [
  { value: "", label: "-- No SFX --" },
  { value: "ambient-tension", label: "Ambient Tension" },
  { value: "war-drums", label: "War Drums (distant)" },
  { value: "paper-shuffle", label: "Paper Shuffle" },
  { value: "door-close", label: "Heavy Door Close" },
  { value: "crowd-murmur", label: "Crowd Murmur" },
  { value: "typing", label: "Keyboard Typing" },
  { value: "explosion-distant", label: "Distant Explosion" },
  { value: "clock-ticking", label: "Clock Ticking" },
  { value: "heartbeat", label: "Heartbeat" },
  { value: "wind", label: "Desert Wind" },
  { value: "helicopter", label: "Helicopter Flyover" },
  { value: "news-broadcast", label: "News Broadcast Chatter" },
];

/** Regex to match visual style directive lines (e.g. "dossier wide", "schema medium") */
const STYLE_DIRECTIVE_RE =
  /^(dossier|schema|echo|holographic hud|cinematic illustration|clay mannequin)\s*(wide|medium|closeup|environmental|portrait|overhead|low_angle)?\s*$/im;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function splitSentences(text: string): string[] {
  return text
    .split(/(?<=[.!?\u2014])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Strip visual style directive lines from scene text for display. */
function stripStyleDirectives(text: string): string {
  return text
    .split("\n")
    .filter((line) => !STYLE_DIRECTIVE_RE.test(line.trim()))
    .join("\n")
    .trim();
}

function initFromApi(apiScenes: ApiScriptScene[], assets?: Asset[]): SceneState[] {
  const sorted = [...apiScenes].sort((a, b) => (a.scene || 0) - (b.scene || 0));
  const total = sorted.length;
  const actsCount = Math.min(total, 6);

  return sorted.map((s) => {
    const sceneAssets = (assets || [])
      .filter((a) => a.scene === s.scene)
      .sort((a, b) => (a.image_index || 0) - (b.image_index || 0));

    const sentences: SentenceState[] =
      sceneAssets.length > 0
        ? sceneAssets
            .filter((a) => !!a.sentence_text)
            .map((a) => ({
              text: a.sentence_text!,
              sfxMode: "none" as const,
              sfxLibraryValue: "",
              sfxCustomPrompt: "",
              durationSeconds: (a as any).duration_seconds ?? null,
              cumulativeStart: null,
              imagePrompt: (a as any).image_prompt ?? null,
              imageIndex: a.image_index ?? null,
            }))
        : splitSentences(s.scene_text || "").map((text) => ({
            text,
            sfxMode: "none" as const,
            sfxLibraryValue: "",
            sfxCustomPrompt: "",
            durationSeconds: null,
            cumulativeStart: null,
            imagePrompt: null,
            imageIndex: null,
          }));

    const rawText = s.scene_text || "";
    return {
      id: s.id,
      sceneNumber: s.scene || 0,
      actNumber: Math.ceil((s.scene || 1) / Math.ceil(total / actsCount)),
      narrationText: rawText,
      displayText: stripStyleDirectives(rawText),
      visualStyle: "dossier",
      composition: "wide",
      sources: s.sources
        ? (() => {
            try {
              return JSON.parse(s.sources!);
            } catch {
              return [];
            }
          })()
        : [],
      imageGenerated: sceneAssets.some((a) => !!a.image_url),
      voiceOverUrl: s.voice_over_url || null,
      voiceStatus: s.voice_status || null,
      scriptStatus: s.script_status || null,
      tone: s.tone || null,
      sentences,
    };
  });
}

// ---------------------------------------------------------------------------
// Status badges
// ---------------------------------------------------------------------------

function VoiceStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const lower = status.toLowerCase();
  if (lower === "finished" || lower === "done") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(0, 230, 138, 0.12)", color: "var(--green)" }}
      >
        <CheckCircle size={8} /> Voice Done
      </span>
    );
  }
  if (lower === "create" || lower === "pending") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(255, 186, 8, 0.12)", color: "var(--gold)" }}
      >
        <Clock size={8} /> Voice Pending
      </span>
    );
  }
  return (
    <span
      className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
      style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-tertiary)" }}
    >
      {status}
    </span>
  );
}

function ScriptStatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return null;
  const lower = status.toLowerCase();
  if (lower === "finished" || lower === "done") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(0, 188, 212, 0.12)", color: "var(--turquoise)" }}
      >
        <CheckCircle size={8} /> Script Done
      </span>
    );
  }
  if (lower === "create" || lower === "pending") {
    return (
      <span
        className="flex items-center gap-1 text-[9px] font-medium px-1.5 py-0.5 rounded-full"
        style={{ background: "rgba(255, 120, 73, 0.12)", color: "var(--orange)" }}
      >
        <AlertCircle size={8} /> Script Pending
      </span>
    );
  }
  return null;
}

// ---------------------------------------------------------------------------
// SegmentEditor — save segment text edits to backend
// ---------------------------------------------------------------------------

function SegmentEditor({ videoId, sceneNumber }: { videoId: string; sceneNumber: number }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["segments", videoId, sceneNumber],
    queryFn: () => getSceneSegments(videoId, sceneNumber),
  });
  const [edits, setEdits] = useState<Record<number, string>>({});
  const [saved, setSaved] = useState(false);

  const segments = data?.segments || [];
  const hasEdits = Object.keys(edits).length > 0;

  const saveMutation = useMutation({
    mutationFn: () => {
      const updated = segments.map((seg) => ({
        image_index: seg.image_index,
        sentence_text: edits[seg.image_index] ?? seg.sentence_text,
      }));
      return updateSceneSegments(videoId, sceneNumber, updated);
    },
    onSuccess: () => {
      setEdits({});
      setSaved(true);
      setTimeout(() => setSaved(false), 1500);
      queryClient.invalidateQueries({ queryKey: ["segments", videoId, sceneNumber] });
      queryClient.invalidateQueries({ queryKey: ["video-assets", videoId] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-3 justify-center">
        <Loader2 size={14} className="animate-spin" style={{ color: "var(--turquoise)" }} />
        <span className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>Loading segments...</span>
      </div>
    );
  }

  if (segments.length === 0) return null;

  return (
    <div className="mt-3 pt-3" style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}>
      <div className="flex items-center gap-2 mb-2">
        <Save size={11} style={{ color: "var(--turquoise)" }} />
        <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          Segments
        </span>
      </div>
      <div className="space-y-1.5">
        {segments.map((seg) => {
          const text = edits[seg.image_index] ?? seg.sentence_text;
          const isDirty = seg.image_index in edits;
          return (
            <div
              key={seg.image_index}
              className="rounded-lg p-2"
              style={{
                background: isDirty ? "rgba(0,212,170,0.04)" : "rgba(255,255,255,0.02)",
                border: `1px solid ${isDirty ? "rgba(0,212,170,0.2)" : "rgba(255,255,255,0.05)"}`,
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded"
                  style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}>
                  Seg {seg.image_index}
                </span>
                <span className="text-[9px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                  {seg.word_count}w · {seg.duration_seconds.toFixed(1)}s
                </span>
                {isDirty && (
                  <span className="text-[9px] font-medium" style={{ color: "var(--turquoise)" }}>modified</span>
                )}
              </div>
              <textarea
                value={text}
                onChange={(e) => {
                  const val = e.target.value;
                  setEdits((prev) => {
                    if (val === seg.sentence_text) {
                      const next = { ...prev };
                      delete next[seg.image_index];
                      return next;
                    }
                    return { ...prev, [seg.image_index]: val };
                  });
                }}
                rows={Math.max(1, Math.ceil(text.length / 90))}
                className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                style={{ color: "var(--text-primary)", background: "transparent", border: "1px solid transparent" }}
                onFocus={(e) => { e.target.style.background = "var(--bg-elevated)"; e.target.style.borderColor = "var(--turquoise)"; }}
                onBlur={(e) => { e.target.style.background = "transparent"; e.target.style.borderColor = "transparent"; }}
              />
            </div>
          );
        })}
        <div className="flex items-center gap-2 pt-1">
          <button
            onClick={() => saveMutation.mutate()}
            disabled={!hasEdits || saveMutation.isPending}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all disabled:opacity-30"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {saveMutation.isPending ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
            Save Segments
          </button>
          {saved && (
            <span className="text-[11px] font-medium" style={{ color: "var(--green)" }}>
              <CheckCircle size={12} className="inline mr-1" />Saved
            </span>
          )}
          {saveMutation.isError && (
            <span className="text-[11px]" style={{ color: "var(--red)" }}>
              Save failed: {(saveMutation.error as Error).message}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom voice (ElevenLabs) — paste a voice ID so narration uses your own voice
// instead of the default Kie roster. Saves to the same per-tenant key store as
// Settings → Keys, surfaced here where you actually generate voice.
// ---------------------------------------------------------------------------

function CustomVoiceCard() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [apiKey, setApiKeyValue] = useState("");

  const { data: voiceStatus } = useQuery({
    queryKey: ["key-status", "elevenlabs_voice_id"],
    queryFn: () => getApiKeyStatus("elevenlabs_voice_id"),
  });
  const { data: keyStatus } = useQuery({
    queryKey: ["key-status", "elevenlabs_api_key"],
    queryFn: () => getApiKeyStatus("elevenlabs_api_key"),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (apiKey.trim()) await setApiKey("elevenlabs_api_key", apiKey.trim());
      if (voiceId.trim()) await setApiKey("elevenlabs_voice_id", voiceId.trim());
    },
    onSuccess: () => {
      toast.success("Saved — new voice generations will use your ElevenLabs voice.");
      setVoiceId("");
      setApiKeyValue("");
      queryClient.invalidateQueries({ queryKey: ["key-status", "elevenlabs_voice_id"] });
      queryClient.invalidateQueries({ queryKey: ["key-status", "elevenlabs_api_key"] });
    },
    onError: (err) => toast.error(`Couldn't save voice: ${(err as Error).message}`),
  });

  const voiceSet = !!voiceStatus?.configured;
  const keySet = !!keyStatus?.configured;
  const canSave = !!voiceId.trim() && (keySet || !!apiKey.trim()) && !save.isPending;

  return (
    <GlassCard className="p-5">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center justify-between w-full text-left"
      >
        <span className="text-[10px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
          Custom Voice (ElevenLabs)
        </span>
        <span className="flex items-center gap-2">
          {voiceSet && (
            <span className="inline-flex items-center gap-1 text-[10px]" style={{ color: "var(--green)" }}>
              <CheckCircle size={11} /> set
            </span>
          )}
          {open ? <ChevronDown size={14} style={{ color: "var(--text-tertiary)" }} /> : <ChevronRight size={14} style={{ color: "var(--text-tertiary)" }} />}
        </span>
      </button>

      {open && (
        <div className="space-y-2.5 mt-3">
          <p className="text-[11px] leading-snug" style={{ color: "var(--text-tertiary)" }}>
            Paste a Voice ID from your ElevenLabs voice library to narrate in your own voice.
            {voiceSet ? " A voice is already saved — paste a new ID to change it." : ""}
          </p>
          <input
            value={voiceId}
            onChange={(e) => setVoiceId(e.target.value)}
            placeholder="ElevenLabs Voice ID (e.g. 21m00Tcm4TlvDq8ikWAM)"
            className="w-full px-3 py-2 rounded-lg text-sm font-mono"
            style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
          />
          {!keySet && (
            <input
              value={apiKey}
              onChange={(e) => setApiKeyValue(e.target.value)}
              placeholder="ElevenLabs API key (needed once)"
              type="password"
              className="w-full px-3 py-2 rounded-lg text-sm font-mono"
              style={{ background: "var(--bg-elevated)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
            />
          )}
          <ActionButton
            variant="outline"
            icon={save.isPending ? Loader2 : Save}
            className="w-full"
            onClick={() => canSave && save.mutate()}
            disabled={!canSave}
          >
            {save.isPending ? "Saving..." : "Save voice"}
          </ActionButton>
        </div>
      )}
    </GlassCard>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function ScriptVoiceTab({ video, onAdvanced }: ScriptVoiceTabProps) {
  const queryClient = useQueryClient();
  const toast = useToast();

  // ---- Data fetching ----
  const { data: apiScenes, isLoading } = useQuery({
    queryKey: ["video-script", video.id],
    queryFn: () => getVideoScript(video.id),
    enabled: !!video.id,
  });

  const { data: apiAssets } = useQuery({
    queryKey: ["video-assets", video.id],
    queryFn: () => getVideoAssets(video.id),
    enabled: !!video.id,
  });

  const computed = useMemo(
    () => (apiScenes ? initFromApi(apiScenes, apiAssets || undefined) : []),
    [apiScenes, apiAssets],
  );

  // ---- Local state ----
  const [scenes, setScenes] = useState<SceneState[]>([]);
  const [collapsedActs, setCollapsedActs] = useState<Record<number, boolean>>({});
  const [expandedScenes, setExpandedScenes] = useState<Set<number>>(new Set());

  // Script actions
  const [approving, setApproving] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [regeneratingScript, setRegeneratingScript] = useState(false);
  const [deletingScene, setDeletingScene] = useState<number | null>(null);
  const [savingScene, setSavingScene] = useState<number | null>(null);
  const [savedScene, setSavedScene] = useState<number | null>(null);
  const [showRevisionModal, setShowRevisionModal] = useState(false);
  const [revisionNotes, setRevisionNotes] = useState("");
  const [revisionScope, setRevisionScope] = useState("Minor tweaks");
  const [approved, setApproved] = useState(false);

  // Voice actions
  const [generatingVoiceAll, setGeneratingVoiceAll] = useState(false);
  const [generatingVoiceScene, setGeneratingVoiceScene] = useState<number | null>(null);

  // Task polling (script generation)
  const [scriptTaskRunning, setScriptTaskRunning] = useState(false);
  const { message: scriptTaskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: scriptTaskRunning,
    interval: 3000,
    onComplete: async () => {
      setScriptTaskRunning(false);
      setRegeneratingScript(false);
      invalidateAll();
      // Auto-split sentences after script generation
      try {
        setSplitting(true);
        await runSplit(video.id);
        setSplitDone(true);
        invalidateAll();
      } catch {
        // Split failure is non-blocking — user can retry from sidebar
      } finally {
        setSplitting(false);
      }
    },
    onFailed: (error) => {
      setScriptTaskRunning(false);
      setRegeneratingScript(false);
      toast.error(`Script generation failed: ${error}`);
    },
  });

  // Task polling (voice generation)
  const [voiceTaskRunning, setVoiceTaskRunning] = useState(false);
  const { message: voiceTaskMessage } = useTaskPoller({
    videoId: video.id,
    enabled: voiceTaskRunning,
    interval: 3000,
    onComplete: () => {
      setVoiceTaskRunning(false);
      setGeneratingVoiceAll(false);
      setGeneratingVoiceScene(null);
      invalidateAll();
    },
    onFailed: (error) => {
      setVoiceTaskRunning(false);
      setGeneratingVoiceAll(false);
      setGeneratingVoiceScene(null);
      toast.error(`Voice generation failed: ${error}`);
    },
  });

  // Rehydrate after a page refresh: if the backend is still working on this
  // video, put the tab back into its generating state (spinner + disabled
  // buttons) instead of looking idle. This state used to live only in the
  // browser session that clicked the button, so a refresh went blind and
  // re-clicks bounced off the 409 guard with no explanation.
  useEffect(() => {
    let cancelled = false;
    getPipelineTaskStatus(video.id)
      .then((task) => {
        if (cancelled || !task || task.status !== "running") return;
        const msg = (task.message || "").toLowerCase();
        if (msg.includes("voic")) {
          setVoiceTaskRunning(true);
          setGeneratingVoiceAll(true);
        } else if (msg.includes("script")) {
          setScriptTaskRunning(true);
          setRegeneratingScript(true);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [video.id]);

  // Scene segment state (declared here so fetchAndExpandScene is available to the prompt poller below)
  const [loadingSegments, setLoadingSegments] = useState<Set<number>>(new Set());

  const fetchAndExpandScene = useCallback(async (sceneNum: number) => {
    setLoadingSegments((prev) => new Set(prev).add(sceneNum));
    try {
      const resp = await getSceneSegments(video.id, sceneNum);
      if (resp.segments && resp.segments.length > 0) {
        setScenes((prev) =>
          prev.map((s) => {
            if (s.sceneNumber !== sceneNum) return s;
            const newSentences: SentenceState[] = resp.segments.map((seg: Segment) => ({
              text: seg.sentence_text || "",
              sfxMode: "none" as const,
              sfxLibraryValue: "",
              sfxCustomPrompt: "",
              durationSeconds: seg.duration_seconds ?? null,
              cumulativeStart: seg.cumulative_start ?? null,
              imagePrompt: seg.image_prompt ?? null,
              imageIndex: seg.image_index ?? null,
            }));
            return { ...s, sentences: newSentences };
          }),
        );
      }
    } catch {
      // Fall back to existing local sentences
    } finally {
      setLoadingSegments((prev) => {
        const next = new Set(prev);
        next.delete(sceneNum);
        return next;
      });
    }
    setExpandedScenes((prev) => new Set(prev).add(sceneNum));
  }, [video.id]);

  // Sentence splitting
  const [splitDone, setSplitDone] = useState(false);
  const [splitting, setSplitting] = useState(false);

  const invalidateAll = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["video", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-script", video.id] });
    queryClient.invalidateQueries({ queryKey: ["video-assets", video.id] });
  }, [queryClient, video.id]);

  // ---- Google Drive script sync ----
  const { data: driveStatus, refetch: refetchDrive } = useQuery({
    queryKey: ["drive-script-status", video.id],
    queryFn: () => getDriveScriptStatus(video.id),
    enabled: !!video.id,
  });

  // Performance track: the dialogue-intelligence timeline (who speaks vs the
  // narrator). Before this card it existed only as 💬 badges on scene picture
  // cards — invisible until images existed, so creators couldn't tell the
  // hybrid voice was even wired (Ryan hit exactly that).
  const { data: dialogueMap } = useQuery({
    queryKey: ["dialogue-map", video.id],
    queryFn: () => getDialogueMap(video.id),
    enabled: !!video.id,
    staleTime: 30_000,
  });
  const performanceTrack = useMemo(() => {
    if (!dialogueMap) return null;
    const bySpeaker = new Map<
      string,
      { count: number; lines: Array<{ scene: number; index: number; text: string; voiced: boolean }> }
    >();
    let narration = 0;
    for (const sc of dialogueMap.scenes ?? []) {
      for (const seg of sc.segments ?? []) {
        if (seg.type === "dialogue" && seg.speaker) {
          const entry = bySpeaker.get(seg.speaker) ?? { count: 0, lines: [] };
          entry.count += 1;
          entry.lines.push({ scene: sc.scene, index: seg.index, text: seg.text || "", voiced: seg.voiced });
          bySpeaker.set(seg.speaker, entry);
        } else if (seg.type === "narration") {
          narration += 1;
        }
      }
    }
    return { mode: dialogueMap.dialogue_mode, bySpeaker: [...bySpeaker.entries()], narration };
  }, [dialogueMap]);

  // Per-line audition: tap a line on the Performance Track card to hear that
  // character's cast voice (the scene player only carries the narrator). The
  // segment MP3 streams via GET dialogue-audio/{scene}/{index} with the same
  // short-lived browser token the animatic uses.
  const lineAudioRef = useRef<HTMLAudioElement | null>(null);
  const [playingLine, setPlayingLine] = useState<string | null>(null);
  const playLine = useCallback(async (scene: number, index: number) => {
    const key = `${scene}:${index}`;
    const a = lineAudioRef.current;
    if (!a) return;
    if (playingLine === key) {
      a.pause();
      setPlayingLine(null);
      return;
    }
    try {
      const { token } = await getAudioToken(video.id);
      a.src = `${API_URL}/api/videos/${video.id}/dialogue-audio/${scene}/${index}?token=${token}`;
      await a.play();
      setPlayingLine(key);
    } catch {
      setPlayingLine(null);
      toast.error("Couldn't play that line — generate the voiceover first.");
    }
  }, [playingLine, video.id, toast]);
  const [driveMsg, setDriveMsg] = useState<string | null>(null);
  const [driveConflict, setDriveConflict] = useState(false);

  const pushDriveMutation = useMutation({
    mutationFn: () => pushScriptToDrive(video.id),
    onSuccess: (res) => {
      setDriveMsg(null);
      setDriveConflict(false);
      refetchDrive();
      if (res.doc_url) window.open(res.doc_url, "_blank", "noopener,noreferrer");
    },
    onError: (e: Error) => setDriveMsg(e.message),
  });

  const pullDriveMutation = useMutation({
    mutationFn: (force: boolean) => syncScriptFromDrive(video.id, force),
    onSuccess: (res) => {
      if (res.conflict) {
        setDriveConflict(true);
        setDriveMsg(res.message || "Both sides changed since the last sync.");
        return;
      }
      setDriveConflict(false);
      setDriveMsg(res.message || (res.changed ? "Synced from Drive." : "No new edits."));
      if (res.changed) invalidateAll();
      refetchDrive();
    },
    onError: (e: Error) => { setDriveConflict(false); setDriveMsg(e.message); },
  });

  // Sync API data into local state (once)
  useEffect(() => {
    if (computed.length > 0 && scenes.length === 0) {
      setScenes(computed);
    }
  }, [computed, scenes.length]);

  // Re-sync voice data when API data refreshes (voice URLs may have appeared)
  useEffect(() => {
    if (computed.length > 0 && scenes.length > 0) {
      setScenes((prev) =>
        prev.map((s) => {
          const fresh = computed.find((c) => c.sceneNumber === s.sceneNumber);
          if (!fresh) return s;
          return {
            ...s,
            voiceOverUrl: fresh.voiceOverUrl,
            voiceStatus: fresh.voiceStatus,
          };
        }),
      );
    }
  }, [computed]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Act grouping ----
  const actGroups = useMemo(
    () =>
      scenes.reduce(
        (acc, scene) => {
          if (!acc[scene.actNumber]) acc[scene.actNumber] = [];
          acc[scene.actNumber].push(scene);
          return acc;
        },
        {} as Record<number, SceneState[]>,
      ),
    [scenes],
  );

  // ---- Derived stats ----
  const totalScenes = scenes.length;
  const totalSentences = scenes.reduce((sum, s) => sum + s.sentences.length, 0);
  const wordCount = scenes.reduce(
    (sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length,
    0,
  );
  // A character-dialogue scene's voice lives in its per-segment performance
  // track, not a narrator MP3 — voice_over_url never exists for the pure
  // couple format, which left "Voice 0/1" stuck after every line was voiced.
  const dialogueVoicedScenes = useMemo(() => {
    const done = new Set<number>();
    if (dialogueMap?.dialogue_mode === "character_dialogue") {
      for (const sc of dialogueMap.scenes ?? []) {
        const segs = sc.segments ?? [];
        if (segs.length > 0 && segs.every((g) => g.voiced)) done.add(sc.scene);
      }
    }
    return done;
  }, [dialogueMap]);
  const sceneHasVoice = (s: { voiceOverUrl: string | null; sceneNumber: number }) =>
    !!s.voiceOverUrl || dialogueVoicedScenes.has(s.sceneNumber);
  const scenesWithVoice = scenes.filter(sceneHasVoice).length;
  const scenesWithScript = scenes.filter(
    (s) => !!s.narrationText.trim(),
  ).length;
  // Voice is OPTIONAL. When the creator turned AI voice-over off (skip_voice, or
  // no "voice" stage in the plan) it must not be required to finish this stage or
  // advance — otherwise a no-voice video is stuck behind a mandatory voice step.
  const voiceSkipped = !!video.skip_voice ||
    (Array.isArray(video.pipeline_stages) && !video.pipeline_stages.includes("voice"));
  const allReady = totalScenes > 0 && scenesWithScript === totalScenes &&
    (voiceSkipped || scenesWithVoice === totalScenes);

  // ---------------------------------------------------------------------------
  // Script handlers
  // ---------------------------------------------------------------------------

  const handleApprove = useCallback(async () => {
    if (!confirm("Approve script & voice and advance to next stage?")) return;
    setApproving(true);
    try {
      await advanceVideo(video.id);
      invalidateAll();
      setApproved(true);
    } catch (err) {
      toast.error(`Failed to approve: ${(err as Error).message}`);
      setApproving(false);
    }
  }, [video.id, invalidateAll]);

  const handleReject = useCallback(() => {
    setShowRevisionModal(true);
  }, []);

  const handleSubmitRevision = useCallback(async () => {
    setRejecting(true);
    try {
      const notes = `[${revisionScope}] ${revisionNotes}`;
      await updateVideo(video.id, { revision_notes: notes });
      await rejectVideo(video.id, notes);
      invalidateAll();
      setShowRevisionModal(false);
      setRevisionNotes("");
      setRevisionScope("Minor tweaks");
    } catch (err) {
      toast.error(`Failed to request revision: ${(err as Error).message}`);
    } finally {
      setRejecting(false);
    }
  }, [video.id, revisionScope, revisionNotes, invalidateAll]);

  const handleRegenerateScript = useCallback(async () => {
    setRegeneratingScript(true);
    try {
      await runPipelineStage(video.id, "script");
      setScriptTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "script");
          setScriptTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Failed to regenerate: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Failed to regenerate: ${message}`);
      }
      setRegeneratingScript(false);
    }
  }, [video.id]);

  const handleSplitSentences = useCallback(async () => {
    setSplitting(true);
    setSplitDone(false);
    try {
      await runSplit(video.id);
      setSplitDone(true);
      invalidateAll();
      setTimeout(() => setSplitDone(false), 3000);
      // Auto-expand all scenes to show the split results
      const sceneNums = scenes.map((s) => s.sceneNumber);
      await Promise.allSettled(sceneNums.map((n) => fetchAndExpandScene(n)));
    } catch (err) {
      toast.error(`Split failed: ${(err as Error).message}`);
    } finally {
      setSplitting(false);
    }
  }, [video.id, invalidateAll, scenes, fetchAndExpandScene]);

  const handleDeleteScene = useCallback(
    async (sceneNum: number) => {
      setDeletingScene(sceneNum);
      try {
        await updateSceneText(video.id, sceneNum, "");
        invalidateAll();
        setScenes((prev) => prev.filter((s) => s.sceneNumber !== sceneNum));
      } catch (err) {
        toast.error(`Failed to delete scene: ${(err as Error).message}`);
      } finally {
        setDeletingScene(null);
      }
    },
    [video.id, invalidateAll],
  );

  const handleNarrationBlur = useCallback(
    async (sceneNum: number, text: string) => {
      setSavingScene(sceneNum);
      try {
        await updateSceneText(video.id, sceneNum, text);
        setSavedScene(sceneNum);
        setTimeout(() => setSavedScene(null), 1500);
      } catch (err) {
        console.error(`Failed to save scene ${sceneNum}:`, err);
      } finally {
        setSavingScene(null);
      }
    },
    [video.id],
  );

  // ---------------------------------------------------------------------------
  // Voice handlers
  // ---------------------------------------------------------------------------

  const handleGenerateAllVoice = useCallback(async () => {
    setGeneratingVoiceAll(true);
    try {
      await runPipelineStage(video.id, "voice");
      setVoiceTaskRunning(true);
    } catch (err: unknown) {
      const message = (err as Error).message || "";
      if (message.includes("409")) {
        try {
          await clearStaleTask(video.id);
          await runPipelineStage(video.id, "voice");
          setVoiceTaskRunning(true);
          return;
        } catch (retryErr) {
          toast.error(`Voice generation failed: ${(retryErr as Error).message}`);
        }
      } else {
        toast.error(`Voice generation failed: ${message}`);
      }
      setGeneratingVoiceAll(false);
    }
  }, [video.id]);

  const handleGenerateSceneVoice = useCallback(
    async (sceneNum: number) => {
      setGeneratingVoiceScene(sceneNum);
      try {
        await runVoiceForScene(video.id, sceneNum);
        setVoiceTaskRunning(true);
      } catch (err: unknown) {
        const message = (err as Error).message || "";
        if (message.includes("409")) {
          try {
            await clearStaleTask(video.id);
            await runVoiceForScene(video.id, sceneNum);
            setVoiceTaskRunning(true);
            return;
          } catch (retryErr) {
            toast.error(`Voice generation failed: ${(retryErr as Error).message}`);
          }
        } else {
          toast.error(`Voice generation failed: ${message}`);
        }
        setGeneratingVoiceScene(null);
      }
    },
    [video.id],
  );

  // ---------------------------------------------------------------------------
  // Scene editing helpers
  // ---------------------------------------------------------------------------

  const toggleAct = (actNum: number) => {
    setCollapsedActs((prev) => ({ ...prev, [actNum]: !prev[actNum] }));
  };

  const toggleExpand = async (sceneNum: number) => {
    if (expandedScenes.has(sceneNum)) {
      setExpandedScenes((prev) => {
        const next = new Set(prev);
        next.delete(sceneNum);
        return next;
      });
      return;
    }
    await fetchAndExpandScene(sceneNum);
  };

  const updateNarration = (sceneNum: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = splitSentences(text).map((t, i) => ({
          ...(s.sentences[i] || { sfxMode: "none" as const, sfxLibraryValue: "", sfxCustomPrompt: "", durationSeconds: null, cumulativeStart: null, imagePrompt: null, imageIndex: null }),
          text: t,
        }));
        return { ...s, narrationText: text, displayText: stripStyleDirectives(text), sentences: newSentences };
      }),
    );
  };

  const updateSentence = (sceneNum: number, sentIdx: number, text: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) => (i === sentIdx ? { ...sent, text } : sent));
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const mergeSentenceUp = (sceneNum: number, sentIdx: number) => {
    if (sentIdx === 0) return;
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences[sentIdx - 1] = {
          ...newSentences[sentIdx - 1],
          text: newSentences[sentIdx - 1].text + " " + newSentences[sentIdx].text,
        };
        newSentences.splice(sentIdx, 1);
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const deleteSentence = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.filter((_, i) => i !== sentIdx);
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const addSentenceAfter = (sceneNum: number, sentIdx: number) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = [...s.sentences];
        newSentences.splice(sentIdx + 1, 0, {
          text: "",
          sfxMode: "none",
          sfxLibraryValue: "",
          sfxCustomPrompt: "",
          durationSeconds: null,
          cumulativeStart: null,
          imagePrompt: null,
          imageIndex: null,
        });
        const narrationText = newSentences.map((sent) => sent.text).join(" ");
        return { ...s, sentences: newSentences, narrationText, displayText: stripStyleDirectives(narrationText) };
      }),
    );
  };

  const updateSfxMode = (sceneNum: number, sentIdx: number, mode: SentenceState["sfxMode"]) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) => (i === sentIdx ? { ...sent, sfxMode: mode } : sent));
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const updateSfxLibrary = (sceneNum: number, sentIdx: number, value: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx
            ? { ...sent, sfxLibraryValue: value, sfxMode: (value ? "library" : "none") as SentenceState["sfxMode"] }
            : sent,
        );
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const updateSfxPrompt = (sceneNum: number, sentIdx: number, prompt: string) => {
    setScenes((prev) =>
      prev.map((s) => {
        if (s.sceneNumber !== sceneNum) return s;
        const newSentences = s.sentences.map((sent, i) =>
          i === sentIdx ? { ...sent, sfxCustomPrompt: prompt } : sent,
        );
        return { ...s, sentences: newSentences };
      }),
    );
  };

  const mergeSceneUp = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      if (idx <= 0) return prev;
      const merged = [...prev];
      const narrationText = merged[idx - 1].narrationText + " " + merged[idx].narrationText;
      merged[idx - 1] = {
        ...merged[idx - 1],
        narrationText,
        displayText: stripStyleDirectives(narrationText),
        sentences: [...merged[idx - 1].sentences, ...merged[idx].sentences],
      };
      merged.splice(idx, 1);
      return merged;
    });
  };

  const addSceneAfter = (sceneNum: number) => {
    setScenes((prev) => {
      const idx = prev.findIndex((s) => s.sceneNumber === sceneNum);
      const actNum = prev[idx]?.actNumber || 1;
      const newScene: SceneState = {
        id: `new-${Date.now()}`,
        sceneNumber: Math.max(...prev.map((s) => s.sceneNumber)) + 1,
        actNumber: actNum,
        narrationText: "",
        displayText: "",
        visualStyle: "dossier",
        composition: "medium",
        sources: [],
        imageGenerated: false,
        voiceOverUrl: null,
        voiceStatus: null,
        scriptStatus: null,
        tone: null,
        sentences: [{ text: "", sfxMode: "none", sfxLibraryValue: "", sfxCustomPrompt: "", durationSeconds: null, cumulativeStart: null, imagePrompt: null, imageIndex: null }],
      };
      const result = [...prev];
      result.splice(idx + 1, 0, newScene);
      return result;
    });
  };

  // ---- Advance stage ----
  // HOOKS MUST STAY ABOVE THE EARLY RETURNS: these lived after the loading /
  // empty-state returns, so the hook count changed once the script loaded and
  // React threw #310 ("rendered more hooks than during the previous render"),
  // crashing the whole pipeline page to the error boundary.
  const [advancing, setAdvancing] = useState(false);
  const handleAdvanceStage = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceVideo(video.id);
      invalidateAll();
      onAdvanced?.();
    } catch (err) {
      toast.error(`Advance failed: ${(err as Error).message}`);
    } finally {
      setAdvancing(false);
    }
  }, [video.id, invalidateAll, onAdvanced]);

  // ---------------------------------------------------------------------------
  // Loading state
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--orange)" }} />
        <span className="ml-3 text-sm" style={{ color: "var(--text-secondary)" }}>
          Loading script & voice...
        </span>
      </div>
    );
  }

  // ---------------------------------------------------------------------------
  // Empty state
  // ---------------------------------------------------------------------------

  if (!apiScenes || apiScenes.length === 0) {
    return (
      <GlassCard className="p-12 text-center">
        <Pencil size={32} className="mx-auto mb-3" style={{ color: "var(--text-tertiary)", opacity: 0.4 }} />
        <p className="text-lg font-display mb-2" style={{ color: "var(--text-secondary)" }}>
          Script Not Generated Yet
        </p>
        <p className="text-sm mb-6" style={{ color: "var(--text-tertiary)" }}>
          Research must be approved before script generation can begin. Current stage:{" "}
          <span style={{ color: "var(--turquoise)" }}>{(video.status || "").replace(/_/g, " ")}</span>
        </p>
        <button
          onClick={handleRegenerateScript}
          disabled={regeneratingScript || scriptTaskRunning}
          className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl text-base font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {regeneratingScript || scriptTaskRunning ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Pencil size={18} />
          )}
          {scriptTaskRunning
            ? scriptTaskMessage || "Generating Script..."
            : regeneratingScript
              ? "Starting..."
              : "Generate Script"}
        </button>
      </GlassCard>
    );
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  const isVoiceBusy = generatingVoiceAll || generatingVoiceScene !== null || voiceTaskRunning;

  // ---- Script pipeline stepper ----
  const scriptDone = scenesWithScript === totalScenes && totalScenes > 0;
  const voiceDone = voiceSkipped || (scenesWithVoice === totalScenes && totalScenes > 0);

  return (
    <div className="space-y-6 pb-24">
      {/* Top action bar */}
      <div className="rounded-xl px-4 py-3 mb-4" style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)" }}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-4 text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
            <span>Script {scenesWithScript}/{totalScenes}</span>
            <span>Voice {voiceSkipped ? "off" : `${scenesWithVoice}/${totalScenes}`}</span>
          </div>
          <button onClick={handleAdvanceStage} disabled={advancing}
            className="px-3 py-1.5 rounded-lg text-[10px] font-semibold inline-flex items-center gap-1 disabled:opacity-50 transition-all hover:brightness-110"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}>
            {advancing ? <Loader2 size={12} className="animate-spin" /> : null}
            Advance Stage <ChevronRight size={12} />
          </button>
        </div>
      </div>

      {/* Script System Prompt */}
      <SystemPromptEditor
        label="Script System Prompt"
        currentValue={video.script_system_prompt}
        onSave={async (text) => {
          await updateVideo(video.id, { script_system_prompt: text || null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
        }}
        onReset={async () => {
          const res = await getDefaultScriptPrompt();
          await updateVideo(video.id, { script_system_prompt: null });
          queryClient.invalidateQueries({ queryKey: ["video", video.id] });
          return res.prompt;
        }}
      />

      {/* Script Pipeline Steps */}
      <div
        className="rounded-xl p-4"
        style={{ background: "rgba(255, 120, 73, 0.04)", border: "1px solid rgba(255, 120, 73, 0.12)" }}
      >
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[10px] uppercase tracking-wider font-semibold" style={{ color: "var(--orange)" }}>
            Script Pipeline
          </span>
        </div>
        <div className="flex items-center gap-0">
          {[
            { label: "Generate Script", done: scriptDone, count: `${scenesWithScript}/${totalScenes}` },
            { label: voiceSkipped ? "Voice (off)" : "Generate Voice", done: voiceDone, count: voiceSkipped ? "Skipped" : `${scenesWithVoice}/${totalScenes}` },
            { label: "Approve", done: approved, count: approved ? "Done" : "Pending" },
          ].map((step, i, arr) => {
            const isNext = !step.done && (i === 0 || arr[i - 1].done);
            return (
              <div key={step.label} className="flex items-center gap-0 flex-1">
                <div className="flex flex-col items-center flex-1">
                  <div
                    className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold mb-1"
                    style={{
                      background: step.done ? "var(--green)" : isNext ? "var(--orange)" : "rgba(255,255,255,0.06)",
                      color: step.done || isNext ? "var(--bg-void)" : "var(--text-tertiary)",
                      border: isNext ? "2px solid var(--orange)" : "none",
                    }}
                  >
                    {step.done ? "✓" : i + 1}
                  </div>
                  <span className="text-[9px] font-medium" style={{ color: step.done ? "var(--green)" : isNext ? "var(--orange)" : "var(--text-tertiary)" }}>
                    {step.label}
                  </span>
                  <span className="text-[8px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                    {step.count}
                  </span>
                </div>
                {i < arr.length - 1 && (
                  <div className="w-8 h-px mx-1" style={{ background: step.done ? "var(--green)" : "rgba(255,255,255,0.1)" }} />
                )}
              </div>
            );
          })}
        </div>
        {/* Next action CTA */}
        {(() => {
          if (!scriptDone) return (
            <button
              onClick={handleRegenerateScript}
              disabled={regeneratingScript || scriptTaskRunning}
              className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}
            >
              {(regeneratingScript || scriptTaskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
              {scriptTaskRunning ? scriptTaskMessage || "Generating..." : "Step 1: Generate Script"}
            </button>
          );
          if (!voiceDone) return (
            <button
              onClick={handleGenerateAllVoice}
              disabled={isVoiceBusy}
              className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
              style={{ background: "var(--orange)", color: "var(--bg-void)" }}
            >
              {isVoiceBusy ? <Loader2 size={14} className="animate-spin" /> : <Mic size={14} />}
              {voiceTaskRunning ? voiceTaskMessage || "Generating..." : "Step 2: Generate Voice"}
            </button>
          );
          if (!approved) return (
            <>
              <button
                onClick={handleApprove}
                disabled={approving || !allReady}
                className="mt-3 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-xs font-semibold transition-all disabled:opacity-50"
                style={{ background: "var(--green)", color: "var(--bg-void)" }}
              >
                {approving ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle size={14} />}
                Step 3: Approve Script & Voice
              </button>
              {/* Go back and rewrite the script (e.g. after changing the style or scene rules). */}
              <button
                onClick={handleRegenerateScript}
                disabled={regeneratingScript || scriptTaskRunning}
                className="mt-2 w-full inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-xs font-medium transition-all disabled:opacity-50"
                style={{ background: "transparent", border: "1px solid var(--orange)", color: "var(--orange)" }}
              >
                {(regeneratingScript || scriptTaskRunning) ? <Loader2 size={14} className="animate-spin" /> : <Pencil size={14} />}
                {scriptTaskRunning ? scriptTaskMessage || "Regenerating…" : "Regenerate script"}
              </button>
            </>
          );
          return (
            <p className="mt-3 text-[10px] text-center" style={{ color: "var(--green)" }}>
              ✓ Script pipeline complete
            </p>
          );
        })()}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
        {/* ============================================================= */}
        {/* Main content area                                              */}
        {/* ============================================================= */}
        <div className="space-y-4">
          {Object.entries(actGroups).map(([actNum, actScenes]) => {
            const isCollapsed = collapsedActs[Number(actNum)];
            const actWordCount = actScenes.reduce(
              (sum, s) => sum + s.narrationText.split(/\s+/).filter(Boolean).length,
              0,
            );

            return (
              <div key={actNum}>
                {/* Act header */}
                <button
                  onClick={() => toggleAct(Number(actNum))}
                  className="flex items-center gap-3 w-full mb-3 group"
                >
                  <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                  <div
                    className="flex items-center gap-2 px-3 py-1 rounded-full transition-all"
                    style={{ background: isCollapsed ? "rgba(255, 120, 73, 0.1)" : "transparent" }}
                  >
                    {isCollapsed ? (
                      <ChevronRight size={14} style={{ color: "var(--orange)" }} />
                    ) : (
                      <ChevronDown size={14} style={{ color: "var(--orange)" }} />
                    )}
                    <span
                      className="text-xs font-semibold uppercase tracking-wider"
                      style={{ color: "var(--orange)" }}
                    >
                      Act {actNum}
                    </span>
                    <span className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                      {actScenes.length} scenes &middot; {actWordCount} words
                    </span>
                  </div>
                  <div className="flex-1 h-px" style={{ background: "var(--orange)", opacity: 0.3 }} />
                </button>

                {!isCollapsed && (
                  <div className="space-y-3">
                    {actScenes.map((scene) => {
                      const isExpanded = expandedScenes.has(scene.sceneNumber);
                      const hasVoice = sceneHasVoice(scene);
                      const isPlayingThis = false;
                      const isGeneratingThisVoice = generatingVoiceScene === scene.sceneNumber;

                      return (
                        <GlassCard
                          key={scene.sceneNumber}
                          className="p-4"
                          style={{
                            borderLeftWidth: 3,
                            borderLeftColor: hasVoice
                              ? "var(--green)"
                              : scene.imageGenerated
                                ? "var(--turquoise)"
                                : "var(--orange)",
                          }}
                        >
                          {/* ---- Scene header ---- */}
                          <div className="flex items-center gap-2 mb-2">
                            <SegmentBadge
                              label={`S-${String(scene.sceneNumber).padStart(2, "0")}`}
                              color={scene.imageGenerated ? undefined : "var(--orange)"}
                            />

                            {/* Status badges */}
                            <ScriptStatusBadge status={scene.scriptStatus} />
                            <VoiceStatusBadge status={scene.voiceStatus} />

                            <div className="flex-1" />

                            {/* Tone badge */}
                            {scene.tone && (
                              <span
                                className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                                style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-tertiary)" }}
                              >
                                {scene.tone}
                              </span>
                            )}

                            {/* Expand/collapse toggle */}
                            <button
                              onClick={() => toggleExpand(scene.sceneNumber)}
                              disabled={loadingSegments.has(scene.sceneNumber)}
                              title={isExpanded ? "Collapse to unified text" : "Expand into timed sentence segments"}
                              className="flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-medium transition-all"
                              style={{
                                background: isExpanded ? "var(--turquoise-dim)" : "transparent",
                                color: isExpanded ? "var(--turquoise)" : "var(--text-tertiary)",
                                border: `1px solid ${isExpanded ? "var(--turquoise-dim)" : "transparent"}`,
                              }}
                            >
                              {loadingSegments.has(scene.sceneNumber) ? (
                                <Loader2 size={11} className="animate-spin" />
                              ) : (
                                <Layers size={11} />
                              )}
                              {isExpanded ? "Collapse" : "Expand"}
                              <span className="font-mono">{scene.sentences.length}</span>
                            </button>

                            <button
                              onClick={() => mergeSceneUp(scene.sceneNumber)}
                              title="Merge into scene above"
                              className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                              style={{ color: "var(--text-tertiary)" }}
                            >
                              <Merge size={12} />
                            </button>
                            <button
                              onClick={() => addSceneAfter(scene.sceneNumber)}
                              title="Add scene below"
                              className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                              style={{ color: "var(--text-tertiary)" }}
                            >
                              <Plus size={12} />
                            </button>
                            <button
                              onClick={() => handleDeleteScene(scene.sceneNumber)}
                              disabled={deletingScene === scene.sceneNumber}
                              title="Delete scene"
                              className="p-1 rounded transition-colors hover:bg-[var(--bg-surface)]"
                              style={{ color: "var(--text-tertiary)" }}
                              onMouseEnter={(e) => {
                                e.currentTarget.style.color = "var(--orange)";
                              }}
                              onMouseLeave={(e) => {
                                e.currentTarget.style.color = "var(--text-tertiary)";
                              }}
                            >
                              {deletingScene === scene.sceneNumber ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <Trash2 size={12} />
                              )}
                            </button>
                          </div>

                          {/* ---- COLLAPSED: Unified text view ---- */}
                          {!isExpanded && (
                            <div className="relative">
                              <textarea
                                value={scene.displayText}
                                onChange={(e) => updateNarration(scene.sceneNumber, e.target.value)}
                                rows={Math.max(2, Math.ceil(scene.displayText.length / 100))}
                                className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-3 py-2 transition-all"
                                style={{
                                  color: "var(--text-primary)",
                                  background: "transparent",
                                  border: "1px solid transparent",
                                }}
                                onFocus={(e) => {
                                  e.target.style.background = "var(--bg-elevated)";
                                  e.target.style.borderColor = "var(--orange)";
                                }}
                                onBlur={(e) => {
                                  e.target.style.background = "transparent";
                                  e.target.style.borderColor = "transparent";
                                  handleNarrationBlur(scene.sceneNumber, scene.narrationText);
                                }}
                              />
                              {savingScene === scene.sceneNumber && (
                                <Loader2
                                  size={12}
                                  className="animate-spin absolute top-2 right-2"
                                  style={{ color: "var(--turquoise)" }}
                                />
                              )}
                              {savedScene === scene.sceneNumber && (
                                <span
                                  className="absolute top-2 right-2 text-[10px] font-medium"
                                  style={{ color: "var(--green)" }}
                                >
                                  Saved
                                </span>
                              )}
                            </div>
                          )}

                          {/* ---- EXPANDED: Individual sentence cards ---- */}
                          <AnimatePresence>
                            {isExpanded && (
                              <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: "auto" }}
                                exit={{ opacity: 0, height: 0 }}
                                transition={{ duration: 0.3 }}
                                className="space-y-2"
                              >
                                {scene.sentences.map((sent, sentIdx) => (
                                  <div
                                    key={sentIdx}
                                    className="rounded-xl p-3 transition-all"
                                    style={{
                                      background: "rgba(255,255,255,0.02)",
                                      border: "1px solid rgba(255,255,255,0.05)",
                                    }}
                                  >
                                    <div className="flex items-center gap-2 mb-1.5">
                                      <span
                                        className="text-[9px] font-mono font-medium px-1.5 py-0.5 rounded"
                                        style={{ background: "var(--orange-dim)", color: "var(--orange)" }}
                                      >
                                        {sentIdx + 1}/{scene.sentences.length}
                                      </span>
                                      {sent.durationSeconds != null && (
                                        <span
                                          className="text-[9px] font-mono px-1.5 py-0.5 rounded"
                                          style={{ background: "rgba(0, 188, 212, 0.1)", color: "var(--turquoise)" }}
                                          title={sent.cumulativeStart != null ? `Starts at ${sent.cumulativeStart.toFixed(1)}s` : undefined}
                                        >
                                          {sent.durationSeconds.toFixed(1)}s
                                        </span>
                                      )}
                                      {sent.cumulativeStart != null && (
                                        <span
                                          className="text-[8px] font-mono"
                                          style={{ color: "var(--text-tertiary)" }}
                                        >
                                          @{sent.cumulativeStart.toFixed(1)}s
                                        </span>
                                      )}
                                      <div className="flex-1" />
                                      <button
                                        onClick={() => mergeSentenceUp(scene.sceneNumber, sentIdx)}
                                        title="Merge up"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Merge size={10} />
                                      </button>
                                      <button
                                        onClick={() => addSentenceAfter(scene.sceneNumber, sentIdx)}
                                        title="Add below"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Plus size={10} />
                                      </button>
                                      <button
                                        onClick={() => deleteSentence(scene.sceneNumber, sentIdx)}
                                        title="Delete"
                                        className="p-0.5 rounded hover:bg-[var(--bg-surface)]"
                                        style={{ color: "var(--text-tertiary)" }}
                                      >
                                        <Trash2 size={10} />
                                      </button>
                                    </div>

                                    <textarea
                                      value={sent.text}
                                      onChange={(e) => updateSentence(scene.sceneNumber, sentIdx, e.target.value)}
                                      rows={Math.max(1, Math.ceil(sent.text.length / 90))}
                                      className="w-full text-sm leading-relaxed resize-none outline-none rounded-lg px-2 py-1 transition-all"
                                      style={{
                                        color: "var(--text-primary)",
                                        background: "transparent",
                                        border: "1px solid transparent",
                                      }}
                                      onFocus={(e) => {
                                        e.target.style.background = "var(--bg-elevated)";
                                        e.target.style.borderColor = "var(--turquoise)";
                                      }}
                                      onBlur={(e) => {
                                        e.target.style.background = "transparent";
                                        e.target.style.borderColor = "transparent";
                                      }}
                                    />

                                    {/* SFX per sentence */}
                                    <div className="flex items-center gap-2 mt-2 flex-wrap">
                                      <Volume2 size={10} style={{ color: "var(--gold)", opacity: 0.5 }} />
                                      {(["none", "library", "elevenlabs", "custom"] as const).map((mode) => {
                                        const labels = {
                                          none: "None",
                                          library: "Library",
                                          elevenlabs: "ElevenLabs",
                                          custom: "AI Prompt",
                                        };
                                        const icons = {
                                          none: null,
                                          library: <Library size={9} />,
                                          elevenlabs: <Mic size={9} />,
                                          custom: <Wand2 size={9} />,
                                        };
                                        const colors = {
                                          none: "var(--text-tertiary)",
                                          library: "var(--gold)",
                                          elevenlabs: "var(--green)",
                                          custom: "var(--purple)",
                                        };
                                        const isActive = sent.sfxMode === mode;
                                        return (
                                          <button
                                            key={mode}
                                            onClick={() => updateSfxMode(scene.sceneNumber, sentIdx, mode)}
                                            className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[9px] font-medium transition-all"
                                            style={{
                                              background: isActive ? `${colors[mode]}15` : "transparent",
                                              color: isActive ? colors[mode] : "var(--text-tertiary)",
                                              border: `1px solid ${isActive ? `${colors[mode]}30` : "transparent"}`,
                                            }}
                                          >
                                            {icons[mode]}
                                            {labels[mode]}
                                          </button>
                                        );
                                      })}
                                    </div>

                                    {sent.sfxMode === "library" && (
                                      <div className="flex items-center gap-2 mt-1.5">
                                        <select
                                          value={sent.sfxLibraryValue}
                                          onChange={(e) =>
                                            updateSfxLibrary(scene.sceneNumber, sentIdx, e.target.value)
                                          }
                                          className="text-[10px] font-mono px-2 py-1 rounded-lg outline-none flex-1"
                                          style={{
                                            background: "var(--bg-elevated)",
                                            color: "var(--text-secondary)",
                                            border: "1px solid var(--border-subtle)",
                                          }}
                                        >
                                          <option value="">Select sound...</option>
                                          {SFX_LIBRARY.map((sfx) => (
                                            <option key={sfx.value} value={sfx.value}>
                                              {sfx.label}
                                            </option>
                                          ))}
                                        </select>
                                        {sent.sfxLibraryValue && (
                                          <button
                                            className="w-5 h-5 rounded-full flex items-center justify-center"
                                            style={{ background: "var(--green)", color: "var(--bg-void)" }}
                                          >
                                            <Play size={8} className="ml-px" />
                                          </button>
                                        )}
                                      </div>
                                    )}

                                    {sent.sfxMode === "elevenlabs" && (
                                      <div className="mt-1.5 flex items-start gap-2">
                                        <Mic size={11} style={{ color: "var(--green)", marginTop: 5 }} />
                                        <div className="flex-1">
                                          <textarea
                                            value={sent.sfxCustomPrompt}
                                            onChange={(e) =>
                                              updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)
                                            }
                                            placeholder="Describe the sound for ElevenLabs to generate..."
                                            rows={2}
                                            className="w-full text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                            style={{
                                              color: "var(--text-secondary)",
                                              background: "var(--bg-elevated)",
                                              border: "1px solid rgba(0, 230, 138, 0.15)",
                                            }}
                                            onFocus={(e) => {
                                              e.target.style.borderColor = "var(--green)";
                                            }}
                                            onBlur={(e) => {
                                              e.target.style.borderColor = "rgba(0, 230, 138, 0.15)";
                                            }}
                                          />
                                          <div className="flex items-center gap-2 mt-1">
                                            <button
                                              className="text-[9px] font-medium px-2 py-0.5 rounded-lg"
                                              style={{ background: "var(--green)", color: "var(--bg-void)" }}
                                            >
                                              Generate SFX
                                            </button>
                                            <span
                                              className="text-[9px] font-mono"
                                              style={{ color: "var(--text-tertiary)" }}
                                            >
                                              ~$0.03
                                            </span>
                                          </div>
                                        </div>
                                      </div>
                                    )}

                                    {sent.sfxMode === "custom" && (
                                      <div className="mt-1.5 flex items-start gap-2">
                                        <Wand2 size={11} style={{ color: "var(--purple)", marginTop: 5 }} />
                                        <textarea
                                          value={sent.sfxCustomPrompt}
                                          onChange={(e) =>
                                            updateSfxPrompt(scene.sceneNumber, sentIdx, e.target.value)
                                          }
                                          placeholder="Describe the SFX for AI generation..."
                                          rows={2}
                                          className="flex-1 text-[10px] font-mono outline-none rounded-lg px-2 py-1.5 resize-none transition-all"
                                          style={{
                                            color: "var(--text-secondary)",
                                            background: "var(--bg-elevated)",
                                            border: "1px solid var(--purple-dim)",
                                          }}
                                          onFocus={(e) => {
                                            e.target.style.borderColor = "var(--purple)";
                                          }}
                                          onBlur={(e) => {
                                            e.target.style.borderColor = "var(--purple-dim)";
                                          }}
                                        />
                                      </div>
                                    )}

                                  </div>
                                ))}
                              </motion.div>
                            )}
                          </AnimatePresence>

                          {/* ---- Voice status (generation controls only, playback moved to Storyboard tab) ---- */}
                          <div
                            className="mt-3 pt-3 flex items-center gap-3 flex-wrap"
                            style={{ borderTop: "1px solid rgba(255,255,255,0.06)" }}
                          >
                            <span
                              className="text-[10px] font-mono px-2 py-0.5 rounded-full"
                              style={{
                                color: hasVoice ? "var(--green)" : "var(--text-tertiary)",
                                background: hasVoice ? "rgba(0, 200, 83, 0.08)" : "rgba(255,255,255,0.04)",
                                border: `1px solid ${hasVoice ? "rgba(0, 200, 83, 0.2)" : "rgba(255,255,255,0.06)"}`,
                              }}
                            >
                              {hasVoice ? "Voice Ready" : "No Voice"}
                            </span>
                            <span
                              className="text-[10px] font-mono shrink-0"
                              style={{ color: "var(--text-tertiary)" }}
                            >
                              {Math.round((scene.narrationText.split(/\s+/).filter(Boolean).length || 0) / 2.5)}s
                            </span>
                            <button
                              onClick={() => handleGenerateSceneVoice(scene.sceneNumber)}
                              disabled={isVoiceBusy}
                              className="text-[10px] font-medium px-2 py-1 rounded-lg transition-all hover:brightness-110 disabled:opacity-40"
                              style={{
                                border: hasVoice ? "1px solid var(--turquoise)" : "none",
                                color: hasVoice ? "var(--turquoise)" : "var(--bg-void)",
                                background: hasVoice ? "transparent" : "var(--turquoise)",
                              }}
                            >
                              {isGeneratingThisVoice || (voiceTaskRunning && generatingVoiceScene === scene.sceneNumber)
                                ? (voiceTaskMessage || "Generating...")
                                : hasVoice ? "Regenerate Voice" : "Generate Voice"}
                            </button>
                          </div>

                          {/* Segment Editor — save segment text edits to backend */}
                          {isExpanded && <SegmentEditor videoId={video.id} sceneNumber={scene.sceneNumber} />}

                          {/* Sources + metadata */}
                          <div className="flex items-center gap-2 mt-2 flex-wrap">
                            {scene.sources?.map((src, srcIdx) => (
                              <span
                                key={srcIdx}
                                className="text-[10px] font-mono px-2 py-0.5 rounded"
                                style={{ background: "var(--yellow-dim)", color: "var(--yellow)" }}
                              >
                                [{src}]
                              </span>
                            ))}
                            {/* Visual style/composition hidden — internal pipeline metadata */}
                          </div>
                        </GlassCard>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* ============================================================= */}
        {/* Sidebar                                                        */}
        {/* ============================================================= */}
        <div className="space-y-4">
          {/* Script details */}
          <GlassCard className="p-5">
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-secondary)" }}
            >
              Script &amp; Voice Details
            </h3>
            <div className="space-y-3">
              {[
                { label: "Framework", value: video.framework || video.framework_angle || "--" },
                { label: "Word Count", value: String(wordCount) },
                { label: "Scenes", value: String(totalScenes) },
                { label: "Sentences", value: String(totalSentences) },
                { label: "Target Length", value: `${video.videoLengthMin || video.video_length_minutes || 0} min` },
                { label: "Est. Cost", value: `$${(video.estimatedCost || video.total_cost || 0).toFixed(2)}` },
              ].map((row) => (
                <div key={row.label} className="flex items-center justify-between">
                  <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                    {row.label}
                  </span>
                  <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                    {row.value}
                  </span>
                </div>
              ))}
            </div>
          </GlassCard>

          {/* Performance track: narrator vs character lines (dialogue intelligence) */}
          {performanceTrack?.mode && (
            <GlassCard className="p-5">
              <h3 className="text-xs font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-secondary)" }}>
                Performance Track
              </h3>
              {performanceTrack.mode === "character_dialogue" ? (
                <div className="space-y-2">
                  <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                    Character dialogue detected. Each character performs their lines in their
                    own cast voice; the narrator carries everything else. Tap a line to hear it.
                  </p>
                  {performanceTrack.bySpeaker.map(([speaker, info]) => (
                    <div key={speaker}>
                      <div className="flex items-center justify-between">
                        <span className="text-xs" style={{ color: "var(--text-secondary)" }}>💬 {speaker}</span>
                        <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                          {info.count} line{info.count === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="mt-1 space-y-1">
                        {info.lines.map((l) => {
                          const key = `${l.scene}:${l.index}`;
                          return (
                            <div key={key} className="flex items-center gap-2">
                              <button
                                onClick={() => playLine(l.scene, l.index)}
                                disabled={!l.voiced}
                                title={l.voiced ? "Play this line" : "Not voiced yet — create the voiceover first"}
                                className="w-5 h-5 rounded-full flex items-center justify-center shrink-0"
                                style={{
                                  background: l.voiced ? "var(--turquoise)" : "rgba(255,255,255,0.08)",
                                  color: "var(--bg-void)",
                                  opacity: l.voiced ? 1 : 0.4,
                                  cursor: l.voiced ? "pointer" : "not-allowed",
                                }}
                              >
                                {playingLine === key ? <Square size={8} /> : <Play size={8} className="ml-px" />}
                              </button>
                              <span
                                className="text-[11px] truncate"
                                title={l.text}
                                style={{ color: l.voiced ? "var(--text-secondary)" : "var(--text-tertiary)" }}
                              >
                                S{l.scene} · {l.text}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                  <div className="flex items-center justify-between">
                    <span className="text-xs" style={{ color: "var(--text-secondary)" }}>🎙 Narrator</span>
                    <span className="text-sm font-mono font-medium" style={{ color: "var(--text-primary)" }}>
                      {performanceTrack.narration} segment{performanceTrack.narration === 1 ? "" : "s"}
                    </span>
                  </div>
                  <audio ref={lineAudioRef} onEnded={() => setPlayingLine(null)} className="hidden" />
                </div>
              ) : (
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  Narration only — one narrator voice reads the whole script.
                </p>
              )}
            </GlassCard>
          )}

          {/* Google Drive script sync */}
          <GlassCard className="p-5">
            <div className="flex items-center gap-2 mb-3">
              <Cloud size={14} style={{ color: "var(--turquoise)" }} />
              <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Google Drive</h3>
              {driveStatus?.drive_newer && (
                <span className="ml-auto text-[9px] font-medium px-1.5 py-0.5 rounded-full"
                  style={{ background: "rgba(255,186,8,0.14)", color: "var(--gold)" }}>
                  Drive edited
                </span>
              )}
            </div>

            {driveStatus && !driveStatus.connected ? (
              <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                Connect Google Drive in{" "}
                <a href="/settings" className="underline" style={{ color: "var(--turquoise)" }}>Settings</a>
                {" "}to edit this script as a Google Doc — in any AI tool — and sync edits back.
              </p>
            ) : (
              <div className="space-y-2">
                <p className="text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                  Edit your script as a Google Doc in your own Drive, then sync changes back here.
                </p>

                <button
                  onClick={() => pushDriveMutation.mutate()}
                  disabled={pushDriveMutation.isPending}
                  className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
                  style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                >
                  {pushDriveMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <CloudUpload size={13} />}
                  {driveStatus?.doc_id ? "Update Doc in Drive" : "Edit in Google Drive"}
                </button>

                {driveStatus?.doc_id && (
                  <>
                    <a
                      href={driveStatus.doc_url || "#"}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-medium transition-all hover:bg-[var(--bg-surface)]"
                      style={{ color: "var(--turquoise)", border: "1px solid var(--turquoise-dim)" }}
                    >
                      <ExternalLink size={12} /> Open Doc
                    </a>
                    <button
                      onClick={() => pullDriveMutation.mutate(false)}
                      disabled={pullDriveMutation.isPending}
                      className="inline-flex items-center justify-center gap-2 w-full px-4 py-2 rounded-lg text-[12px] font-semibold transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50"
                      style={{
                        background: driveStatus?.drive_newer ? "var(--gold)" : "rgba(255,255,255,0.05)",
                        color: driveStatus?.drive_newer ? "var(--bg-void)" : "var(--text-secondary)",
                        border: "1px solid var(--border-subtle)",
                      }}
                    >
                      {pullDriveMutation.isPending ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
                      Sync from Drive
                    </button>
                  </>
                )}

                {driveStatus?.synced_at && (
                  <p className="text-[10px] font-mono" style={{ color: "var(--text-tertiary)" }}>
                    Last sync: {new Date(driveStatus.synced_at).toLocaleString()}
                  </p>
                )}

                {driveMsg && (
                  <div className="text-[11px] leading-relaxed rounded-lg px-2.5 py-2"
                    style={{
                      background: driveConflict ? "rgba(255,120,73,0.1)" : "rgba(255,255,255,0.04)",
                      color: driveConflict ? "var(--orange)" : "var(--text-secondary)",
                    }}>
                    {driveMsg}
                    {driveConflict && (
                      <button
                        onClick={() => pullDriveMutation.mutate(true)}
                        disabled={pullDriveMutation.isPending}
                        className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold disabled:opacity-50"
                        style={{ background: "var(--orange)", color: "var(--bg-void)" }}
                      >
                        {pullDriveMutation.isPending ? <Loader2 size={11} className="animate-spin" /> : null}
                        Sync anyway (Drive wins)
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </GlassCard>

          {/* Script Validation */}
          {(() => {
            if (!video.script_validation) return null;
            let validation: { passed?: boolean; checks?: { name: string; passed: boolean; detail: string; advisory?: boolean }[] } | null = null;
            try {
              validation = typeof video.script_validation === "string" ? JSON.parse(video.script_validation) : video.script_validation;
            } catch { return null; }
            if (!validation?.checks) return null;
            const passCount = validation.checks.filter((c) => c.passed).length;
            const total = validation.checks.length;
            return (
              <GlassCard className="p-5">
                <div className="flex items-center gap-2 mb-3">
                  <ShieldCheck size={14} style={{ color: validation.passed ? "var(--green)" : "var(--red)" }} />
                  <h3 className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-secondary)" }}>Script Validation</h3>
                  <span className="ml-auto text-[10px] font-mono" style={{ color: validation.passed ? "var(--green)" : "var(--red)" }}>
                    {passCount}/{total}
                  </span>
                </div>
                <div className="space-y-1.5">
                  {validation.checks.map((check) => {
                    const color = check.passed ? "var(--green)" : check.advisory ? "var(--gold)" : "var(--red)";
                    const label = check.passed ? "PASS" : check.advisory ? "WARN" : "FAIL";
                    return (
                      <div key={check.name} className="flex items-start gap-2">
                        <span className="text-[9px] font-mono font-semibold px-1.5 py-0.5 rounded shrink-0 mt-0.5"
                          style={{ background: `${color}20`, color }}>{label}</span>
                        <div className="min-w-0">
                          <span className="text-[11px] font-medium block" style={{ color: "var(--text-primary)" }}>
                            {check.name.replace(/_/g, " ")}
                          </span>
                          <span className="text-[10px] block truncate" style={{ color: "var(--text-tertiary)" }} title={check.detail}>
                            {check.detail}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </GlassCard>
            );
          })()}

          {/* Voice progress */}
          <GlassCard className="p-5">
            <div className="space-y-4">
              <div>
                <p className="text-[10px] uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                  Voice Progress
                </p>
                <div className="flex items-center gap-3">
                  <p className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
                    {scenesWithVoice}/{totalScenes}
                  </p>
                  <ProgressRing
                    value={totalScenes > 0 ? (scenesWithVoice / totalScenes) * 100 : 0}
                    size={50}
                    color="var(--green)"
                    strokeWidth={4}
                  />
                </div>
                <p className="text-[10px] font-mono mt-1" style={{ color: "var(--text-tertiary)" }}>
                  {totalScenes > 0 ? Math.round((scenesWithVoice / totalScenes) * 100) : 0}% voiced
                </p>
              </div>
            </div>
          </GlassCard>

          {/* Custom voice (ElevenLabs) — paste your own voice ID */}
          <CustomVoiceCard />

          {/* Action buttons */}
          <div className="space-y-2">
            {/* Generate All Voice */}
            <ActionButton
              variant="outline"
              icon={isVoiceBusy ? Loader2 : Mic}
              className="w-full"
              onClick={handleGenerateAllVoice}
              disabled={isVoiceBusy || scenesWithVoice === totalScenes}
            >
              {voiceTaskRunning && generatingVoiceAll
                ? voiceTaskMessage || "Generating Voice..."
                : generatingVoiceAll
                  ? "Starting..."
                  : scenesWithVoice === totalScenes
                    ? "All Voiced"
                    : "Generate All Voice"}
            </ActionButton>

            {/* Regenerate Script */}
            <button
              onClick={handleRegenerateScript}
              disabled={regeneratingScript || scriptTaskRunning}
              className="inline-flex items-center justify-center gap-2 w-full px-5 py-2.5 rounded-xl text-sm font-semibold font-body transition-all hover:brightness-110 active:scale-[0.98] disabled:opacity-50 disabled:cursor-not-allowed"
              style={{
                background: "rgba(255, 120, 73, 0.15)",
                color: "var(--orange)",
                border: "1px solid var(--orange)",
              }}
            >
              {regeneratingScript || scriptTaskRunning ? (
                <>
                  <Loader2 size={14} className="animate-spin" />{" "}
                  {scriptTaskRunning ? scriptTaskMessage || "Generating..." : "Starting..."}
                </>
              ) : (
                "Regenerate Script"
              )}
            </button>

            {/* Divider */}
            <div className="pt-2" style={{ borderTop: "1px solid var(--border-subtle)" }} />

            {/* Approve / Reject / Approved */}
            {approved ? (
              <div
                className="flex items-center justify-center gap-2 w-full px-5 py-2.5 rounded-xl text-sm font-semibold"
                style={{ color: "var(--green)" }}
              >
                <CheckCircle size={14} /> Script &amp; Voice Approved
              </div>
            ) : (
              <>
                <ActionButton
                  variant="filled"
                  className="w-full"
                  onClick={handleApprove}
                  disabled={approving || !allReady}
                >
                  {approving ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Advancing...
                    </>
                  ) : (
                    "Approve Script & Voice"
                  )}
                </ActionButton>
                {!allReady && (
                  <p className="text-[10px] text-center" style={{ color: "var(--text-tertiary)" }}>
                    All scenes need script text and voice audio before approval.
                  </p>
                )}
                <ActionButton variant="outline" className="w-full" onClick={handleReject} disabled={rejecting}>
                  {rejecting ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Requesting...
                    </>
                  ) : (
                    "Request Revision"
                  )}
                </ActionButton>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Audio playback moved to Storyboard & Visuals tab */}

      {/* ============================================================= */}
      {/* Revision Modal                                                  */}
      {/* ============================================================= */}
      {showRevisionModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setShowRevisionModal(false)}
        >
          <div
            className="w-full max-w-md rounded-xl p-6 space-y-4"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-base font-semibold" style={{ color: "var(--text-primary)" }}>
              Request Revision
            </h3>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                Revision Scope
              </label>
              <select
                value={revisionScope}
                onChange={(e) => setRevisionScope(e.target.value)}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
              >
                <option>Minor tweaks</option>
                <option>Major rewrite</option>
                <option>Different angle entirely</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium mb-1.5" style={{ color: "var(--text-secondary)" }}>
                What needs to change?
              </label>
              <textarea
                value={revisionNotes}
                onChange={(e) => setRevisionNotes(e.target.value)}
                placeholder="Describe the changes needed..."
                rows={4}
                className="w-full px-3 py-2 rounded-lg text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
                autoFocus
              />
            </div>
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setShowRevisionModal(false)}
                className="px-4 py-2 rounded-lg text-sm"
                style={{ color: "var(--text-secondary)" }}
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitRevision}
                disabled={rejecting || !revisionNotes.trim()}
                className="px-4 py-2 rounded-lg text-sm font-semibold disabled:opacity-40"
                style={{ background: "var(--orange)", color: "var(--bg-void)" }}
              >
                {rejecting ? "Submitting..." : "Submit Revision"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
