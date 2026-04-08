"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  Rocket,
  Key,
  Film,
  Brain,
  BarChart3,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Zap,
  Settings,
  Upload,
} from "lucide-react";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";

const container = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: "easeOut" as const } },
};

interface StepCardProps {
  number: number;
  title: string;
  description: string;
  href: string;
  icon: React.ElementType;
  color: string;
}

function StepCard({ number, title, description, href, icon: Icon, color }: StepCardProps) {
  return (
    <Link href={href}>
      <GlassCard hover className="!p-5">
        <div className="flex items-start gap-4">
          <div
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-sm font-bold"
            style={{ background: `color-mix(in srgb, ${color} 15%, transparent)`, color }}
          >
            {number}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Icon size={16} style={{ color }} />
              <h3 className="font-semibold text-sm" style={{ color: "var(--text-primary)" }}>
                {title}
              </h3>
            </div>
            <p className="text-xs mt-1" style={{ color: "var(--text-secondary)" }}>
              {description}
            </p>
          </div>
          <ChevronRight size={16} style={{ color: "var(--text-tertiary)" }} className="shrink-0 mt-1" />
        </div>
      </GlassCard>
    </Link>
  );
}

interface FAQItemProps {
  question: string;
  answer: string;
}

function FAQItem({ question, answer }: FAQItemProps) {
  const [open, setOpen] = useState(false);
  return (
    <button
      onClick={() => setOpen(!open)}
      className="w-full text-left rounded-xl px-4 py-3 transition-colors"
      style={{ background: "rgba(255,255,255,0.02)", border: "1px solid var(--border-subtle)" }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
          {question}
        </span>
        <ChevronDown
          size={14}
          style={{
            color: "var(--text-tertiary)",
            transform: open ? "rotate(180deg)" : "rotate(0)",
            transition: "transform 0.2s",
          }}
        />
      </div>
      {open && (
        <p className="text-xs mt-2 leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          {answer}
        </p>
      )}
    </button>
  );
}

export default function DocsPage() {
  return (
    <motion.div className="space-y-8" variants={container} initial="hidden" animate="show">
      {/* Header */}
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          Getting Started
        </h1>
        <p className="text-sm mt-2" style={{ color: "var(--text-secondary)" }}>
          Go from zero to your first AI-generated video in 5 minutes.
        </p>
      </motion.div>

      {/* Quick Start Steps */}
      <motion.div variants={item} className="space-y-3">
        <h2
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          Quick Start
        </h2>

        <StepCard
          number={1}
          title="Configure API Keys"
          description="Connect your AI services: Anthropic (scripts), ElevenLabs (voice), Kie.ai (images). Each key has a test button to verify it works."
          href="/settings/keys"
          icon={Key}
          color="var(--turquoise)"
        />
        <StepCard
          number={2}
          title="Set Up Your Channel"
          description="Enter your channel name, niche, and target audience. This shapes how scripts are written and topics are chosen."
          href="/settings"
          icon={Settings}
          color="var(--gold)"
        />
        <StepCard
          number={3}
          title="Create Your First Video"
          description="Type a topic or headline and hit Create. The pipeline handles research, scripting, voice, images, and rendering automatically."
          href="/pipeline"
          icon={Film}
          color="var(--orange)"
        />
        <StepCard
          number={4}
          title="Review & Approve"
          description="Check each stage as it completes. Edit scripts inline, swap images, choose thumbnails. Approve to advance."
          href="/review"
          icon={Zap}
          color="var(--purple)"
        />
        <StepCard
          number={5}
          title="Upload to YouTube"
          description="Once rendered, upload as an unlisted draft to YouTube. Review in YouTube Studio, then publish when ready."
          href="/pipeline"
          icon={Upload}
          color="var(--green)"
        />
      </motion.div>

      {/* Feature Guides */}
      <motion.div variants={item} className="space-y-3">
        <h2
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          Feature Guides
        </h2>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Link href="/autopilot">
            <GlassCard hover className="!p-4">
              <div className="flex items-center gap-3">
                <Brain size={20} style={{ color: "var(--turquoise)" }} />
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    Autopilot
                  </h3>
                  <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    Let AI recommend and produce videos automatically based on competitor analysis.
                  </p>
                </div>
              </div>
            </GlassCard>
          </Link>

          <Link href="/analytics">
            <GlassCard hover className="!p-4">
              <div className="flex items-center gap-3">
                <BarChart3 size={20} style={{ color: "var(--gold)" }} />
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    Analytics
                  </h3>
                  <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    Track CTR, views, and retention. Get post-mortem reports and actionable learnings.
                  </p>
                </div>
              </div>
            </GlassCard>
          </Link>

          <Link href="/competitors">
            <GlassCard hover className="!p-4">
              <div className="flex items-center gap-3">
                <Rocket size={20} style={{ color: "var(--orange)" }} />
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    Competitors
                  </h3>
                  <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    Add competitor YouTube channels. We scrape their videos to find high-performing topics.
                  </p>
                </div>
              </div>
            </GlassCard>
          </Link>

          <Link href="/profile">
            <GlassCard hover className="!p-4">
              <div className="flex items-center gap-3">
                <Film size={20} style={{ color: "var(--purple)" }} />
                <div>
                  <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                    Visual Styles
                  </h3>
                  <p className="text-[11px]" style={{ color: "var(--text-secondary)" }}>
                    Choose from 4 visual styles or create your own. Set character references for consistency.
                  </p>
                </div>
              </div>
            </GlassCard>
          </Link>
        </div>
      </motion.div>

      {/* Pipeline Stages */}
      <motion.div variants={item}>
        <GlassCard className="!p-5">
          <h2
            className="text-[11px] font-semibold uppercase tracking-wider mb-4"
            style={{ color: "var(--text-secondary)" }}
          >
            Pipeline Stages
          </h2>
          <div className="space-y-2">
            {[
              { stage: "Research", desc: "AI deep-dives into your topic, gathering facts and sources" },
              { stage: "Script", desc: "6-scene script with hook, narrative arc, and call-to-action" },
              { stage: "Voice", desc: "ElevenLabs synthesizes narration for each scene" },
              { stage: "Storyboards", desc: "Visual storyboard panels planned for each scene" },
              { stage: "Images", desc: "AI-generated images matching each script segment" },
              { stage: "Thumbnail", desc: "Eye-catching thumbnail with accent color and text overlay" },
              { stage: "Render", desc: "Remotion composites images, voice, captions, and music into MP4" },
              { stage: "Upload", desc: "Push to YouTube as an unlisted draft for final review" },
            ].map((s, i) => (
              <div
                key={s.stage}
                className="flex items-center gap-3 rounded-lg px-3 py-2"
                style={{ background: i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent" }}
              >
                <span
                  className="text-[10px] font-mono font-bold w-5 text-center"
                  style={{ color: "var(--turquoise)" }}
                >
                  {i + 1}
                </span>
                <span className="text-xs font-semibold w-24" style={{ color: "var(--text-primary)" }}>
                  {s.stage}
                </span>
                <span className="text-xs" style={{ color: "var(--text-secondary)" }}>
                  {s.desc}
                </span>
              </div>
            ))}
          </div>
        </GlassCard>
      </motion.div>

      {/* FAQ */}
      <motion.div variants={item} className="space-y-3">
        <h2
          className="text-[11px] font-semibold uppercase tracking-wider"
          style={{ color: "var(--text-secondary)" }}
        >
          Frequently Asked Questions
        </h2>

        <div className="space-y-2">
          <FAQItem
            question="How much does each video cost to produce?"
            answer="Typical cost is $11-19 per video, covering AI generation (images, video clips), voice synthesis, and rendering. You pay your API providers directly — StoryEngine doesn't mark up API costs."
          />
          <FAQItem
            question="Which API keys are required?"
            answer="You need Anthropic (Claude for scripts), ElevenLabs (voice), Kie.ai (images/video), and OpenAI (Whisper transcription). Gemini and Google Drive are optional but recommended."
          />
          <FAQItem
            question="Can I edit the script before rendering?"
            answer="Yes. The Script tab lets you edit scene text inline, change tone per scene, and split/merge segments. Changes are saved immediately."
          />
          <FAQItem
            question="What video lengths are supported?"
            answer="You can set video length from 5 to 20 minutes when creating a video. The script and number of scenes scale automatically."
          />
          <FAQItem
            question="How does Autopilot work?"
            answer="Autopilot scrapes competitor channels, scores video ideas by views-per-hour, and recommends the best topics. Enable it to auto-produce videos on a cadence you set."
          />
          <FAQItem
            question="Can I use my own visual style?"
            answer="Yes. Go to Visual Profile to create custom styles, upload reference images, and set character references for visual consistency across videos."
          />
        </div>
      </motion.div>

      {/* Support */}
      <motion.div variants={item}>
        <GlassCard className="!p-5">
          <div className="flex items-center gap-3">
            <ExternalLink size={16} style={{ color: "var(--turquoise)" }} />
            <div>
              <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
                Need help?
              </h3>
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                Check the{" "}
                <a
                  href="https://github.com/vibecoder10/economy-fastforward/issues"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline"
                  style={{ color: "var(--turquoise)" }}
                >
                  GitHub Issues
                </a>{" "}
                page or reach out via the Settings page.
              </p>
            </div>
          </div>
        </GlassCard>
      </motion.div>
    </motion.div>
  );
}
