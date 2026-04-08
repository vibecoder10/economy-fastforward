"use client";

import { useRef, type ReactNode } from "react";
import { usePipelineSSE, SSEActivityEvent, SSEStageChangeEvent } from "@/hooks/use-pipeline-sse";
import { useToast } from "@/components/ui/toast";
import { getStageLabel } from "@/lib/constants";

const COOLDOWN_MS = 5_000; // Min 5s between toasts to avoid spam

function formatStageLabel(status: string): string {
  return getStageLabel(status);
}

export function PipelineNotificationProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const lastToast = useRef<number>(0);

  const shouldThrottle = (): boolean => {
    const now = Date.now();
    if (now - lastToast.current < COOLDOWN_MS) return true;
    lastToast.current = now;
    return false;
  };

  usePipelineSSE({
    onStageChange: (event: SSEStageChangeEvent) => {
      if (shouldThrottle()) return;

      const title = event.video_title || "Video";
      const stage = formatStageLabel(event.new_status);
      toast.info(`${title} → ${stage}`);
    },
    onActivity: (event: SSEActivityEvent) => {
      if (!event.status) return;

      // Only notify on completed or error statuses
      if (event.status === "completed") {
        if (shouldThrottle()) return;
        const label = event.video_title || event.bot_name || "Task";
        toast.success(`${label}: ${event.message || "Done"}`);
      } else if (event.status === "error" || event.status === "failed") {
        if (shouldThrottle()) return;
        const label = event.video_title || event.bot_name || "Pipeline";
        toast.error(`${label}: ${event.message || "Failed"}`);
      }
    },
  });

  return <>{children}</>;
}
