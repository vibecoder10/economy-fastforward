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
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Send, Loader2, CheckCircle2, ArrowRight, Clapperboard, AlertTriangle, Youtube, HardDrive, TrendingUp, Eye, Palette, CalendarDays, Lightbulb, Compass, Activity, Link2, Settings2, History, Plus, Paperclip, X } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import { visualPresetById } from "@/lib/visual-presets";
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
  type ChatCard,
  type ChatTurnRequest,
  type ProductionPlan,
  type SuggestedModels,
  type SuggestedModelVideo,
  type ChatConversationSummary,
} from "@/lib/api";
import { PasswordInput } from "@/components/forms";

// localStorage keys for the OAuth round-trip during onboarding: the connect
// button stashes the active conversation so ChatCore can resume it when Google
// sends the user back to /?connected=yt|drive.
const CHAT_CID_KEY = "se_chat_cid";
// The dock caches a SEPARATE conversation id per video (instant reload). Never
// reuse the tenant-level home thread for a video's co-pilot, and vice versa.
const dockCidKey = (videoId: string) => `se_chat_cid_${videoId}`;

// The 5 plain-English progress states, in order (mirrors status_map.FRIENDLY_STATE_ORDER).
const FRIENDLY_ORDER = [
  "Story Approved",
  "Script Ready",
  "Visuals Creating",
  "Video Rendering",
  "Ready for Review",
];

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
  const autoTriedRef = useRef(false);

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
  const actionCard = lastCards?.find((c) => c.id === "confirm_action" || c.id === "prompt_apply" || c.id === "secure_key") ?? null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
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
  // as chat_assets ids. Home chat only for now (the dock ignores attachments).
  async function attachFiles(files: FileList | File[]) {
    if (docked) return;
    const list = Array.from(files).slice(0, Math.max(0, 5 - attachments.length));
    for (const f of list) {
      setUploadingFiles((n) => n + 1);
      try {
        const res = await uploadChatAsset(f, conversationId);
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

  // The active zone (cards / plan / created confirmation), shared by both layouts.
  const activeZone = (
    <>
      {actionCard?.id === "prompt_apply" && !sending && (
        <PromptProposalCard
          key={`pp-${messages.length}`}
          card={actionCard}
          onApply={(text) => turn({ selections: { prompt_apply: "yes", prompt_text: text } }, "Apply this prompt")}
          onCancel={() => turn({ selections: { prompt_apply: "no" } }, "Cancel")}
        />
      )}
      {actionCard?.id === "confirm_action" && !sending && (
        <ConfirmActionCard
          card={actionCard}
          onChoose={(value, label) => turn({ selections: { confirm_action: value } }, label)}
        />
      )}
      {actionCard?.id === "secure_key" && !sending && (
        <SecureKeyCard
          key={`sk-${messages.length}`}
          card={actionCard}
          onSaved={(provider) => turn({ selections: { secure_key: "saved", key_provider: provider } }, "🔒 Key saved")}
          onSkip={() => turn({ selections: { secure_key: "skip" } }, "Skip for now")}
        />
      )}
      {activeCards && !actionCard && !activePlan && !sending && (
        <SelectorCards cards={activeCards} picks={picks} onToggle={togglePick} onSetValue={setPickValue} onSubmit={submitPicks} canSubmit={allCardsAnswered} />
      )}
      {activePlan && !sending && (
        <ProductionPlanCard plan={activePlan} onApprove={() => turn({ approve: true }, "Make it ✨")} />
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
        {/* pb-44: the confirm/prompt action cards render at the thread's end —
            with pb-28 their buttons could sit under the pinned composer overlay
            (creators saw the card label but no Do it button). */}
        <div className="flex-1 overflow-y-auto px-4 pt-4 pb-44 flex flex-col gap-4">
          {!started && (
            <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{DOCK_HINT}</p>
          )}
          <MessageThread messages={messages} />
          {sending && <Thinking />}
          {activeZone}
          <div ref={endRef} />
        </div>
        <div className="absolute bottom-0 left-0 right-0 px-3 py-3" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
          <Composer input={input} setInput={setInput} onSubmit={submitInput} sending={sending} placeholder="Ask or tell me what to do…" />
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
      {messages.map((m, i) => (
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
          </div>
        </motion.div>
      ))}
    </AnimatePresence>
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
  // File drop-in (home chat only — the dock doesn't pass these).
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
  return (
    <GlassCard className="flex flex-col gap-3" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-start gap-2">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: "var(--gold)" }} />
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>{card.label}</span>
      </div>
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

function SelectorCards({
  cards,
  picks,
  onToggle,
  onSetValue,
  onSubmit,
  canSubmit,
}: {
  cards: ChatCard[];
  picks: Record<string, string | string[]>;
  onToggle: (card: ChatCard, value: string) => void;
  onSetValue: (cardId: string, value: string) => void;
  onSubmit: () => void;
  canSubmit: boolean;
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
          {(card.id === "connect_yt" || card.id === "connect_drive") && (
            <ConnectButton kind={card.id} />
          )}
          {isSliderCard(card) ? (
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
              const preset = visualPresetById(opt.value);
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
                    <img
                      src={preset.icon}
                      alt={preset.label}
                      className="w-20 h-20 rounded-lg object-cover"
                      style={{ background: "var(--bg-surface)" }}
                    />
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

function ProductionPlanCard({ plan, onApprove }: { plan: ProductionPlan; onApprove: () => void }) {
  // Surface the visual style so the creator confirms what will actually generate.
  // An explicit pick WINS over the reference (modeling no longer clobbers it), so
  // show the picked look first; only fall back to "matched from reference".
  const spec = (plan.spec ?? {}) as { reference_url?: string; visual_style_label?: string; visual_style?: string; detected_style_label?: string };
  const PRESET_LABELS: Record<string, string> = {
    pixar_3d: "Pixar 3D", flat_2d: "2D Flat", realistic: "Realistic",
    anime: "Anime", watercolor: "Watercolor", comic: "Comic",
  };
  const picked = spec.visual_style_label
    || (spec.visual_style ? (PRESET_LABELS[spec.visual_style] || spec.visual_style) : "");
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

      <div className="flex items-center justify-end gap-3 pt-1">
        <span className="text-xs" style={{ color: "var(--text-tertiary)" }}>Want changes? Just tell me below.</span>
        <ActionButton onClick={onApprove} icon={Sparkles}>
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
  const [current, setCurrent] = useState("Story Approved");
  const [failed, setFailed] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  usePipelineSSE({
    videoId,
    onStageChange: (e) => {
      if (e.friendly) setCurrent(e.friendly);
      if (e.error_message) setFailed(e.error_message);
    },
    onTaskProgress: (e) => {
      if (e.status === "failed") setFailed(e.error || e.message || "Something needs a look.");
      else if (e.status === "running") {
        setFailed(null);
        if (e.message) setNote(e.message); // live "Drawing the pictures…" / "Recording the voiceover…"
      } else if (e.status === "completed" && e.message) {
        setNote(e.message);
      }
    },
  });

  const currentIdx = Math.max(0, FRIENDLY_ORDER.indexOf(current));
  const isDone = current === "Ready for Review";

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

      <div className="flex flex-col gap-2.5">
        {FRIENDLY_ORDER.map((label, i) => {
          const done = isDone || i < currentIdx;
          const active = !isDone && i === currentIdx;
          const isFailedStep = active && !!failed;
          return (
            <div key={label} className="flex items-center gap-3">
              <span className="shrink-0 w-5 h-5 flex items-center justify-center">
                {done ? (
                  <CheckCircle2 size={18} style={{ color: "var(--green)" }} />
                ) : isFailedStep ? (
                  <AlertTriangle size={16} style={{ color: "var(--orange)" }} />
                ) : active ? (
                  <Loader2 size={16} className="animate-spin" style={{ color: "var(--turquoise)" }} />
                ) : (
                  <span className="w-2 h-2 rounded-full" style={{ background: "var(--text-tertiary)", opacity: 0.5 }} />
                )}
              </span>
              <span
                className="text-sm"
                style={{
                  color: done
                    ? "var(--text-primary)"
                    : active
                      ? "var(--turquoise)"
                      : "var(--text-tertiary)",
                  fontWeight: active ? 600 : 400,
                }}
              >
                {label}
              </span>
            </div>
          );
        })}
      </div>

      {failed ? (
        <div
          className="text-xs rounded-lg px-3 py-2 flex items-start gap-2"
          style={{ background: "rgba(255, 120, 73, 0.1)", color: "var(--orange)", border: "1px solid rgba(255,120,73,0.2)" }}
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span>{failed} — you can ask me to try again below.</span>
        </div>
      ) : (
        <div className="text-xs" style={{ color: "var(--text-secondary)" }}>
          {isDone
            ? "Take a look and tell me if you want any changes."
            : note || "I'll keep working — follow along here or ask for a change anytime."}
        </div>
      )}
    </GlassCard>
  );
}
