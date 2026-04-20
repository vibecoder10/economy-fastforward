"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "@/components/auth/AuthProvider";
import { ToastProvider } from "@/components/ui/toast";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            // Polling is opt-in. Previously a global 60s refetchInterval
            // meant every useQuery background-polled even when pointless,
            // which made the free-plan 15-req/min rate limit hair-trigger
            // on the dashboard. Queries that actually need freshness
            // (pending-review, task-status, discovery-status, etc.)
            // already declare their own refetchInterval.
            refetchInterval: false,
            refetchOnWindowFocus: true,
            refetchOnReconnect: true,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>{children}</ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
