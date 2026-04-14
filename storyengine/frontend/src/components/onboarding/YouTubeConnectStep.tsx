"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
import { Check, Youtube, BarChart3 } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";

interface YouTubeConnectStepProps {
  connected: boolean;
  channelName: string | null;
  onConnect: () => void;
  onNext: () => void;
  onSkip: () => void;
  connecting: boolean;
  syncing?: boolean;
  onStartSync?: () => void;
}

export function YouTubeConnectStep({
  connected,
  channelName,
  onConnect,
  onNext,
  onSkip,
  connecting,
  syncing,
  onStartSync,
}: YouTubeConnectStepProps) {
  // Auto-trigger sync when YouTube gets connected
  useEffect(() => {
    if (connected && onStartSync) {
      onStartSync();
    }
  }, [connected, onStartSync]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="w-full max-w-lg mx-auto"
    >
      <GlassCard className="flex flex-col items-center text-center gap-6 py-10">
        <div>
          <h2
            className="text-xl font-semibold font-body mb-1"
            style={{ color: "var(--text-primary)" }}
          >
            Connect YouTube
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            Link your channel to unlock analytics and auto-sync performance data.
          </p>
        </div>

        {connected ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3 }}
            className="space-y-3"
          >
            <GlassCard
              className="border"
              style={{ borderColor: "var(--success)" }}
            >
              <div className="flex items-center gap-3">
                <Check size={20} style={{ color: "var(--success)" }} />
                <span
                  className="text-sm font-semibold font-body"
                  style={{ color: "var(--text-primary)" }}
                >
                  Connected: {channelName}
                </span>
              </div>
            </GlassCard>
            {syncing && (
              <div className="flex items-center justify-center gap-2">
                <Spinner size="sm" />
                <span className="text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
                  Syncing your analytics in the background...
                </span>
              </div>
            )}
          </motion.div>
        ) : (
          <>
            <div className="flex items-center gap-2 text-xs font-body" style={{ color: "var(--text-tertiary)" }}>
              <BarChart3 size={14} />
              <span>Your analytics dashboard will populate automatically</span>
            </div>
            <ActionButton
              icon={Youtube}
              onClick={onConnect}
              disabled={connecting}
            >
              {connecting ? (
                <span className="flex items-center gap-2">
                  <Spinner size="sm" /> Connecting...
                </span>
              ) : (
                "Connect YouTube"
              )}
            </ActionButton>
          </>
        )}

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton onClick={onNext}>Continue</ActionButton>

          {!connected && (
            <button
              onClick={onSkip}
              className="text-xs font-body hover:underline"
              style={{ color: "var(--text-secondary)" }}
            >
              Skip — you can connect later in Settings
            </button>
          )}
        </div>
      </GlassCard>
    </motion.div>
  );
}
