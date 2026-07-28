"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowUp, Loader2 } from "lucide-react";
import {
  createVideo,
  getProductionStyles,
  getVideos,
  type ProductionStyleId,
  type VideoSummary,
} from "@/lib/api";
import { cn, timeAgo, toDisplayImageUrl } from "@/lib/utils";
import { COMPLETED_STATUSES, getStageLabel } from "@/lib/constants";
import {
  MODEL_VIDEO_MESSAGE_PREFIX,
  LENGTH_FLOOR_MINUTES,
  parseLengthMinutes,
  parseSpendCapDollars,
} from "@/lib/prompt-parse";
import { useDirector } from "./DirectorContext";
import { StyleLibrary } from "./StyleLibrary";

/**
 * Director home screen. Entry point rebuilt (see PromptEntrySection below) to
 * match the single-prompt "front door" Ryan approved from OpenArt's Director
 * reference (`Open Art UI/Screenshot 2026-07-24 at 7.44.41 AM.png`): one big
 * box under a headline, right at the TOP of the page — Ryan's own correction
 * (in chat, after the first pass of this chunk removed the sections below):
 * "the first thing that you see is a place to type something in and then the
 * rest of the stuff that is currently on what are we making today would fall
 * below it." So every section that lived here before (channel cards, "Or
 * just describe it", "Or clone a video you like", saved styles) stays on the
 * page, in the same order, BELOW the box — none of them got deleted.
 *
 * None of those sections could be wired to a real creation flow within this
 * chunk's scope (each needs its own, separate build). Per the "no dead
 * buttons" rule they instead render their action as a visibly disabled
 * "Coming soon" control — never an active-looking button with no handler.
 * "Recent videos" was already fully wired and is unchanged.
 *
 * "Or clone a video you like" REMOVED (2026-07-27, honesty pass): a QA pass
 * driving the live app flagged it as a full static mockup — a fake YouTube
 * URL, fake "what we found" analysis tags, and fake reference images
 * (Pikachu/Bulbasaur/Charizard) with only a small "coming soon" tag as the
 * tell. That reads as a working demo, not an unbuilt section — exactly the
 * "customer could be misled" failure mode this pass exists to remove, and
 * unlike the other three sections it isn't a single disabled button, it's a
 * whole fabricated result screen. It's also fully redundant: the real,
 * working version of "paste a link to model a video" already lives in the
 * entry box at the top of this page (YouTube modeling, gated behind its own
 * confirm-and-cost card — see PromptEntrySection above). Removing it outright
 * was the safer call over re-labeling, since there's no real content behind
 * it to label honestly and the working equivalent is already on this same
 * screen.
 */

// The mockup's `.art` gradient placeholders (index.html `.g1`-`.g7`, ~L77-83).
const ART_GRADIENTS: Record<string, string> = {
  g1: "linear-gradient(150deg,#1B2E4A,#3E5C86 55%,#8FA9C9)",
  g2: "linear-gradient(150deg,#2A1B3D,#5B3A6E 55%,#C08BB0)",
  g3: "linear-gradient(150deg,#0E3A34,#1C7A66 55%,#7FD8C0)",
  g4: "linear-gradient(150deg,#3D2413,#8A4A22 55%,#E0A167)",
  g5: "linear-gradient(150deg,#101826,#243A54 55%,#5E7FA6)",
  g6: "linear-gradient(150deg,#2B0F19,#7A2338 55%,#D9738C)",
  g7: "linear-gradient(150deg,#151A24,#2E3646 60%,#59617A)",
};

// A visibly-disabled stand-in for an action that isn't wired to anything yet.
// Real `disabled` (not just muted color) so it's genuinely unclickable and
// announces as disabled to assistive tech — never an active-looking dead end.
function ComingSoonButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      disabled
      title="Not available yet"
      className="mt-auto inline-flex w-fit items-center gap-1.5 rounded-[9px] border border-line-soft bg-white/[0.02] px-3 py-1.5 text-[11.5px] font-medium text-faint disabled:cursor-not-allowed"
    >
      {label} <span className="text-[10px] uppercase tracking-wide">&middot; coming soon</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Section 1 — the single-prompt entry box
// ---------------------------------------------------------------------------

const QUICK_STARTS = [
  "A boy in San Francisco is sad in his room, until he presses a button and gets pulled into an adventure in Bali",
  "A 90-second explainer on why the sky is blue, made for curious kids",
  "A dry, funny documentary about why nobody ever fixes potholes",
];

