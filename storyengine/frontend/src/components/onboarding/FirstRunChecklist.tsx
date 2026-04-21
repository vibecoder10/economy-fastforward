"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { Key, Youtube, Film, Check, ArrowRight } from "lucide-react";
import type { OnboardingStatus } from "@/lib/api";

// Stage 6.2 — the persistent system-readiness strip that fills the gap between
// onboarding and first-video. Onboarding can be marked "complete" while YouTube
// is still disconnected or a key was never saved; FinishSetupBanner only fires
// for users who explicitly skipped step 2. Once onboarding is marked complete,
// those users lose every reminder — this component keeps the gates visible
// until the studio is actually ready.

interface FirstRunChecklistProps {
  status: OnboardingStatus;
}

type Gate = {
  id: string;
  label: string;
  done: boolean;
  href: string;
  icon: typeof Key;
  accent: string;
  cta: string;
};

export function FirstRunChecklist({ status }: FirstRunChecklistProps) {
  const keysDone =
    status.steps.api_keys.configured >= status.steps.api_keys.required;
  const ytDone = status.steps.youtube_connected;
  const videoDone = status.steps.first_video_created;

  const gates: Gate[] = [
    {
      id: "api-keys",
      label: "Add your API keys",
      done: keysDone,
      href: "/settings",
      icon: Key,
      accent: "var(--gold)",
      cta: "Add keys",
    },
    {
      id: "youtube",
      label: "Connect YouTube",
      done: ytDone,
      href: "/settings",
      icon: Youtube,
      accent: "var(--orange)",
      cta: "Connect",
    },
    {
      id: "first-video",
      label: "Create your first video",
      done: videoDone,
      href: "/pipeline",
      icon: Film,
      accent: "var(--turquoise)",
      cta: "Start",
    },
  ];

  const doneCount = gates.filter((g) => g.done).length;

  // All gates met → studio is ready, hide for good.
  if (doneCount === gates.length) return null;

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
      data-testid="first-run-checklist"
      className="rounded-xl overflow-hidden"
      style={{
        background:
          "linear-gradient(90deg, rgba(255, 180, 0, 0.05), rgba(0, 212, 170, 0.04))",
        border: "1px solid rgba(255, 180, 0, 0.22)",
      }}
    >
      <div className="px-5 py-3 sm:px-6 sm:py-4 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span
              className="text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full"
              style={{
                color: "var(--gold)",
                background: "rgba(255, 180, 0, 0.10)",
              }}
            >
              Studio setup
            </span>
            <span
              className="text-[10px] font-mono"
              style={{ color: "var(--text-tertiary)" }}
            >
              {doneCount} of {gates.length} ready
            </span>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {gates.map((gate) => {
            const Icon = gate.icon;
            return (
              <Link
                key={gate.id}
                href={gate.href}
                data-testid={`first-run-checklist-${gate.id}`}
                className="group flex items-center justify-between gap-2 px-3 py-2 rounded-lg transition-all hover:brightness-110"
                style={{
                  background: gate.done
                    ? "rgba(0, 212, 170, 0.06)"
                    : "rgba(255, 255, 255, 0.03)",
                  border: gate.done
                    ? "1px solid rgba(0, 212, 170, 0.30)"
                    : "1px solid rgba(255, 255, 255, 0.06)",
                }}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                    style={{
                      background: gate.done
                        ? "var(--green)"
                        : "rgba(255, 255, 255, 0.06)",
                      color: gate.done ? "#0a0a0a" : gate.accent,
                    }}
                  >
                    {gate.done ? (
                      <Check size={12} strokeWidth={3} />
                    ) : (
                      <Icon size={12} />
                    )}
                  </div>
                  <span
                    className="text-xs font-body truncate"
                    style={{
                      color: gate.done
                        ? "var(--text-secondary)"
                        : "var(--text-primary)",
                      textDecoration: gate.done ? "line-through" : "none",
                    }}
                  >
                    {gate.label}
                  </span>
                </div>
                {!gate.done && (
                  <div
                    className="flex items-center gap-1 text-[11px] font-semibold font-body shrink-0"
                    style={{ color: gate.accent }}
                  >
                    {gate.cta}
                    <ArrowRight
                      size={11}
                      className="transition-transform group-hover:translate-x-0.5"
                    />
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
