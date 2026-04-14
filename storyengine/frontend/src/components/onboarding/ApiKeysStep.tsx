"use client";

import { motion } from "framer-motion";
import { Check, Circle, ExternalLink } from "lucide-react";
import { useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

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
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="Paste your API key..."
            className={cn(
              "flex-1 rounded-lg border bg-[var(--bg-void)] px-3 py-1.5 text-sm",
              "placeholder:text-[var(--text-secondary)]/50",
              "focus:border-[var(--accent)] focus:outline-none focus:ring-1 focus:ring-[var(--accent)]",
              "border-[var(--border)]"
            )}
            disabled={saving}
          />
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

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton
            onClick={onNext}
            disabled={configuredCount < total}
          >
            {configuredCount < total
              ? `Connect all ${total} tools to continue`
              : "Continue"}
          </ActionButton>
        </div>
      </GlassCard>
    </motion.div>
  );
}
