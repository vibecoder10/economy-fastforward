"use client";

import { motion } from "framer-motion";
import { Check, Youtube } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { TextInput } from "@/components/forms/text-input";
import { Select } from "@/components/forms/select";
import { Textarea } from "@/components/forms/textarea";
import { Spinner } from "@/components/ui/spinner";

interface ChannelIdentityStepProps {
  channelName: string;
  niche: string;
  audience: string;
  onChange: (field: string, value: string) => void;
  onNext: () => void;
  onSkip: () => void;
  saving: boolean;
  error: string | null;
  showYouTubeConnect?: boolean;
  youtubeConnected?: boolean;
  youtubeChannelName?: string;
  onConnectYouTube?: () => void;
}

const nicheOptions = [
  { value: "economy_finance", label: "Economy & Finance" },
  { value: "technology", label: "Technology" },
  { value: "science", label: "Science" },
  { value: "health_wellness", label: "Health & Wellness" },
  { value: "history", label: "History" },
  { value: "politics", label: "Politics" },
  { value: "education", label: "Education" },
  { value: "entertainment", label: "Entertainment" },
  { value: "sports", label: "Sports" },
  { value: "cooking", label: "Cooking" },
  { value: "travel", label: "Travel" },
  { value: "gaming", label: "Gaming" },
  { value: "other", label: "Other" },
];

export function ChannelIdentityStep({
  channelName,
  niche,
  audience,
  onChange,
  onNext,
  onSkip,
  saving,
  error,
  showYouTubeConnect,
  youtubeConnected,
  youtubeChannelName,
  onConnectYouTube,
}: ChannelIdentityStepProps) {
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
            Your Channel
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            Tell us about the channel you want to build.
          </p>
        </div>

        {showYouTubeConnect && (
          <div className="flex items-center gap-3">
            {youtubeConnected ? (
              <div className="flex items-center gap-2">
                <Check size={16} style={{ color: "var(--success)" }} />
                <span
                  className="text-sm font-body"
                  style={{ color: "var(--success)" }}
                >
                  Connected: {youtubeChannelName}
                </span>
              </div>
            ) : (
              <ActionButton
                variant="outline"
                icon={Youtube}
                onClick={onConnectYouTube}
              >
                Connect YouTube Channel
              </ActionButton>
            )}
          </div>
        )}

        <TextInput
          label="Channel Name"
          placeholder="e.g., Economy FastForward"
          value={channelName}
          onChange={(e) => onChange("channelName", e.target.value)}
          required
        />

        <Select
          label="What topics will you cover?"
          options={nicheOptions}
          value={niche}
          onChange={(e) => onChange("niche", e.target.value)}
          placeholder="Select a niche..."
        />

        <Textarea
          label="Who are you making videos for?"
          placeholder="e.g., Busy professionals who want to understand global economics without reading 50 articles."
          value={audience}
          onChange={(e) => onChange("audience", e.target.value)}
          rows={3}
        />

        {error && (
          <p className="text-sm" style={{ color: "var(--error)" }}>
            {error}
          </p>
        )}

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton
            onClick={onNext}
            disabled={!channelName.trim() || saving}
          >
            {saving ? (
              <span className="flex items-center gap-2">
                <Spinner size="sm" /> Saving...
              </span>
            ) : (
              "Continue"
            )}
          </ActionButton>

          <button
            onClick={onSkip}
            className="text-xs font-body hover:underline"
            style={{ color: "var(--text-secondary)" }}
          >
            Skip for now
          </button>
        </div>
      </GlassCard>
    </motion.div>
  );
}
