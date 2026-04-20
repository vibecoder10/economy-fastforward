"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getSystemPrompts,
  updateSystemPrompt,
  resetSystemPrompt,
  generateSystemPrompts,
  getChannelProfile,
} from "@/lib/api";
import { SystemPromptEditor } from "@/components/ui/SystemPromptEditor";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Textarea } from "@/components/forms/textarea";
import { Loader2, Wand2, Sparkles } from "lucide-react";
import { humanizeError } from "@/lib/errors";

const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.06 } } };
const item = { hidden: { opacity: 0, y: 16 }, show: { opacity: 1, y: 0, transition: { duration: 0.5 } } };

export default function SystemPromptsPage() {
  const queryClient = useQueryClient();
  const { data: prompts, isLoading, error } = useQuery({
    queryKey: ["system-prompts"],
    queryFn: getSystemPrompts,
  });

  const { data: profile } = useQuery({
    queryKey: ["channel-profile"],
    queryFn: getChannelProfile,
  });

  const [styleDescription, setStyleDescription] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generated, setGenerated] = useState(false);
  const [summary, setSummary] = useState<string | null>(null);
  const [genError, setGenError] = useState<string | null>(null);

  // Pre-fill textarea from channel profile
  useEffect(() => {
    if (profile?.style_description && !styleDescription) {
      setStyleDescription(profile.style_description);
    }
  }, [profile?.style_description]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleGenerate = async () => {
    if (!styleDescription.trim()) return;
    setGenerating(true);
    setGenError(null);
    setSummary(null);
    setGenerated(false);
    try {
      const res = await generateSystemPrompts({
        style_description: styleDescription,
        channel_name: profile?.channel_name,
        niche: profile?.niche,
        target_audience: profile?.target_audience,
      });
      setSummary(res.summary);
      setGenerated(true);
      queryClient.invalidateQueries({ queryKey: ["system-prompts"] });
    } catch (err) {
      setGenError(humanizeError(err, "We couldn't generate prompts. Please try again."));
    } finally {
      setGenerating(false);
    }
  };

  // Derive whether prompts have been customized before
  const hasCustomPrompts = prompts?.some((p) => p.is_custom) ?? false;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 size={24} className="animate-spin" style={{ color: "var(--text-tertiary)" }} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-20" style={{ color: "var(--text-tertiary)" }}>
        Failed to load system prompts.
      </div>
    );
  }

  return (
    <motion.div className="space-y-6" variants={container} initial="hidden" animate="show">
      <motion.div variants={item}>
        <h1 className="text-4xl font-display" style={{ color: "var(--text-primary)" }}>
          System Prompts
        </h1>
        <p className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>
          Customize the AI system prompts used across your pipeline. Changes here become the default for all new videos.
        </p>
      </motion.div>

      {/* AI Style Generator Card */}
      <motion.div variants={item}>
        <GlassCard>
          <div className="flex items-center gap-3 mb-4">
            <div
              className="shrink-0 rounded-xl p-2.5"
              style={{ background: "var(--purple-dim, rgba(168, 85, 247, 0.12))" }}
            >
              <Wand2 size={20} style={{ color: "var(--purple, #a855f7)" }} />
            </div>
            <div>
              <h2
                className="text-lg font-semibold font-body"
                style={{ color: "var(--text-primary)" }}
              >
                AI Style Generator
              </h2>
              <p
                className="text-sm font-body"
                style={{ color: "var(--text-secondary)" }}
              >
                Describe your channel&apos;s voice and the AI will customize all your prompts.
              </p>
            </div>
          </div>

          <Textarea
            placeholder="e.g., I want casual, approachable videos that feel like chatting with a knowledgeable friend"
            value={styleDescription}
            onChange={(e) => setStyleDescription(e.target.value)}
            rows={4}
            disabled={generating}
          />

          <div className="flex items-center gap-3 mt-4">
            <ActionButton
              onClick={handleGenerate}
              disabled={!styleDescription.trim() || generating}
              icon={generating ? Loader2 : Wand2}
            >
              {generating ? "Generating..." : "Generate All Prompts"}
            </ActionButton>

            {hasCustomPrompts && !generated && (
              <span
                className="text-xs font-body"
                style={{ color: "var(--text-tertiary)" }}
              >
                Prompts customized
              </span>
            )}
          </div>

          {/* Success summary */}
          {generated && summary && (
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.3 }}
              className="mt-4"
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

          {/* Error message */}
          {genError && (
            <p className="text-sm mt-3" style={{ color: "var(--error)" }}>
              {genError}
            </p>
          )}
        </GlassCard>
      </motion.div>

      <motion.div variants={item} className="space-y-3">
        {prompts?.map((p) => (
          <SystemPromptEditor
            key={p.key}
            label={`${p.label} System Prompt`}
            currentValue={p.is_custom ? p.prompt : null}
            saveLabel="Save as Default"
            onSave={async (text) => {
              await updateSystemPrompt(p.key, text);
              queryClient.invalidateQueries({ queryKey: ["system-prompts"] });
            }}
            onReset={async () => {
              const res = await resetSystemPrompt(p.key);
              queryClient.invalidateQueries({ queryKey: ["system-prompts"] });
              return res.prompt;
            }}
          />
        ))}
      </motion.div>
    </motion.div>
  );
}
