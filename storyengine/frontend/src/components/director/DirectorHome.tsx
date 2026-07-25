"use client";

import { useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  getProductionStyles,
  getVideos,
  type ProductionStyleId,
  type VideoSummary,
} from "@/lib/api";
import { cn, timeAgo, toDisplayImageUrl } from "@/lib/utils";
import { COMPLETED_STATUSES, getStageLabel } from "@/lib/constants";
import { useDirector } from "./DirectorContext";
import { StyleLibrary } from "./StyleLibrary";

/**
 * Director home screen (Chunk 1.D) — the screen that did not exist before
 * this chunk. Spec of record: storyengine/tasks/director-mockup/index.html
 * `#home` (~L484-744). Every user-facing string below is copied verbatim
 * from that mockup; do not paraphrase or "clean up" the copy.
 */

// ---------------------------------------------------------------------------
// Section 1 — "Start from a channel you've built"
// ---------------------------------------------------------------------------

// The mockup's `.art` gradient placeholders (index.html `.g1`-`.g7`, ~L77-83).
// Reused verbatim as inline gradients since these are one-off decorative
// tiles, not reusable design-system colors.
const ART_GRADIENTS: Record<string, string> = {
  g1: "linear-gradient(150deg,#1B2E4A,#3E5C86 55%,#8FA9C9)",
  g2: "linear-gradient(150deg,#2A1B3D,#5B3A6E 55%,#C08BB0)",
  g3: "linear-gradient(150deg,#0E3A34,#1C7A66 55%,#7FD8C0)",
  g4: "linear-gradient(150deg,#3D2413,#8A4A22 55%,#E0A167)",
  g5: "linear-gradient(150deg,#101826,#243A54 55%,#5E7FA6)",
  g6: "linear-gradient(150deg,#2B0F19,#7A2338 55%,#D9738C)",
  g7: "linear-gradient(150deg,#151A24,#2E3646 60%,#59617A)",
};

// Chunk brief: "If the API's labels are the old internal names, map them to
// the approved labels in the frontend." Verified live — GET /api/production-styles
// (backend/migrations/121_production_style_profiles.sql) still serves the old
// internal labels ("Bilingual Character Animation", "Animated Investigative
// Documentary", etc). This maps each production_style_id to the de-jargoned
// name and description approved in the mockup — never render the API's raw
// `label`/`description` fields on these cards.
const CHANNEL_CARDS: Array<{
  id: ProductionStyleId;
  label: string;
  description: string;
  art: string;
}> = [
  {
    id: "bilingual_character_animation",
    label: "Bilingual Character Cartoon",
    description: "Animated characters talking, two languages side by side",
    art: "g2",
  },
  {
    id: "simple_language_animation",
    label: "Simple-Language Cartoon",
    description: "Animation that teaches with easy words, built for learners",
    art: "g3",
  },
  {
    id: "animated_investigative_documentary",
    label: "Animated Investigation",
    description: "A research deep-dive told with illustrations",
    art: "g6",
  },
  {
    id: "photo_documentary",
    label: "Photo Documentary",
    description: "Real photographs with documentary narration, images sequenced to the script",
    art: "g5",
  },
];

