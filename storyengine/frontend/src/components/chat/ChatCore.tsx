"use client";

// The shared chat engine. Lives in TWO places:
//   - the home screen (un-docked) — the creative producer + "Start Here" onboarding,
//   - the in-pipeline dock (docked, scoped to one videoId) — the co-pilot that can
//     run any pipeline action by voice, with paid/destructive actions held behind a
//     one-tap confirm card.
// All intelligence is server-side (/api/chat). `docked` gates the home-only bits
// (welcome hero, auto-onboarding, OAuth resume) and the layout (composer + width).
// ChatHome is a thin wrapper over <ChatCore /> so the home flow is unchanged.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Send, Loader2, CheckCircle2, ArrowRight, Clapperboard, AlertTriangle, Youtube, HardDrive, TrendingUp, Eye, Palette, CalendarDays, Lightbulb, Compass, Activity, Link2, Settings2, History, Plus, Paperclip, X, CircleDollarSign, Dna, RotateCcw, MinusCircle, XCircle, PencilLine } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import type { SSEStageChangeEvent, SSETaskProgressEvent } from "@/hooks/use-pipeline-sse";
import { useStyleDescriptions, styleDescriptionIcon, styleDescriptionById } from "@/hooks/use-style-descriptions";
import type { StyleDescription } from "@/lib/api";
import { StylePresetGallery } from "@/components/style/StylePresetGallery";
import { ChatPipelineMap } from "@/components/chat/ChatPipelineMap";
import { ScriptResultCard, CastLocationsCard, StoryboardGridCard, ApprovalGateCard } from "@/components/chat/ChatResultCards";
import { ProductionStyleSelector } from "@/components/production/ProductionStyleSelector";
import {
  sendChatTurn,
  uploadChatAsset,
  setOnboardingKey,
  getOnboardingStatus,
  getYouTubeConnectUrl,
  getDriveConnectUrl,
  getChatConversation,
  getSuggestedModels,
  listChatConversations,
  getChatConversationById,
  getVideo,
  getChannelCast,
  getStyleDefault,
  type ChatUiContext,
  type ChatCard,
  type ChatCardImage,
  type ChatDnaFieldRow,
  type ChatDnaLearnerRow,
  type ChatDnaPatternRow,
  type ChatCustomFilmOrchestrationBeat,
  type ChatTurnRequest,
  type ProductionPlan,
  type ProductionStyleId,
  type SuggestedModels,
  type SuggestedModelVideo,
  type ChatConversationSummary,
  type VideoDetail,
} from "@/lib/api";
import { PasswordInput } from "@/components/forms";
import { withMediaAuth } from "@/lib/utils";
import {
  durableCreatedVideoId,
  failedCustomFilmApprovalCards,
  resolvedCustomFilmApprovalCards,
} from "@/lib/custom-film-approval-truth";
import {
  MODEL_VIDEO_MESSAGE_PREFIX,
  parseSpendCapDollars,
  mentionsSpendCapWithoutAmount,
} from "@/lib/prompt-parse";

// localStorage keys for the OAuth round-trip during onboarding: the connect
// button stashes the active conversation so ChatCore can resume it when Google
// sends the user back to /?connected=yt|drive.
const CHAT_CID_KEY = "se_chat_cid";
// The dock caches a SEPARATE conversation id per video (instant reload). Never
// reuse the tenant-level home thread for a video's co-pilot, and vice versa.
const dockCidKey = (videoId: string) => `se_chat_cid_${videoId}`;

// One invalidation call for every in-chat result card (ChatResultCards.tsx)
// plus the video record itself — called on every stage_change / completed
// task_progress so a finished stage's script/cast/storyboards show up in
// the chat without a manual refresh. Simpler to keep this list in one place
// than to remember to update N call sites when a new result card is added.
function invalidateResultCards(queryClient: QueryClient, videoId: string) {
  queryClient.invalidateQueries({ queryKey: ["video", videoId] });
  queryClient.invalidateQueries({ queryKey: ["videoScript", videoId] });
  queryClient.invalidateQueries({ queryKey: ["videoCharacters", videoId] });
  queryClient.invalidateQueries({ queryKey: ["videoEnvironments", videoId] });
}

type Msg = {
  role: "user" | "assistant";
  text: string;
  cards?: ChatCard[] | null;
  plan?: ProductionPlan | null;
};

const GREETING =
  "Tell me about the video you want to make — one sentence is plenty. I'll ask anything I need, then build it for you.";
const EXAMPLES = [
  "A video about a dragon who finds a lonely owner, becomes his best friend, and they go on an adventure",
  "A 60-second explainer on why the sky is blue, made for curious kids",
  "A cinematic short about a lighthouse keeper who talks to the sea",
];

// One-click on-ramps to the command-center capabilities (Phases A-C + G3/G4). Each
// either sends a message (fires the capability) or prefills the composer (when the
// creator still needs to add something, like a link to model).
const QUICK_ACTIONS: {
  label: string;
  icon: typeof Sparkles;
  message?: string;
  prefill?: string;
}[] = [
  { label: "What to make next", icon: Lightbulb, message: "What should I make next? Score my best options and tell me which one to build and why." },
  { label: "What's working", icon: TrendingUp, message: "What's working on my competitors right now? Show their top videos with the numbers." },
  { label: "Plan my month", icon: CalendarDays, message: "Plan my next 30 days of videos." },
  { label: "Find an opening", icon: Compass, message: "Give me an opportunity map — where can I win that my competitors aren't covering?" },
  { label: "Model a video", icon: Link2, prefill: "Model this video: " },
  { label: "How are my videos doing?", icon: Activity, message: "How are my published videos doing? Diagnose the latest and tell me the one fix." },
  { label: "Update my channel", icon: Settings2, message: "I want to update my channel setup — my competitors, niche, and look." },
];
const DOCK_HINT =
  "Ask about this video, or tell me what to do next — e.g. “animate scene 2”, “redo the thumbnail”, or “how much has this cost?”";

// Length is a slider: 1 minute → 30 minutes, in 5-second steps. The engine's floor
// is 1 minute, so the slider starts there (no offering lengths it can't build).
const LENGTH_MIN = 60;
const LENGTH_MAX = 1800;
const LENGTH_STEP = 5;
const LENGTH_DEFAULT = 60;

const isSliderCard = (c: ChatCard) => c.id === "length" || (c as { type?: string }).type === "slider";

// --- card-kind dispatch (S9-3) ----------------------------------------------
// Before this, card rendering dispatched by string-matching card.id at 4
// scattered sites (the action-card finder, the 3-way action-card render
// branch, the inline scene-boards filter, and the connect-button check) — a
// new card kind meant a 5th ad hoc comparison. ONE lookup replaces all four:
// cardKind() is the single place that classifies a card, and the render
// sites below key off its result instead of comparing card.id inline. C21b
// adds the "look_engine" gallery card as one more entry here (the 5-preset
// engine axis, StylePresetGallery, rendered inside SelectorCards alongside
// the pre-existing 6-item "style" card — the two axes are independent and
// both may appear together), not a new scattered check. C22 adds "style_draft"
// (the conversational "make me a new style" preview/confirm card) the same way.
// C42 adds "channel_dna_digest" (the "learn this channel" confirmable digest)
// the same way — one more lookup-table entry, no new string-match branch.
// feat/approval-gates adds "approval_gate" (DIRECTOR-CHAT-PLAN.md Task 5.2) —
// ONE reusable kind for the script and anchors (cast+locations) review
// checkpoints, same pattern as every entry above: one more lookup-table row,
// not a new scattered `card.id === …` branch anywhere else.
type CardKind = "prompt_apply" | "confirm_action" | "custom_film_approval" | "secure_key" | "connect" | "images" | "look_engine" | "style_draft" | "channel_dna_digest" | "approval_gate" | "generic";

function cardKind(card: ChatCard): CardKind {
  if (card.id === "prompt_apply") return "prompt_apply";
  if (card.id === "confirm_action") return "confirm_action";
  if (card.id === "custom_film_approval") return "custom_film_approval";
  if (card.id === "secure_key") return "secure_key";
  if (card.id === "connect_yt" || card.id === "connect_drive") return "connect";
  if (card.id === "look_engine") return "look_engine";
  if (card.id === "style_draft") return "style_draft";
  if (card.id === "channel_dna_digest") return "channel_dna_digest";
  if (card.id === "approval_gate") return "approval_gate";
  if ((card.images?.length ?? 0) > 0) return "images";
  return "generic";
}

const ACTION_CARD_KINDS: ReadonlySet<CardKind> = new Set(["prompt_apply", "confirm_action", "custom_film_approval", "secure_key", "style_draft", "channel_dna_digest", "approval_gate"]);

function formatLength(secs: number): string {
  if (secs < 60) return `${secs} sec`;
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return s === 0 ? `${m} min` : `${m}m ${s}s`;
}

// The effective slider value: the creator's pick, else the producer's recommended length
// (stamped on the card by the backend), else the 1-minute floor.
function effLengthSecs(card: ChatCard, picks: Record<string, string | string[]>): number {
  const picked = picks[card.id];
  const rec = (card as { recommended_seconds?: number }).recommended_seconds;
  return Number(picked ?? rec ?? LENGTH_DEFAULT);
}

// A live "director" note under the length slider — instant feedback by band as the creator
// drags. The producer's chat message carries the story-specific reasoning; this is the cue.
function lengthHint(secs: number): string {
  if (secs < 90) return "Tight for a real story — a beginning, middle, and end may feel rushed.";
  if (secs < 180) return "Short and punchy — good for one clear idea.";
  if (secs <= 720) return "A comfortable length — room for real story beats without dragging.";
  if (secs <= 1200) return "On the longer side — make sure the story earns it, or scenes may drag.";
  return "Long — worth it only for a rich story; a simple idea will drag and lose viewers.";
}

// Minimal markdown for chat bubbles: **bold** -> <strong> and [text](url) ->
// a new-tab link (used by the onboarding key step). Newlines are handled by CSS
// (whitespace-pre-wrap). ponytail: no markdown dependency for two patterns.
function renderRich(text: string) {
  return text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={i}>{part.slice(2, -2)}</strong>;
    }
    const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (link) {
      return (
        <a
          key={i}
          href={link[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="font-semibold underline underline-offset-2"
          style={{ color: "var(--turquoise)" }}
        >
          {link[1]}
        </a>
      );
    }
    return part;
  });
}

// Hide a pasted API key in the transcript — it's a secret, so we don't leave it
// readable on screen or in a screenshot. A key is one long token with no spaces.
function maskSecret(text: string): string {
  const t = text.trim();
  if (/^(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_-]{24,})$/.test(t)) {
    return "•".repeat(8) + t.slice(-4);
  }
  return text;
}

// Root-cause context (found live 2026-07-27): a "make a video about a
// dystopian world... bugs, cap the spend at $1" entry (1) silently
// inherited PocoAPoco's locked Ryan/Vanessa cast + dialogue format, and
// (2) silently dropped the $1 spend cap — the classifier picks exactly ONE
// verb per turn and never surfaces either side effect. DirectorHome.tsx
// fixed the actual behavior (apply_channel_identity: false on create,
// max_spend parsed at creation); this builds the disclosure line(s) so
// NEITHER outcome is silent — a cap that landed, a cap that couldn't be
// read, and a skipped channel identity all get said out loud, once, as the
// very first message in the room. Returns null when there's nothing to say
// (no cap language, and the tenant has no locked identity to skip).
async function buildEntryDisclosureNote(message: string): Promise<string | null> {
  const lines: string[] = [];

  const cap = parseSpendCapDollars(message);
  if (cap != null) {
    lines.push(`Capped this video's spend at $${cap.toFixed(2)} — I'll check in before any build would push past it.`);
  } else if (mentionsSpendCapWithoutAmount(message)) {
    lines.push(`I saw a spending cap mentioned but couldn't read an amount — nothing's capped yet. Say "cap it at $5" any time.`);
  }

  // Modeling a reference video is its own explicit choice (confirmModel()
  // in DirectorHome.tsx) — it keeps inheriting the locked channel identity
  // on purpose, so this disclosure doesn't apply to that path.
  if (!message.startsWith(MODEL_VIDEO_MESSAGE_PREFIX)) {
    try {
      const [cast, style] = await Promise.allSettled([getChannelCast(), getStyleDefault()]);
      const castLocked = cast.status === "fulfilled" && cast.value.cast_locked;
      const formatLocked = style.status === "fulfilled" && style.value.source === "locked_format";
      if (castLocked || formatLocked) {
        lines.push(
          "This reads like a fresh idea, so I skipped your locked channel look/cast for it — want them applied here too? Just say so."
        );
      }
    } catch {
      // Disclosure is enrichment, not a gate — a failed lookup just means
      // no identity note, never a broken room.
    }
  }

  return lines.length ? lines.join(" ") : null;
}

