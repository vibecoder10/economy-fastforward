"use client";

import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { ActionButton } from "@/components/ui/ActionButton";

interface ReadyStepProps {
  displayName: string;
  onStart: () => void;
}

export function ReadyStep({ displayName, onStart }: ReadyStepProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="flex flex-col items-center text-center gap-8 py-12"
    >
      <motion.div
        initial={{ scale: 0 }}
        animate={{ scale: 1 }}
        transition={{ type: "spring", stiffness: 200, damping: 15, delay: 0.2 }}
        className="rounded-full p-6"
        style={{ background: "var(--turquoise-dim)" }}
      >
        <Check size={48} style={{ color: "var(--turquoise)" }} />
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.4, duration: 0.4 }}
      >
        <h2
          className="text-2xl font-semibold font-body mb-2"
          style={{ color: "var(--text-primary)" }}
        >
          You&apos;re All Set, {displayName}!
        </h2>
        <p
          className="text-sm font-body max-w-md"
          style={{ color: "var(--text-secondary)" }}
        >
          Your AI video studio is ready. Create your first video or explore the
          platform.
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.6, duration: 0.4 }}
      >
        <ActionButton onClick={onStart} className="text-base px-8 py-3">
          Create Your First Video
        </ActionButton>
      </motion.div>
    </motion.div>
  );
}
