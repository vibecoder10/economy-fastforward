"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  AlertTriangle,
  CheckCircle,
  Circle,
  ExternalLink,
  Info,
  Loader2,
  Eye,
  EyeOff,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ActionButton } from "@/components/ui/ActionButton";

interface ReadinessKeyInfo {
  key: string;
  label: string;
  reason: string;
  url: string;
}

interface ReadinessCheckProps {
  missing: ReadinessKeyInfo[];
  configured: string[];
  warnings: ReadinessKeyInfo[];
  onConfigureKey: (keyName: string, value: string) => Promise<boolean>;
  onProceedAnyway: () => void;
  onClose: () => void;
}

export function ReadinessCheck({
  missing,
  configured,
  warnings,
  onConfigureKey,
  onProceedAnyway,
  onClose,
}: ReadinessCheckProps) {
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [keyValues, setKeyValues] = useState<Record<string, string>>({});
  const [savingKey, setSavingKey] = useState<string | null>(null);
  const [savedKeys, setSavedKeys] = useState<Set<string>>(new Set());
  const [errorKeys, setErrorKeys] = useState<Record<string, string>>({});
  const [showPassword, setShowPassword] = useState<Record<string, boolean>>({});

  const handleSaveKey = async (keyName: string) => {
    const value = keyValues[keyName]?.trim();
    if (!value) return;

    setSavingKey(keyName);
    setErrorKeys((prev) => {
      const next = { ...prev };
      delete next[keyName];
      return next;
    });

    try {
      const success = await onConfigureKey(keyName, value);
      if (success) {
        setSavedKeys((prev) => new Set(prev).add(keyName));
        setExpandedKey(null);
        setKeyValues((prev) => {
          const next = { ...prev };
          delete next[keyName];
          return next;
        });
      } else {
        setErrorKeys((prev) => ({ ...prev, [keyName]: "Key validation failed. Check the value and try again." }));
      }
    } catch {
      setErrorKeys((prev) => ({ ...prev, [keyName]: "Failed to save key. Please try again." }));
    } finally {
      setSavingKey(null);
    }
  };

  // Build a combined list: configured keys first, then missing
  const allRequired = [
    ...configured.map((key) => ({
      key,
      label: key,
      reason: "",
      url: "",
      isConfigured: true,
    })),
    ...missing.map((m) => ({
      ...m,
      isConfigured: savedKeys.has(m.key),
    })),
  ];

  return (
    <>
      {/* Backdrop */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onClose}
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
      />

      {/* Modal */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        transition={{ type: "spring", damping: 30, stiffness: 300 }}
        className="fixed left-1/2 top-1/2 z-50 -translate-x-1/2 -translate-y-1/2 w-[calc(100vw-32px)] max-w-lg max-h-[85vh] overflow-y-auto"
      >
        <div
          className="rounded-xl border shadow-2xl"
          style={{
            background: "var(--surface)",
            borderColor: "var(--border)",
          }}
        >
          {/* Header */}
          <div className="px-6 pt-6 pb-4 text-center">
            <div
              className="inline-flex items-center justify-center w-12 h-12 rounded-full mb-3"
              style={{ background: "rgba(245, 158, 11, 0.1)" }}
            >
              <AlertTriangle size={24} style={{ color: "var(--gold)" }} />
            </div>
            <h2
              className="text-xl font-display font-bold mb-1"
              style={{ color: "var(--text-primary)" }}
            >
              Almost There!
            </h2>
            <p className="text-sm font-body" style={{ color: "var(--text-secondary)" }}>
              Your pipeline needs a few more tools to create a video.
            </p>
          </div>

          {/* Key List */}
          <div className="px-6 space-y-2">
            {allRequired.map((item) => {
              const isConfigured = item.isConfigured;
              const isExpanded = expandedKey === item.key;
              const isSaving = savingKey === item.key;
              const error = errorKeys[item.key];

              return (
                <div
                  key={item.key}
                  className="rounded-lg border transition-all"
                  style={{
                    background: "var(--bg-elevated)",
                    borderColor: isConfigured
                      ? "rgba(16, 185, 129, 0.2)"
                      : error
                      ? "rgba(239, 68, 68, 0.3)"
                      : "var(--border)",
                  }}
                >
                  <div className="flex items-center gap-3 px-4 py-3">
                    {isConfigured ? (
                      <CheckCircle size={18} style={{ color: "var(--green)", flexShrink: 0 }} />
                    ) : (
                      <Circle size={18} style={{ color: "var(--gold)", flexShrink: 0 }} />
                    )}
                    <div className="flex-1 min-w-0">
                      <div
                        className="text-sm font-semibold font-body"
                        style={{ color: "var(--text-primary)" }}
                      >
                        {item.label}
                      </div>
                      {isConfigured && (
                        <span className="text-xs font-body" style={{ color: "var(--green)" }}>
                          Connected
                        </span>
                      )}
                      {!isConfigured && item.reason && (
                        <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                          {item.reason}
                        </span>
                      )}
                    </div>
                    {!isConfigured && (
                      <button
                        onClick={() => setExpandedKey(isExpanded ? null : item.key)}
                        className="text-xs font-semibold font-body px-3 py-1.5 rounded-md transition-all hover:brightness-110"
                        style={{
                          background: "rgba(0, 212, 170, 0.1)",
                          color: "var(--turquoise)",
                        }}
                      >
                        {isExpanded ? "Cancel" : "Configure"}
                      </button>
                    )}
                  </div>

                  {/* Inline key input */}
                  <AnimatePresence>
                    {isExpanded && !isConfigured && (
                      <motion.div
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        transition={{ duration: 0.2 }}
                        className="overflow-hidden"
                      >
                        <div className="px-4 pb-3 space-y-2">
                          <div className="relative">
                            <input
                              type={showPassword[item.key] ? "text" : "password"}
                              value={keyValues[item.key] || ""}
                              onChange={(e) =>
                                setKeyValues((prev) => ({ ...prev, [item.key]: e.target.value }))
                              }
                              placeholder={`Paste your ${item.label} key...`}
                              className="w-full pl-3 pr-10 py-2 rounded-lg text-sm font-mono outline-none transition-all"
                              style={{
                                background: "var(--bg-void)",
                                color: "var(--text-primary)",
                                border: `1px solid ${error ? "var(--red)" : "var(--border)"}`,
                              }}
                              onFocus={(e) => {
                                if (!error) e.target.style.borderColor = "var(--turquoise)";
                              }}
                              onBlur={(e) => {
                                if (!error) e.target.style.borderColor = "var(--border)";
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Enter") handleSaveKey(item.key);
                              }}
                              autoFocus
                            />
                            <button
                              type="button"
                              onClick={() =>
                                setShowPassword((prev) => ({
                                  ...prev,
                                  [item.key]: !prev[item.key],
                                }))
                              }
                              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded"
                              style={{ color: "var(--text-tertiary)" }}
                            >
                              {showPassword[item.key] ? <EyeOff size={14} /> : <Eye size={14} />}
                            </button>
                          </div>
                          <div className="flex items-center justify-between gap-2">
                            {item.url && (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 text-[11px] font-body transition-colors hover:underline"
                                style={{ color: "var(--turquoise-dim)" }}
                              >
                                Get key <ExternalLink size={10} />
                              </a>
                            )}
                            <button
                              onClick={() => handleSaveKey(item.key)}
                              disabled={!keyValues[item.key]?.trim() || isSaving}
                              className={cn(
                                "inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold font-body transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
                              )}
                              style={{
                                background: "var(--turquoise)",
                                color: "var(--bg-void)",
                              }}
                            >
                              {isSaving ? (
                                <>
                                  <Loader2 size={12} className="animate-spin" /> Testing...
                                </>
                              ) : (
                                "Save & Test"
                              )}
                            </button>
                          </div>
                          {error && (
                            <p className="text-[11px] font-body" style={{ color: "var(--red)" }}>
                              {error}
                            </p>
                          )}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              );
            })}
          </div>

          {/* Warnings */}
          {warnings.length > 0 && (
            <div className="px-6 mt-4">
              <div className="flex items-center gap-2 mb-2">
                <Info size={14} style={{ color: "var(--text-tertiary)" }} />
                <span className="text-xs font-body font-medium" style={{ color: "var(--text-tertiary)" }}>
                  Optional integrations
                </span>
              </div>
              <div className="space-y-1.5">
                {warnings.map((w) => (
                  <div
                    key={w.key}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-body"
                    style={{
                      background: "rgba(255, 255, 255, 0.02)",
                      color: "var(--text-tertiary)",
                    }}
                  >
                    <Info size={12} style={{ flexShrink: 0, color: "var(--text-tertiary)" }} />
                    <span>
                      <strong style={{ color: "var(--text-secondary)" }}>{w.label}</strong> &mdash; {w.reason}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Footer */}
          <div className="px-6 py-5 mt-4 space-y-3" style={{ borderTop: "1px solid var(--border-subtle)" }}>
            <ActionButton
              variant="filled"
              onClick={onClose}
              className="w-full justify-center"
            >
              I&apos;ve Added My Keys
            </ActionButton>
            <button
              onClick={onProceedAnyway}
              className="w-full text-center text-xs font-body transition-colors hover:underline"
              style={{ color: "var(--text-tertiary)" }}
            >
              Create anyway &mdash; pipeline will stop at missing stages
            </button>
          </div>
        </div>
      </motion.div>
    </>
  );
}
