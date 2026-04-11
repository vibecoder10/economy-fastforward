"use client";

import { motion } from "framer-motion";
import { CheckCircle2, Circle } from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { cn } from "@/lib/utils";

export interface ChecklistItem {
  label: string;
  done: boolean;
  detail?: string;
  href?: string;
}

interface SetupChecklistProps {
  items: ChecklistItem[];
  percentComplete: number;
}

export function SetupChecklist({ items, percentComplete }: SetupChecklistProps) {
  const allDone = percentComplete >= 100;

  return (
    <GlassCard>
      <h2
        className="text-[11px] font-semibold uppercase tracking-wider mb-4"
        style={{ color: "var(--text-secondary)" }}
      >
        Setup Progress
      </h2>

      {/* Progress bar */}
      <div className="mb-5">
        <div className="flex items-center justify-between mb-2">
          <span
            className="text-xs font-mono font-semibold"
            style={{ color: "var(--turquoise)" }}
          >
            {percentComplete}%
          </span>
        </div>
        <div
          className="h-2 rounded-full overflow-hidden"
          style={{ background: "rgba(255,255,255,0.06)" }}
        >
          <motion.div
            className="h-full rounded-full"
            style={{ background: "var(--turquoise)" }}
            initial={{ width: 0 }}
            animate={{ width: `${percentComplete}%` }}
            transition={{ duration: 0.8, ease: "easeOut" }}
          />
        </div>
      </div>

      {/* Checklist items */}
      <div className="space-y-1">
        {items.map((item) => {
          const Wrapper = item.href && !item.done ? "a" : "div";
          const wrapperProps = item.href && !item.done ? { href: item.href } : {};

          return (
            <Wrapper
              key={item.label}
              {...wrapperProps}
              className={cn(
                "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200",
                item.href && !item.done && "cursor-pointer hover:bg-white/[0.04]"
              )}
            >
              {item.done ? (
                <CheckCircle2
                  size={18}
                  className="shrink-0"
                  style={{ color: "var(--green)" }}
                />
              ) : (
                <Circle
                  size={18}
                  className="shrink-0"
                  style={{ color: "var(--text-tertiary)" }}
                />
              )}
              <span
                className={cn(
                  "text-sm flex-1",
                  item.done && "line-through opacity-60"
                )}
                style={{ color: item.done ? "var(--text-secondary)" : "var(--text-primary)" }}
              >
                {item.label}
              </span>
              {item.detail && (
                <span
                  className="text-xs font-mono shrink-0"
                  style={{ color: "var(--turquoise-dim)" }}
                >
                  {item.detail}
                </span>
              )}
            </Wrapper>
          );
        })}
      </div>

      {/* Celebration line */}
      {allDone && (
        <motion.p
          className="text-sm font-medium mt-4 text-center"
          style={{ color: "var(--green)" }}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3, duration: 0.5 }}
        >
          All set! You're ready to create.
        </motion.p>
      )}
    </GlassCard>
  );
}