function ChannelSection() {
  // Reuses the same fetch ProductionStyleSelector already uses — this call
  // only confirms the four profiles are live; the cards themselves render
  // the approved labels/copy above, not the API's fields (see CHANNEL_CARDS).
  useQuery({
    queryKey: ["production-styles"],
    queryFn: getProductionStyles,
    staleTime: 5 * 60 * 1000,
  });

  return (
    <div className="mb-11">
      <div className="mb-3.5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight text-ink">
          Start from a channel you&apos;ve built
        </h2>
        <span className="text-[12.5px] text-faint">
          How it&apos;s built, written and drawn — already locked in
        </span>
      </div>
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        {CHANNEL_CARDS.map((card) => (
          <button
            key={card.id}
            type="button"
            // Not wired — starting a NEW video from a channel needs a
            // title/creation flow that is out of this chunk's scope (this
            // chunk only builds the home screen). Phase 2 wires this.
            className="group flex flex-col overflow-hidden rounded-card border border-edge bg-surface text-left transition-transform duration-150 hover:-translate-y-[3px] hover:border-turquoise/40"
          >
            <div
              className="h-[84px] w-full"
              style={{ background: ART_GRADIENTS[card.art] }}
            />
            <div className="flex flex-1 flex-col p-[13px_15px_15px]">
              <h3 className="mb-1 text-[14.5px] font-semibold text-ink">{card.label}</h3>
              <p className="text-[12.5px] leading-relaxed text-dim">{card.description}</p>
              <div className="mt-auto flex items-center gap-1.5 pt-2.5 text-[11.5px] font-semibold text-turquoise">
                Open <span>&rsaquo;</span>
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — "Or just describe it" (presentational only this phase)
// ---------------------------------------------------------------------------

function DescribeSection() {
  const [prompt, setPrompt] = useState(
    "A short doc about why nobody fixes potholes — dry, funny, ends on a real number"
  );

  return (
    <div className="mb-11">
      <div className="mb-3.5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight text-ink">Or just describe it</h2>
        <span className="text-[12.5px] text-faint">
          The engine builds a new style out of the parts it already knows
        </span>
      </div>
      <div className="rounded-card border border-edge bg-gradient-to-b from-turquoise/5 to-transparent bg-surface p-[22px]">
        <div className="flex items-center gap-2.5 rounded-xl border border-line-soft bg-deep py-3 pl-4 pr-3 transition-colors focus-within:border-turquoise/45">
          <span className="text-base text-turquoise">&#9679;</span>
          <input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            spellCheck={false}
            className="flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
          />
          <button
            type="button"
            // Phase 2 wires this to the compose API. Local state only for now.
            className="inline-flex h-8 items-center gap-1.5 rounded-[9px] bg-gradient-to-b from-[#00E4B8] to-[#00B492] px-3.5 text-[13px] font-semibold text-[#04120E] shadow-[0_2px_14px_rgba(0,212,170,0.28)] transition-[filter] hover:brightness-[1.08]"
          >
            Compose style &rarr;
          </button>
        </div>

        <div className="mt-5">
          <div className="mb-3 flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-turquoise">
              Here&apos;s what it picked
            </span>
            <span className="text-[11.5px] text-faint">
              For each part of the video it picks how to build it, how to write it, and how it
              should look
            </span>
          </div>
          <div className="flex flex-col gap-2">
            <ComposeRow
              name="The opening"
              sub="First 20 seconds"
              builtLike="an investigation"
              writtenLike="a photo documentary"
              looksLike="a character cartoon"
            />
            <ComposeRow
              name="The middle"
              sub="Where the proof goes"
              builtLike="a photo documentary"
              writtenLike="an investigation"
              looksLike="a photo documentary"
            />
            <ComposeRow
              name="The ending"
              sub="Last 45 seconds"
              builtLike="simple language"
              writtenLike="a character cartoon"
              looksLike="an investigation"
            />
          </div>
          <div className="mt-3 text-[11.5px] leading-relaxed text-faint">
            Three dials per section: <b className="font-semibold text-dim">Built like</b> is the
            order and pacing, <b className="font-semibold text-dim">Written like</b> is how the
            script sounds, <b className="font-semibold text-dim">Looks like</b> is how it&apos;s
            drawn or shot. It mixes them freely.
          </div>
        </div>
      </div>
    </div>
  );
}

function ComposeRow({
  name,
  sub,
  builtLike,
  writtenLike,
  looksLike,
}: {
  name: string;
  sub: string;
  builtLike: string;
  writtenLike: string;
  looksLike: string;
}) {
  return (
    <div className="grid grid-cols-1 items-center gap-3.5 rounded-xl border border-line-soft bg-deep px-3.5 py-2.5 sm:grid-cols-[190px_1fr]">
      <div className="text-[13px] font-medium text-ink">
        {name}
        <span className="mt-0.5 block text-[11px] font-normal text-faint">{sub}</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <Tag label="Built like" value={builtLike} />
        <Tag label="Written like" value={writtenLike} />
        <Tag label="Looks like" value={looksLike} />
      </div>
    </div>
  );
}

function Tag({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-[7px] border border-line-soft bg-white/[0.03] px-2.5 py-1 text-[11px] text-dim">
      <i className="not-italic font-semibold text-ink">{label}</i>
      <b className="font-normal text-dim">{value}</b>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Section 3 — "Or clone a video you like" (presentational only this phase)
// ---------------------------------------------------------------------------

function CloneSection() {
  const [videoUrl, setVideoUrl] = useState("https://youtube.com/watch?v=9Xk1p2Qd7Lm");
  const [twist, setTwist] = useState("Same energy, but do it with Pokemon.");
  const [automate, setAutomate] = useState(false);

  return (
    <div className="mb-11">
      <div className="mb-3.5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight text-ink">
          Or clone a video you like
        </h2>
        <span className="text-[12.5px] text-faint">Drop one in, tell it your twist, let it run</span>
      </div>
      <div className="rounded-card border border-edge bg-gradient-to-b from-turquoise/5 to-transparent bg-surface p-[22px]">
        <div className="grid grid-cols-1 items-start gap-3.5 md:grid-cols-2">
          <div>
            <Step n={1}>
              <div className="mb-1.5 text-[12.5px] font-semibold text-ink">Paste a video link</div>
              <div className="flex items-center gap-2.5 rounded-[10px] border border-line-soft bg-deep px-2.5 py-2 text-[12.5px]">
                <span className="text-turquoise">&#128279;</span>
                <input
                  value={videoUrl}
                  onChange={(e) => setVideoUrl(e.target.value)}
                  spellCheck={false}
                  className="flex-1 bg-transparent text-[12.5px] text-ink outline-none"
                />
                <span className="inline-flex h-[22px] items-center gap-1.5 rounded-full border border-line-soft bg-deep px-2.5 text-[10.5px] text-dim">
                  <span className="h-1.5 w-1.5 rounded-full bg-turquoise" /> Read
                </span>
              </div>
              <div className="mt-1.5 text-[11px] text-faint">YouTube, Instagram or TikTok</div>
            </Step>

            <Step n={2}>
              <div className="mb-1.5 text-[12.5px] font-semibold text-ink">What we found</div>
              <div className="rounded-[10px] border border-line-soft bg-deep p-[11px_12px]">
                <div className="mb-2 flex flex-wrap gap-1.5">
                  <Tag label="Built like" value="a fast hook and payoff" />
                  <Tag label="Written like" value="punchy narration" />
                  <Tag label="Looks like" value="photorealistic live-action" />
                </div>
                <div className="text-[11px] leading-relaxed text-faint">
                  We pulled real frames from the middle of the video and described what is
                  actually on screen — so when the footage is real people, it says{" "}
                  <b className="font-semibold text-turquoise">live-action</b>. It never guesses
                  &ldquo;cartoon&rdquo; at a real video.
                </div>
              </div>
            </Step>
          </div>

          <div>
            <Step n={3}>
              <div className="mb-1.5 text-[12.5px] font-semibold text-ink">Make it yours</div>
              <div className="flex items-center gap-2.5 rounded-[10px] border border-line-soft bg-deep px-2.5 py-2 text-[12.5px]">
                <input
                  value={twist}
                  onChange={(e) => setTwist(e.target.value)}
                  spellCheck={false}
                  className="flex-1 bg-transparent text-[12.5px] text-ink outline-none"
                />
              </div>
            </Step>

            <Step n={4}>
              <div className="mb-1.5 text-[12.5px] font-semibold text-ink">Reference images</div>
              <div className="rounded-[11px] border border-dashed border-white/[0.14] p-[11px]">
                <div className="mb-2 flex gap-1.5">
                  <RefThumb label="Pikachu" art="g4" />
                  <RefThumb label="Bulbasaur" art="g3" />
                  <RefThumb label="Charizard" art="g6" />
                  <button
                    type="button"
                    className="flex h-[52px] w-[52px] flex-none items-center justify-center rounded-[9px] border border-dashed border-white/[0.16] text-base text-faint"
                  >
                    +
                  </button>
                </div>
                <div className="text-[11px] leading-relaxed text-faint">
                  Drop pictures so it knows exactly which ones you mean — which character, which
                  product, which person.
                </div>
              </div>
            </Step>

            <Step n={5}>
              <div className="mb-1.5 text-[12.5px] font-semibold text-ink">Build it</div>
              <div className="flex items-center gap-2.5 rounded-[11px] border border-gold-director/[0.22] bg-gold-director/[0.06] px-3 py-2.5">
                <button
                  type="button"
                  aria-pressed={automate}
                  onClick={() => setAutomate((v) => !v)}
                  className={cn(
                    "relative h-[19px] w-[34px] flex-none rounded-full transition-colors",
                    automate ? "bg-gold-director/35" : "bg-white/[0.12]"
                  )}
                >
                  <span
                    className={cn(
                      "absolute top-[2px] h-[15px] w-[15px] rounded-full transition-all",
                      automate ? "left-[17px] bg-gold-director" : "left-[2px] bg-faint"
                    )}
                  />
                </button>
                <div className="flex-1">
                  <div className="text-[12.5px] font-semibold text-ink">Automate this</div>
                  <div className="text-[11px] text-faint">Keep making these on a schedule</div>
                </div>
                <button
                  type="button"
                  // Not wired — cloning is an on-ramp for a NEW video, out of
                  // this chunk's scope. Phase 2 wires this.
                  className="inline-flex h-8 items-center gap-1.5 rounded-[9px] bg-gradient-to-b from-[#00E4B8] to-[#00B492] px-3.5 text-[13px] font-semibold text-[#04120E] shadow-[0_2px_14px_rgba(0,212,170,0.28)] transition-[filter] hover:brightness-[1.08]"
                >
                  Build &rarr;
                </button>
              </div>
            </Step>
          </div>
        </div>
      </div>
    </div>
  );
}

function Step({ n, children }: { n: number; children: React.ReactNode }) {
  return (
    <div className="mb-[15px] flex gap-3">
      <div className="mt-px flex h-[22px] w-[22px] flex-none items-center justify-center rounded-full border border-turquoise/30 bg-turquoise/[0.12] text-[11px] font-bold text-turquoise">
        {n}
      </div>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

function RefThumb({ label, art }: { label: string; art: string }) {
  return (
    <div
      className="relative h-[52px] w-[52px] flex-none overflow-hidden rounded-[9px] border border-line-soft"
      style={{ background: ART_GRADIENTS[art] }}
    >
      <span className="absolute inset-x-0 bottom-0 bg-[rgba(5,8,13,0.8)] py-[2px] text-center text-[8px] text-[#D8DEEC]">
        {label}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 5 — "Recent videos"
// ---------------------------------------------------------------------------

// Chunk brief's mockup color mapping: teal done, gold building, gray draft,
// red needs-redraw. Real status strings come from lib/constants.ts
// (PIPELINE_STAGES / COMPLETED_STATUSES) and backend/production_styles-style
// docs (docs/failure-modes.md — qa_rejected = a parked, needs-attention
// render). This bucketing is this chunk's own judgment call, grounded in
// those real values — not literal mockup copy, since the mockup's 5 example
// cards use invented status text ("Building", "Script only", etc) that don't
// map 1:1 to backend status strings.
function statusPillClasses(status: string | null): string {
  if (status === "qa_rejected") return "bg-red/[0.14] text-red";
  if (status === "done" || COMPLETED_STATUSES.has(status ?? "") || status === "rendered") {
    return "bg-turquoise/[0.14] text-turquoise";
  }
  if (!status || status === "idea_logged") return "bg-white/[0.07] text-dim";
  return "bg-gold-director/[0.14] text-gold-director";
}

function RecentVideoCard({ video }: { video: VideoSummary }) {
  const { setSelectedVideoId } = useDirector();
  const thumb = toDisplayImageUrl(video.thumbnail_url);

  return (
    <button
      type="button"
      onClick={() => setSelectedVideoId(video.id)}
      className="flex w-[212px] flex-none flex-col overflow-hidden rounded-2xl border border-line-soft bg-surface text-left transition-transform duration-150 hover:-translate-y-[3px] hover:border-turquoise/40"
    >
      <div
        className="h-[118px] w-full bg-cover bg-center"
        style={{
          background: thumb ? undefined : ART_GRADIENTS.g7,
          backgroundImage: thumb ? `url(${thumb})` : undefined,
        }}
      />
      <div className="p-[11px_12px_13px]">
        <h4 className="mb-2 line-clamp-2 min-h-[35px] text-[13px] font-medium leading-snug text-ink">
          {video.video_title || "Untitled video"}
        </h4>
        <div className="flex items-center justify-between text-[11px] text-faint">
          <span className={cn("rounded-full px-2 py-[3px] text-[10.5px] font-semibold tracking-wide", statusPillClasses(video.status))}>
            {getStageLabel(video.status || "idea_logged")}
          </span>
          <span>{timeAgo(video.updated_at)}</span>
        </div>
      </div>
    </button>
  );
}

function RecentSection() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["videos"],
    queryFn: () => getVideos(),
    staleTime: 30 * 1000,
  });
  const videos = data ?? [];

  return (
    <div className="mb-11">
      <div className="mb-3.5 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight text-ink">Recent videos</h2>
        <span className="text-[12.5px] text-faint">Pick up where you left off</span>
      </div>

      {isLoading && (
        <div className="rounded-card border border-line-soft bg-surface px-4 py-8 text-center text-xs text-dim">
          Loading your recent videos…
        </div>
      )}

      {!isLoading && isError && (
        <div className="rounded-card border border-red/30 bg-red/[0.05] px-4 py-8 text-center text-xs text-dim">
          Couldn&apos;t load your recent videos. Refresh the page to try again.
        </div>
      )}

      {!isLoading && !isError && videos.length === 0 && (
        <div className="rounded-card border border-line-soft bg-surface px-4 py-8 text-center text-xs text-dim">
          No videos yet — start one above and it will show up here.
        </div>
      )}

      {!isLoading && !isError && videos.length > 0 && (
        <div className="flex gap-3.5 overflow-x-auto pb-2">
          {videos.map((video) => (
            <RecentVideoCard key={video.id} video={video} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top-level assembly
// ---------------------------------------------------------------------------

export function DirectorHome() {
  return (
    <div className="h-full w-full overflow-y-auto bg-void">
      <div className="mx-auto max-w-[1180px] px-10 pb-[90px] pt-[34px]">
        <div className="mb-10 flex items-center justify-between">
          <div className="flex items-center gap-2.5 text-[15px] font-semibold tracking-tight text-ink">
            <div className="flex h-[26px] w-[26px] items-center justify-center rounded-lg bg-gradient-to-br from-turquoise to-[#0B7F9E] text-[13px] font-extrabold text-[#04120E]">
              S
            </div>
            StoryEngine
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex h-7 items-center gap-1.5 rounded-full border border-line-soft bg-deep px-2.5 text-xs text-dim">
              <span className="h-1.5 w-1.5 rounded-full bg-turquoise" /> 4 looks ready
            </span>
            <Link
              href="/settings"
              className="inline-flex h-8 items-center rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink transition-colors hover:border-edge hover:bg-[#1B2231]"
            >
              Settings
            </Link>
          </div>
        </div>

        <div className="mb-11">
          <h1 className="mb-2.5 text-[34px] font-bold leading-tight tracking-tight text-ink">
            What are we making today?
          </h1>
          <p className="max-w-[640px] text-[15px] text-dim">
            Start from a channel you&apos;ve already built, or describe something new and let the
            engine compose a style out of the parts it already knows.
          </p>
        </div>

        <ChannelSection />
        <DescribeSection />
        <CloneSection />
        <StyleLibrary />
        <RecentSection />
      </div>
    </div>
  );
}