export function ChatCore({
  videoId,
  docked = false,
  uiContext,
  selectionChip,
  onVideoCreated,
  activeVideoId,
  initialMessage,
  initialIntent,
}: {
  videoId?: string;
  docked?: boolean;
  uiContext?: ChatUiContext | null;
  // An optional small pill rendered directly above the composer, naming
  // whatever the NEXT message will act on (a selected shot or character) —
  // "honest and small", per the Director-surface brief: the creator should
  // never have to guess what "make him older" is about to change. Deliberately
  // a plain ReactNode, not a DirectorContext read: ChatCore is also mounted by
  // the old pipeline dock and ImagesStagePanel, neither of which has a
  // DirectorProvider in its tree, so the caller (DirectorSurface.tsx) builds
  // the chip itself and hands it down as a prop — same pattern as `uiContext`.
  selectionChip?: ReactNode;
  onVideoCreated?: (id: string) => void;
  activeVideoId?: string | null;
  // A message to send as the FIRST turn, automatically, the moment this mounts
  // with a blank thread — the DirectorHome entry box's one-sentence pitch,
  // carried across the createVideo() -> setSelectedVideoId() hand-off so the
  // sentence the creator already typed doesn't have to be retyped into this
  // (freshly mounted, brand-new-conversation) ChatCore instance. Undocked
  // only — the dock always resumes a real prior conversation instead (see
  // the DOCK hydrate effect below), so it never has a "blank thread" moment
  // this could apply to.
  initialMessage?: string | null;
  // The declared intent for `initialMessage` — "build" when the producer of
  // that message already KNOWS it means "build the whole video" (today, only
  // DirectorHome's plain-description box; see DirectorContext.tsx
  // `pendingInitialIntent`). Sent to the backend as `explicit_verb`, which
  // bypasses the co-pilot's free-text classifier for this one turn — it does
  // NOT skip the paid-confirm-card/cost-quote step, only the guess of WHICH
  // verb to run. `null`/undefined for every other initialMessage producer,
  // which keeps going through the classifier exactly as before.
  initialIntent?: "build" | null;
}) {
  const queryClient = useQueryClient();
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [createdVideoId, setCreatedVideoId] = useState<string | null>(null);
  // The video whose live pipeline map + inline result cards (script/cast/
  // locations/storyboards) this chat instance shows. The DOCK is always
  // scoped to its own `videoId`. The undocked Director-surface flow is NOT
  // always "just created this turn" — reopening an existing video (the
  // home's "Recent videos" row, or DirectorSurface after a refresh) mounts
  // ChatCore with `activeVideoId` already set and `createdVideoId` still
  // null, since no NEW turn ever ran in this mounted instance. Bug caught in
  // review (2026-07-27): result cards were wired to `createdVideoId` alone,
  // so they only ever appeared in the single-turn window right after a
  // brand-new video's first message — reopening any other video's Director
  // chat showed nothing. Falling back to `activeVideoId` covers that path.
  const resultCardsVideoId = docked ? (videoId ?? null) : (createdVideoId ?? activeVideoId ?? null);
  const { data: dockedVideo } = useQuery({
    queryKey: ["video", resultCardsVideoId],
    queryFn: () => getVideo(resultCardsVideoId!),
    enabled: !!resultCardsVideoId,
  });
  const dockProgress = usePipelineSSE({
    enabled: !!resultCardsVideoId,
    videoId: resultCardsVideoId ?? undefined,
    onStageChange: () => {
      if (resultCardsVideoId) invalidateResultCards(queryClient, resultCardsVideoId);
    },
    onTaskProgress: (event) => {
      if (resultCardsVideoId && event.status !== "running") {
        invalidateResultCards(queryClient, resultCardsVideoId);
      }
    },
  });
  const [picks, setPicks] = useState<Record<string, string | string[]>>({});
  const [checking, setChecking] = useState(true); // first-load onboarding-status / hydrate
  const [suggested, setSuggested] = useState<SuggestedModels | null>(null); // "worth modeling" (home)
  // Files dropped/attached but not yet sent with a message (home chat only).
  const [attachments, setAttachments] = useState<{ id: string; filename: string; kind: string }[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);
  const messagesScrollRef = useRef<HTMLDivElement>(null);
  const autoTriedRef = useRef(false);
  // The six style-description ids (checklist §C21b) — one shared query, also
  // used by the New Video "Style description" grid (pipeline/page.tsx).
  const { descriptions: styleDescriptions } = useStyleDescriptions();

  const cidKey = docked && videoId ? dockCidKey(videoId) : CHAT_CID_KEY;

  const started = messages.length > 0;
  const last = messages[messages.length - 1];
  // In the dock the video always exists, so createdVideoId must NOT suppress the
  // active cards (on the home page, "created" takes over the view instead).
  const showActive = (docked || !createdVideoId) && last?.role === "assistant";
  const activeCards = showActive ? last.cards : null;
  const activePlan = showActive ? last.plan : null;
  // One-tap action cards: the spend confirm and the editable proposed-prompt card.
  // These render even in the home "created" view — paid follow-ups always confirm
  // (the backend gates them everywhere now), so the card must never be hidden.
  const lastCards = last?.role === "assistant" ? last.cards : null;
  const actionCard = lastCards?.find((c) => ACTION_CARD_KINDS.has(cardKind(c))) ?? null;

  useEffect(() => {
    // Pin the thread to its newest content. In the DOCK, scroll the panel's own
    // container imperatively — smooth scrollIntoView loses the race when a
    // reply arrives WITH an action card (the panel resizes mid-scroll), which
    // left confirm cards rendered below the fold: creators saw no Do-it button
    // at all and thought the action had no UI. Run twice (now + after layout
    // settles) so late-painting cards are still brought into view.
    const toBottom = () => {
      const el = messagesScrollRef.current;
      if (el) el.scrollTop = el.scrollHeight;
      else endRef.current?.scrollIntoView({ behavior: "smooth" });
    };
    toBottom();
    // Staggered retries: on hydration/reload the surrounding page keeps
    // reflowing for a second or two AFTER the first scroll, which used to
    // leave the newest card ~a row below the fold again.
    const ts = [180, 600, 1500].map((ms) => setTimeout(toBottom, ms));
    return () => ts.forEach(clearTimeout);
  }, [messages, sending, createdVideoId]);

  // Home only: load "worth modeling" suggestions from the creator's modeled channel.
  useEffect(() => {
    if (docked) return;
    getSuggestedModels().then(setSuggested).catch(() => { /* none — fall back to examples */ });
  }, [docked]);

  async function turn(req: ChatTurnRequest, userBubble?: string) {
    if (sending) return;
    const failedApprovalCards = failedCustomFilmApprovalCards(
      req,
      lastCards,
    );
    if (userBubble) setMessages((m) => [...m, { role: "user", text: userBubble }]);
    setSending(true);
    setPicks({});
    try {
      const res = await sendChatTurn({
        ...req,
        conversation_id: conversationId ?? req.conversation_id ?? null,
        // The dock tags every turn with its video so the backend gates paid actions.
        video_id: docked ? videoId ?? null : req.video_id ?? activeVideoId ?? null,
        // ...and what the creator is viewing, so "this image" resolves.
        ui_context: docked ? uiContext ?? null : uiContext ?? null,
      });
      setConversationId(res.conversation_id);
      try { localStorage.setItem(cidKey, res.conversation_id); } catch { /* private mode */ }
      // Only the home flow flips into the "created" tracker view; the dock stays a
      // plain thread (live progress comes from the pipeline page itself).
      const durableVideoId = durableCreatedVideoId(res);
      if (!docked) {
        if (durableVideoId) {
          setCreatedVideoId(durableVideoId);
          onVideoCreated?.(durableVideoId);
        } else if (failedApprovalCards) {
          // HTTP success is not durable approval when the server remains in
          // plan. Keep the approval gate visible and remove false progress.
          setCreatedVideoId(null);
        }
      }
      const responseCards = resolvedCustomFilmApprovalCards(
        req,
        res,
        lastCards,
      );
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: res.assistant_text,
          cards: responseCards,
          plan: res.plan,
        },
      ]);
    } catch (e) {
      if (failedApprovalCards && !docked) {
        // A reserved video id is not proof that approval succeeded. Keep the
        // exact approval card actionable and remove fabricated progress UI.
        setCreatedVideoId(null);
      }
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          text: e instanceof Error ? e.message : "Something went wrong — try again.",
          cards: failedApprovalCards,
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  // --- DOCK: resume this video's conversation on open (the whole backstory) ---
  useEffect(() => {
    if (!docked || !videoId) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await getChatConversation(videoId);
        if (cancelled) return;
        if (data.conversation_id) setConversationId(data.conversation_id);
        if (data.messages?.length) {
          setMessages(data.messages.map((m) => ({ role: m.role, text: m.text, cards: m.cards, plan: m.plan })));
        }
      } catch {
        // no prior conversation — the next turn find-or-creates it
      } finally {
        if (!cancelled) setChecking(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docked, videoId]);

  // --- HOME: auto-start guided setup for brand-new users; never in the dock. ---
  // Established tenants get the normal welcome and are never re-onboarded. Runs
  // once; any failure falls back to the welcome.
  // NO `cancelled` FLAG HERE, ON PURPOSE. `autoTriedRef` already makes this body
  // run at most once per mounted ChatCore, so there is no second in-flight run to
  // race against, and React 18+ makes a setState on a truly unmounted component a
  // silent no-op. The two guards TOGETHER were the bug. React Strict Mode (on by
  // default for the App Router: next.config.ts doesn't set `reactStrictMode`, and
  // Next then defaults `__NEXT_STRICT_MODE_APP` to true) mounts, cleans up, and
  // remounts every component once in dev. That cleanup flipped `cancelled` for
  // run #1, and `autoTriedRef` then made run #2 return immediately, so NOTHING
  // ever called `setChecking(false)` and the undocked chat sat on its first-load
  // spinner forever even though `/api/dashboard/onboarding/status` returned 200.
  // It hit the Director chat column (DirectorSurface.tsx, the only `docked={false}`
  // mount site) on every page load in dev. The dock's own hydrate effect below
  // never had this: it re-runs on `[docked, videoId]` with a fresh flag each time.
  useEffect(() => {
    if (docked) return; // the dock hydrates instead — no onboarding here
    if (autoTriedRef.current) return;
    autoTriedRef.current = true;

    // DirectorHome hand-off: a brand-new video was just created (free, via
    // createVideo()) and this mount's ONE job is to open with the creator's
    // own sentence already sent, in the context of that video (activeVideoId
    // feeds turn()'s video_id — see turn() above). Takes priority over the
    // savedCid/onboarding checks below on purpose: this IS the first turn of
    // a brand-new conversation, never a resume.
    if (initialMessage) {
      (async () => {
        // Disclosure, not silence (found live 2026-07-27, same report as
        // apply_channel_identity below): a typed sentence can carry a spend
        // cap ("cap the spend at $1") and/or land on a tenant with a locked
        // channel identity — either way the creator must be told what
        // happened, never left to guess. This runs BEFORE the actual turn()
        // so the disclosure reads as the room's opening line, not a
        // follow-up to the classifier's own reply.
        const note = await buildEntryDisclosureNote(initialMessage);
        if (note) setMessages((m) => [...m, { role: "assistant", text: note }]);
        // DirectorHome's plain-description box declares its own intent — this
        // IS "build the whole video", not a sentence for the co-pilot's
        // classifier to guess at (see explicit_verb's root-cause note in
        // backend/routes/chat.py `_handle_copilot`). initialIntent is null
        // for every other producer of initialMessage (e.g. the YouTube model
        // confirm), so this stays a no-op for them — same classified path
        // as before.
        await turn(
          {
            message: initialMessage,
            ...(initialIntent === "build" ? { explicit_verb: "build" } : {}),
          },
          initialMessage
        );
        setChecking(false);
      })();
      return;
    }

    // Director surface, an EXISTING video (no initialMessage — this is a
    // reopen, not a fresh pitch): the home's "Recent videos" row, or a page
    // reload while a video is open, both mount ChatCore with `activeVideoId`
    // already set. Bug found in review (2026-07-27): with no branch for
    // this case, execution fell through to the tenant-level `savedCid`
    // check below (or the plain welcome) — showing either an unrelated
    // GLOBAL conversation or the "What should we make?" hero INSIDE a
    // specific video's room, and because `started` gates the whole
    // conversation layout (activeZone, holding the pipeline map + result
    // cards), NOTHING about this video's progress ever rendered here.
    // Mirrors the dock's own per-video hydrate effect below, just for the
    // undocked column.
    if (activeVideoId) {
      (async () => {
        try {
          const data = await getChatConversation(activeVideoId);
          if (data.conversation_id) setConversationId(data.conversation_id);
          if (data.messages?.length) {
            setMessages(data.messages.map((m) => ({ role: m.role, text: m.text, cards: m.cards, plan: m.plan })));
          }
        } catch {
          // No conversation yet for this video — fine, the room still shows
          // its live progress + result cards (see the `started` render gate
          // below); the next message just starts one.
        } finally {
          setChecking(false);
        }
      })();
      return;
    }

    // Resume onboarding after an account-connect OAuth round-trip. Google sends
    // the user back to /?connected=yt|drive; we reload the stashed conversation
    // and tell the backend that step is done so it advances to the next one.
    const connected = new URLSearchParams(window.location.search).get("connected");
    if (connected === "yt" || connected === "drive") {
      let cid: string | null = null;
      try { cid = localStorage.getItem(CHAT_CID_KEY); } catch { /* private mode */ }
      window.history.replaceState(null, "", window.location.pathname); // don't re-resume on refresh
      const sel = connected === "yt" ? { connect_yt: "connected" } : { connect_drive: "connected" };
      (async () => {
        await turn({ conversation_id: cid, selections: sel });
        setChecking(false);
      })();
      return;
    }

    (async () => {
      // Resume where you left off: if a conversation is saved, hydrate it instead of
      // dropping into a blank welcome (chat no longer vanishes on refresh).
      let savedCid: string | null = null;
      try { savedCid = localStorage.getItem(CHAT_CID_KEY); } catch { /* private mode */ }
      if (savedCid) {
        try {
          const data = await getChatConversationById(savedCid);
          if (data.messages?.length) {
            setConversationId(data.conversation_id);
            setMessages(data.messages.map((m) => ({ role: m.role, text: m.text, cards: m.cards, plan: m.plan })));
            setCreatedVideoId(durableCreatedVideoId(data));
            setChecking(false);
            return;
          }
        } catch { /* stale id — fall through to the normal welcome */ }
      }
      try {
        const s = await getOnboardingStatus();
        const brandNew =
          !s.completed && !s.steps?.first_video_created && !s.steps?.channel_configured;
        if (brandNew) {
          await turn({ start_onboarding: true }, "Help me get set up");
          return; // keep `checking` until the first turn renders (no welcome flash)
        }
      } catch {
        // status check failed — just show the normal welcome
      }
      // Returning, onboarded creators get the clean welcome; a fresh modeled-idea
      // pitch is one click away via the "Suggest a video idea" button (turn({})).
      setChecking(false);
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submitInput() {
    const text = input.trim();
    if ((!text && attachments.length === 0) || sending || uploadingFiles > 0) return;
    setInput("");
    const ids = attachments.map((a) => a.id);
    const names = attachments.map((a) => a.filename).join(", ");
    setAttachments([]);
    const bubble = text ? (names ? `${text}\n📎 ${names}` : text) : `📎 ${names}`;
    turn({ message: text || null, attachments: ids.length ? ids : undefined }, bubble);
  }

  // Upload dropped/picked/pasted files right away; they ride the NEXT sent turn
  // as chat_assets ids. Works in both the home chat and the docked co-pilot —
  // docked drops carry videoId so the backend stamps the asset to this video.
  async function attachFiles(files: FileList | File[]) {
    const list = Array.from(files).slice(0, Math.max(0, 5 - attachments.length));
    for (const f of list) {
      setUploadingFiles((n) => n + 1);
      try {
        const res = await uploadChatAsset(f, conversationId, docked ? videoId ?? null : null);
        setAttachments((a) => [
          ...a,
          { id: res.asset.id, filename: res.asset.filename || f.name, kind: res.asset.kind },
        ]);
      } catch (e) {
        setMessages((m) => [
          ...m,
          { role: "assistant", text: `I couldn't take “${f.name}” — ${e instanceof Error ? e.message : "try again?"}` },
        ]);
      } finally {
        setUploadingFiles((n) => n - 1);
      }
    }
  }

  function removeAttachment(id: string) {
    setAttachments((a) => a.filter((x) => x.id !== id));
  }

  // History (home only): start a clean thread, or resume a past one.
  function newChat() {
    if (sending) return;
    setMessages([]);
    setConversationId(null);
    setCreatedVideoId(null);
    setInput("");
    try { localStorage.removeItem(CHAT_CID_KEY); } catch { /* private mode */ }
  }

  async function loadConversation(cid: string) {
    if (sending) return;
    try {
      const data = await getChatConversationById(cid);
      setConversationId(data.conversation_id);
      setMessages((data.messages || []).map((m) => ({ role: m.role, text: m.text, cards: m.cards, plan: m.plan })));
      setCreatedVideoId(durableCreatedVideoId(data));
      try { localStorage.setItem(CHAT_CID_KEY, cid); } catch { /* private mode */ }
    } catch {
      /* gone — keep current state */
    }
  }

  function togglePick(card: ChatCard, value: string) {
    setPicks((prev) => {
      if (card.type === "multi") {
        const cur = Array.isArray(prev[card.id]) ? (prev[card.id] as string[]) : [];
        const next = cur.includes(value) ? cur.filter((v) => v !== value) : [...cur, value];
        return { ...prev, [card.id]: next };
      }
      return { ...prev, [card.id]: value };
    });
  }

  function setPickValue(cardId: string, value: string) {
    setPicks((prev) => ({ ...prev, [cardId]: value }));
  }

  function submitPicks() {
    if (!activeCards || sending) return;
    // An untouched slider submits the producer's recommended length (stamped on the card),
    // falling back to the 1-minute floor — so it never silently overrides the recommendation.
    const sel: Record<string, string | string[]> = { ...picks };
    for (const c of activeCards) {
      if (isSliderCard(c) && sel[c.id] === undefined) {
        const rec = (c as { recommended_seconds?: number }).recommended_seconds;
        sel[c.id] = String(rec ?? LENGTH_DEFAULT);
      }
    }
    const labelFor = (cardId: string, val: string) =>
      activeCards.find((c) => c.id === cardId)?.options?.find((o) => o.value === val)?.label ?? val;
    const summary = activeCards
      .map((c) => {
        const v = sel[c.id];
        if (v === undefined) return "";
        if (isSliderCard(c)) return formatLength(Number(v));
        return Array.isArray(v) ? v.map((x) => labelFor(c.id, x)).join(", ") : labelFor(c.id, v);
      })
      .filter(Boolean)
      .join(" · ");
    turn({ selections: sel }, summary || "Sounds good");
  }

  // Slider cards always count as answered (they carry a default).
  const allCardsAnswered =
    !!activeCards && activeCards.every((c) => {
      if (isSliderCard(c)) return true;
      const v = picks[c.id];
      return Array.isArray(v) ? v.length > 0 : !!v;
    });

  // One renderer per action-card kind (S9-3) — the 3-way string-match branch
  // is now data, keyed by cardKind(actionCard). Each entry's props/handlers
  // are byte-identical to the branch it replaces. C21b adds the LOOK/gallery
  // card kind as one more entry, not a 4th scattered `actionCard?.id === …`.
  const ACTION_CARD_RENDERERS: Partial<Record<CardKind, () => React.ReactNode>> = {
    prompt_apply: () => (
      <PromptProposalCard
        key={`pp-${messages.length}`}
        card={actionCard!}
        onApply={(text) => turn({ selections: { prompt_apply: "yes", prompt_text: text } }, "Apply this prompt")}
        onCancel={() => turn({ selections: { prompt_apply: "no" } }, "Cancel")}
      />
    ),
    confirm_action: () => (
      <ConfirmActionCard
        card={actionCard!}
        onChoose={(value, label) => turn({ selections: { confirm_action: value } }, label)}
      />
    ),
    custom_film_approval: () => (
      <CustomFilmApprovalCard
        card={actionCard!}
        onChoose={(value, label) => turn(
          { selections: { custom_film_approval: value } },
          label,
        )}
      />
    ),
    style_draft: () => (
      <StyleDraftCard
        card={actionCard!}
        onChoose={(value, label) => {
          turn({ selections: { style_draft: value } }, label);
          // The row is only ever created backend-side on "yes" — invalidate the
          // profile page's ["visualStyles"] query so it shows the new style
          // without waiting out the 30s default staleTime (C22: chat and the
          // Profile page are different route trees but share ONE QueryClient
          // via the root Providers, so this invalidation reaches it directly).
          if (value === "yes") queryClient.invalidateQueries({ queryKey: ["visualStyles"] });
        }}
      />
    ),
    secure_key: () => (
      <SecureKeyCard
        key={`sk-${messages.length}`}
        card={actionCard!}
        onSaved={(provider) => turn({ selections: { secure_key: "saved", key_provider: provider } }, "🔒 Key saved")}
        onSkip={() => turn({ selections: { secure_key: "skip" } }, "Skip for now")}
      />
    ),
    channel_dna_digest: () => (
      <DnaDigestCard
        key={`dna-${messages.length}`}
        card={actionCard!}
        onAction={(selections, label) => turn({ selections }, label)}
      />
    ),
    approval_gate: () => (
      resultCardsVideoId ? (
        <ApprovalGateCard
          key={`gate-${messages.length}`}
          card={actionCard!}
          videoId={resultCardsVideoId}
          onChoose={(value, label) => turn({ selections: { approval_gate: value } }, label)}
        />
      ) : null
    ),
  };

  // The active zone (cards / plan / created confirmation), shared by both layouts.
  const activeZone = (
    <>
      {actionCard && !sending && ACTION_CARD_RENDERERS[cardKind(actionCard)]?.()}
      {activeCards && !actionCard && !activePlan && !sending && (
        <SelectorCards cards={activeCards} picks={picks} onToggle={togglePick} onSetValue={setPickValue} onSubmit={submitPicks} canSubmit={allCardsAnswered} styleDescriptions={styleDescriptions} />
      )}
      {activePlan && !sending && (
        <ProductionPlanCard
          plan={activePlan}
          onApprove={(productionStyleId) => turn(
            { approve: true, selections: { production_style: productionStyleId } },
            "Make it ✨",
          )}
          styleDescriptions={styleDescriptions}
        />
      )}
      {!docked && createdVideoId && (
        <CreatedCard
          videoId={createdVideoId}
          video={dockedVideo}
          stageChange={dockProgress.lastStageChange}
          taskProgress={dockProgress.lastTaskProgress}
        />
      )}
      {/* Director surface fix (2026-07-27 review): this used to be gated on
          `createdVideoId` alone, which is ONLY ever set by a turn that
          creates/confirms a video IN THIS mounted conversation. Opening an
          EXISTING video's Director chat (the home's "Recent videos" row, or
          just reloading the page) mounts ChatCore with `activeVideoId`
          already set and `createdVideoId` still null — so the live
          pipeline map and every result card silently never appeared there.
          `resultCardsVideoId` (declared above, alongside dockedVideo/
          dockProgress) covers both cases. */}
      {!docked && resultCardsVideoId && (
        <>
          <ChatPipelineMap
            video={dockedVideo}
            stageChange={dockProgress.lastStageChange}
            taskProgress={dockProgress.lastTaskProgress}
            connected={dockProgress.isConnected}
          />
          <ScriptResultCard videoId={resultCardsVideoId} />
          <CastLocationsCard videoId={resultCardsVideoId} />
          <StoryboardGridCard videoId={resultCardsVideoId} />
        </>
      )}
    </>
  );

  // --- first-load: checking / hydrating (avoids a welcome flash) ---
  if (!started && checking) {
    return (
      <div className={docked ? "flex items-center justify-center h-full" : "max-w-3xl mx-auto flex flex-col items-center justify-center pt-32"}>
        <Loader2 className="animate-spin" size={docked ? 22 : 28} style={{ color: "var(--turquoise)" }} />
      </div>
    );
  }

  // --- DOCK conversation: relative panel, composer pinned inside it ---
  if (docked) {
    return (
      <div className="relative h-full flex flex-col">
        <div className="px-3 pt-3 shrink-0">
          <ChatPipelineMap
            video={dockedVideo}
            stageChange={dockProgress.lastStageChange}
            taskProgress={dockProgress.lastTaskProgress}
            connected={dockProgress.isConnected}
          />
        </div>
        {/* pb-44: the confirm/prompt action cards render at the thread's end —
            with pb-28 their buttons could sit under the pinned composer overlay
            (creators saw the card label but no Do it button). */}
        <div ref={messagesScrollRef} className="flex-1 overflow-y-auto px-4 pt-4 pb-44 flex flex-col gap-4">
          {!started && (
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{DOCK_HINT}</p>
          )}
          {/* Results land in the chat (bug (b)) — script/cast/storyboards
              render right here as they're ready, never gated behind a trip
              to /pipeline/{videoId}. Each card is self-gating (null with no
              data), so it's safe to always mount. */}
          {resultCardsVideoId && (
            <>
              <ScriptResultCard videoId={resultCardsVideoId} />
              <CastLocationsCard videoId={resultCardsVideoId} />
              <StoryboardGridCard videoId={resultCardsVideoId} />
            </>
          )}
          <MessageThread messages={messages} />
          {sending && <Thinking />}
          {activeZone}
          <div ref={endRef} />
        </div>
        <div className="absolute bottom-0 left-0 right-0 px-3 py-3" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
          {selectionChip}
          <Composer
            input={input}
            setInput={setInput}
            onSubmit={submitInput}
            sending={sending}
            placeholder="Ask or tell me what to do…"
            attachments={attachments}
            uploading={uploadingFiles > 0}
            onAttach={attachFiles}
            onRemoveAttachment={removeAttachment}
          />
        </div>
      </div>
    );
  }

  // --- HOME welcome screen (no conversation yet) ---
  // `&& !activeVideoId` (2026-07-27 review fix): the big "What should we
  // make?" hero is for the tenant-level home (no video open). The Director
  // surface's room ALSO mounts this undocked flavor, but scoped to a real,
  // already-selected video (`activeVideoId`) — showing the generic hero
  // there, instead of that video's live pipeline map + result cards, was
  // the actual bug: a video with no chat history yet (or not hydrated in
  // time) fell through to this branch and activeZone — where the pipeline
  // map and result cards live — never rendered at all.
  if (!started && !activeVideoId) {
    return (
      <div className="max-w-3xl mx-auto flex flex-col items-center text-center pt-10 md:pt-20">
        <div className="w-full flex justify-end mb-2">
          <ChatHistoryMenu onPick={loadConversation} onNew={newChat} disabled={sending} scopeVideoId={activeVideoId} />
        </div>
        <div
          className="w-14 h-14 rounded-2xl flex items-center justify-center mb-5"
          style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
        >
          <Sparkles size={28} />
        </div>
        <h1 className="text-3xl md:text-4xl font-display font-bold mb-3" style={{ color: "var(--text-primary)" }}>
          What should we make?
        </h1>
        <p className="text-base mb-8 max-w-xl" style={{ color: "var(--text-secondary)" }}>
          {GREETING}
        </p>
        <Composer
          input={input}
          setInput={setInput}
          onSubmit={submitInput}
          sending={sending}
          autoFocus
          attachments={attachments}
          uploading={uploadingFiles > 0}
          onAttach={attachFiles}
          onRemoveAttachment={removeAttachment}
        />

        <div className="mt-4 flex items-center justify-center gap-3 flex-wrap">
          {/* Suggest a modeled idea on demand (Phase 2 pitch). Repeatable, no
              surprise spend — the model call happens only when the creator asks. */}
          <button
            onClick={() => turn({})}
            disabled={sending}
            className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full text-sm font-medium transition-all hover:brightness-110 disabled:opacity-50"
            style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)", border: "1px solid var(--turquoise-dim)" }}
          >
            {sending ? <Loader2 size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {sending ? "Finding ideas…" : "Suggest a video idea"}
          </button>
          <button
            onClick={() => turn({ start_onboarding: true }, "Help me get set up")}
            className="inline-flex items-center gap-2 text-sm font-medium transition-colors hover:brightness-125"
            style={{ color: "var(--turquoise)" }}
          >
            <Sparkles size={14} /> New here? Start here — I'll set up your channel
          </button>
        </div>

        {/* One-click on-ramps to the command-center capabilities */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {QUICK_ACTIONS.map((a) => {
            const Icon = a.icon;
            return (
              <button
                key={a.label}
                onClick={() => {
                  if (a.message) turn({ message: a.message }, a.label);
                  else if (a.prefill) setInput(a.prefill);
                }}
                disabled={sending}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-all hover:brightness-110 disabled:opacity-50"
                style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
              >
                <Icon size={14} style={{ color: "var(--turquoise)" }} />
                {a.label}
              </button>
            );
          })}
        </div>

        {suggested?.videos?.length ? (
          <ModelSuggestions
            data={suggested}
            onPick={(v) =>
              turn(
                { message: `Make a video modeled on "${v.title}" from ${suggested.channel ?? "the channel I'm modeling"} — same hook and winning format, but my own spin.${v.url ? ` Reference: ${v.url}` : ""}` },
                `Make one like “${v.title}”`,
              )
            }
          />
        ) : (
          <div className="mt-6 flex flex-col gap-2 w-full">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                onClick={() => turn({ message: ex }, ex)}
                className="text-left text-sm rounded-xl px-4 py-3 transition-all hover:brightness-110"
                style={{
                  background: "var(--bg-surface)",
                  border: "1px solid var(--border-subtle)",
                  color: "var(--text-secondary)",
                }}
              >
                <span style={{ color: "var(--turquoise)" }}>“</span>
                {ex}
                <span style={{ color: "var(--turquoise)" }}>”</span>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  // --- HOME conversation (also covers the Director surface's per-video
  // room with no chat history yet — see the `started` gate above) ---
  // Bug fix (2026-07-27, reported live on the Director chat column): the
  // composer below used to be `position: absolute; bottom: 0` inside THIS
  // SAME element — and this element was ALSO the scrolling container (no
  // separate scroll region existed). An absolutely-positioned descendant
  // whose containing block is the scroll container itself is laid out
  // relative to the container's scrollable content, not the visible
  // viewport — so as messages/cards accumulated, "bottom: 0" pinned the
  // composer partway UP the column, overlapping message and progress cards
  // instead of sitting below them. Fixed the same way the DOCK branch above
  // already does it correctly: a non-scrolling outer shell (`relative h-full
  // flex flex-col`, the composer's containing block) wraps a SEPARATE
  // `flex-1 min-h-0 overflow-y-auto` region that is the only thing that
  // scrolls. `messagesScrollRef` (renamed from `dockScrollRef` — now shared
  // by both branches, only one of which ever mounts) keeps the existing
  // imperative "scroll to bottom" effect above working unchanged.
  return (
    <div className="relative h-full flex flex-col">
      <div
        ref={messagesScrollRef}
        className="w-full max-w-3xl mx-auto flex-1 min-h-0 overflow-y-auto flex flex-col gap-4 pb-32"
      >
        <div className="flex justify-end -mb-1">
          <ChatHistoryMenu onPick={loadConversation} onNew={newChat} disabled={sending} scopeVideoId={activeVideoId} />
        </div>
        {!started && activeVideoId && (
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>{DOCK_HINT}</p>
        )}
        <MessageThread messages={messages} />

        {sending && <Thinking />}

        {/* Active zone: cards, plan, or created confirmation */}
        {activeZone}

        <div ref={endRef} />
      </div>

      {/* composer pinned at the bottom of the (non-scrolling) shell */}
      <div className="absolute bottom-0 left-0 right-0 px-4 py-4" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
        <div className="max-w-3xl mx-auto">
          {selectionChip}
          <Composer
            input={input}
            setInput={setInput}
            onSubmit={submitInput}
            sending={sending}
            placeholder={createdVideoId ? "Ask for a change…" : "Reply…"}
            attachments={attachments}
            uploading={uploadingFiles > 0}
            onAttach={attachFiles}
            onRemoveAttachment={removeAttachment}
          />
        </div>
      </div>
    </div>
  );
}

// --- message thread + thinking indicator (shared by both layouts) ---------

function MessageThread({ messages }: { messages: Msg[] }) {
  return (
    <AnimatePresence initial={false}>
      {messages.map((m, i) => {
        // C15b: any card carrying `images` (id "scene_boards" today, but
        // cardKind() guards on the field, not the id, so it fail-safes on
        // both old frontends — which never read the key — and old backends —
        // which never send it) renders inline, in EVERY past turn, so the
        // boards stay visible as you scroll back through the conversation
        // rather than only on the newest message like the ephemeral confirm
        // cards. (S9-3: routed through the shared cardKind() lookup.)
        const imageCards = m.role === "assistant" ? (m.cards ?? []).filter((c) => cardKind(c) === "images") : [];
        return (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className="max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap"
            style={
              m.role === "user"
                ? { background: "var(--turquoise)", color: "var(--bg-void)" }
                : { background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }
            }
          >
            {m.role === "user" ? maskSecret(m.text) : renderRich(m.text)}
            {imageCards.map((c) => (
              <SceneBoardsGrid key={c.id} images={c.images!} />
            ))}
          </div>
        </motion.div>
        );
      })}
    </AnimatePresence>
  );
}

// C15b: thumbnail grid for a scene's storyboards/keyframes, surfaced inline in
// the chat stream (tasks/storyengine-copilot-ux-map.md director-review loop).
// Every url already came from the backend's media proxy (tenant-authorized,
// never a raw Drive/external link) — this component only displays them. Tap
// opens the full-size image in a new tab (no existing lightbox is shared
// across chat + the Scenes tab yet, so this is the simple fallback door the
// checklist allows rather than reaching into ScenesWorkspaceTab's private
// modal). A failed image swaps to its label instead of a broken-image icon.
// C25a: the proxy URL from the backend carries no auth of its own — attach
// the current session token here (withMediaAuth), same as every other place
// this app turns a media-proxy path into an <img src>.
function SceneBoardsGrid({ images }: { images: ChatCardImage[] }) {
  const [broken, setBroken] = useState<Record<string, boolean>>({});
  const shown = images.slice(0, 6);
  if (shown.length === 0) return null;
  return (
    <div className="mt-3 grid grid-cols-3 gap-2 max-w-[280px]">
      {shown.map((img) => (
        <a
          key={img.asset_id}
          href={withMediaAuth(img.url)}
          target="_blank"
          rel="noopener noreferrer"
          title={img.label}
          className="relative aspect-video rounded-lg overflow-hidden block"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          {broken[img.asset_id] ? (
            <div className="w-full h-full flex items-center justify-center text-center px-1">
              <span className="text-[9px] leading-tight" style={{ color: "var(--text-tertiary)" }}>
                {img.label}
              </span>
            </div>
          ) : (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={withMediaAuth(img.url)}
              alt={img.label}
              loading="lazy"
              className="w-full h-full object-cover"
              onError={() => setBroken((b) => ({ ...b, [img.asset_id]: true }))}
            />
          )}
          <span
            className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-[9px] truncate"
            style={{ background: "rgba(0,0,0,0.55)", color: "#fff" }}
          >
            {img.label}
          </span>
        </a>
      ))}
    </div>
  );
}

function Thinking() {
  return (
    <div className="flex justify-start">
      <div
        className="rounded-2xl px-4 py-3 flex items-center gap-2"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
      >
        <Loader2 size={16} className="animate-spin" style={{ color: "var(--turquoise)" }} />
        <span className="text-sm">Thinking…</span>
      </div>
    </div>
  );
}

// --- "worth modeling" suggestions (home) ----------------------------------
// Real top videos from the channel the creator is modeling, with metrics + an AI
// "why model this". Clicking one starts a video modeled on that proven format.
function fmtViews(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function ModelSuggestions({ data, onPick }: { data: SuggestedModels; onPick: (v: SuggestedModelVideo) => void }) {
  return (
    <div className="mt-6 w-full flex flex-col gap-3 text-left">
      <div className="flex items-center gap-2">
        <TrendingUp size={15} style={{ color: "var(--turquoise)" }} />
        <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
          Worth modeling{data.channel ? ` · ${data.channel}` : ""}
        </span>
      </div>
      <div className="flex flex-col gap-2">
        {data.videos.map((v) => {
          const ytUrl = v.url || (v.video_id ? `https://www.youtube.com/watch?v=${v.video_id}` : null);
          return (
          <div
            key={v.video_id}
            className="group flex gap-3 items-stretch text-left rounded-xl p-2 transition-all hover:brightness-110"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
          >
            <button
              onClick={() => onPick(v)}
              title="Make one like this"
              className="shrink-0 w-28 aspect-video rounded-lg overflow-hidden"
              style={{ background: "var(--bg-deep)" }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={v.thumbnail} alt="" className="w-full h-full object-cover" loading="lazy" />
            </button>
            <div className="flex-1 min-w-0 flex flex-col gap-1 py-0.5">
              <button
                onClick={() => onPick(v)}
                className="text-left text-sm font-medium line-clamp-1 hover:underline"
                style={{ color: "var(--text-primary)" }}
              >
                {v.title}
              </button>
              <div className="flex items-center gap-3 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                <span className="inline-flex items-center gap-1"><Eye size={11} /> {fmtViews(v.views)}</span>
                <span>{v.posted}</span>
                <span style={{ color: "var(--turquoise)" }}>{v.vph.toLocaleString()}/hr</span>
                {ytUrl && (
                  <a
                    href={ytUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                    title="Open the source video on YouTube to verify it's real and current"
                    className="inline-flex items-center gap-1 font-semibold underline underline-offset-2 hover:brightness-110"
                    style={{ color: "var(--turquoise)" }}
                  >
                    <Youtube size={12} /> Watch on YouTube
                  </a>
                )}
              </div>
              <button
                onClick={() => onPick(v)}
                className="text-left text-xs line-clamp-2"
                style={{ color: "var(--text-secondary)" }}
              >
                {v.why}
              </button>
              <div className="text-[11px] font-medium opacity-0 group-hover:opacity-100 transition-opacity inline-flex items-center gap-1" style={{ color: "var(--turquoise)" }}>
                Make one like this <ArrowRight size={11} />
              </div>
            </div>
          </div>
          );
        })}
      </div>
    </div>
  );
}

// --- history menu (recent chats + new chat) -------------------------------
function ChatHistoryMenu({
  onPick,
  onNew,
  disabled,
  scopeVideoId,
}: {
  onPick: (cid: string) => void;
  onNew: () => void;
  disabled?: boolean;
  // Bug fix (2026-07-27 audit, "does one video's chat bleed into another's"):
  // `listChatConversations` returns the TENANT'S conversations, not this
  // video's — verified live, picking an entry for a different video loaded
  // that video's whole thread (script summary, production-progress widget,
  // "Write the script" action) into THIS video's still-open canvas/header,
  // with no indication anything had switched. Every call site that renders
  // this menu today is scoped to one open video (the tenant-level "no video
  // open" home branch that would leave this `undefined` is currently
  // unreachable — DirectorSurface always supplies a real video — but the
  // filter degrades safely to "show everything" if that ever changes). When
  // set, the list only offers conversations that belong to THIS video, so
  // picking one can never swap in another video's context.
  scopeVideoId?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ChatConversationSummary[] | null>(null);
  const [loading, setLoading] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      try {
        const all = await listChatConversations(20);
        setItems(scopeVideoId ? all.filter((c) => c.video_id === scopeVideoId) : all);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  }

  return (
    <div className="relative">
      <button
        onClick={toggle}
        disabled={disabled}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors hover:brightness-110 disabled:opacity-50"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
      >
        <History size={14} /> History
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div
            className="absolute right-0 mt-2 w-72 max-h-96 overflow-auto rounded-xl z-20 p-1.5"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", boxShadow: "0 8px 30px rgba(0,0,0,0.4)" }}
          >
            <button
              onClick={() => { onNew(); setOpen(false); }}
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors hover:brightness-110"
              style={{ color: "var(--turquoise)" }}
            >
              <Plus size={14} /> New chat
            </button>
            <div className="my-1 h-px" style={{ background: "var(--border-subtle)" }} />
            {loading && <div className="px-3 py-2 text-xs" style={{ color: "var(--text-tertiary)" }}>Loading…</div>}
            {!loading && items && items.length === 0 && (
              <div className="px-3 py-2 text-xs" style={{ color: "var(--text-tertiary)" }}>
                {scopeVideoId ? "No past chats for this video yet." : "No past chats yet."}
              </div>
            )}
            {!loading && items && items.map((c) => (
              <button
                key={c.conversation_id}
                onClick={() => { onPick(c.conversation_id); setOpen(false); }}
                className="w-full text-left px-3 py-2 rounded-lg transition-colors hover:brightness-110"
                style={{ color: "var(--text-secondary)" }}
              >
                <p className="text-xs font-medium truncate" style={{ color: "var(--text-primary)" }}>{c.title}</p>
                {c.preview && <p className="text-[10px] truncate" style={{ color: "var(--text-tertiary)" }}>{c.preview}</p>}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// --- composer -------------------------------------------------------------

function Composer({
  input,
  setInput,
  onSubmit,
  sending,
  placeholder = "Describe your video…",
  autoFocus,
  attachments,
  uploading,
  onAttach,
  onRemoveAttachment,
}: {
  input: string;
  setInput: (v: string) => void;
  onSubmit: () => void;
  sending: boolean;
  placeholder?: string;
  autoFocus?: boolean;
  // File drop-in: home chat and the docked co-pilot both pass these (docked
  // drops carry the video's id through to /api/chat/upload — see attachFiles).
  attachments?: { id: string; filename: string; kind: string }[];
  uploading?: boolean;
  onAttach?: (files: FileList | File[]) => void;
  onRemoveAttachment?: (id: string) => void;
}) {
  const fileRef = useRef<HTMLInputElement>(null);
  const canAttach = !!onAttach;
  const hasAttachments = !!attachments?.length;
  return (
    <div
      className="w-full flex flex-col gap-1.5"
      onDragOver={canAttach ? (e) => e.preventDefault() : undefined}
      onDrop={
        canAttach
          ? (e) => {
              e.preventDefault();
              if (e.dataTransfer.files?.length) onAttach!(e.dataTransfer.files);
            }
          : undefined
      }
    >
      {hasAttachments && (
        <div className="flex flex-wrap gap-1.5 px-1">
          {attachments!.map((a) => (
            <span
              key={a.id}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium"
              style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
            >
              <Paperclip size={11} /> {a.filename}
              <button
                onClick={() => onRemoveAttachment?.(a.id)}
                aria-label={`Remove ${a.filename}`}
                className="hover:brightness-125"
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div
        className="flex items-end gap-2 rounded-2xl px-3 py-2 w-full"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
      >
        {canAttach && (
          <>
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              accept=".csv,.pdf,.txt,.md,image/*"
              onChange={(e) => {
                if (e.target.files?.length) onAttach!(e.target.files);
                e.target.value = "";
              }}
            />
            <button
              onClick={() => fileRef.current?.click()}
              disabled={sending || !!uploading}
              aria-label="Attach a file"
              title="Drop in a CSV of titles, a script, or character sheets"
              className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all enabled:hover:brightness-125 disabled:opacity-30"
              style={{ background: "transparent", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
            >
              {uploading ? <Loader2 size={15} className="animate-spin" /> : <Paperclip size={15} />}
            </button>
          </>
        )}
        <textarea
          autoFocus={autoFocus}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
            }
          }}
          onPaste={
            canAttach
              ? (e) => {
                  if (e.clipboardData?.files?.length) {
                    e.preventDefault();
                    onAttach!(e.clipboardData.files);
                  }
                }
              : undefined
          }
          rows={1}
          placeholder={placeholder}
          className="flex-1 bg-transparent resize-none outline-none text-sm py-2 px-1 max-h-40"
          style={{ color: "var(--text-primary)" }}
        />
        <button
          onClick={onSubmit}
          disabled={sending || !!uploading || (!input.trim() && !hasAttachments)}
          aria-label="Send"
          className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all enabled:hover:brightness-110 disabled:opacity-30"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
        </button>
      </div>
    </div>
  );
}

// --- account-connect button (YouTube analytics / Google Drive OAuth) ------
// Stashes a "chat" origin so the existing callbacks return to /?connected=…,
// then sends the user same-tab to Google. ChatCore resumes onboarding on return.
function ConnectButton({ kind }: { kind: string }) {
  const [opening, setOpening] = useState(false);
  const isYt = kind === "connect_yt";
  async function connect() {
    setOpening(true);
    try {
      localStorage.setItem(isYt ? "youtube_oauth_origin" : "drive_oauth_origin", "chat");
      const { auth_url } = isYt ? await getYouTubeConnectUrl() : await getDriveConnectUrl();
      window.location.href = auth_url;
    } catch {
      setOpening(false); // surfaced as a no-op; the Skip option still advances
    }
  }
  return (
    <button
      onClick={connect}
      disabled={opening}
      className="mb-3 inline-flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-50"
      style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
    >
      {opening ? <Loader2 size={16} className="animate-spin" /> : isYt ? <Youtube size={16} /> : <HardDrive size={16} />}
      {opening ? "Opening Google…" : isYt ? "Connect YouTube" : "Connect Google Drive"}
    </button>
  );
}

// --- confirm-action card (the co-pilot's spend gate) ----------------------
// A one-tap Confirm / Cancel for a paid or destructive action. The backend sent
// it as a single-select card (id "confirm_action"); we render its two options as
// direct buttons and reply with selections.confirm_action = yes|no.
function ConfirmActionCard({
  card,
  onChoose,
}: {
  card: ChatCard;
  onChoose: (value: string, label: string) => void;
}) {
  const yes = card.options?.find((o) => o.value === "yes");
  const no = card.options?.find((o) => o.value === "no");
  // C15 (checklist §1.2): itemized per-model/tier quote, present only when the
  // backend had something to break down (actions.cost_breakdown) — absent on
  // any older payload or any quote with nothing routed yet, in which case this
  // renders exactly the pre-C15 card below.
  const breakdown = card.breakdown;
  const hasBreakdown = !!breakdown && breakdown.lines.length > 0;
  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-start gap-2">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: "var(--gold)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>
      {hasBreakdown && (
        <div
          className="flex flex-col gap-1.5 rounded-lg px-3 py-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          {breakdown!.lines.map((ln) => (
            <div key={ln.model_id} className="flex items-center justify-between text-xs">
              <span style={{ color: "var(--text-secondary)" }}>
                {ln.count} × {ln.display_name}
              </span>
              <span style={{ color: "var(--text-primary)" }}>${ln.subtotal.toFixed(2)}</span>
            </div>
          ))}
          {breakdown!.all_premium_total != null && breakdown!.all_premium_total > breakdown!.total && (
            <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
              vs ${breakdown!.all_premium_total.toFixed(2)} all-premium
            </div>
          )}
          {breakdown!.hero_scenes.length > 0 && breakdown!.lines.length > 1 && (
            <div className="text-xs" style={{ color: "var(--gold)" }}>
              {breakdown!.hero_scenes
                .slice(0, 3)
                .filter((h) => h.scene != null)
                .map((h) => `Scene ${h.scene} — ${h.display_name}`)
                .join(" · ")}
            </div>
          )}
        </div>
      )}
      <div className="flex items-center gap-2">
        <button
          onClick={() => yes && onChoose("yes", yes.label)}
          className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98]"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {yes?.label ?? "Do it"}
        </button>
        <button
          onClick={() => onChoose("no", no?.label ?? "Cancel")}
          className="px-4 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
          style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
        >
          {no?.label ?? "Cancel"}
        </button>
      </div>
    </GlassCard>
  );
}

// --- Custom Film production blueprint -------------------------------------
// A creator-safe, one-tap review of the exact immutable plan and shared BYOK
// quote. This replaces the generic radio-card treatment at the moment where
// approval can start paid work, without exposing internal profiles/providers.
function exactSeconds(value: number): string {
  return Number(value.toFixed(3)).toString();
}

function exactBeatTime(beat: ChatCustomFilmOrchestrationBeat): string {
  const endSeconds = beat.start_seconds + beat.duration_seconds;
  return `${exactSeconds(beat.start_seconds)}–${exactSeconds(endSeconds)} sec`;
}

function publicMediaLabel(mediaKind: string): string {
  const normalized = mediaKind.trim().toLowerCase();
  if (normalized === "video") return "Approved footage";
  if (normalized === "image") return "Animated imagery";
  if (normalized === "adaptive") return "Best approved media";
  return mediaKind;
}

function CustomFilmOrchestrationBeatRow({
  beat,
}: {
  beat: ChatCustomFilmOrchestrationBeat;
}) {
  const direction = [
    ["Transform", beat.transformation_summary],
    ["Camera", beat.camera_summary],
    ["Captions", beat.captions_summary],
    ["Sound", beat.audio_summary],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));

  return (
    <article
      className="min-w-0 overflow-hidden rounded-lg p-3"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[9px] font-bold uppercase tracking-[0.14em]" style={{ color: "var(--text-tertiary)" }}>
            Beat {beat.beat_order}
          </p>
          <h4 className="mt-1 break-words text-xs font-semibold leading-snug" style={{ color: "var(--text-primary)" }}>
            {beat.narrative_label}
          </h4>
        </div>
        <span
          className="shrink-0 rounded-full px-2 py-1 text-[9px] font-bold tabular-nums"
          style={{ background: "rgba(0,212,170,0.10)", color: "var(--turquoise)" }}
          aria-label={`Starts at ${beat.start_seconds} seconds and lasts ${beat.duration_seconds} seconds`}
        >
          {exactBeatTime(beat)}
        </span>
      </div>

      <div className="mt-2.5 flex min-w-0 flex-wrap gap-1.5">
        <span
          className="max-w-full break-words rounded-full px-2 py-1 text-[9px] font-semibold"
          style={{ background: "rgba(255,255,255,0.06)", color: "var(--text-primary)" }}
        >
          {publicMediaLabel(beat.media_kind)}
        </span>
        {beat.capability_labels.map((label) => (
          <span
            key={label}
            className="max-w-full break-words rounded-full px-2 py-1 text-[9px]"
            style={{ background: "rgba(0,212,170,0.07)", color: "var(--text-secondary)", border: "1px solid rgba(0,212,170,0.12)" }}
          >
            + {label}
          </span>
        ))}
      </div>

      {direction.length > 0 && (
        <dl className="mt-3 grid min-w-0 grid-cols-1 gap-x-3 gap-y-1.5 sm:grid-cols-2">
          {direction.map(([label, value]) => (
            <div key={label} className="min-w-0">
              <dt className="text-[9px] font-bold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
                {label}
              </dt>
              <dd className="mt-0.5 break-words text-[10px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </article>
  );
}

function CustomFilmApprovalCard({
  card,
  onChoose,
}: {
  card: ChatCard;
  onChoose: (value: string, label: string) => void;
}) {
  if (card.custom_film_director_stage) {
    return (
      <CustomFilmDirectorStageCard
        card={card}
        onChoose={onChoose}
      />
    );
  }
  const yes = card.options?.find((o) => o.value === "yes");
  const no = card.options?.find((o) => o.value === "no");
  const sections = card.custom_film_sections ?? [];
  const orchestrationBeats = card.custom_film_orchestration_beats ?? [];
  const totals = card.custom_film_totals;
  const duration = totals
    ? `${Math.floor(totals.duration_seconds / 60)}:${String(totals.duration_seconds % 60).padStart(2, "0")}`
    : "—";
  const remotionLocked = card.finishing_engine === "remotion";
  const hasOrchestrationBlueprint = orchestrationBeats.length > 0;
  const beatsBySection = sections
    .map((section) => ({
      section,
      beats: orchestrationBeats
        .filter((beat) => beat.section_order === section.order)
        .sort((a, b) => a.beat_order - b.beat_order),
    }))
    .filter((group) => group.beats.length > 0);

  return (
    <GlassCard
      className="overflow-hidden p-0"
      style={{ borderColor: "rgba(0, 212, 170, 0.38)" }}
    >
      <div
        className="px-4 py-4 sm:px-5"
        style={{
          background: "linear-gradient(135deg, rgba(0,212,170,0.14), rgba(0,212,170,0.03))",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div
              className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              <Clapperboard size={19} />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: "var(--turquoise)" }}>
                Ready for your review
              </p>
              <h2 className="mt-1 break-words text-lg font-display font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
                {card.label}
              </h2>
              <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                {card.header ?? "Custom Film"} · {duration} · {sections.length} acts
              </p>
            </div>
          </div>
          <span
            className="shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide"
            style={{ background: "rgba(0,212,170,0.12)", color: "var(--turquoise)", border: "1px solid rgba(0,212,170,0.25)" }}
          >
            {hasOrchestrationBlueprint && remotionLocked
              ? "Layered vision locked"
              : remotionLocked
                ? "Remotion locked"
                : "FFmpeg finishing"}
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
          {sections.map((section) => (
            <div
              key={section.order}
              className="min-w-0 rounded-xl p-3"
              style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <span
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold"
                    style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
                  >
                    {section.order}
                  </span>
                  <p className="min-w-0 break-words text-xs font-bold uppercase tracking-wide" style={{ color: "var(--text-primary)" }}>
                    {section.role}
                  </p>
                </div>
                <span className="shrink-0 text-xs font-semibold" style={{ color: "var(--turquoise)" }}>
                  {Math.floor(section.duration_seconds / 60)}:{String(section.duration_seconds % 60).padStart(2, "0")}
                </span>
              </div>
              <p className="mt-2 break-words text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {section.purpose}
              </p>
              <p className="mt-1 break-words text-[11px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
                {section.feel}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-1.5 text-[10px]">
                <span className="rounded-full px-2 py-1" style={{ background: "var(--bg-surface)", color: "var(--text-secondary)" }}>
                  {section.still_images} images
                </span>
                <span className="rounded-full px-2 py-1" style={{ background: "var(--bg-surface)", color: "var(--text-secondary)" }}>
                  {section.animation_clips} clips
                </span>
                <span className="rounded-full px-2 py-1" style={{ background: "var(--bg-surface)", color: "var(--text-secondary)" }}>
                  {section.voice_tracks} voice
                </span>
                <span className="ml-auto rounded-full px-2 py-1 font-semibold" style={{ background: "rgba(0,212,170,0.08)", color: "var(--turquoise)" }}>
                  ~${section.estimated_cost.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>

        {hasOrchestrationBlueprint && (
          <div
            className="min-w-0 overflow-hidden rounded-xl"
            style={{ background: "var(--bg-deep)", border: "1px solid rgba(0,212,170,0.22)" }}
          >
            <div
              className="px-3 py-3 sm:px-4"
              style={{ background: "linear-gradient(110deg, rgba(0,212,170,0.10), transparent)", borderBottom: "1px solid var(--border-subtle)" }}
            >
              <p className="text-[10px] font-bold uppercase tracking-[0.16em]" style={{ color: "var(--turquoise)" }}>
                Director&apos;s shot blueprint
              </p>
              <p className="mt-1 max-w-2xl text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                Every beat combines approved media, visual systems, camera, captions, and sound into one timed composition.
              </p>
            </div>

            <div className="flex min-w-0 flex-col gap-4 p-3 sm:p-4">
              {beatsBySection.map(({ section, beats }) => (
                <section
                  key={section.order}
                  className="min-w-0"
                  aria-label={`Section ${section.order}: ${section.role}`}
                >
                  <div className="mb-2 flex min-w-0 items-center gap-2">
                    <span
                      className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[9px] font-bold"
                      style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
                    >
                      {section.order}
                    </span>
                    <h3
                      className="min-w-0 break-words text-[11px] font-bold uppercase tracking-[0.12em]"
                      style={{ color: "var(--text-primary)" }}
                    >
                      {section.role}
                    </h3>
                    <span className="h-px min-w-4 flex-1" style={{ background: "var(--border-subtle)" }} />
                    <span className="shrink-0 text-[10px]" style={{ color: "var(--text-tertiary)" }}>
                      {beats.length} {beats.length === 1 ? "beat" : "beats"}
                    </span>
                  </div>

                  <div className="grid min-w-0 grid-cols-1 gap-2.5 xl:grid-cols-2">
                    {beats.map((beat) => (
                      <CustomFilmOrchestrationBeatRow
                        key={`${beat.section_order}:${beat.beat_order}`}
                        beat={beat}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </div>
        )}

        {totals && (
          <div
            className="grid grid-cols-2 gap-3 rounded-xl p-3 sm:grid-cols-4"
            style={{ background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.18)" }}
          >
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Media bill</p>
              <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                {totals.still_images} + {totals.animation_clips} + {totals.voice_tracks}
              </p>
              <p className="text-[10px]" style={{ color: "var(--text-secondary)" }}>images · clips · voice</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>BYOK estimate</p>
              <p className="mt-1 text-xl font-display font-bold" style={{ color: "var(--turquoise)" }}>
                ${totals.estimated_cost.toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Hard ceiling</p>
              <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                ${totals.max_spend.toFixed(2)}
              </p>
              <p className="text-[10px]" style={{ color: "var(--text-secondary)" }}>cannot silently exceed</p>
            </div>
            <div>
              <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Unused headroom</p>
              <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                ${totals.headroom.toFixed(2)}
              </p>
              <p className="text-[10px]" style={{ color: "var(--text-secondary)" }}>not reroll permission</p>
            </div>
          </div>
        )}

        {card.finishing_notice && (
          <div
            className="flex items-start gap-2 rounded-lg px-3 py-2"
            style={{
              background: remotionLocked ? "rgba(0,212,170,0.06)" : "var(--bg-deep)",
              border: remotionLocked
                ? "1px solid rgba(0,212,170,0.18)"
                : "1px solid var(--border-subtle)",
            }}
          >
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" style={{ color: "var(--turquoise)" }} />
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.14em]" style={{ color: "var(--turquoise)" }}>
                {remotionLocked ? "Remotion finishing locked" : "Verified fallback"}
              </p>
              <p className="mt-1 break-words text-[11px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {card.finishing_notice}
              </p>
            </div>
          </div>
        )}

        {card.approval_notice && (
          <div className="flex items-start gap-2">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" style={{ color: "var(--gold)" }} />
            <p className="break-words text-[11px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {card.approval_notice}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => yes && onChoose("yes", yes.label)}
            className="min-w-0 flex-1 rounded-xl px-4 py-3 text-sm font-bold transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {yes?.label ?? "Approve paid production"}
          </button>
          <button
            onClick={() => onChoose("no", no?.label ?? "Keep editing")}
            className="rounded-xl px-4 py-3 text-sm font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
          >
            {no?.label ?? "Keep editing"}
          </button>
        </div>
      </div>
    </GlassCard>
  );
}

function CustomFilmDirectorStageCard({
  card,
  onChoose,
}: {
  card: ChatCard;
  onChoose: (value: string, label: string) => void;
}) {
  const stage = card.custom_film_director_stage!;
  const yes = card.options?.find((option) => option.value === "yes");
  const no = card.options?.find((option) => option.value === "no");
  const duration = `${Math.floor(stage.duration_seconds / 60)}:${String(stage.duration_seconds % 60).padStart(2, "0")}`;

  return (
    <GlassCard
      className="overflow-hidden p-0"
      style={{ borderColor: "rgba(0, 212, 170, 0.38)" }}
    >
      <div
        className="px-4 py-4 sm:px-5"
        style={{
          background: "linear-gradient(135deg, rgba(0,212,170,0.14), rgba(0,212,170,0.03))",
          borderBottom: "1px solid var(--border-subtle)",
        }}
      >
        <div className="flex min-w-0 items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div
              className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-xl"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              <Clapperboard size={19} />
            </div>
            <div className="min-w-0">
              <p className="text-[10px] font-bold uppercase tracking-[0.18em]" style={{ color: "var(--turquoise)" }}>
                Planning approval
              </p>
              <h2 className="mt-1 break-words text-lg font-display font-bold leading-tight" style={{ color: "var(--text-primary)" }}>
                {card.label}
              </h2>
              <p className="mt-1 text-xs" style={{ color: "var(--text-secondary)" }}>
                {card.header ?? "Custom Film"} · {duration} · about {stage.planned_shots} shots
              </p>
            </div>
          </div>
          <span
            className="shrink-0 rounded-full px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide"
            style={{ background: "rgba(0,212,170,0.12)", color: "var(--turquoise)", border: "1px solid rgba(0,212,170,0.25)" }}
          >
            No media approved
          </span>
        </div>
      </div>

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          <p className="text-[10px] font-bold uppercase tracking-[0.15em]" style={{ color: "var(--turquoise)" }}>
            {stage.stage}
          </p>
          <p className="mt-2 break-words text-sm leading-relaxed" style={{ color: "var(--text-primary)" }}>
            {stage.produces}
          </p>
          <p className="mt-2 text-[11px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
            Locks the story, cast, environments, visual style, dialogue, exposition,
            silent action, and shot-to-shot storyboard progression before imagery.
          </p>
        </div>

        <div
          className="grid grid-cols-1 gap-3 rounded-xl p-3 sm:grid-cols-3"
          style={{ background: "rgba(0,212,170,0.06)", border: "1px solid rgba(0,212,170,0.18)" }}
        >
          <div>
            <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Already accounted</p>
            <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              {stage.prior_cumulative}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Stage maximum</p>
            <p className="mt-1 text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              {stage.stage_maximum}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>Exact cumulative ceiling</p>
            <p className="mt-1 text-xl font-display font-bold" style={{ color: "var(--turquoise)" }}>
              {stage.exact_cumulative_ceiling}
            </p>
          </div>
        </div>

        {card.approval_notice && (
          <div className="flex items-start gap-2">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" style={{ color: "var(--gold)" }} />
            <p className="break-words text-[11px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {card.approval_notice}
            </p>
          </div>
        )}

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            onClick={() => yes && onChoose("yes", yes.label)}
            className="min-w-0 flex-1 rounded-xl px-4 py-3 text-sm font-bold transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            {yes?.label ?? "Approve screenplay and direction"}
          </button>
          <button
            onClick={() => onChoose("no", no?.label ?? "Keep editing")}
            className="rounded-xl px-4 py-3 text-sm font-semibold transition-all hover:brightness-110 active:scale-[0.98]"
            style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
          >
            {no?.label ?? "Keep editing"}
          </button>
        </div>
      </div>
    </GlassCard>
  );
}

// --- style-draft card (conversational "make me a new style…", C22) -------
// A text-only preview of the producer's drafted style (name + one-sentence
// look) with a Save / Not-quite pair, same shape as ConfirmActionCard. No
// image preview here on purpose (checklist's cost cap — a preview render
// would be paid generation with no quote gate; text-only confirm instead).
function StyleDraftCard({
  card,
  onChoose,
}: {
  card: ChatCard;
  onChoose: (value: string, label: string) => void;
}) {
  const yes = card.options?.find((o) => o.value === "yes");
  const no = card.options?.find((o) => o.value === "no");
  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Palette size={16} style={{ color: "var(--turquoise)" }} />
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>
      {card.body && (
        <p
          className="text-sm leading-relaxed rounded-lg px-3 py-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
        >
          {card.body}
        </p>
      )}
      <div className="flex items-center gap-2">
        <button
          onClick={() => yes && onChoose("yes", yes.label)}
          className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98]"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {yes?.label ?? "Save this style"}
        </button>
        <button
          onClick={() => onChoose("no", no?.label ?? "Not quite")}
          className="px-4 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
          style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
        >
          {no?.label ?? "Not quite"}
        </button>
      </div>
      <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        Saved styles show up on the Profile page, and you can say &quot;use it&quot; on any future video.
      </p>
    </GlassCard>
  );
}

// --- channel-DNA digest card ("learn this channel", C42) ------------------
// Per-learner status rows (learned/skipped/failed + a summary sentence),
// per-field rows (label, value, provenance caption, a Revert button wherever
// the backend says there's a prior value to revert to), a free-text
// correction box, and a "keep everything" close-out — mirrors the "no
// action needed by default" design: nothing here is a checkbox the creator
// must tick, every field is already saved (C41's write-then-review), these
// are just ways to undo or fix one. Absent fields/learners are simply not
// rendered (fail-safe, never "undefined" in the copy).
function DnaDigestCard({
  card,
  onAction,
}: {
  card: ChatCard;
  onAction: (selections: Record<string, string>, label: string) => void;
}) {
  const [correction, setCorrection] = useState("");
  const learners: ChatDnaLearnerRow[] = card.learners ?? [];
  const fields: ChatDnaFieldRow[] = card.fields ?? [];
  const patterns: ChatDnaPatternRow[] = card.patterns ?? [];

  const statusIcon = (status: ChatDnaLearnerRow["status"]) => {
    if (status === "learned") return <CheckCircle2 size={14} style={{ color: "var(--turquoise)" }} aria-hidden />;
    if (status === "failed") return <XCircle size={14} style={{ color: "var(--gold)" }} aria-hidden />;
    return <MinusCircle size={14} style={{ color: "var(--text-tertiary)" }} aria-hidden />;
  };
  // Never color-only: every row also carries the word (Learned/Skipped/Not
  // available) alongside the icon.
  const statusLabel = (status: ChatDnaLearnerRow["status"]) =>
    status === "learned" ? "Learned" : status === "failed" ? "Not available" : "Skipped";

  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Dna size={16} style={{ color: "var(--turquoise)" }} />
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>

      {card.header && (
        <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{card.header}</p>
      )}

      {learners.length > 0 && (
        <div
          className="flex flex-col gap-2 rounded-lg px-3 py-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          {learners.map((l) => (
            <div key={l.name} className="flex items-start gap-2 text-xs">
              <span className="mt-0.5 shrink-0">{statusIcon(l.status)}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="font-medium" style={{ color: "var(--text-primary)" }}>{l.label}</span>
                  <span style={{ color: "var(--text-tertiary)" }}>· {statusLabel(l.status)}</span>
                </div>
                {l.summary && <p style={{ color: "var(--text-secondary)" }}>{l.summary}</p>}
              </div>
            </div>
          ))}
        </div>
      )}

      {fields.length > 0 && (
        <div className="flex flex-col gap-2">
          {fields.map((f) => (
            <div
              key={f.field}
              className="flex items-start justify-between gap-2 rounded-lg px-3 py-2"
              style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
            >
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium" style={{ color: "var(--text-primary)" }}>{f.label}</div>
                <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{f.value}</div>
                {(f.learner || f.at) && (
                  <div className="text-[11px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    via {f.learner ?? "unknown"}{f.at ? ` · ${new Date(f.at).toLocaleDateString()}` : ""}
                  </div>
                )}
                {f.overridden_by && (
                  <div className="text-[11px] mt-1 flex items-start gap-1" style={{ color: "var(--gold)" }}>
                    <PencilLine size={11} className="mt-0.5 shrink-0" aria-hidden />
                    <span>Overridden by your standing direction: &ldquo;{f.overridden_by}&rdquo;</span>
                  </div>
                )}
              </div>
              {f.revertable && (
                <button
                  onClick={() => onAction({ channel_dna_digest: "revert", field: f.field }, `Revert ${f.label}`)}
                  className="shrink-0 inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all hover:brightness-110"
                  style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
                >
                  <RotateCcw size={11} aria-hidden /> Revert
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {patterns.length > 0 && (
        <div
          className="flex flex-col gap-2 rounded-lg px-3 py-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--text-primary)" }}>
            <Activity size={12} aria-hidden /> Patterns from your analytics
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
            Nothing here takes effect until you confirm it.
          </p>
          {patterns.map((p) => (
            <div key={p.id} className="flex items-start justify-between gap-2">
              <div className="min-w-0 flex-1">
                <p className="text-xs" style={{ color: "var(--text-secondary)" }}>{p.pattern}</p>
                {p.evidence_summary && (
                  <p className="text-[11px] mt-0.5" style={{ color: "var(--text-tertiary)" }}>{p.evidence_summary}</p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-1">
                <button
                  onClick={() => onAction({ channel_dna_digest: "confirm_pattern", pattern_id: p.id }, "Confirm pattern")}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all hover:brightness-110"
                  style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--turquoise)" }}
                >
                  <CheckCircle2 size={11} aria-hidden /> Confirm
                </button>
                <button
                  onClick={() => onAction({ channel_dna_digest: "retire_pattern", pattern_id: p.id }, "Retire pattern")}
                  className="inline-flex items-center gap-1 px-2 py-1 rounded-lg text-[11px] font-medium transition-all hover:brightness-110"
                  style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-tertiary)" }}
                >
                  <XCircle size={11} aria-hidden /> Retire
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {(card.standing_directions?.length ?? 0) > 0 && (
        <div
          className="flex flex-col gap-1.5 rounded-lg px-3 py-2"
          style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
        >
          <div className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--text-primary)" }}>
            <History size={12} aria-hidden /> Your standing directions
          </div>
          <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
            These apply to every future build, on top of whatever's learned above.
          </p>
          <ul className="flex flex-col gap-1">
            {(card.standing_directions ?? []).map((text, i) => (
              <li key={i} className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {text}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-1.5">
        <label htmlFor="dna-digest-correction" className="text-xs" style={{ color: "var(--text-secondary)" }}>
          Something off? Tell me what to fix:
        </label>
        <div className="flex items-center gap-2">
          <input
            id="dna-digest-correction"
            type="text"
            name="dna-correction"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            placeholder="e.g. actually the voice is more playful"
            autoComplete="off"
            className="flex-1 min-w-0 px-3 py-2 rounded-lg text-xs"
            style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)" }}
          />
          <button
            onClick={() => {
              const text = correction.trim();
              if (!text) return;
              onAction({ channel_dna_digest: "correct", correction_text: text }, "Save correction");
              setCorrection("");
            }}
            disabled={!correction.trim()}
            className="shrink-0 inline-flex items-center gap-1 px-3 py-2 rounded-lg text-xs font-medium transition-all hover:brightness-110 disabled:opacity-50"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
          >
            <PencilLine size={12} aria-hidden /> Save
          </button>
        </div>
      </div>

      <button
        onClick={() => onAction({ channel_dna_digest: "keep" }, "Keep everything")}
        className="px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98]"
        style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
      >
        Keep everything
      </button>
    </GlassCard>
  );
}

// --- secure key card (onboarding key intake) ------------------------------
// The same masked input the Settings/keys page uses, rendered inline in chat.
// On save it POSTs the key straight to /api/chat/onboarding-key (vault path) —
// the raw key never enters the message stream — then advances onboarding with a
// benign selection. The Claude-upgrade step passes a "skip" option so we show a
// Skip button; the required Kie step has none.
function SecureKeyCard({
  card,
  onSaved,
  onSkip,
}: {
  card: ChatCard;
  onSaved: (provider: string) => void;
  onSkip: () => void;
}) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const skippable = !!card.options?.find((o) => o.value === "skip");

  async function save() {
    const v = value.trim();
    if (!v || saving) return;
    setSaving(true);
    setError(null);
    try {
      const res = await setOnboardingKey(v);
      if (!res.ok) {
        setError(res.message);
        setSaving(false);
        return;
      }
      setValue("");
      onSaved(res.provider ?? "kie");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save that — try again.");
      setSaving(false);
    }
  }

  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Sparkles size={16} style={{ color: "var(--turquoise)" }} />
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>
      <PasswordInput
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); save(); } }}
        placeholder={card.placeholder ?? "Paste your API key — it stays hidden"}
        autoFocus
        disabled={saving}
        error={error ?? undefined}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={save}
          disabled={!value.trim() || saving}
          className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-40"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {saving ? "Saving…" : "Save key 🔒"}
        </button>
        {skippable && (
          <button
            onClick={onSkip}
            disabled={saving}
            className="px-4 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
            style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
          >
            Skip
          </button>
        )}
      </div>
      <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        🔒 Saved straight to your encrypted vault — it never appears in the chat.
      </p>
    </GlassCard>
  );
}

// --- proposed-prompt card (full prompt edit access) -----------------------
// The co-pilot's rewritten prompt, shown in an editable box so the creator can
// tweak it directly before applying. Apply sends back whatever's in the box; the
// backend redraws/re-animates/re-does just that one shot. Keep refining in words
// works too (that arrives as a fresh card via the message box).
function PromptProposalCard({
  card,
  onApply,
  onCancel,
}: {
  card: ChatCard;
  onApply: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState(card.body ?? "");
  const apply = card.options?.find((o) => o.value === "yes");
  const cancel = card.options?.find((o) => o.value === "no");
  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Sparkles size={16} style={{ color: "var(--turquoise)" }} />
        <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={6}
        spellCheck={false}
        className="w-full rounded-xl px-3 py-2 text-sm leading-relaxed resize-y outline-none"
        style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)", color: "var(--text-primary)", minHeight: 120 }}
      />
      <div className="flex items-center gap-2">
        <button
          onClick={() => onApply(text.trim())}
          disabled={!text.trim()}
          className="flex-1 px-4 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98] disabled:opacity-40"
          style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
        >
          {apply?.label ?? "Apply"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-2.5 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
          style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
        >
          {cancel?.label ?? "Cancel"}
        </button>
      </div>
      <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        Edit the prompt above, or tell me how to adjust it in the message box.
      </p>
    </GlassCard>
  );
}

// --- selector cards -------------------------------------------------------

// S9-4: the LOOK option's preview image never had an onError fallback (a dead
// icon file swaps to a broken-image glyph instead of the label — contrast
// SceneBoardsGrid's C15b onError -> label pattern above). Fixed here for the
// existing preset picker (now server-sourced, checklist §C21b).
function PresetOptionImage({ preset }: { preset: StyleDescription }) {
  const [broken, setBroken] = useState(false);
  if (broken) {
    return (
      <div
        className="w-20 h-20 rounded-lg flex items-center justify-center text-center px-1"
        style={{ background: "var(--bg-surface)" }}
      >
        <span className="text-[9px] leading-tight" style={{ color: "var(--text-secondary)" }}>{preset.label}</span>
      </div>
    );
  }
  return (
    <img
      src={styleDescriptionIcon(preset.id)}
      alt={preset.label}
      onError={() => setBroken(true)}
      className="w-20 h-20 rounded-lg object-cover"
      style={{ background: "var(--bg-surface)" }}
    />
  );
}

function SelectorCards({
  cards,
  picks,
  onToggle,
  onSetValue,
  onSubmit,
  canSubmit,
  styleDescriptions,
}: {
  cards: ChatCard[];
  picks: Record<string, string | string[]>;
  onToggle: (card: ChatCard, value: string) => void;
  onSetValue: (cardId: string, value: string) => void;
  onSubmit: () => void;
  canSubmit: boolean;
  styleDescriptions: StyleDescription[];
}) {
  const isSelected = (card: ChatCard, value: string) => {
    const v = picks[card.id];
    return Array.isArray(v) ? v.includes(value) : v === value;
  };
  return (
    <GlassCard className="flex flex-col gap-5">
      {cards.map((card) => (
        <div key={card.id}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--text-tertiary)" }}>
              {card.label}
            </span>
            {isSliderCard(card) && (
              <span className="text-sm font-semibold" style={{ color: "var(--turquoise)" }}>
                {formatLength(effLengthSecs(card, picks))}
              </span>
            )}
          </div>
          {cardKind(card) === "connect" && (
            <ConnectButton kind={card.id} />
          )}
          {cardKind(card) === "look_engine" ? (
            // The 5-preset structural "Look Engine" gallery — the SAME
            // component + query as the New Video flow's gallery (checklist
            // §C21b), rendered as one more selector card alongside "style"
            // (both axes can appear together; neither clobbers the other).
            <StylePresetGallery
              selectedId={(picks[card.id] as string) || ""}
              onSelect={(id) => onToggle(card, id)}
            />
          ) : isSliderCard(card) ? (
            <div className="px-1">
              <input
                type="range"
                min={LENGTH_MIN}
                max={LENGTH_MAX}
                step={LENGTH_STEP}
                value={effLengthSecs(card, picks)}
                onChange={(e) => onSetValue(card.id, e.target.value)}
                className="w-full cursor-pointer"
                style={{ accentColor: "var(--turquoise)" }}
              />
              <div className="flex justify-between text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
                <span>1 min</span>
                <span>30 min</span>
              </div>
              <p className="text-[11px] mt-2 leading-snug" style={{ color: "var(--text-secondary)" }}>
                {lengthHint(effLengthSecs(card, picks))}
              </p>
            </div>
          ) : (
          <div className="flex flex-wrap gap-2">
            {(card.options ?? []).map((opt) => {
              const sel = isSelected(card, opt.value);
              // Style options render the same preview image as the New Video flow.
              const preset = styleDescriptionById(styleDescriptions, opt.value);
              if (preset) {
                const isRec = card.recommended_value === opt.value;
                return (
                  <button
                    key={opt.value}
                    onClick={() => onToggle(card, opt.value)}
                    title={isRec ? (card.recommended_hint || opt.hint) : opt.hint}
                    className="relative flex flex-col items-center gap-1.5 p-2 rounded-xl transition-all active:scale-[0.98]"
                    style={{
                      background: sel ? "rgba(0,212,170,0.1)" : "var(--bg-deep)",
                      border: `1px solid ${sel || isRec ? "var(--turquoise)" : "var(--border-subtle)"}`,
                    }}
                  >
                    {isRec && (
                      <span
                        className="absolute -top-2 left-1/2 -translate-x-1/2 text-[8px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded-full whitespace-nowrap"
                        style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
                      >
                        ✨ Recommended
                      </span>
                    )}
                    <PresetOptionImage preset={preset} />
                    <span
                      className="text-xs font-medium"
                      style={{ color: sel || isRec ? "var(--turquoise)" : "var(--text-secondary)" }}
                    >
                      {opt.label}
                    </span>
                  </button>
                );
              }
              return (
                <button
                  key={opt.value}
                  onClick={() => onToggle(card, opt.value)}
                  title={opt.hint}
                  className="px-4 py-2 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
                  style={{
                    background: sel ? "var(--turquoise)" : "var(--bg-deep)",
                    color: sel ? "var(--bg-void)" : "var(--text-secondary)",
                    border: `1px solid ${sel ? "var(--turquoise)" : "var(--border-subtle)"}`,
                  }}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
          )}
        </div>
      ))}
      <div className="flex justify-end">
        <ActionButton onClick={onSubmit} disabled={!canSubmit} icon={ArrowRight}>
          Continue
        </ActionButton>
      </div>
    </GlassCard>
  );
}

// --- production plan ------------------------------------------------------

function ProductionPlanCard({
  plan,
  onApprove,
  styleDescriptions,
}: {
  plan: ProductionPlan;
  onApprove: (productionStyleId: ProductionStyleId) => void;
  styleDescriptions: StyleDescription[];
}) {
  // Surface the visual style so the creator confirms what will actually generate.
  // An explicit pick WINS over the reference (modeling no longer clobbers it), so
  // show the picked look first; only fall back to "matched from reference".
  const spec = (plan.spec ?? {}) as {
    reference_url?: string;
    visual_style_label?: string;
    visual_style?: string;
    detected_style_label?: string;
    video_length_minutes?: number;
  };
  const [productionStyleId, setProductionStyleId] = useState<ProductionStyleId | "">("");
  // Server-sourced label lookup (checklist §C21b) — was a hardcoded
  // PRESET_LABELS dict here, a THIRD copy of the same six ids/labels.
  const picked = spec.visual_style_label
    || (spec.visual_style
          ? (styleDescriptionById(styleDescriptions, spec.visual_style)?.label || spec.visual_style)
          : "");
  const styleText = picked
    || (spec.reference_url
          ? (spec.detected_style_label
              ? `Matched from your reference — looks like ${spec.detected_style_label}`
              : "Matched from your reference video")
          : "Cinematic (default)");
  return (
    <GlassCard className="flex flex-col gap-4" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Clapperboard size={18} style={{ color: "var(--turquoise)" }} />
        <span className="font-display font-bold text-lg" style={{ color: "var(--text-primary)" }}>
          Your production plan
        </span>
      </div>

      <Section title="Look">
        <p className="text-sm flex items-center gap-2" style={{ color: "var(--text-secondary)" }}>
          <Palette size={14} className="shrink-0" style={{ color: "var(--turquoise)" }} />
          {styleText}
        </p>
      </Section>

      <ProductionStyleSelector
        selectedId={productionStyleId}
        onSelect={setProductionStyleId}
        durationMinutes={Number(spec.video_length_minutes || 10)}
      />

      {plan.story_concept && (
        <Section title="The story">
          <p className="text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>{plan.story_concept}</p>
        </Section>
      )}

      {!!plan.recommended_titles?.length && (
        <Section title="Title ideas">
          <ul className="flex flex-col gap-1.5">
            {plan.recommended_titles!.map((t, i) => (
              <li key={i} className="text-sm flex items-start gap-2" style={{ color: "var(--text-primary)" }}>
                <CheckCircle2 size={14} className="mt-0.5 shrink-0" style={{ color: "var(--turquoise)" }} />
                {t}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {!!plan.thumbnail_concepts?.length && (
        <Section title="Thumbnail concepts">
          <ul className="flex flex-col gap-1.5">
            {plan.thumbnail_concepts!.map((t, i) => (
              <li key={i} className="text-sm flex items-start gap-2" style={{ color: "var(--text-secondary)" }}>
                <span style={{ color: "var(--gold)" }}>•</span>
                {t}
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* C15a: real, server-sourced quote so "Make it" is informed consent, not
          a blind paid tap. Absent on an older backend build — the card simply
          skips this section, unchanged from before. */}
      {!!plan.estimated_cost_text && (
        <Section title="Estimated cost">
          <p className="text-sm flex items-center gap-2" style={{ color: "var(--text-secondary)" }}>
            <CircleDollarSign size={14} className="shrink-0" style={{ color: "var(--gold)" }} />
            {plan.estimated_cost_text}
          </p>
        </Section>
      )}

      <div className="flex items-center justify-end gap-3 pt-1">
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Want changes? Just tell me below.</span>
        <ActionButton
          onClick={() => productionStyleId && onApprove(productionStyleId)}
          disabled={!productionStyleId}
          icon={Sparkles}
        >
          Make it
        </ActionButton>
      </div>
    </GlassCard>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs font-semibold uppercase tracking-wide mb-2" style={{ color: "var(--text-tertiary)" }}>
        {title}
      </div>
      {children}
    </div>
  );
}

// --- created confirmation + live friendly progress tracker ----------------

// Bug fix (2026-07-27, reported live: two "Standard production" progress
// cards stacked in the chat at once — one saying "Working on Script — 7s",
// the other "Writing the script…"). Root cause: this component used to open
// its OWN `useQuery(["video", videoId])` + its OWN `usePipelineSSE(...)` and
// render its OWN embedded `<ChatPipelineMap>` — a second, independently
// ticking instance of the exact same stepper, right next to the ALREADY
// top-level `dockedVideo`/`dockProgress` (declared once, above, keyed off
// `resultCardsVideoId` — which equals `createdVideoId` whenever this card is
// showing) that drives the standalone `<ChatPipelineMap>` rendered directly
// below this card in `activeZone`. Two component instances subscribing to
// the same SSE stream each keep their own local `runningSince`/`flavorIdx`
// state, so they drift out of sync and show different text at the same
// moment even though the underlying data is identical. Fix: this card only
// ever renders the "Building your video…" header — `video`/`stageChange` are
// now props from the SAME single source the standalone map below uses, so
// there is exactly one stepper on screen, not two.
function CreatedCard({
  videoId,
  video,
  stageChange,
  taskProgress,
}: {
  videoId: string;
  video: VideoDetail | undefined;
  stageChange: SSEStageChangeEvent | null;
  taskProgress: SSETaskProgressEvent | null;
}) {
  const currentStatus = stageChange?.current_status || video?.status;
  const isDone = ["rendered", "uploaded", "uploaded_draft", "published", "done"].includes(
    String(currentStatus || ""),
  );
  // "idea_logged" is the video's pre-work status (routes/videos.py::create_video
  // sets it before anything has run) — this card renders as soon as a video id
  // durably exists on this thread (phase==="created" on EVERY co-pilot reply
  // once a conversation is bound to a video, not just the turn that actually
  // started work), so "Building your video…" was claiming work was underway
  // when the creator hadn't tapped a single confirm card yet. Ryan flagged
  // this as exactly the kind of copy that reads as spend-has-started when it
  // hasn't (2026-07-27). Distinguish "nothing has run yet" from "something is
  // actually in progress" instead of collapsing both into one claim.
  const notStarted = String(currentStatus || "") === "idea_logged";

  return (
    <GlassCard className="flex flex-col gap-4" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center justify-between gap-4">
        <div className="font-display font-bold text-base" style={{ color: "var(--text-primary)" }}>
          {isDone
            ? "Your video is ready to review 🎬"
            : notStarted
              ? "Video started — nothing's running yet"
              : "Building your video…"}
        </div>
        <Link
          href={`/pipeline/${videoId}`}
          className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
          style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
        >
          {isDone ? "Review it" : "Open it"} <ArrowRight size={14} />
        </Link>
      </div>

      {/* The live stepper/progress block lives ONLY in the standalone
          `<ChatPipelineMap>` rendered right after this card (activeZone,
          below) — not duplicated here. See fix note above. */}
      {!taskProgress?.message && (
        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {isDone
            ? "Take a look and tell me if you want any changes."
            : "I'll keep working — follow along here or ask for a change anytime."}
        </div>
      )}
    </GlassCard>
  );
}
