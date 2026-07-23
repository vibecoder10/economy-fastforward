"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Sparkles,
  Loader2,
  X,
  ArrowRight,
  ArrowLeft,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ActionButton } from "@/components/ui/ActionButton";
import { ProductionStyleSelector } from "@/components/production/ProductionStyleSelector";
import {
  suggestTitles,
  type ProductionStyleId,
  type TitleSuggestion,
} from "@/lib/api";
import { humanizeError } from "@/lib/errors";

interface FirstVideoFlowProps {
  onCreateVideo: (
    title: string,
    videoLength: number,
    productionStyleId: ProductionStyleId,
    angle?: string,
  ) => void;
  onClose: () => void;
  initialTopic?: string;
}

export function FirstVideoFlow({
  onCreateVideo,
  onClose,
  initialTopic = "",
}: FirstVideoFlowProps) {
  const [step, setStep] = useState(1);
  const [topic, setTopic] = useState(initialTopic);
  const [selectedTitle, setSelectedTitle] = useState("");
  const [suggestions, setSuggestions] = useState<TitleSuggestion[] | null>(null);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [suggestError, setSuggestError] = useState("");
  const [videoLength, setVideoLength] = useState(10);
  const [productionStyleId, setProductionStyleId] = useState<ProductionStyleId | "">("");
  const [angle, setAngle] = useState("");
  const [creating, setCreating] = useState(false);

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
    setStep(2);
  };

  const handleSelectSuggestion = (title: string) => {
    setSelectedTitle(title);
    setStep(2);
  };

  const handleCreate = () => {
    if (!selectedTitle.trim() || !productionStyleId) return;
    setCreating(true);
    onCreateVideo(
      selectedTitle.trim(),
      videoLength,
      productionStyleId,
      angle.trim() || undefined,
    );
  };

  const lengthOptions = [
    { value: 5, label: "5 min", desc: "Quick explainer" },
    { value: 10, label: "10 min", desc: "Standard deep-dive" },
    { value: 15, label: "15 min", desc: "Full documentary" },
  ];

  return (
    // One motion root owns the only exit animation. A fragment root with two
    // exiting motion.divs stalls mid-exit on framer-motion 12 + React 19 and
    // never unmounts, leaving the backdrop blocking every click (same bug as
    // ui/modal.tsx, verified 2026-07-16).
    <motion.div
      data-testid="first-video-flow"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50"
    >
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Modal */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        transition={{ type: "spring", damping: 30, stiffness: 300 }}
        className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-32px)] max-w-lg max-h-[85vh] overflow-y-auto"
      >
        <div
          className="rounded-xl border shadow-2xl"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between px-6 pt-5 pb-0">
            <div className="flex items-center gap-2">
              {/* Step indicator */}
              <div className="flex items-center gap-1.5">
                {[1, 2].map((s) => (
                  <div
                    key={s}
                    className="h-1.5 rounded-full transition-all"
                    style={{
                      width: s === step ? 24 : 8,
                      background: s <= step ? "var(--turquoise)" : "var(--border)",
                    }}
                  />
                ))}
              </div>
              <span className="text-[11px] font-mono ml-2" style={{ color: "var(--text-tertiary)" }}>
                Step {step} of 2
              </span>
            </div>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 transition-all"
              style={{ color: "var(--text-tertiary)" }}
            >
              <X size={18} />
            </button>
          </div>

          <AnimatePresence mode="wait">
            {/* Step 1: Topic */}
            {step === 1 && (
              <motion.div
                key="step1"
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.2 }}
                className="px-6 py-5 space-y-4"
              >
                <div>
                  <h2
                    className="text-lg font-display font-bold mb-1"
                    style={{ color: "var(--text-primary)" }}
                  >
                    What&apos;s your video about?
                  </h2>
                  <p className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                    Describe your topic and we&apos;ll help craft the perfect title.
                  </p>
                </div>

                <textarea
                  value={topic}
                  onChange={(e) => setTopic(e.target.value)}
                  placeholder="e.g., Why the US dollar might lose its reserve currency status"
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

                {/* Suggested titles */}
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

            {/* Step 2: Config */}
            {step === 2 && (
              <motion.div
                key="step2"
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 20 }}
                transition={{ duration: 0.2 }}
                className="px-6 py-5 space-y-5"
              >
                {/* Selected title preview */}
                <div>
                  <button
                    onClick={() => setStep(1)}
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

                <ProductionStyleSelector
                  selectedId={productionStyleId}
                  onSelect={setProductionStyleId}
                  durationMinutes={videoLength}
                />

                {/* Video length */}
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

                {/* Angle (optional) */}
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
                    placeholder="e.g., Focus on the geopolitical implications rather than economics"
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

                {/* Create button */}
                <ActionButton
                  variant="filled"
                  onClick={handleCreate}
                  disabled={creating || !productionStyleId}
                  icon={creating ? Loader2 : undefined}
                  className={cn("w-full justify-center", creating && "[&_svg]:animate-spin")}
                >
                  {creating ? "Creating..." : "Create Video & Start Pipeline"}
                </ActionButton>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </motion.div>
    </motion.div>
  );
}
