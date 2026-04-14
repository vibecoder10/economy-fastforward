"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getOnboardingStatus } from "@/lib/api";

/**
 * Redirects to /onboarding if the user hasn't completed onboarding.
 * Returns { isComplete, isLoading } so the consuming page can show a loader.
 */
export function useOnboardingGate() {
  const router = useRouter();

  const { data: onboarding, isLoading } = useQuery({
    queryKey: ["onboarding-status"],
    queryFn: getOnboardingStatus,
  });

  const isComplete = onboarding?.completed ?? false;

  useEffect(() => {
    if (!isLoading && onboarding && !onboarding.completed) {
      router.replace("/onboarding");
    }
  }, [isLoading, onboarding, router]);

  return { isComplete, isLoading };
}
