"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import {
  DRAIN_MODE_EVENT,
  getHealthStatus,
  type DrainState,
} from "@/lib/api";

type DrainModeContextValue = {
  draining: boolean;
  state: DrainState | null;
  activeTasks: number;
};

const DrainModeContext = createContext<DrainModeContextValue>({
  draining: false,
  state: null,
  activeTasks: 0,
});

export function DrainModeProvider({ children }: { children: ReactNode }) {
  const [eventState, setEventState] = useState<DrainState | null>(null);
  const { data } = useQuery({
    queryKey: ["system-health"],
    queryFn: getHealthStatus,
    refetchInterval: 5_000,
    staleTime: 0,
    retry: false,
  });

  useEffect(() => {
    const onDrainResponse = (event: Event) => {
      const detail = (event as CustomEvent<DrainState>).detail;
      setEventState({ ...detail, mode: "draining", draining: true });
    };
    window.addEventListener(DRAIN_MODE_EVENT, onDrainResponse);
    return () => window.removeEventListener(DRAIN_MODE_EVENT, onDrainResponse);
  }, []);

  // A successful health poll is authoritative and clears an earlier 503 event
  // as soon as the deploy reopens generation.
  useEffect(() => {
    if (data?.drain && !data.drain.draining) {
      setEventState(null);
    }
  }, [data?.drain]);

  const state = eventState?.draining ? eventState : data?.drain || eventState;
  const value = useMemo(
    () => ({
      draining: Boolean(state?.draining),
      state,
      activeTasks: data?.active_tasks ?? 0,
    }),
    [data?.active_tasks, state]
  );

  return <DrainModeContext.Provider value={value}>{children}</DrainModeContext.Provider>;
}

export function useDrainMode() {
  return useContext(DrainModeContext);
}

export function DrainModeBanner() {
  const { draining, state, activeTasks } = useDrainMode();
  if (!draining) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="px-4 py-3 pl-16 flex items-start gap-2 text-sm font-body sm:pl-4 sm:items-center"
      style={{
        background: "rgba(212, 168, 82, 0.12)",
        borderBottom: "1px solid rgba(212, 168, 82, 0.35)",
        color: "var(--gold)",
      }}
    >
      <AlertTriangle size={16} className="mt-0.5 shrink-0 sm:mt-0" />
      <span className="leading-snug">
        New generation is briefly paused for a safe update.
        {activeTasks > 0
          ? ` ${activeTasks} active work signal${activeTasks === 1 ? " is" : "s are"} finishing.`
          : " Existing work is safe and generation will reopen shortly."}
        {state?.reason && state.reason !== "safe production deploy" ? ` ${state.reason}` : ""}
      </span>
    </div>
  );
}
