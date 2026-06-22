"use client";

// Chat-first creative producer — the home screen. The creator describes a video
// in plain English; Claude (the producer, backend /api/chat) asks only what's
// missing, offers selector cards, proposes a plan, and on approval creates the
// video. This component owns the conversation UI; all intelligence is server-side.
// ponytail: cards/plan render in one "active zone" below the thread (answered
// choices collapse into a user bubble), so we never re-render stale interactivity.

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Send, Loader2, CheckCircle2, ArrowRight, Clapperboard, AlertTriangle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { usePipelineSSE } from "@/hooks/use-pipeline-sse";
import { visualPresetById } from "@/lib/visual-presets";
import {
  sendChatTurn,
  getOnboardingStatus,
  type ChatCard,
  type ChatTurnRequest,
  type ProductionPlan,
} from "@/lib/api";

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

// Length is a slider: 5 seconds → 30 minutes, in 5-second steps.
const LENGTH_MIN = 5;
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

// Minimal markdown for chat bubbles: **bold** -> <strong>; newlines are handled
// by CSS (whitespace-pre-wrap). ponytail: no markdown dependency for one feature.
function renderRich(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      part
    )
  );
}

export function ChatHome() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [createdVideoId, setCreatedVideoId] = useState<string | null>(null);
  const [picks, setPicks] = useState<Record<string, string | string[]>>({});
  const [checking, setChecking] = useState(true); // first-load onboarding-status check
  const endRef = useRef<HTMLDivElement>(null);
  const autoTriedRef = useRef(false);

  const started = messages.length > 0;
  const last = messages[messages.length - 1];
  const activeCards = !createdVideoId && last?.role === "assistant" ? last.cards : null;
  const activePlan = !createdVideoId && last?.role === "assistant" ? last.plan : null;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending, createdVideoId]);

  async function turn(req: ChatTurnRequest, userBubble?: string) {
    if (sending) return;
    if (userBubble) setMessages((m) => [...m, { role: "user", text: userBubble }]);
    setSending(true);
    setPicks({});
    try {
      const res = await sendChatTurn({ ...req, conversation_id: conversationId ?? req.conversation_id ?? null });
      setConversationId(res.conversation_id);
      if (res.video_id) setCreatedVideoId(res.video_id);
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

  // Auto-start the guided setup for genuinely brand-new users (no channel, no
  // videos, onboarding not completed). Established tenants get the normal welcome
  // and are never re-onboarded. Runs once; any failure falls back to the welcome.
  useEffect(() => {
    if (autoTriedRef.current) return;
    autoTriedRef.current = true;
    let cancelled = false;
    (async () => {
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
      if (!cancelled) setChecking(false);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function submitInput() {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    turn({ message: text }, text);
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
    // Slider cards default to LENGTH_DEFAULT if the creator never touched them.
    const sel: Record<string, string | string[]> = { ...picks };
    for (const c of activeCards) {
      if (isSliderCard(c) && sel[c.id] === undefined) sel[c.id] = String(LENGTH_DEFAULT);
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

  // --- first-load: checking whether to auto-start setup (avoids a welcome flash) ---
  if (!started && checking) {
    return (
      <div className="max-w-3xl mx-auto flex flex-col items-center justify-center pt-32">
        <Loader2 className="animate-spin" size={28} style={{ color: "var(--turquoise)" }} />
      </div>
    );
  }

  // --- welcome screen (no conversation yet) ---
  if (!started) {
    return (
      <div className="max-w-3xl mx-auto flex flex-col items-center text-center pt-10 md:pt-20">
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
        />

        <button
          onClick={() => turn({ start_onboarding: true }, "Help me get set up")}
          className="mt-4 inline-flex items-center gap-2 text-sm font-medium transition-colors hover:brightness-125"
          style={{ color: "var(--turquoise)" }}
        >
          <Sparkles size={14} /> New here? Start here — I'll set up your channel
        </button>

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
      </div>
    );
  }

  // --- conversation ---
  return (
    <div className="max-w-3xl mx-auto flex flex-col gap-4 pb-32">
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
              {m.role === "user" ? m.text : renderRich(m.text)}
            </div>
          </motion.div>
        ))}
      </AnimatePresence>

      {sending && (
        <div className="flex justify-start">
          <div
            className="rounded-2xl px-4 py-3 flex items-center gap-2"
            style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", color: "var(--text-secondary)" }}
          >
            <Loader2 size={16} className="animate-spin" style={{ color: "var(--turquoise)" }} />
            <span className="text-sm">Thinking…</span>
          </div>
        </div>
      )}

      {/* Active zone: cards, plan, or created confirmation */}
      {activeCards && !sending && (
        <SelectorCards cards={activeCards} picks={picks} onToggle={togglePick} onSetValue={setPickValue} onSubmit={submitPicks} canSubmit={allCardsAnswered} />
      )}
      {activePlan && !sending && (
        <ProductionPlanCard plan={activePlan} onApprove={() => turn({ approve: true }, "Make it ✨")} />
      )}
      {createdVideoId && (
        <CreatedCard videoId={createdVideoId} />
      )}

      <div ref={endRef} />

      {/* composer pinned at the bottom of the shell */}
      <div className="fixed bottom-0 left-0 right-0 md:left-60 px-4 py-4" style={{ background: "linear-gradient(to top, var(--bg-void) 70%, transparent)" }}>
        <div className="max-w-3xl mx-auto">
          <Composer input={input} setInput={setInput} onSubmit={submitInput} sending={sending} placeholder={createdVideoId ? "Ask for a change…" : "Reply…"} />
        </div>
      </div>
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
}: {
  input: string;
  setInput: (v: string) => void;
  onSubmit: () => void;
  sending: boolean;
  placeholder?: string;
  autoFocus?: boolean;
}) {
  return (
    <div
      className="flex items-end gap-2 rounded-2xl px-3 py-2 w-full"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border)" }}
    >
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
        rows={1}
        placeholder={placeholder}
        className="flex-1 bg-transparent resize-none outline-none text-sm py-2 px-1 max-h-40"
        style={{ color: "var(--text-primary)" }}
      />
      <button
        onClick={onSubmit}
        disabled={sending || !input.trim()}
        aria-label="Send"
        className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all enabled:hover:brightness-110 disabled:opacity-30"
        style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
      >
        {sending ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
      </button>
    </div>
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
                {formatLength(Number(picks[card.id] ?? LENGTH_DEFAULT))}
              </span>
            )}
          </div>
          {isSliderCard(card) ? (
            <div className="px-1">
              <input
                type="range"
                min={LENGTH_MIN}
                max={LENGTH_MAX}
                step={LENGTH_STEP}
                value={Number(picks[card.id] ?? LENGTH_DEFAULT)}
                onChange={(e) => onSetValue(card.id, e.target.value)}
                className="w-full cursor-pointer"
                style={{ accentColor: "var(--turquoise)" }}
              />
              <div className="flex justify-between text-[10px] mt-1" style={{ color: "var(--text-tertiary)" }}>
                <span>5 sec</span>
                <span>30 min</span>
              </div>
            </div>
          ) : (
          <div className="flex flex-wrap gap-2">
            {(card.options ?? []).map((opt) => {
              const sel = isSelected(card, opt.value);
              // Style options render the same preview image as the New Video flow.
              const preset = visualPresetById(opt.value);
              if (preset) {
                return (
                  <button
                    key={opt.value}
                    onClick={() => onToggle(card, opt.value)}
                    title={opt.hint}
                    className="flex flex-col items-center gap-1.5 p-2 rounded-xl transition-all active:scale-[0.98]"
                    style={{
                      background: sel ? "rgba(0,212,170,0.1)" : "var(--bg-deep)",
                      border: `1px solid ${sel ? "var(--turquoise)" : "var(--border-subtle)"}`,
                    }}
                  >
                    <img
                      src={preset.icon}
                      alt={preset.label}
                      className="w-20 h-20 rounded-lg object-cover"
                      style={{ background: "var(--bg-surface)" }}
                    />
                    <span
                      className="text-xs font-medium"
                      style={{ color: sel ? "var(--turquoise)" : "var(--text-secondary)" }}
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
  return (
    <GlassCard className="flex flex-col gap-4" style={{ borderColor: "var(--turquoise-dim)" }}>
      <div className="flex items-center gap-2">
        <Clapperboard size={18} style={{ color: "var(--turquoise)" }} />
        <span className="font-display font-bold text-lg" style={{ color: "var(--text-primary)" }}>
          Your production plan
        </span>
      </div>

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

  usePipelineSSE({
    videoId,
    onStageChange: (e) => {
      if (e.friendly) setCurrent(e.friendly);
      if (e.error_message) setFailed(e.error_message);
    },
    onTaskProgress: (e) => {
      if (e.status === "failed") setFailed(e.error || e.message || "Something needs a look.");
      else if (e.status === "running") setFailed(null);
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
          {isDone ? "Take a look and tell me if you want any changes." : "I'll keep working — follow along here or ask for a change anytime."}
        </div>
      )}
    </GlassCard>
  );
}
