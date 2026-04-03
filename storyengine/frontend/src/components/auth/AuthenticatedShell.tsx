"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "./AuthProvider";
import { Sidebar } from "@/components/nav/sidebar";
import { BottomTabs } from "@/components/nav/bottom-tabs";
import { Spinner } from "@/components/ui/spinner";

const PUBLIC_PATHS = ["/login", "/onboarding"];

export function AuthenticatedShell({ children }: { children: ReactNode }) {
  const { user, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.some((p) => pathname.startsWith(p));

  useEffect(() => {
    if (isLoading) return;
    if (!user && !isPublicPath) {
      router.replace("/login");
    }
  }, [user, isLoading, isPublicPath, router]);

  // Public pages (login) render without shell
  if (isPublicPath) {
    return <div className="min-h-screen relative z-10">{children}</div>;
  }

  // Show loading while checking auth
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen relative z-10">
        <Spinner size="lg" />
      </div>
    );
  }

  // Not authenticated — will redirect via useEffect
  if (!user) return null;

  // Authenticated — full app shell
  return (
    <div className="flex min-h-screen relative z-10">
      <Sidebar />
      <main className="flex-1 pb-16 md:pb-0 md:ml-60">
        <div className="mx-auto max-w-[1400px] px-6 py-6 md:px-12 md:py-10">
          {children}
        </div>
      </main>
      <BottomTabs />
    </div>
  );
}
