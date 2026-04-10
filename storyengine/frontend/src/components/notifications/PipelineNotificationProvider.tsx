"use client";

import { useRef, type ReactNode } from "react";
import { usePipelineSSE, SSETaskProgressEvent, SSEStageChangeEvent } from "@/hooks/use-pipeline-sse";
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
      const stage = formatStageLabel(event.to_status);
      toast.info(`${title} → ${stage}`);
    },
    onTaskProgress: (event: SSETaskProgressEvent) => {
      if (!event.status || event.status === "idle" || event.status === "running") return;

      if (event.status === "completed") {
        if (shouldThrottle()) return;
        toast.success(event.message || "Task completed");
      } else if (event.status === "failed") {
        if (shouldThrottle()) return;
        toast.error(event.error || event.message || "Task failed");
      }
    },
  });

  return <>{children}</>;
}
