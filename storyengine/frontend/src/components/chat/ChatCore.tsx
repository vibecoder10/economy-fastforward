"use client";

// The shared chat engine. Lives in TWO places:
//   - the home screen (un-docked) — the creative producer + "Start Here" onboarding,
//   - the in-pipeline dock (docked, scoped to one videoId) — the co-pilot that can
//     run any pipeline action by voice, with paid/destructive actions held behind a
//     one-tap confirm card.
// All intelligence is server-side (/api/chat). `docked` gates the home-only bits
// (welcome hero, auto-onboarding, OAuth resume) and the layout (composer + width).
// ChatHome is a thin wrapper over <ChatCore /> so the home flow is unchanged.

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Send, Loader2, CheckCircle2, ArrowRight, Clapperboard, AlertTriangle, Youtube, HardDrive, TrendingUp, Eye, Palette, CalendarDays, Lightbulb, Compass, Activity, Link2, Settings2, History, Plus, Paperclip, X, CircleDollarSign, Dna, RotateCcw, MinusCircle, XCircle, PencilLine } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import { useStyleDescriptions, styleDescriptionIcon, styleDescriptionById } from "@/hooks/use-style-descriptions";
import type { StyleDescription } from "@/lib/api";
import { StylePresetGallery } from "@/components/style/StylePresetGallery";
import { ChatPipelineMap } from "@/components/chat/ChatPipelineMap";
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
  type ChatCard,
  type ChatCardImage,
  type ChatDnaFieldRow,
  type ChatDnaLearnerRow,
  type ChatDnaPatternRow,
  type ChatTurnRequest,
  type ProductionPlan,
  type ProductionStyleId,
  type SuggestedModels,
  type SuggestedModelVideo,
  type ChatConversationSummary,
} from "@/lib/api";
import { PasswordInput } from "@/components/forms";
import { withMediaAuth } from "@/lib/utils";

// localStorage keys for the OAuth round-trip during onboarding: the connect
// button stashes the active conversation so ChatCore can resume it when Google
// sends the user back to /?connected=yt|drive.
const CHAT_CID_KEY = "se_chat_cid";
// The dock caches a SEPARATE conversation id per video (instant reload). Never
// reuse the tenant-level home thread for a video's co-pilot, and vice versa.
const dockCidKey = (videoId: string) => `se_chat_cid_${videoId}`;

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
type CardKind = "prompt_apply" | "confirm_action" | "custom_film_approval" | "secure_key" | "connect" | "images" | "look_engine" | "style_draft" | "channel_dna_digest" | "generic";

function cardKind(card: ChatCard): CardKind {
  if (card.id === "prompt_apply") return "prompt_apply";
  if (card.id === "confirm_action") return "confirm_action";
  if (card.id === "custom_film_approval") return "custom_film_approval";
  if (card.id === "secure_key") return "secure_key";
  if (card.id === "connect_yt" || card.id === "connect_drive") return "connect";
  if (card.id === "look_engine") return "look_engine";
  if (card.id === "style_draft") return "style_draft";
  if (card.id === "channel_dna_digest") return "channel_dna_digest";
  if ((card.images?.length ?? 0) > 0) return "images";
  return "generic";
}

const ACTION_CARD_KINDS: ReadonlySet<CardKind> = new Set(["prompt_apply", "confirm_action", "custom_film_approval", "secure_key", "style_draft", "channel_dna_digest"]);

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

