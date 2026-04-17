"use client";

import { motion } from "framer-motion";
import { Check, Circle, ExternalLink, Eye, EyeOff } from "lucide-react";
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

// Format hints per provider — gives users a visual template so they can
// eyeball a paste before submitting. Keys not in this map fall back to the
// generic "Paste your API key..." placeholder.
const KEY_FORMAT_HINTS: Record<string, string> = {
  anthropic_api_key: "sk-ant-xxxxxxxxxxxxxxxx…",
  elevenlabs_api_key: "sk_xxxxxxxxxxxxxxxx…",
  elevenlabs_voice_id: "e.g. 21m00Tcm4TlvDq8ikWAM",
  kie_ai_api_key: "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
  openai_api_key: "sk-proj-xxxxxxxxxxxxxxxx…",
  gemini_api_key: "AIzaxxxxxxxxxxxxxxxxxxxx…",
};

// Keys that are public identifiers, not secrets — shouldn't be masked.
const UNMASKED_KEYS = new Set<string>(["elevenlabs_voice_id"]);

interface ApiKeyConfig {
  key: string;
  label: string;
  reason: string;
  url: string;
  configured: boolean;
}

interface ApiKeysStepProps {
  keys: ApiKeyConfig[];
  onSaveKey: (keyName: string, value: string) => Promise<boolean>;
  onTestKey: (keyName: string) => Promise<boolean>;
  onNext: () => void;
  // Optional escape hatch — when present, a "Skip for now" link renders
  // below the Continue button. Lets users who don't have all their API
  // keys handy push into the dashboard and come back later. Parent is
  // responsible for any flagging + navigation.
  onSkipForNow?: () => void;
}

function KeyRow({
  config,
  onSaveKey,
  onTestKey,
}: {
  config: ApiKeyConfig;
  onSaveKey: (keyName: string, value: string) => Promise<boolean>;
  onTestKey: (keyName: string) => Promise<boolean>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [connected, setConnected] = useState(config.configured);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);

  const isMasked = !UNMASKED_KEYS.has(config.key) && !revealed;
  const placeholder = KEY_FORMAT_HINTS[config.key] ?? "Paste your API key…";

  async function handleSave() {
    if (!value.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await onSaveKey(config.key, value.trim());
      if (!saved) {
        setError("Failed to save key.");
        setSaving(false);
        return;
      }
      const tested = await onTestKey(config.key);
      if (tested) {
        setConnected(true);
        setEditing(false);
        setValue("");
      } else {
        setError("Key saved but connection test failed. Check the key and try again.");
      }
    } catch {
      setError("An error occurred. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="flex flex-col gap-2 rounded-lg px-4 py-3"
      style={{ background: "var(--surface)" }}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {connected ? (
            <Check size={16} className="shrink-0" style={{ color: "var(--success)" }} />
          ) : (
            <Circle size={16} className="shrink-0" style={{ color: "var(--gold)" }} />
          )}
          <div className="min-w-0">
            <p
              className="text-sm font-semibold font-body truncate"
              style={{ color: "var(--text-primary)" }}
            >
              {config.label}
            </p>
            <p
              className="text-xs font-body"
              style={{ color: "var(--text-secondary)" }}
            >
              {config.reason}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {connected ? (
            <span
              className="text-xs font-semibold font-body"
              style={{ color: "var(--success)" }}
            >
              Connected
            </span>
          ) : !editing ? (
            <button
              onClick={() => setEditing(true)}
              className="text-xs font-semibold font-body px-3 py-1 rounded-lg border transition-colors hover:brightness-110"
              style={{
                color: "var(--turquoise)",
                borderColor: "var(--turquoise)",
              }}
            >
              Configure
            </button>
          ) : null}

          <a
            href={config.url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:brightness-125"
            style={{ color: "var(--text-secondary)" }}
          >
            <ExternalLink size={14} />
          </a>
        </div>
      </div>

      {editing && !connected && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          transition={{ duration: 0.2 }}
          className="flex items-center gap-2 pt-1"
        >
          <div className="relative flex-1">
            <input
              type={isMasked ? "password" : "text"}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={placeholder}
              aria-label={`${config.label} value`}
              className={cn(
                "w-full rounded-lg border bg-[var(--bg-void)] px-3 py-1.5 text-sm",
                "placeholder:text-[var(--text-secondary)]/50",
                "focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
                "border-[var(--border)]",
                // Leave room on the right for the eye toggle when it renders.
                !UNMASKED_KEYS.has(config.key) && "pr-9"
              )}
              disabled={saving}
            />
            {!UNMASKED_KEYS.has(config.key) && (
              <button
                type="button"
                onClick={() => setRevealed((v) => !v)}
                aria-label={revealed ? "Hide key" : "Show key"}
                aria-pressed={revealed}
                disabled={saving}
                className={cn(
                  "absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded",
                  "text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
                  "focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
                  "disabled:opacity-40 disabled:cursor-not-allowed"
                )}
              >
                {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            )}
          </div>
          <ActionButton
            onClick={handleSave}
            disabled={!value.trim() || saving}
          >
            {saving ? (
              <span className="flex items-center gap-1">
                <Spinner size="sm" /> Testing...
              </span>
            ) : (
              "Save & Test"
            )}
          </ActionButton>
        </motion.div>
      )}

      {error && (
        <p className="text-xs" style={{ color: "var(--error)" }}>
          {error}
        </p>
      )}
    </div>
  );
}

export function ApiKeysStep({
  keys,
  onSaveKey,
  onTestKey,
  onNext,
  onSkipForNow,
}: ApiKeysStepProps) {
  const configuredCount = keys.filter((k) => k.configured).length;
  const total = keys.length;
  const progress = total > 0 ? (configuredCount / total) * 100 : 0;

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
            Connect Your Tools
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            These API keys power your video pipeline. Each service handles a
            different part.
          </p>
          <p
            className="text-xs font-body mt-2"
            style={{ color: "var(--text-tertiary)" }}
          >
            BYOK — you pay providers directly. Weekly cadence runs ~$15–30/mo
            across all four.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <span
              className="text-xs font-semibold font-body"
              style={{ color: "var(--text-secondary)" }}
            >
              {configuredCount} of {total} connected
            </span>
          </div>
          <div
            className="h-2 w-full rounded-full overflow-hidden"
            style={{ background: "var(--border)" }}
          >
            <motion.div
              className="h-full rounded-full"
              style={{ background: "var(--turquoise)" }}
              initial={{ width: 0 }}
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>

        <div className="flex flex-col gap-2">
          {keys.map((config) => (
            <KeyRow
              key={config.key}
              config={config}
              onSaveKey={onSaveKey}
              onTestKey={onTestKey}
            />
          ))}
        </div>

        <div className="flex flex-col items-center gap-2 pt-2">
          <ActionButton
            onClick={onNext}
            disabled={configuredCount < total}
          >
            {configuredCount < total
              ? `Connect all ${total} tools to continue`
              : "Continue"}
          </ActionButton>
          {onSkipForNow && configuredCount < total && (
            <button
              type="button"
              onClick={onSkipForNow}
              className="text-xs font-body underline-offset-4 hover:underline transition-colors"
              style={{ color: "var(--text-tertiary)" }}
            >
              Skip for now — finish later in Settings
            </button>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
