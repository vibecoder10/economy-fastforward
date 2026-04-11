"use client";

import { motion } from "framer-motion";
import { Download, Check } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { Spinner } from "@/components/ui/spinner";

interface ImportDataStepProps {
  onSync: () => void;
  onNext: () => void;
  onSkip: () => void;
  syncing: boolean;
  syncResult: { videos_synced: number; videos_total: number } | null;
}

export function ImportDataStep({
  onSync,
  onNext,
  onSkip,
  syncing,
  syncResult,
}: ImportDataStepProps) {
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
            Import Your Data
          </h2>
          <p
            className="text-sm font-body"
            style={{ color: "var(--text-secondary)" }}
          >
            We&apos;ll analyze your existing videos to learn what works for your
            audience.
          </p>
        </div>

        {syncResult ? (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.3 }}
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
                  Synced {syncResult.videos_synced} of {syncResult.videos_total}{" "}
                  videos
                </span>
              </div>
            </GlassCard>
          </motion.div>
        ) : (
          <ActionButton
            icon={Download}
            onClick={onSync}
            disabled={syncing}
          >
            {syncing ? (
              <span className="flex items-center gap-2">
                <Spinner size="sm" /> Syncing...
              </span>
            ) : (
              "Sync My Channel"
            )}
          </ActionButton>
        )}

        <div className="flex flex-col items-center gap-3 pt-2">
          <ActionButton onClick={onNext}>Continue</ActionButton>

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
