"use client";

import { motion } from "framer-motion";
import { Sparkles, Youtube } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";

interface UserTypeStepProps {
  onSelect: (type: "new_creator" | "existing_channel") => void;
}

const container = {
  hidden: { opacity: 0 },
  show: {
    opacity: 1,
    transition: { staggerChildren: 0.15 },
  },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4 } },
};

export function UserTypeStep({ onSelect }: UserTypeStepProps) {
  return (
    <div className="flex flex-col items-center gap-8">
      <motion.div
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="text-center"
      >
        <h2
          className="text-2xl font-semibold font-body mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          Welcome to StoryEngine
        </h2>
        <p
          className="text-sm font-body"
          style={{ color: "var(--text-secondary)" }}
        >
          How would you like to get started?
        </p>
      </motion.div>

      <motion.div
        variants={container}
        initial="hidden"
        animate="show"
        className="grid grid-cols-1 sm:grid-cols-2 gap-6 w-full max-w-2xl"
      >
        <motion.div variants={item}>
          <GlassCard
            hover
            onClick={() => onSelect("new_creator")}
            className="flex flex-col items-center text-center gap-4 py-10 px-6 border border-transparent hover:border-[var(--turquoise)]/30 transition-colors"
          >
            <div
              className="rounded-full p-4"
              style={{ background: "var(--turquoise-dim)" }}
            >
              <Sparkles size={32} style={{ color: "var(--turquoise)" }} />
            </div>
            <h3
              className="text-lg font-semibold font-body"
              style={{ color: "var(--text-primary)" }}
            >
              I&apos;m Starting Fresh
            </h3>
            <p
              className="text-sm font-body"
              style={{ color: "var(--text-secondary)" }}
            >
              I want AI to help me build a channel from scratch
            </p>
          </GlassCard>
        </motion.div>

        <motion.div variants={item}>
          <GlassCard
            hover
            onClick={() => onSelect("existing_channel")}
            className="flex flex-col items-center text-center gap-4 py-10 px-6 border border-transparent hover:border-[var(--turquoise)]/30 transition-colors"
          >
            <div
              className="rounded-full p-4"
              style={{ background: "var(--turquoise-dim)" }}
            >
              <Youtube size={32} style={{ color: "var(--turquoise)" }} />
            </div>
            <h3
              className="text-lg font-semibold font-body"
              style={{ color: "var(--text-primary)" }}
            >
              I Have a Channel
            </h3>
            <p
              className="text-sm font-body"
              style={{ color: "var(--text-secondary)" }}
            >
              I want to automate my production and grow my audience
            </p>
          </GlassCard>
        </motion.div>
      </motion.div>
    </div>
  );
}