// The one box takes THREE kinds of input (Ryan's correction): a plain
// description, a YouTube link ("model this"), or an Instagram/TikTok link.
// Only YouTube is actually wired end to end — `createVideo({ reference_url })`
// -> `_run_modeling` (backend/routes/videos.py:535-545, `_parse_youtube_id`)
// rejects anything that isn't a youtube.com/youtu.be URL with a 400. There is
// no Instagram/TikTok modeling path anywhere in the backend today (checked:
// no route, no parser) — so that branch must say so, not pretend to work.
const YOUTUBE_URL_RE = /\bhttps?:\/\/(www\.)?(youtube\.com\/(watch\?[^\s]*v=|shorts\/)|youtu\.be\/)[\w-]+[^\s]*/i;
const UNSUPPORTED_MODEL_URL_RE = /\bhttps?:\/\/(www\.)?(instagram\.com|tiktok\.com)\/[^\s]+/i;

function detectModelUrl(text: string): { kind: "youtube" | "unsupported"; url: string } | null {
  const yt = text.match(YOUTUBE_URL_RE);
  if (yt) return { kind: "youtube", url: yt[0] };
  const other = text.match(UNSUPPORTED_MODEL_URL_RE);
  if (other) return { kind: "unsupported", url: other[0] };
  return null;
}

// Ryan's own example of this box: "make me a five minute video about a boy
// who found a dragon" — the length is typed IN the sentence, in words, not
// digits. Traced live (2026-07-27): the seeded message is sent through the
// existing co-pilot classifier (backend/routes/chat.py `_handle_copilot`),
// not the producer-pitch flow that owns the length slider — and that
// classifier's "build" verb (the one "make me a video about X" naturally
// matches — its own prompt lists "make the video"/"make it" as build
// triggers) NEVER reads the length it extracts; only "script" applies it,
// and only after the creator taps the confirm card (actions.py
// apply_followup_edit:240-256). So a typed length was being silently
// dropped in the realistic case — the row would just sit at whatever
// createVideo() set. Fixed at the actual point of creation instead: parse
// it here, clamp to the engine's real 1-30 minute range, and pass it
// straight to createVideo(). Same story for a typed spend cap ("cap the
// spend at $1") — see @/lib/prompt-parse for both parsers (shared with
// ChatCore, which discloses what was found/not-found in the opening turn).

