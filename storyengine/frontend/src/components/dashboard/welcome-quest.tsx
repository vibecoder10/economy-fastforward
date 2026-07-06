"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import Link from "next/link";
import {
  Users,
  Sparkles,
  Film,
  ArrowRight,
  Check,
  X,
} from "lucide-react";

// Hide the panel after dismissal so it stays out of the way for returning
// users who haven't quite finished but don't want the reminder every session.
const DISMISS_KEY = "welcome_quest_dismissed";

export interface WelcomeQuestStatus {
  competitorCount: number;
  distilledCount: number;
  videoCount: number;
  displayName: string | null;
}

interface WelcomeQuestProps {
  status: WelcomeQuestStatus;
}

type QuestStep = {
  num: number;
  title: string;
  description: string;
  cta: string;
  href: string;
  icon: typeof Users;
  done: boolean;
  accent: string;
};

export function WelcomeQuest({ status }: WelcomeQuestProps) {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(DISMISS_KEY) === "1";
  });

  // Only meaningful for users who haven't shipped their first video. Once
  // they've shipped, the quest is retired for good — the dashboard's
  // populated analytics widgets become the home base.
  if (status.videoCount > 0 || dismissed) {
    return null;
  }

  const handleDismiss = () => {
    window.localStorage.setItem(DISMISS_KEY, "1");
    setDismissed(true);
  };

  const firstName = (status.displayName || "").split(" ")[0] || "there";

  const steps: QuestStep[] = [
    {
      num: 1,
      title: "Train your AI with competitors",
      description:
        "Paste 3 YouTube channels you admire. We'll learn their hooks, tones, and thumbnail DNA so your videos inherit the patterns that already work.",
      cta: status.competitorCount > 0 ? "Add more" : "Add competitors",
      href: "/discovery",
      icon: Users,
      done: status.competitorCount >= 3,
      accent: "var(--turquoise)",
    },
    {
      num: 2,
      title: "Distill your first insight",
      description:
        "Pick a competitor video that's already crushing. We'll extract the exact structure — hook, pacing, thumbnail style — so you can remix what works.",
      cta: status.distilledCount > 0 ? "Distill another" : "Try it",
      href: "/discovery",
      icon: Sparkles,
      done: status.distilledCount >= 1,
      accent: "var(--gold)",
    },
    {
      num: 3,
      title: "Create your first video",
      description:
        "Use what we learned to generate your first script, storyboard, and thumbnail. End-to-end in one flow — you review the pieces you care about, we do the rest.",
      cta: "Start your video",
      href: "/pipeline",
      icon: Film,
      done: status.videoCount >= 1,
      accent: "var(--green)",
    },
  ];

  const doneCount = steps.filter((s) => s.done).length;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      data-testid="welcome-quest"
      className="relative rounded-2xl overflow-hidden"
      style={{
        background:
          "linear-gradient(135deg, rgba(0, 212, 170, 0.06), rgba(158, 120, 255, 0.05) 50%, rgba(255, 180, 0, 0.05))",
        border: "1px solid rgba(0, 212, 170, 0.22)",
      }}
    >
      <button
        type="button"
        aria-label="Dismiss welcome quest"
        onClick={handleDismiss}
        className="absolute top-3 right-3 w-7 h-7 rounded-full flex items-center justify-center transition-all hover:brightness-125"
        style={{
          background: "rgba(255, 255, 255, 0.05)",
          color: "var(--text-tertiary)",
        }}
      >
        <X size={13} />
      </button>

      <div className="p-5 sm:p-6 space-y-5">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
              style={{
                color: "var(--turquoise)",
                background: "rgba(0, 212, 170, 0.10)",
              }}
            >
              Get started
            </span>
            <span
              className="text-[10px] font-mono"
              style={{ color: "var(--text-tertiary)" }}
            >
              {doneCount} of {steps.length} done
            </span>
          </div>
          <h2
            className="text-2xl sm:text-3xl font-display"
            style={{ color: "var(--text-primary)" }}
          >
            Welcome, {firstName}. Let's light the engine.
          </h2>
          <p
            className="text-sm mt-1 font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            Three steps, about ten minutes. Skip around — order doesn't matter.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
          {steps.map((step) => {
            const Icon = step.icon;
            return (
              <Link
                key={step.num}
                href={step.href}
                data-testid={`welcome-quest-step-${step.num}`}
                className="group relative flex flex-col justify-between gap-4 p-4 rounded-xl transition-all duration-200 hover:brightness-110"
                style={{
                  background: step.done
                    ? "rgba(0, 212, 170, 0.06)"
                    : "rgba(255, 255, 255, 0.03)",
                  border: step.done
                    ? `1px solid ${step.accent}55`
                    : "1px solid rgba(255, 255, 255, 0.06)",
                }}
              >
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center shrink-0"
                      style={{
                        background: step.done
                          ? step.accent
                          : "rgba(255, 255, 255, 0.06)",
                        color: step.done ? "#0a0a0a" : step.accent,
                      }}
                    >
                      {step.done ? (
                        <Check size={15} strokeWidth={3} />
                      ) : (
                        <Icon size={14} />
                      )}
                    </div>
                    <span
                      className="text-[10px] font-mono font-semibold"
                      style={{ color: "var(--text-tertiary)" }}
                    >
                      Step {step.num}
                    </span>
                  </div>
                  <h3
                    className="text-base font-display mb-1"
                    style={{ color: "var(--text-primary)" }}
                  >
                    {step.title}
                  </h3>
                  <p
                    className="text-xs font-body leading-relaxed"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {step.description}
                  </p>
                </div>
                <div
                  className="flex items-center gap-1 text-xs font-semibold font-body"
                  style={{ color: step.done ? step.accent : "var(--text-primary)" }}
                >
                  {step.done ? "Done" : step.cta}
                  {!step.done && (
                    <ArrowRight
                      size={13}
                      className="transition-transform group-hover:translate-x-0.5"
                    />
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
