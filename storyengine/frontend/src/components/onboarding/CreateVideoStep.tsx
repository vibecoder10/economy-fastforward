"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Sparkles, Loader2, ArrowRight, ArrowLeft, Clock, Crop, Search, Mic } from "lucide-react";
import { cn } from "@/lib/utils";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  suggestTitles,
  createVideo,
  completeOnboarding,
  type TitleSuggestion,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";

// Starter topics per niche — the user just spent 4 steps setting up; asking
// them to invent a topic cold on Step 5 is blank-page cruelty. When the
// topic field is empty we surface 3 starters tuned to their declared niche
// from Step 1. They're prompts, not final titles — one click fills the
// textarea, they can edit, then Suggest Titles or Use as Title as usual.
//
// Keys match `ChannelIdentityStep.tsx::nicheOptions` values.
const TOPIC_STARTERS_BY_NICHE: Record<string, string[]> = {
  economy_finance: [
    "How the Fed's latest move affects your wallet",
    "3 recession signals hiding in plain sight",
    "What rising treasury yields mean for everyday Americans",
  ],
  technology: [
    "Why the latest AI announcement actually matters",
    "The state of open-source agent frameworks in 2026",
    "5 hidden features in a tool you already use",
  ],
  science: [
    "How a phenomenon you see every day actually works",
    "The truth about a science myth you've heard a hundred times",
    "A recent discovery that could reshape its field",
  ],
  health_wellness: [
    "5 mobility drills to do while you drink coffee",
    "How to actually read a nutrition label",
    "The truth about a supplement everyone's taking",
  ],
  history: [
    "The real story behind an event textbooks skim",
    "5 things pop culture got wrong about a famous era",
    "A historical figure we forgot — and why we shouldn't have",
  ],
  politics: [
    "What a new bill actually does (in plain English)",
    "The history behind a modern political fight",
    "How a federal institution really works — no spin",
  ],
  education: [
    "How to learn a new skill in 30 days",
    "3 myths about a subject you were taught wrong",
    "5 free resources that beat most paid courses",
  ],
  entertainment: [
    "Why a recent hit actually works",
    "The best scenes in a genre you love",
    "Hidden themes in a show everyone's watching",
  ],
  sports: [
    "How to read advanced stats without the jargon",
    "Why an underrated team is about to break out",
    "The truth about a long-running sports myth",
  ],
  cooking: [
    "5 quick weeknight dinners under $15",
    "How to season a cast iron once and for all",
    "Pantry staples every home cook needs",
  ],
  travel: [
    "Hidden gems in a region everyone visits wrong",
    "How to plan a week abroad on a budget",
    "Mistakes first-time travelers make (and how to avoid them)",
  ],
  gaming: [
    "Every new player in a popular game should know this",
    "Why a core mechanic everyone argues about is broken",
    "The best starter build nobody talks about",
  ],
};

// Fallback for "other" / niche-skipped users. Deliberately generic but
// still shaped like real video concepts so the chip isn't wasted space.
const GENERIC_TOPIC_STARTERS = [
  "The one thing everyone gets wrong about my topic",
  "5 things you're probably doing wrong",
  "How I accomplished something in 30 days",
];

interface CreateVideoStepProps {
  onComplete: (videoId: string) => void;
  niche?: string;
}

