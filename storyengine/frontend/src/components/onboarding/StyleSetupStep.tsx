"use client";

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Textarea } from "@/components/forms/textarea";
import { Spinner } from "@/components/ui/spinner";

interface StyleSetupStepProps {
  styleDescription: string;
  onChange: (value: string) => void;
  onGenerate: () => void;
  onNext: () => void;
  onSkip: () => void;
  generating: boolean;
  generated: boolean;
  summary: string | null;
  error: string | null;
  prefilledFromVoice?: boolean;
}

export function StyleSetupStep({
  styleDescription,
  onChange,
  onGenerate,
  onNext,
  onSkip,
  generating,
  generated,
  summary,
  error,
  prefilledFromVoice = false,
}: StyleSetupStepProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-lg mx-auto"
    >
      <GlassCard className="flex flex-col gap-6">
        <div>
          <h2
            className="text-xl font-semibold font-body mb-1"
            style={{ color: "var(--text-primary)" }}
          >
            Your AI Style
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            Describe how you want your videos to sound and feel.
          </p>
        </div>

        {prefilledFromVoice && (
          <div
            className="flex items-start gap-2 px-3 py-2 rounded-lg text-xs font-body"
            style={{
              background: "rgba(0,212,170,0.08)",
              border: "1px solid rgba(0,212,170,0.3)",
              color: "var(--accent)",
            }}
          >
            <Sparkles size={14} className="flex-shrink-0 mt-0.5" />
            <span>
              We drafted this from your top YouTube videos. Edit anything that doesn&apos;t sound right, then generate.
            </span>
          </div>
        )}

        <Textarea
          placeholder="e.g., I want to sound like a curious friend explaining complex economics to smart people who don't have time to read 50 articles."
          value={styleDescription}
          onChange={(e) => onChange(e.target.value)}
          rows={5}
          disabled={generating}
        />

        <ActionButton
          onClick={onGenerate}
          disabled={!styleDescription.trim() || generating}
        >
          {generating ? (
            <span className="flex items-center gap-2">
              <Spinner size="sm" /> Generating...
            </span>
          ) : (
            "Generate My Style"
          )}
        </ActionButton>

        {generated && summary && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3 }}
          >
            <GlassCard
              className="border"
              style={{ borderColor: "var(--success)" }}
            >
              <div className="flex items-start gap-3">
                <div
                  className="mt-0.5 shrink-0 rounded-full p-1.5"
                  style={{ background: "var(--turquoise-dim)" }}
                >
                  <Sparkles size={16} style={{ color: "var(--turquoise)" }} />
                </div>
                <p
                  className="text-sm font-body leading-relaxed"
                  style={{ color: "var(--text-primary)" }}
                >
                  {summary}
                </p>
              </div>
            </GlassCard>
          </motion.div>
        )}

        {error && (
          <p className="text-sm" style={{ color: "var(--error)" }}>
            {error}
          </p>
        )}

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton onClick={onNext}>Continue</ActionButton>

          <button
            onClick={onSkip}
            className="text-xs font-body hover:underline"
            style={{ color: "var(--text-secondary)" }}
          >
            Use default style
          </button>
        </div>
      </GlassCard>
    </motion.div>
  );
}
