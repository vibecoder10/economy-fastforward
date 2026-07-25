"use client";

// Throwaway preview route for the Director surface (Chunk 1.A). Lets later
// chunks and the final verification walk render <DirectorSurface /> without
// touching app/page.tsx or app/chat/page.tsx (owned by Chunk 1.F). 1.F
// removes this route once the real page is wired.
//
// Query param ?video=1 flips selectedVideoId away from null so the
// two-column chat/canvas layout renders instead of the DirectorHome
// placeholder — useful for screenshotting both states of DirectorSurface.

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { DirectorProvider, useDirector } from "@/components/director/DirectorContext";
import { DirectorSurface } from "@/components/director/DirectorSurface";

function DirectorPreviewInner() {
  const searchParams = useSearchParams();
  const { setSelectedVideoId } = useDirector();

  useEffect(() => {
    if (searchParams.get("video")) {
      setSelectedVideoId("preview-video-id");
    }
  }, [searchParams, setSelectedVideoId]);

  return <DirectorSurface />;
}

export default function DirectorPreviewPage() {
  // `fixed inset-0` (not h-screen/w-screen) — this route renders inside
  // AuthenticatedShell's padded, sidebar-margined main content area
  // (`md:ml-60` + `max-w-[1400px]` + padding, see AuthenticatedShell.tsx).
  // `w-screen`/`h-screen` compute against the real viewport but the div's
  // OFFSET still comes from that ancestor padding/margin, so the box
  // overflowed ~290px past the right edge of the window (verified via
  // Chunk 1.E's browser walk — Build button rendered at x≈1656 on a 1434px
  // viewport). `fixed inset-0` escapes the padded flow entirely instead,
  // which is what a full-bleed app-shell preview route wants anyway.
  return (
    <div className="fixed inset-0 z-50 bg-void">
      <DirectorProvider>
        <DirectorPreviewInner />
      </DirectorProvider>
    </div>
  );
}