export function CreateVideoStep({ onComplete, niche }: CreateVideoStepProps) {
  const router = useRouter();
  const [innerStep, setInnerStep] = useState(1);
  const [topic, setTopic] = useState("");
  const starters =
    (niche && TOPIC_STARTERS_BY_NICHE[niche]) || GENERIC_TOPIC_STARTERS;
  const [selectedTitle, setSelectedTitle] = useState("");
  const [suggestions, setSuggestions] = useState<TitleSuggestion[] | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestError, setSuggestError] = useState("");
  const [videoLength, setVideoLength] = useState(10);
  const [aspectRatio, setAspectRatio] = useState<"16:9" | "9:16">("16:9");
  const [needsResearch, setNeedsResearch] = useState(true);
  const [voiceOver, setVoiceOver] = useState(true);
  const [angle, setAngle] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const handleSuggestTitles = async () => {
    if (!topic.trim()) return;
    setSuggestLoading(true);
    setSuggestError("");
    setSuggestions(null);
    try {
      const result = await suggestTitles(topic.trim());
      setSuggestions(result.titles);
    } catch (err) {
      setSuggestError(humanizeError(err, "We couldn't generate titles. Try again in a moment."));
    } finally {
      setSuggestLoading(false);
    }
  };

  const handleUseAsTitleAndContinue = () => {
    setSelectedTitle(topic.trim());
    setInnerStep(2);
  };

  const handleSelectSuggestion = (title: string) => {
    setSelectedTitle(title);
    setInnerStep(2);
  };

  const handleCreate = async () => {
    if (!selectedTitle.trim()) return;
    setCreating(true);
    setCreateError("");
    try {
      const video = await createVideo({
        title: selectedTitle.trim(),
        video_length_minutes: videoLength,
        aspect_ratio: aspectRatio,
        skip_research: !needsResearch,
        skip_voice: !voiceOver,
        framework_angle: angle.trim() || undefined,
      });
      await completeOnboarding();
      onComplete(video.id);
      router.push(`/pipeline/${video.id}`);
    } catch (err) {
      setCreateError(humanizeError(err, "We couldn't create your video. Give it another try."));
      setCreating(false);
    }
  };

  const lengthOptions = [
    { value: 5, label: "5 min", desc: "Quick explainer" },
    { value: 10, label: "10 min", desc: "Standard deep-dive" },
    { value: 15, label: "15 min", desc: "Full documentary" },
  ];

  const aspectOptions: { value: "16:9" | "9:16"; label: string; desc: string }[] = [
    { value: "16:9", label: "16:9", desc: "Landscape · YouTube" },
    { value: "9:16", label: "9:16", desc: "Vertical · Shorts" },
  ];

  const researchOptions: { value: boolean; label: string; desc: string }[] = [
    { value: true, label: "Research first", desc: "Fact-find the topic" },
    { value: false, label: "Skip it", desc: "Fiction · story" },
  ];

  const voiceOptions: { value: boolean; label: string; desc: string }[] = [
    { value: true, label: "AI voice-over", desc: "Narrate the script" },
    { value: false, label: "No narration", desc: "Clips' own audio" },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-lg mx-auto"
    >
      <GlassCard className="flex flex-col gap-5">
        <AnimatePresence mode="wait">
          {innerStep === 1 && (
            <motion.div
              key="step1"
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -20 }}
              transition={{ duration: 0.2 }}
              className="space-y-4"
            >
              <div>
                <h2
                  className="text-xl font-semibold font-body mb-1"
                  style={{ color: "var(--text-primary)" }}
                >
                  Create Your First Video
                </h2>
                <p className="text-sm font-body" style={{ color: "var(--text-secondary)" }}>
                  Describe your topic and we&apos;ll help craft the perfect title.
                </p>
              </div>

              <textarea
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="A topic you want a video about — a question, a how-to, a hot take…"
                rows={3}
                className="w-full px-4 py-3 rounded-lg text-sm font-body outline-none resize-none transition-all"
                style={{
                  background: "var(--bg-elevated)",
                  color: "var(--text-primary)",
                  border: "1px solid var(--border)",
                }}
                onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
                onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
                autoFocus
              />

              <AnimatePresence>
                {!topic.trim() && starters.length > 0 && (
                  <motion.div
                    key="starters"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.2 }}
                    className="flex flex-col gap-2 overflow-hidden"
                  >
                    <p
                      className="text-xs font-body"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      Or start with one of these:
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {starters.map((starter, i) => (
                        <button
                          key={i}
                          type="button"
                          onClick={() => setTopic(starter)}
                          className="text-left text-xs font-body px-3 py-1.5 rounded-full border transition-all hover:brightness-110"
                          style={{
                            background: "rgba(0, 212, 170, 0.06)",
                            borderColor: "rgba(0, 212, 170, 0.25)",
                            color: "var(--text-secondary)",
                          }}
                        >
                          {starter}
                        </button>
                      ))}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              <div className="flex gap-2">
                <button
                  onClick={handleSuggestTitles}
                  disabled={!topic.trim() || suggestLoading}
                  className={cn(
                    "flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold font-body transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                  )}
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--turquoise)",
                    border: "1px solid var(--turquoise-dim)",
                  }}
                >
                  {suggestLoading ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Thinking...
                    </>
                  ) : (
                    <>
                      <Sparkles size={14} /> Suggest Titles
                    </>
                  )}
                </button>
                <button
                  onClick={handleUseAsTitleAndContinue}
                  disabled={!topic.trim()}
                  className={cn(
                    "flex-1 inline-flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-semibold font-body transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                  )}
                  style={{
                    background: "var(--turquoise)",
                    color: "var(--bg-void)",
                  }}
                >
                  Use as Title <ArrowRight size={14} />
                </button>
              </div>

              {suggestError && (
                <p className="text-xs font-body text-center" style={{ color: "var(--red)" }}>
                  {suggestError}
                </p>
              )}

              <AnimatePresence>
                {suggestions && suggestions.length > 0 && (
                  <motion.div
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    className="space-y-2 overflow-hidden"
                  >
                    <p className="text-xs font-body font-medium" style={{ color: "var(--text-secondary)" }}>
                      Pick a title to continue:
                    </p>
                    {suggestions.map((s, idx) => (
                      <motion.button
                        key={idx}
                        initial={{ opacity: 0, y: 8 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: idx * 0.05 }}
                        onClick={() => handleSelectSuggestion(s.title)}
                        className="w-full text-left p-3 rounded-lg text-sm font-body transition-all group"
                        style={{
                          background: "var(--bg-elevated)",
                          border: "1px solid var(--border)",
                          color: "var(--text-primary)",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = "var(--turquoise)";
                          e.currentTarget.style.background = "rgba(0, 212, 170, 0.05)";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = "var(--border)";
                          e.currentTarget.style.background = "var(--bg-elevated)";
                        }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span>{s.title}</span>
                          <div className="flex items-center gap-2 shrink-0">
                            {s.score > 0 && (
                              <span
                                className="text-[10px] font-mono px-1.5 py-0.5 rounded-full"
                                style={{
                                  background: "rgba(0, 212, 170, 0.1)",
                                  color: "var(--turquoise)",
                                }}
                              >
                                {s.score}/10
                              </span>
                            )}
                            <ArrowRight
                              size={12}
                              className="opacity-0 group-hover:opacity-100 transition-opacity"
                              style={{ color: "var(--turquoise)" }}
                            />
                          </div>
                        </div>
                        {s.thumbnail_text && (
                          <span className="text-[10px] mt-1 block" style={{ color: "var(--text-tertiary)" }}>
                            Thumbnail: {s.thumbnail_text}
                          </span>
                        )}
                      </motion.button>
                    ))}
                  </motion.div>
                )}
              </AnimatePresence>
            </motion.div>
          )}

          {innerStep === 2 && (
            <motion.div
              key="step2"
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: 20 }}
              transition={{ duration: 0.2 }}
              className="space-y-5"
            >
              <div>
                <button
                  onClick={() => setInnerStep(1)}
                  className="inline-flex items-center gap-1 text-xs font-body mb-3 transition-colors hover:underline"
                  style={{ color: "var(--turquoise-dim)" }}
                >
                  <ArrowLeft size={12} /> Change title
                </button>
                <div
                  className="px-4 py-3 rounded-lg text-sm font-body font-medium"
                  style={{
                    background: "rgba(0, 212, 170, 0.05)",
                    border: "1px solid rgba(0, 212, 170, 0.15)",
                    color: "var(--text-primary)",
                  }}
                >
                  {selectedTitle}
                </div>
              </div>

              <div>
                <label
                  className="flex items-center gap-1.5 text-sm font-body font-medium mb-3"
                  style={{ color: "var(--text-primary)" }}
                >
                  <Clock size={14} style={{ color: "var(--text-tertiary)" }} />
                  How long should this video be?
                </label>
                <div className="flex gap-2">
                  {lengthOptions.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setVideoLength(opt.value)}
                      className="flex-1 px-3 py-3 rounded-lg text-center transition-all"
                      style={{
                        background: videoLength === opt.value ? "var(--turquoise)" : "var(--bg-elevated)",
                        color: videoLength === opt.value ? "var(--bg-void)" : "var(--text-secondary)",
                        border: `1px solid ${videoLength === opt.value ? "var(--turquoise)" : "var(--border)"}`,
                      }}
                    >
                      <div className="text-sm font-semibold font-body">{opt.label}</div>
                      <div
                        className="text-[10px] mt-0.5"
                        style={{
                          color: videoLength === opt.value ? "var(--bg-void)" : "var(--text-tertiary)",
                          opacity: videoLength === opt.value ? 0.7 : 1,
                        }}
                      >
                        {opt.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label
                  className="flex items-center gap-1.5 text-sm font-body font-medium mb-3"
                  style={{ color: "var(--text-primary)" }}
                >
                  <Crop size={14} style={{ color: "var(--text-tertiary)" }} />
                  What shape should the video be?
                </label>
                <div className="flex gap-2">
                  {aspectOptions.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setAspectRatio(opt.value)}
                      className="flex-1 px-3 py-3 rounded-lg text-center transition-all"
                      style={{
                        background: aspectRatio === opt.value ? "var(--turquoise)" : "var(--bg-elevated)",
                        color: aspectRatio === opt.value ? "var(--bg-void)" : "var(--text-secondary)",
                        border: `1px solid ${aspectRatio === opt.value ? "var(--turquoise)" : "var(--border)"}`,
                      }}
                    >
                      <div className="text-sm font-semibold font-body">{opt.label}</div>
                      <div
                        className="text-[10px] mt-0.5"
                        style={{
                          color: aspectRatio === opt.value ? "var(--bg-void)" : "var(--text-tertiary)",
                          opacity: aspectRatio === opt.value ? 0.7 : 1,
                        }}
                      >
                        {opt.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label
                  className="flex items-center gap-1.5 text-sm font-body font-medium mb-3"
                  style={{ color: "var(--text-primary)" }}
                >
                  <Search size={14} style={{ color: "var(--text-tertiary)" }} />
                  Research this topic first?
                </label>
                <div className="flex gap-2">
                  {researchOptions.map((opt) => (
                    <button
                      key={String(opt.value)}
                      onClick={() => setNeedsResearch(opt.value)}
                      className="flex-1 px-3 py-3 rounded-lg text-center transition-all"
                      style={{
                        background: needsResearch === opt.value ? "var(--turquoise)" : "var(--bg-elevated)",
                        color: needsResearch === opt.value ? "var(--bg-void)" : "var(--text-secondary)",
                        border: `1px solid ${needsResearch === opt.value ? "var(--turquoise)" : "var(--border)"}`,
                      }}
                    >
                      <div className="text-sm font-semibold font-body">{opt.label}</div>
                      <div
                        className="text-[10px] mt-0.5"
                        style={{
                          color: needsResearch === opt.value ? "var(--bg-void)" : "var(--text-tertiary)",
                          opacity: needsResearch === opt.value ? 0.7 : 1,
                        }}
                      >
                        {opt.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label
                  className="flex items-center gap-1.5 text-sm font-body font-medium mb-3"
                  style={{ color: "var(--text-primary)" }}
                >
                  <Mic size={14} style={{ color: "var(--text-tertiary)" }} />
                  Add AI voice-over?
                </label>
                <div className="flex gap-2">
                  {voiceOptions.map((opt) => (
                    <button
                      key={String(opt.value)}
                      onClick={() => setVoiceOver(opt.value)}
                      className="flex-1 px-3 py-3 rounded-lg text-center transition-all"
                      style={{
                        background: voiceOver === opt.value ? "var(--turquoise)" : "var(--bg-elevated)",
                        color: voiceOver === opt.value ? "var(--bg-void)" : "var(--text-secondary)",
                        border: `1px solid ${voiceOver === opt.value ? "var(--turquoise)" : "var(--border)"}`,
                      }}
                    >
                      <div className="text-sm font-semibold font-body">{opt.label}</div>
                      <div
                        className="text-[10px] mt-0.5"
                        style={{
                          color: voiceOver === opt.value ? "var(--bg-void)" : "var(--text-tertiary)",
                          opacity: voiceOver === opt.value ? 0.7 : 1,
                        }}
                      >
                        {opt.desc}
                      </div>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label
                  className="block text-sm font-body font-medium mb-2"
                  style={{ color: "var(--text-primary)" }}
                >
                  Anything specific about the angle?
                  <span className="text-[10px] font-normal ml-1.5" style={{ color: "var(--text-tertiary)" }}>
                    Optional
                  </span>
                </label>
                <textarea
                  value={angle}
                  onChange={(e) => setAngle(e.target.value)}
                  placeholder="Any specific angle, POV, or detail you want the video to take on?"
                  rows={2}
                  className="w-full px-4 py-3 rounded-lg text-sm font-body outline-none resize-none transition-all"
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--text-primary)",
                    border: "1px solid var(--border)",
                  }}
                  onFocus={(e) => (e.target.style.borderColor = "var(--turquoise)")}
                  onBlur={(e) => (e.target.style.borderColor = "var(--border)")}
                />
              </div>

              {createError && (
                <p className="text-xs font-body text-center" style={{ color: "var(--red)" }}>
                  {createError}
                </p>
              )}

              <ActionButton
                variant="filled"
                onClick={handleCreate}
                disabled={creating}
                icon={creating ? Loader2 : undefined}
                className={cn("w-full justify-center", creating && "[&_svg]:animate-spin")}
              >
                {creating ? "Creating..." : "Create Video & Start Pipeline"}
              </ActionButton>
            </motion.div>
          )}
        </AnimatePresence>
      </GlassCard>
    </motion.div>
  );
}
