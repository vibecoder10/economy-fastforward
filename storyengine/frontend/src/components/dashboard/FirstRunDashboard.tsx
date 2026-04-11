"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { Lightbulb, Play } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { SetupChecklist, type ChecklistItem } from "./SetupChecklist";

interface FirstRunDashboardProps {
  displayName: string;
  checklistItems: ChecklistItem[];
  percentComplete: number;
  onCreateVideo: (topic: string) => void;
  onBrowseIdeas: () => void;
}

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.12 } },
};

const item = {
  hidden: { opacity: 0, y: 20 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

export function FirstRunDashboard({
  displayName,
  checklistItems,
  percentComplete,
  onCreateVideo,
  onBrowseIdeas,
}: FirstRunDashboardProps) {
  const [topic, setTopic] = useState("");

  return (
    <motion.div
      className="max-w-2xl mx-auto space-y-6"
      variants={container}
      initial="hidden"
      animate="show"
    >
      {/* Welcome header */}
      <motion.div variants={item} className="text-center pt-4">
        <h1
          className="text-4xl font-display mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          Welcome to StoryEngine, {displayName}!
        </h1>
        <p className="text-base" style={{ color: "var(--text-secondary)" }}>
          Your AI video studio is ready. Let&apos;s make your first video.
        </p>
      </motion.div>

      {/* Setup Checklist */}
      <motion.div variants={item}>
        <SetupChecklist items={checklistItems} percentComplete={percentComplete} />
      </motion.div>

      {/* Create first video */}
      <motion.div variants={item}>
        <GlassCard>
          <h2
            className="text-sm font-semibold mb-3"
            style={{ color: "var(--text-primary)" }}
          >
            Ready to create your first video?
          </h2>
          <textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="What's your video about?"
            rows={3}
            className="w-full rounded-xl px-4 py-3 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-[rgba(0,212,170,0.4)] transition-all mb-4"
            style={{
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
              color: "var(--text-primary)",
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = "rgba(0, 212, 170, 0.4)";
            }}
            onBlur={(e) => {
              e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
            }}
          />
          <ActionButton
            onClick={() => onCreateVideo(topic)}
            disabled={!topic.trim()}
          >
            Start My First Video
          </ActionButton>
        </GlassCard>
      </motion.div>

      {/* Two helper cards */}
      <motion.div variants={item} className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <GlassCard
          hover
          onClick={onBrowseIdeas}
          className="!p-5 flex flex-col items-center text-center gap-2 cursor-pointer"
        >
          <Lightbulb size={24} style={{ color: "var(--gold)" }} />
          <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
            Not sure what to make?
          </p>
          <span className="text-xs" style={{ color: "var(--turquoise)" }}>
            Browse AI Ideas
          </span>
        </GlassCard>

        <GlassCard
          hover
          onClick={() => window.open("https://youtube.com/@economyfastforward", "_blank")}
          className="!p-5 flex flex-col items-center text-center gap-2 cursor-pointer"
        >
          <Play size={24} style={{ color: "var(--turquoise)" }} />
          <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
            See how it works
          </p>
          <span className="text-xs" style={{ color: "var(--turquoise)" }}>
            Watch Demo
          </span>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
