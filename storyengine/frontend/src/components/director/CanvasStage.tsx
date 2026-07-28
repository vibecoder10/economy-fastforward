"use client";

import { useDirector } from "./DirectorContext";
import { SceneAltitudeView } from "./SceneAltitudeView";
import { TimelineAltitudeView } from "./TimelineAltitudeView";

/**
 * Altitude router for the canvas stage (Chunk 1.E). Renders one of Shot /
 * Scene / Timeline based on DirectorContext's `altitude`, matching
 * storyengine/tasks/director-mockup/index.html `#tab-shot` / `#tab-scene` /
 * `#tab-timeline` (~L894-1131).
 *
 * Timeline chunk T2 (2026-07-28) replaced the old static
 * `TimelineAltitudePlaceholder` mock with a real, read-only
 * `TimelineAltitudeView` — see TIMELINE-WORKBENCH-PLAN.md and
 * canvas-shared/timeline-slots.ts (T1) for the data model it renders.
 */
export function CanvasStage({ videoId }: { videoId: string }) {
  const { altitude } = useDirector();

  if (altitude === "scene") return <SceneAltitudeView videoId={videoId} />;
  if (altitude === "shot") return <ShotAltitudePlaceholder />;
  return <TimelineAltitudeView videoId={videoId} />;
}

/**
 * Mockup `#tab-shot` (~L1076-1083) ships a placeholder here too — copy
 * reproduced verbatim, including the mockup's own admission it isn't
 * designed yet.
 */
function ShotAltitudePlaceholder() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2.5 px-5 py-16 text-center">
      <div className="text-[30px]" aria-hidden="true">
        ▤
      </div>
      <h3 className="text-[17px] font-semibold text-ink">Shot view</h3>
      <p className="max-w-[440px] text-[13px] leading-relaxed text-dim">
        One shot, full width — the still, the prompt that made it, the motion prompt, the model, and a redraw
        button. Not designed yet; say the word and it gets built out.
      </p>
    </div>
  );
}
