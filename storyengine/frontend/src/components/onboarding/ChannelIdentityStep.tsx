"use client";

import { motion } from "framer-motion";
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
  saving: boolean;
  error: string | null;
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
  saving,
  error,
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

        <TextInput
          label="Channel Name"
          placeholder="Your channel name"
          value={channelName}
          onChange={(e) => onChange("channelName", e.target.value)}
          required
        />

        <div className="flex flex-col gap-1">
          <Select
            label="What topics will you cover? (optional)"
            options={nicheOptions}
            value={niche}
            onChange={(e) => onChange("niche", e.target.value)}
            placeholder="Select a niche..."
          />
          <p
            className="text-xs font-body"
            style={{ color: "var(--text-tertiary)" }}
          >
            We&apos;ll tune your scripts and visuals to this.
          </p>
        </div>

        <Textarea
          label="Who are you making videos for? (optional)"
          placeholder="Describe your ideal viewer — what they care about, what they want to learn."
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
        </div>
      </GlassCard>
    </motion.div>
  );
}
