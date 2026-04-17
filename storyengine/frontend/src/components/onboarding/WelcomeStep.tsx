"use client";

import { motion } from "framer-motion";
import { Film, Key, Palette, User, Youtube } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";

const PIPELINE_PREVIEW = [
  { icon: User, label: "Channel" },
  { icon: Key, label: "Tools" },
  { icon: Palette, label: "Style" },
  { icon: Youtube, label: "YouTube" },
  { icon: Film, label: "First Video" },
];

interface WelcomeStepProps {
  displayName: string;
  onContinue: () => void;
}

function firstNameFromDisplay(name: string): string {
  const first = name.trim().split(/\s+/)[0] || "";
  return first || "there";
}

export function WelcomeStep({ displayName, onContinue }: WelcomeStepProps) {
  const firstName = firstNameFromDisplay(displayName);

  return (
    <motion.div
      initial={{ opacity: 0, y: 24 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, ease: "easeOut" }}
      className="w-full max-w-lg mx-auto"
    >
      <GlassCard className="flex flex-col gap-8 py-10 px-6 sm:px-10 text-center">
        <div className="flex flex-col gap-3">
          <motion.h1
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.05 }}
            className="text-2xl sm:text-3xl font-semibold font-body"
            style={{ color: "var(--text-primary)" }}
          >
            Hey {firstName} <span aria-hidden>👋</span>
          </motion.h1>
          <motion.p
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.45, delay: 0.15 }}
            className="text-sm sm:text-base font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            5 quick steps and you&apos;ll have your first AI-produced video. Here&apos;s the path:
          </motion.p>
        </div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.25 }}
          className="flex items-center justify-between gap-1 sm:gap-2"
          aria-label="Onboarding steps"
        >
          {PIPELINE_PREVIEW.map((s) => {
            const Icon = s.icon;
            return (
              <div
                key={s.label}
                className="flex flex-col items-center gap-1.5 min-w-0 flex-1"
              >
                <div
                  className="w-9 h-9 sm:w-10 sm:h-10 rounded-full flex items-center justify-center"
                  style={{
                    background: "rgba(0, 212, 170, 0.08)",
                    border: "1px solid rgba(0, 212, 170, 0.25)",
                    color: "var(--turquoise)",
                  }}
                >
                  <Icon size={16} />
                </div>
                <span
                  className="text-[9px] sm:text-[10px] font-mono uppercase tracking-wider truncate w-full text-center"
                  style={{ color: "var(--text-tertiary)" }}
                >
                  {s.label}
                </span>
              </div>
            );
          })}
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, delay: 0.35 }}
          className="flex flex-col items-center gap-2"
        >
          <ActionButton onClick={onContinue}>
            Let&apos;s go →
          </ActionButton>
          <p
            className="text-xs font-body"
            style={{ color: "var(--text-tertiary)" }}
          >
            Takes about 15 minutes. You can pause and come back anytime.
          </p>
        </motion.div>
      </GlassCard>
    </motion.div>
  );
}
