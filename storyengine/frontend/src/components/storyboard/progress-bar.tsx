"use client";

import { motion } from "framer-motion";
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  current: number;
  total: number;
  className?: string;
}

export function StoryboardProgressBar({ current, total, className }: ProgressBarProps) {
  const percentage = total > 0 ? (current / total) * 100 : 0;

  return (
    <div className={cn("space-y-1.5", className)}>
      <div className="flex items-center justify-between text-xs">
        <span className="text-[var(--text-secondary)]">Review Progress</span>
        <span className="font-medium">
          {current}/{total} scenes
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-[var(--surface-elevated)]">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
          className={cn(
            "h-full rounded-full",
            percentage === 100 ? "bg-green-500" : "bg-[var(--accent)]"
          )}
        />
      </div>
    </div>
  );
}
