"use client";

import { useDirector } from "./DirectorContext";
import { SceneAltitudeView } from "./SceneAltitudeView";

/**
 * Altitude router for the canvas stage (Chunk 1.E). Renders one of Shot /
 * Scene / Timeline based on DirectorContext's `altitude`, matching
 * storyengine/tasks/director-mockup/index.html `#tab-shot` / `#tab-scene` /
 * `#tab-timeline` (~L894-1131).
 */
export function CanvasStage({ videoId }: { videoId: string }) {
  const { altitude } = useDirector();

  if (altitude === "scene") return <SceneAltitudeView videoId={videoId} />;
  if (altitude === "shot") return <ShotAltitudePlaceholder />;
  return <TimelineAltitudePlaceholder />;
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

/**
 * Mockup `#tab-timeline` (~L1086-1131) — a fully-fledged-looking timeline
 * with a "New — doesn't exist in the product yet" pill right in the
 * toolbar. Reproduced as a static, non-interactive layout (ruler, three
 * lanes, a playhead) so the pill's honesty holds: nothing here is wired to
 * real clip/narration/music data, and no control does anything.
 */
function TimelineAltitudePlaceholder() {
  const ticks = Array.from({ length: 12 }, (_, i) => i * 13);
  const clips = [
    { label: "1.1", width: 11, bg: "linear-gradient(150deg,#1B2E4A,#3E5C86 55%,#8FA9C9)" },
    { label: "1.2", width: 9, bg: "linear-gradient(150deg,#101826,#243A54 55%,#5E7FA6)" },
    { label: "1.3 hero", width: 14, bg: "linear-gradient(150deg,#3D2413,#8A4A22 55%,#E0A167)" },
    { label: "1.4", width: 8, bg: "linear-gradient(150deg,#151A24,#2E3646 60%,#59617A)" },
    { label: "2.1", width: 12, bg: "linear-gradient(150deg,#0E3A34,#1C7A66 55%,#7FD8C0)" },
    { label: "2.4 hero", width: 16, bg: "linear-gradient(150deg,#2B0F19,#7A2338 55%,#D9738C)" },
    { label: "3.1", width: 10, bg: "linear-gradient(150deg,#2A1B3D,#5B3A6E 55%,#C08BB0)" },
  ];

  return (
    <div className="h-full overflow-y-auto p-[22px]">
      <div className="overflow-hidden rounded-card border border-line-soft bg-surface">
        <div className="flex items-center gap-2.5 border-b border-line-soft px-3.5 py-2.5">
          <span className="font-mono text-xs text-dim">00:41 / 02:18</span>
          <span className="ml-2 flex h-7 items-center rounded-full border border-line-soft bg-deep px-2.5 text-xs text-dim">
            New — doesn&apos;t exist in the product yet
          </span>
          <div className="ml-auto flex gap-1.5">
            <button type="button" disabled className="h-8 rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink opacity-50">
              Split
            </button>
            <button type="button" disabled className="h-8 rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink opacity-50">
              Fit
            </button>
          </div>
        </div>

        <div className="relative">
          <div className="relative h-[26px] border-b border-line-soft bg-deep">
            {ticks.map((secs, i) => (
              <div
                key={i}
                className="absolute top-0 bottom-0 border-l border-white/[0.09]"
                style={{ left: `${(i * 100) / 11}%` }}
              >
                <span className="absolute left-1.5 top-1.5 text-[9.5px] text-faint">
                  {Math.floor(secs / 60)}:{String(secs % 60).padStart(2, "0")}
                </span>
              </div>
            ))}
          </div>

          <div className="flex min-h-14 items-stretch border-b border-line-soft">
            <div className="w-[92px] flex-none border-r border-line-soft bg-deep px-2.5 py-2 text-[11px] text-dim">
              Video
            </div>
            <div className="relative flex flex-1 gap-1 p-2">
              {clips.map((c) => (
                <div
                  key={c.label}
                  className="relative h-10 overflow-hidden rounded-[7px] border border-white/10"
                  style={{ width: `${c.width}%`, background: c.bg }}
                >
                  <span className="absolute bottom-0.5 left-1.5 text-[9px] text-white/90 [text-shadow:0_1px_3px_#000]">
                    {c.label}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="flex min-h-14 items-stretch border-b border-line-soft">
            <div className="w-[92px] flex-none border-r border-line-soft bg-deep px-2.5 py-2 text-[11px] text-dim">
              Narration
            </div>
            <div className="relative flex flex-1 gap-1 p-2">
              <div className="h-10 w-[62%] rounded-[7px] border border-turquoise/32 bg-turquoise/[0.12]" />
              <div className="h-10 w-[26%] rounded-[7px] border border-turquoise/32 bg-turquoise/[0.12]" />
            </div>
          </div>

          <div className="flex min-h-14 items-stretch">
            <div className="w-[92px] flex-none border-r border-line-soft bg-deep px-2.5 py-2 text-[11px] text-dim">
              Music &amp; SFX
            </div>
            <div className="relative flex flex-1 gap-1 p-2">
              <div className="h-10 w-[82%] rounded-[7px] border border-gold-director/30 bg-gold-director/10" />
            </div>
          </div>

          <div className="pointer-events-none absolute inset-y-0 left-[34%] w-0.5 bg-red">
            <div className="absolute -left-[5px] -top-1.5 h-3 w-3 rounded-[3px] bg-red" />
          </div>
        </div>
      </div>
    </div>
  );
}