function PromptEntrySection() {
  const { setSelectedVideoId, setPendingInitialMessage, setPendingInitialIntent } = useDirector();
  const [prompt, setPrompt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set only for a detected YouTube link, held here UNSENT until the creator
  // explicitly taps "Model it" — this IS this box's quote-and-confirm gate
  // (createVideo's own reference_url path has none: backend/routes/videos.py
  // fires the paid `_run_modeling` background task the instant the row is
  // inserted, with no server-side confirm step of its own).
  const [modelConfirm, setModelConfirm] = useState<{ url: string; twist: string } | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function send() {
    const sentence = prompt.trim();
    if (!sentence || submitting) return;
    setError(null);

    const detected = detectModelUrl(sentence);
    if (detected?.kind === "unsupported") {
      setError(
        "Instagram and TikTok modeling isn't wired up yet — paste a YouTube link to model a video, or just describe what you want in words."
      );
      return;
    }
    if (detected?.kind === "youtube") {
      // Hold for explicit confirmation — never auto-fires the paid call.
      setModelConfirm({ url: detected.url, twist: sentence.replace(detected.url, "").trim() });
      return;
    }

    setSubmitting(true);
    try {
      // Free — a plain DB insert plus fail-soft housekeeping (Drive workspace).
      // video_length_minutes: a length typed IN the sentence ("a five minute
      // video…") sticks right here, at creation — see parseLengthMinutes's
      // comment for why this can't be left to the chat that opens next. No
      // length mentioned -> the same 1-minute floor default as before, so
      // this still never blocks on a form. Same story for max_spend: "cap
      // the spend at $1" is parsed here too — found live 2026-07-27 landing
      // as a silently-ignored NULL cap otherwise (the classifier picks ONE
      // verb per turn and "build" never reads a co-occurring budget phrase).
      //
      // apply_channel_identity: false — the OTHER live bug from the same
      // report: this box's whole point is "describe something NEW", so it
      // must not silently come out looking/sounding like an unrelated
      // existing channel (a video about "a dystopian world... bugs" came
      // back as PocoAPoco's locked Ryan/Vanessa two-hander because
      // create_video's house-format/cast/visual-format defaulting ran
      // unconditionally). Channel cards (once wired) SHOULD still inherit —
      // this flag only turns it off for THIS box. ChatCore's initialMessage
      // effect discloses what got skipped/applied in the opening chat turn.
      const spendCap = parseSpendCapDollars(sentence);
      const video = await createVideo({
        title: sentence.length > 300 ? `${sentence.slice(0, 297)}…` : sentence,
        writer_guidance: sentence,
        video_length_minutes: parseLengthMinutes(sentence) ?? LENGTH_FLOOR_MINUTES,
        apply_channel_identity: false,
        ...(spendCap != null ? { max_spend: spendCap } : {}),
      });
      // Seed the sentence as the opening chat turn, then hand off to the room —
      // DirectorSurface mounts ChatCore for this video id and sends it (see
      // ChatCore's initialMessage prop). This box's whole reason to exist is
      // "build me a new video" — that is declared here, not left for the chat
      // classifier to guess from the sentence's wording (see the root-cause
      // note on `explicit_verb` in backend/routes/chat.py `_handle_copilot`).
      setPendingInitialMessage(sentence);
      setPendingInitialIntent("build");
      setSelectedVideoId(video.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start that video — try again.");
      setSubmitting(false);
    }
  }

  async function confirmModel() {
    if (!modelConfirm || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      // Paid path — `reference_url` set means backend/routes/videos.py kicks
      // off `_run_modeling` (a real Claude call, ~$0.01-0.05) the moment this
      // resolves. Only reachable by tapping "Model it" below, never by Enter
      // in the textarea. Deliberately does NOT set apply_channel_identity —
      // modeling a reference video is its own explicit choice, so keeping
      // the channel's locked identity default (inherit) is correct here,
      // unlike the plain-description box above.
      const video = await createVideo({
        title: modelConfirm.twist,
        reference_url: modelConfirm.url,
        video_length_minutes: parseLengthMinutes(modelConfirm.twist) ?? LENGTH_FLOOR_MINUTES,
      });
      setPendingInitialMessage(
        modelConfirm.twist
          ? `${MODEL_VIDEO_MESSAGE_PREFIX} ${modelConfirm.url} — ${modelConfirm.twist}`
          : `${MODEL_VIDEO_MESSAGE_PREFIX} ${modelConfirm.url}`
      );
      setSelectedVideoId(video.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start that one — try again.");
      setSubmitting(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  }

  function useQuickStart(text: string) {
    setPrompt(text);
    setModelConfirm(null);
    setError(null);
    textareaRef.current?.focus();
  }

  return (
    <div className="mb-11">
      <div className="mx-auto max-w-[720px] rounded-card border border-edge bg-gradient-to-b from-turquoise/5 to-transparent bg-surface p-[18px]">
        <label htmlFor="director-entry-prompt" className="sr-only">
          Describe the video you want, or paste a YouTube link to model
        </label>
        <textarea
          id="director-entry-prompt"
          ref={textareaRef}
          value={prompt}
          onChange={(e) => {
            setPrompt(e.target.value);
            if (modelConfirm) setModelConfirm(null);
          }}
          onKeyDown={handleKeyDown}
          disabled={submitting}
          rows={3}
          autoFocus
          spellCheck={false}
          placeholder={`Describe the video you want, or paste a YouTube link to model. e.g. “${QUICK_STARTS[0]}”`}
          className="w-full resize-none bg-transparent text-[15.5px] leading-relaxed text-ink outline-none placeholder:text-faint disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <span className="text-[12px] text-faint">
            Enter to send &middot; Shift+Enter for a new line
          </span>
          <button
            type="button"
            onClick={send}
            disabled={submitting || !prompt.trim()}
            aria-label="Send"
            className="inline-flex h-9 w-9 flex-none items-center justify-center rounded-full bg-gradient-to-b from-[#00E4B8] to-[#00B492] text-[#04120E] shadow-[0_2px_14px_rgba(0,212,170,0.28)] transition-[filter] hover:brightness-[1.08] disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            {submitting ? <Loader2 size={16} className="animate-spin" /> : <ArrowUp size={16} />}
          </button>
        </div>
      </div>

      {modelConfirm && (
        <div className="mx-auto mt-3 max-w-[720px] rounded-card border border-gold-director/25 bg-gold-director/[0.06] p-4">
          <p className="mb-1 text-[13.5px] font-semibold text-ink">Model a new video from this link?</p>
          <p className="mb-3 text-[12.5px] leading-relaxed text-dim">
            I&apos;ll analyze <span className="font-medium text-turquoise">{modelConfirm.url}</span>{" "}
            and pitch a new video modeled on it
            {modelConfirm.twist ? <> — your twist: &ldquo;{modelConfirm.twist}&rdquo;</> : null}.
            This step makes a real AI call (~$0.01&ndash;0.05) to read the video, unlike a plain
            description, which is free.
          </p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={confirmModel}
              disabled={submitting}
              className="inline-flex h-8 items-center gap-1.5 rounded-[9px] bg-gold-director px-3.5 text-[12.5px] font-semibold text-[#1A1200] transition-[filter] hover:brightness-[1.08] disabled:opacity-50"
            >
              {submitting && <Loader2 size={13} className="animate-spin" />} Model it
            </button>
            <button
              type="button"
              onClick={() => setModelConfirm(null)}
              disabled={submitting}
              className="inline-flex h-8 items-center rounded-[9px] border border-line-soft bg-deep px-3.5 text-[12.5px] font-medium text-dim transition-colors hover:text-ink disabled:opacity-50"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="mx-auto mt-2.5 max-w-[720px] text-center text-[12.5px] text-red">{error}</p>
      )}

      <div className="mx-auto mt-3.5 flex max-w-[720px] flex-wrap justify-center gap-2">
        {QUICK_STARTS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => useQuickStart(q)}
            disabled={submitting}
            className="max-w-full truncate rounded-full border border-line-soft bg-deep px-3.5 py-1.5 text-[12.5px] text-dim transition-colors hover:border-turquoise/40 hover:text-ink disabled:opacity-50"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 2 — "Start from a channel you've built"
// ---------------------------------------------------------------------------

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
    <div id="channel-looks" className="mb-11 scroll-mt-6">
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
          <div
            key={card.id}
            className="flex flex-col overflow-hidden rounded-card border border-edge bg-surface text-left opacity-80"
          >
            <div
              className="h-[84px] w-full"
              style={{ background: ART_GRADIENTS[card.art] }}
            />
            <div className="flex flex-1 flex-col p-[13px_15px_15px]">
              <h3 className="mb-1 text-[14.5px] font-semibold text-ink">{card.label}</h3>
              <p className="mb-2.5 text-[12.5px] leading-relaxed text-dim">{card.description}</p>
              <ComingSoonButton label="Open" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section 3 — "Or just describe it" (presentational only this phase)
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
          <ComingSoonButton label="Compose style" />
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
// Section 6 — "Recent videos"
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
            {/* Was a plain <span> styled like the rest of this row's real
                controls (pill shape, border) with no onClick — looked
                clickable, wasn't. Wired to what it's actually describing
                (jump to the channel-look cards below) instead of just
                turning off the affordance, since scrolling to real content
                is something this can genuinely do, not a fake action. Count
                reads off CHANNEL_CARDS.length so it can't drift from the
                cards it's describing. */}
            <button
              type="button"
              onClick={() =>
                document.getElementById("channel-looks")?.scrollIntoView({ behavior: "smooth", block: "start" })
              }
              title="Jump to your ready-to-use channel looks"
              className="inline-flex h-7 items-center gap-1.5 rounded-full border border-line-soft bg-deep px-2.5 text-xs text-dim transition-colors hover:border-turquoise/40 hover:text-ink"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-turquoise" /> {CHANNEL_CARDS.length} looks ready
            </button>
            <Link
              href="/settings"
              className="inline-flex h-8 items-center rounded-[9px] border border-line-soft bg-raise px-3.5 text-[13px] font-medium text-ink transition-colors hover:border-edge hover:bg-[#1B2231]"
            >
              Settings
            </Link>
          </div>
        </div>

        <div className="mb-9 text-center">
          <h1 className="mb-2.5 text-[34px] font-bold leading-tight tracking-tight text-ink">
            What are we making today?
          </h1>
          <p className="mx-auto max-w-[560px] text-[15px] text-dim">
            Describe the video, one sentence is plenty — StoryEngine will ask what it needs, then
            show you the cost before it spends anything.
          </p>
        </div>

        <PromptEntrySection />
        <ChannelSection />
        <DescribeSection />
        <StyleLibrary />
        <RecentSection />
      </div>
    </div>
  );
}
