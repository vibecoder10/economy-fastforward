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
  return (
    <div className="h-screen w-screen bg-void">
      <DirectorProvider>
        <DirectorPreviewInner />
      </DirectorProvider>
    </div>
  );
}