export function ChatCore({
  videoId,
  docked = false,
  uiContext,
}: {
  videoId?: string;
  docked?: boolean;
  uiContext?: { tab?: string; scene?: number; index?: number } | null;
}) {
  const queryClient = useQueryClient();
  const { data: dockedVideo } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId!),
    enabled: docked && !!videoId,
  });
  const dockProgress = usePipelineSSE({
    enabled: docked && !!videoId,
    videoId,
    onStageChange: () => {
      if (videoId) queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    },
    onTaskProgress: (event) => {
      if (videoId && event.status !== "running") {
        queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      }
    },
  });
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [createdVideoId, setCreatedVideoId] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, string | string[]>>({});
  const [checking, setChecking] = useState(true); // first-load onboarding-status / hydrate
  const [suggested, setSuggested] = useState<SuggestedModels | null>(null); // "worth modeling" (home)
  // Files dropped/attached but not yet sent with a message (home chat only).
  const [attachments, setAttachments] = useState<{ id: string; filename: string; kind: string }[]>([]);
  const [uploadingFiles, setUploadingFiles] = useState(0);
  const endRef = useRef<HTMLDivElement>(null);
  const dockScrollRef = useRef<HTMLDivElement>(null);
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
      const el = dockScrollRef.current;
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
    if (userBubble) setMessages((m) => [...m, { role: "user", text: userBubble }]);
    setSending(true);
    setPicks({});
    try {
      const res = await sendChatTurn({
        ...req,
        conversation_id: conversationId ?? req.conversation_id ?? null,
        // The dock tags every turn with its video so the backend gates paid actions.
        video_id: docked ? videoId ?? null : req.video_id ?? null,
        // ...and what the creator is viewing, so "this image" resolves.
        ui_context: docked ? uiContext ?? null : null,
      });
      setConversationId(res.conversation_id);
      try { localStorage.setItem(cidKey, res.conversation_id); } catch { /* private mode */ }
      // Only the home flow flips into the "created" tracker view; the dock stays a
      // plain thread (live progress comes from the pipeline page itself).
      if (res.video_id && !docked) setCreatedVideoId(res.video_id);
      setMessages((m) => [
        ...m,
        { role: "assistant", text: res.assistant_text, cards: res.cards, plan: res.plan },
      ]);
    } catch (e) {
      setMessages((m) => [
        ...m,
        { role: "assistant", text: e instanceof Error ? e.message : "Something went wrong — try again." },
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
  useEffect(() => {
    if (docked) return; // the dock hydrates instead — no onboarding here
    if (autoTriedRef.current) return;
    autoTriedRef.current = true;
    let cancelled = false;

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
        if (!cancelled) await turn({ conversation_id: cid, selections: sel });
        if (!cancelled) setChecking(false);
      })();
      return () => { cancelled = true; };
    }

    (async () => {
      // Resume where you left off: if a conversation is saved, hydrate it instead of
      // dropping into a blank welcome (chat no longer vanishes on refresh).
      let savedCid: string | null = null;
      try { savedCid = localStorage.getItem(CHAT_CID_KEY); } catch { /* private mode */ }
      if (savedCid) {
        try {
          const data = await getChatConversationById(savedCid);
          if (!cancelled && data.messages?.length) {
            setConversationId(data.conversation_id);
            setMessages(data.messages.map((m) => ({ role: m.role, text: m.text, cards: m.cards, plan: m.plan })));
            setCreatedVideoId(data.video_id ?? null);
            setChecking(false);
            return;
          }
        } catch { /* stale id — fall through to the normal welcome */ }
      }
      try {
        const s = await getOnboardingStatus();
        const brandNew =
          !s.completed && !s.steps?.first_video_created && !s.steps?.channel_configured;
        if (!cancelled && brandNew) {
          await turn({ start_onboarding: true }, "Help me get set up");
          return; // keep `checking` until the first turn renders (no welcome flash)
        }
      } catch {
        // status check failed — just show the normal welcome
      }
      // Returning, onboarded creators get the clean welcome; a fresh modeled-idea
      // pitch is one click away via the "Suggest a video idea" button (turn({})).
      if (!cancelled) setChecking(false);
    })();
    return () => {
      cancelled = true;
    };
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
      setCreatedVideoId(data.video_id ?? null);
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
        <CreatedCard videoId={createdVideoId} />
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
        <div ref={dockScrollRef} className="flex-1 overflow-y-auto px-4 pt-4 pb-44 flex flex-col gap-4">
          {!started && (
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{DOCK_HINT}</p>
          )}
          <MessageThread messages={messages} />
          {sending && <Thinking />}
          {activeZone}
          <div ref={endRef} />
        </div>
        <div className="absolute bottom-0 left-0 right-0 px-3 py-3" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
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
  if (!started) {
    return (
      <div className="max-w-3xl mx-auto flex flex-col items-center text-center pt-10 md:pt-20">
        <div className="w-full flex justify-end mb-2">
          <ChatHistoryMenu onPick={loadConversation} onNew={newChat} disabled={sending} />
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

  // --- HOME conversation ---
  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-4 pb-32">
      <div className="flex justify-end -mb-1">
        <ChatHistoryMenu onPick={loadConversation} onNew={newChat} disabled={sending} />
      </div>
      <MessageThread messages={messages} />

      {sending && <Thinking />}

      {/* Active zone: cards, plan, or created confirmation */}
      {activeZone}

      <div ref={endRef} />

      {/* composer pinned at the bottom of the shell */}
      <div className="fixed bottom-0 left-0 right-0 md:left-60 px-4 py-4" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
        <div className="max-w-3xl mx-auto">
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
}: {
  onPick: (cid: string) => void;
  onNew: () => void;
  disabled?: boolean;
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
        setItems(await listChatConversations(20));
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
              <div className="px-3 py-2 text-xs" style={{ color: "var(--text-tertiary)" }}>No past chats yet.</div>
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
function CustomFilmApprovalCard({
  card,
  onChoose,
}: {
  card: ChatCard;
  onChoose: (value: string, label: string) => void;
}) {
  const yes = card.options?.find((o) => o.value === "yes");
  const no = card.options?.find((o) => o.value === "no");
  const sections = card.custom_film_sections ?? [];
  const totals = card.custom_film_totals;
  const duration = totals
    ? `${Math.floor(totals.duration_seconds / 60)}:${String(totals.duration_seconds % 60).padStart(2, "0")}`
    : "—";
  const remotionLocked = card.finishing_engine === "remotion";

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
            {remotionLocked ? "Remotion locked" : "FFmpeg finishing"}
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

function CreatedCard({ videoId }: { videoId: string }) {
  const queryClient = useQueryClient();
  const { data: video } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });
  const progress = usePipelineSSE({
    videoId,
    onStageChange: () => {
      queryClient.invalidateQueries({ queryKey: ["video", videoId] });
    },
    onTaskProgress: (e) => {
      if (e.status !== "running") {
        queryClient.invalidateQueries({ queryKey: ["video", videoId] });
      }
    },
  });

  const currentStatus = progress.lastStageChange?.current_status || video?.status;
  const isDone = ["rendered", "uploaded", "uploaded_draft", "published", "done"].includes(
    String(currentStatus || ""),
  );

  return (
    <GlassCard className="flex flex-col gap-4" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center justify-between gap-4">
        <div className="font-display font-bold text-base" style={{ color: "var(--text-primary)" }}>
          {isDone ? "Your video is ready to review 🎬" : "Building your video…"}
        </div>
        <Link
          href={`/pipeline/${videoId}`}
          className="shrink-0 inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-semibold transition-all hover:brightness-110"
          style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
        >
          {isDone ? "Review it" : "Open it"} <ArrowRight size={14} />
        </Link>
      </div>

      <ChatPipelineMap
        video={video}
        stageChange={progress.lastStageChange}
        taskProgress={progress.lastTaskProgress}
        connected={progress.isConnected}
      />

      {!progress.lastTaskProgress?.message && (
        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {isDone
            ? "Take a look and tell me if you want any changes."
            : "I'll keep working — follow along here or ask for a change anytime."}
        </div>
      )}
    </GlassCard>
  );
}
