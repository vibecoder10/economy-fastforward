"use client";

import { useQuery } from "@tanstack/react-query";
import { getHealthStatus, HealthStatus } from "@/lib/api";

export function useHealthCheck() {
  return useQuery<HealthStatus>({
    queryKey: ["health-status"],
    queryFn: getHealthStatus,
    refetchInterval: 60_000,
    retry: 1,
    staleTime: 55_000,
  });
}
