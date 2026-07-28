"use client";

// Bug (b), Ryan's testing feedback (2026-07-27): "there was no updating
// inside the dialogue... nothing showed up on this UI like the OpenArt
// does." Results (the script, the cast, the storyboards) used to only live
// on /pipeline/{videoId} — the creator had to leave the chat to see what
// was made. These three cards read the SAME data that page reads (via the
// existing REST endpoints — no backend changes), and render it inline,
// in the chat, so nothing requires navigating away. Each card is self-gating
// (renders null with no data) so it is always safe to mount unconditionally
// next to <ChatPipelineMap/> in both the docked co-pilot and the home
// "created" card.
//
// Modeled on ~/Desktop/Open Art UI/ Screenshot 2026-07-24 at 7.57.57/7.58.15
// AM (tiles fill in one at a time, never one spinner that resolves to
// everything at once) and 7.59.43 AM (the compact "Review Anchors" card:
// a collage + a "Characters × N / Locations × M" count line).

import { useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown,
  ChevronUp,
  FileText,
  Users,
  MapPin,
  LayoutGrid,
  ImageOff,
  Loader2,
  PencilLine,
  Images,
  X,
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import {
  getVideoScript,
  getVideoCharacters,
  getEnvironments,
  type VideoCharacter,
  type VideoEnvironment,
  type ChatCard,
} from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";

function wordCount(text: string | null): number {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

// --- Script result card -----------------------------------------------
export function ScriptResultCard({ videoId }: { videoId: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data: scenes } = useQuery({
    queryKey: ["videoScript", videoId],
    queryFn: () => getVideoScript(videoId),
    enabled: !!videoId,
  });
  const rows = (scenes ?? [])
    .filter((s) => (s.scene_text ?? "").trim().length > 0)
    .sort((a, b) => (a.scene ?? 0) - (b.scene ?? 0));
  if (rows.length === 0) return null;
  const totalWords = rows.reduce((sum, s) => sum + wordCount(s.scene_text), 0);

  return (
    <GlassCard className="flex flex-col gap-2.5 p-3.5" style={{ borderColor: "var(--border-subtle)" }}>
      <button
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center justify-between gap-2 text-left"
        aria-expanded={expanded}
      >
        <span className="flex items-center gap-2 min-w-0">
          <FileText size={15} style={{ color: "var(--turquoise)" }} className="shrink-0" />
          <span className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>
            Script — {rows.length} scene{rows.length === 1 ? "" : "s"}
          </span>
        </span>
        <span className="shrink-0 flex items-center gap-1.5 text-xs" style={{ color: "var(--text-tertiary)" }}>
          ~{totalWords} words
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </span>
      </button>
      {!expanded && (
        <p className="text-xs line-clamp-2" style={{ color: "var(--text-secondary)" }}>
          {rows[0].scene_text}
        </p>
      )}
      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="flex flex-col gap-2.5 max-h-72 overflow-y-auto pr-1 pt-1">
              {rows.map((s) => (
                <div
                  key={s.id}
                  className="rounded-lg px-2.5 py-2"
                  style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
                >
                  <p className="text-[10px] font-bold uppercase tracking-wide mb-1" style={{ color: "var(--turquoise)" }}>
                    Scene {s.scene}
                  </p>
                  <p className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                    {s.scene_text}
                  </p>
                </div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </GlassCard>
  );
}

// --- Characters + locations tiles --------------------------------------
// Each row already exists (name known) before its picture is drawn (status
// "draft" with reference_url null) — so a spinner tile followed by a real
// thumbnail IS the real progressive-fill sequence, not a simulated one.
function CastTile({ name, refUrl }: { name: string; refUrl: string | null | undefined }) {
  const [broken, setBroken] = useState(false);
  // Reference images are stored as raw Google Drive links (`drive.google.com/
  // uc?...`) as often as backend-proxied ones — a bare Drive link doesn't
  // render in an <img> tag at all (redirect interstitial, no CORS). Route
  // through the same conversion the rest of the app uses (toDisplayImageUrl:
  // Drive -> media-proxy URL + auth token; anything else passes through +
  // gets the token attached), instead of just tacking a token onto whatever
  // URL shape happened to be stored.
  const displaySrc = toDisplayImageUrl(refUrl);
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.85 }}
      transition={{ duration: 0.25 }}
      className="flex flex-col items-center gap-1 w-16"
    >
      <div
        className="w-16 h-16 rounded-xl overflow-hidden flex items-center justify-center"
        style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
      >
        {displaySrc && !broken ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={displaySrc}
            alt={name}
            className="w-full h-full object-cover"
            onError={() => setBroken(true)}
          />
        ) : (
          <Loader2 size={16} className="animate-spin" style={{ color: "var(--text-tertiary)" }} />
        )}
      </div>
      <span
        className="text-[9px] text-center leading-tight truncate w-full"
        style={{ color: "var(--text-secondary)" }}
        title={name}
      >
        {name}
      </span>
    </motion.div>
  );
}

export function CastLocationsCard({ videoId }: { videoId: string }) {
  const { data: castData } = useQuery({
    queryKey: ["videoCharacters", videoId],
    queryFn: () => getVideoCharacters(videoId),
    enabled: !!videoId,
  });
  const { data: envData } = useQuery({
    queryKey: ["videoEnvironments", videoId],
    queryFn: () => getEnvironments(videoId),
    enabled: !!videoId,
  });
  const characters: VideoCharacter[] = [...(castData?.characters ?? [])].sort((a, b) => a.sort - b.sort);
  const environments: VideoEnvironment[] = [...(envData?.environments ?? [])].sort((a, b) => a.sort - b.sort);
  if (characters.length === 0 && environments.length === 0) return null;

  return (
    <GlassCard className="flex flex-col gap-3 p-3.5" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex items-center gap-4 flex-wrap">
        {characters.length > 0 && (
          <span className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
            <Users size={13} style={{ color: "var(--turquoise)" }} /> Characters × {characters.length}
          </span>
        )}
        {environments.length > 0 && (
          <span className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
            <MapPin size={13} style={{ color: "var(--turquoise)" }} /> Locations × {environments.length}
          </span>
        )}
      </div>
      {characters.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          <AnimatePresence>
            {characters.map((c) => (
              <CastTile key={c.id} name={c.name} refUrl={c.reference_url} />
            ))}
          </AnimatePresence>
        </div>
      )}
      {environments.length > 0 && (
        <div className="flex flex-wrap gap-2.5">
          <AnimatePresence>
            {environments.map((e) => (
              <CastTile key={e.id} name={e.name} refUrl={e.reference_url} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </GlassCard>
  );
}

// A single scene's board thumbnail — its own `broken` state so a dead
// asset URL (verified against this real video: scene 1's board 404s straight
// from Supabase storage, an existing data issue, not something introduced
// here) falls back to the same honest ImageOff icon a truly undrawn scene
// gets, instead of the browser's default broken-image glyph.
function StoryboardTile({ scene, boards }: { scene: number | null; boards: string[] }) {
  const [broken, setBroken] = useState(false);
  const first = toDisplayImageUrl(boards[0]);
  const showImage = first && !broken;
  return (
    <motion.a
      href={first}
      target={first ? "_blank" : undefined}
      rel={first ? "noopener noreferrer" : undefined}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="relative aspect-video rounded-lg overflow-hidden flex items-center justify-center"
      style={{
        background: "var(--bg-deep)",
        border: "1px solid var(--border-subtle)",
        cursor: first ? "pointer" : "default",
      }}
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={first}
          alt={`Scene ${scene}`}
          className="w-full h-full object-cover"
          onError={() => setBroken(true)}
        />
      ) : (
        <ImageOff size={14} style={{ color: "var(--text-tertiary)" }} />
      )}
      <span
        className="absolute bottom-0 left-0 right-0 px-1 py-0.5 text-[8px]"
        style={{ background: "rgba(0,0,0,0.55)", color: "#fff" }}
      >
        Scene {scene}
        {boards.length ? ` · ${boards.length}` : " · not drawn yet"}
      </span>
    </motion.a>
  );
}

// --- Storyboard grid card ------------------------------------------------
// Scenes without a drawn board yet render as an honest "not drawn" tile
// rather than being hidden — that IS the progressive-fill state (some
// scenes done, others not), read straight from real per-scene columns.
export function StoryboardGridCard({ videoId }: { videoId: string }) {
  const { data: scenes } = useQuery({
    queryKey: ["videoScript", videoId],
    queryFn: () => getVideoScript(videoId),
    enabled: !!videoId,
  });
  const rows = (scenes ?? [])
    .filter((s) => s.scene != null)
    .sort((a, b) => (a.scene ?? 0) - (b.scene ?? 0));
  const anyBoards = rows.some((s) => s.storyboard_1_url);
  if (!anyBoards) return null;
  const drawnCount = rows.filter((s) => s.storyboard_1_url).length;

  return (
    <GlassCard className="flex flex-col gap-3 p-3.5" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
        <LayoutGrid size={14} style={{ color: "var(--turquoise)" }} />
        Storyboards — {drawnCount}/{rows.length} scenes drawn
      </div>
      <div className="grid grid-cols-4 gap-2">
        <AnimatePresence>
          {rows.map((s) => {
            const boards = [
              s.storyboard_1_url,
              s.storyboard_2_url,
              s.storyboard_3_url,
              s.storyboard_4_url,
              s.storyboard_5_url,
            ].filter(Boolean) as string[];
            return <StoryboardTile key={s.id} scene={s.scene} boards={boards} />;
          })}
        </AnimatePresence>
      </div>
    </GlassCard>
  );
}

// --- Approval gate (script / anchors) ------------------------------------
// ONE reusable card kind (id "approval_gate", card.gate_kind picks the
// variant) for the two "pause here so I can see it before you spend more"
// checkpoints the product owner asked for (DIRECTOR-CHAT-PLAN.md Task 5.2):
//   - "script": the script just finished — review it before the cast and
//     locations get designed.
//   - "anchors": the cast AND locations just finished (together, one gate,
//     never two) — review them before storyboards/pictures spend more.
// Modeled on ~/Desktop/Open Art UI/ Screenshot 2026-07-24 at 7.48.10 AM (script
// gate: compact card with a document preview, Edit/Looks good!) and 7.59.43 AM
// + 7.59.55 AM (anchor gate: compact "Characters x N / Locations x M" card,
// View opens a named CHARACTERS/LOCATIONS gallery). Both fetch through the
// SAME endpoints ScriptResultCard/CastLocationsCard above already use — this
// card never invents a new query, per the reuse note in the backend's
// _approval_gate_card docstring (routes/chat.py).
//
// Honest divergence from the reference: OpenArt's character tile is a
// composite turnaround sheet (one hero face + smaller full-body/expression
// shots around it). StoryEngine's data model stores exactly ONE reference
// image per character/environment (video_characters.reference_url) — there
// is no multi-angle sheet to show. The large named hero tile below is the
// closest honest match to what this app actually has, not a simulated sheet.

function costLineFor(card: ChatCard) {
  const breakdown = card.breakdown;
  if (breakdown && breakdown.lines.length > 0) {
    return (
      <div
        className="flex flex-col gap-1 rounded-lg px-2.5 py-2"
        style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
      >
        {breakdown.lines.map((ln) => (
          <div key={ln.model_id} className="flex items-center justify-between text-[11px]">
            <span style={{ color: "var(--text-secondary)" }}>
              {ln.count} × {ln.display_name}
            </span>
            <span style={{ color: "var(--text-primary)" }}>${ln.subtotal.toFixed(2)}</span>
          </div>
        ))}
      </div>
    );
  }
  if (card.cost_text) {
    return (
      <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        Next step: {card.cost_text}
      </p>
    );
  }
  return null;
}

function ScriptGatePreview({ videoId, card }: { videoId: string; card: ChatCard }) {
  const { data: scenes } = useQuery({
    queryKey: ["videoScript", videoId],
    queryFn: () => getVideoScript(videoId),
    enabled: !!videoId,
  });
  const rows = (scenes ?? [])
    .filter((s) => (s.scene_text ?? "").trim().length > 0)
    .sort((a, b) => (a.scene ?? 0) - (b.scene ?? 0));
  const first = rows[0]?.scene_text ?? "";
  const secs = card.duration_seconds;
  const durLabel =
    secs != null ? `approx. ${String(Math.floor(secs / 60)).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}` : null;

  return (
    <div
      className="relative overflow-hidden rounded-lg px-3 py-2.5"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)", maxHeight: 108 }}
    >
      {durLabel && (
        <p className="text-[10px] font-semibold mb-1.5" style={{ color: "var(--turquoise)" }}>
          Estimated duration: {durLabel}
        </p>
      )}
      <p className="text-[10px] font-bold uppercase tracking-wide mb-1" style={{ color: "var(--text-tertiary)" }}>
        Story concept
      </p>
      <p className="text-xs leading-relaxed line-clamp-3" style={{ color: "var(--text-secondary)" }}>
        {first || "…"}
      </p>
      <div
        className="pointer-events-none absolute inset-x-0 bottom-0 h-8"
        style={{ background: "linear-gradient(to bottom, transparent, var(--bg-deep))" }}
      />
    </div>
  );
}

function AnchorGatePreview({ videoId, card }: { videoId: string; card: ChatCard }) {
  const { data: castData } = useQuery({
    queryKey: ["videoCharacters", videoId],
    queryFn: () => getVideoCharacters(videoId),
    enabled: !!videoId,
  });
  const { data: envData } = useQuery({
    queryKey: ["videoEnvironments", videoId],
    queryFn: () => getEnvironments(videoId),
    enabled: !!videoId,
  });
  const characters = castData?.characters ?? [];
  const environments = envData?.environments ?? [];
  const collage = [...characters, ...environments].slice(0, 4);

  return (
    <div className="flex items-center gap-3">
      <div
        className="grid grid-cols-2 grid-rows-2 gap-0.5 w-14 h-14 shrink-0 overflow-hidden rounded-lg"
        style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)" }}
      >
        {collage.length > 0 ? (
          collage.map((item, i) => {
            const src = toDisplayImageUrl(item.reference_url);
            return src ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={item.id ?? i} src={src} alt="" className="w-full h-full object-cover" />
            ) : (
              <div key={item.id ?? i} style={{ background: "var(--bg-surface)" }} />
            );
          })
        ) : (
          <Loader2 size={14} className="col-span-2 row-span-2 m-auto animate-spin" style={{ color: "var(--text-tertiary)" }} />
        )}
      </div>
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
          <Users size={12} style={{ color: "var(--turquoise)" }} /> Characters × {card.character_count ?? characters.length}
        </span>
        <span className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "var(--text-primary)" }}>
          <MapPin size={12} style={{ color: "var(--turquoise)" }} /> Locations × {card.location_count ?? environments.length}
        </span>
      </div>
    </div>
  );
}

function ScriptGateFull({ videoId }: { videoId: string }) {
  const { data: scenes } = useQuery({
    queryKey: ["videoScript", videoId],
    queryFn: () => getVideoScript(videoId),
    enabled: !!videoId,
  });
  const { data: castData } = useQuery({
    queryKey: ["videoCharacters", videoId],
    queryFn: () => getVideoCharacters(videoId),
    enabled: !!videoId,
  });
  const rows = (scenes ?? [])
    .filter((s) => (s.scene_text ?? "").trim().length > 0)
    .sort((a, b) => (a.scene ?? 0) - (b.scene ?? 0));
  const characters = castData?.characters ?? [];

  return (
    <div className="flex flex-col gap-6 sm:flex-row sm:gap-8">
      <nav className="hidden sm:flex flex-col gap-1.5 w-40 shrink-0 text-xs" style={{ color: "var(--text-tertiary)" }}>
        {characters.length > 0 && (
          <a href="#se-gate-characters" className="hover:underline">Characters</a>
        )}
        <span className="mt-1" style={{ color: "var(--text-secondary)" }}>Storyboard</span>
        {rows.map((s) => (
          <a key={s.id} href={`#se-gate-scene-${s.scene}`} className="pl-2 truncate hover:underline">
            {s.scene}. Scene {s.scene}
          </a>
        ))}
      </nav>
      <div className="flex-1 min-w-0 flex flex-col gap-5">
        {characters.length > 0 && (
          <section id="se-gate-characters">
            <h3 className="text-xs font-bold uppercase tracking-wide mb-2" style={{ color: "var(--turquoise)" }}>
              Characters
            </h3>
            <ul className="flex flex-col gap-1.5 text-sm">
              {characters.map((c) => (
                <li key={c.id} style={{ color: "var(--text-secondary)" }}>
                  <strong style={{ color: "var(--text-primary)" }}>{c.name}</strong>
                  {c.description ? ` — ${c.description}` : ""}
                </li>
              ))}
            </ul>
          </section>
        )}
        <section>
          <h3 className="text-xs font-bold uppercase tracking-wide mb-3" style={{ color: "var(--turquoise)" }}>
            Storyboard
          </h3>
          <div className="flex flex-col gap-4">
            {rows.map((s) => (
              <div key={s.id} id={`se-gate-scene-${s.scene}`}>
                <p className="text-[11px] font-bold uppercase tracking-wide mb-1" style={{ color: "var(--text-tertiary)" }}>
                  Scene {s.scene}
                </p>
                <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                  {s.scene_text}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

// Real-data finding (2026-07-28, queried live against video_characters —
// see the branch's own verification notes for the exact query and the two
// example rows): `reference_url` is always exactly ONE file per character,
// but what that ONE file CONTAINS varies by when/how it was generated —
// some are a single portrait pose (e.g. a 2048x2048 square), others are a
// full turnaround SHEET baked into one wide image (5 body poses + 6
// expressions + 4 action poses, landscape ~4:3 — matches
// pipeline_executor.py's own "4-view character reference sheets" comment
// on run_characters). There is no separate row/file per view to pull out
// and re-arrange into OpenArt's hero-plus-thumbnails layout — the
// composite, when it exists, is already baked into the one image. The
// honest, correct rendering for BOTH shapes is: show the whole file,
// uncropped (`object-contain`, not `object-cover`) — a single portrait
// pillarboxes cleanly; a rich sheet shows every pose/expression it has,
// instead of `object-cover` hiding ~80% of it behind a portrait crop (the
// bug this replaces — verified live: a 2048x1536 sheet in a 3:4 portrait
// box showed only the first pose in the top-left corner).
function AnchorHeroTile({ name, refUrl }: { name: string; refUrl: string | null | undefined }) {
  const [broken, setBroken] = useState(false);
  const src = toDisplayImageUrl(refUrl);
  return (
    <div
      className="relative overflow-hidden rounded-xl aspect-[4/3]"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
    >
      {src && !broken ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={name} className="w-full h-full object-contain" onError={() => setBroken(true)} />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <ImageOff size={20} style={{ color: "var(--text-tertiary)" }} />
        </div>
      )}
      <span
        className="absolute bottom-2 left-2 rounded-md px-2 py-1 text-xs font-semibold"
        style={{ background: "rgba(0,0,0,0.62)", color: "#fff" }}
      >
        {name}
      </span>
    </div>
  );
}

function LocationPlate({ name, refUrl }: { name: string; refUrl: string | null | undefined }) {
  const [broken, setBroken] = useState(false);
  const src = toDisplayImageUrl(refUrl);
  return (
    <div
      className="relative overflow-hidden rounded-xl aspect-video"
      style={{ background: "var(--bg-deep)", border: "1px solid var(--border-subtle)" }}
    >
      {src && !broken ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} alt={name} className="w-full h-full object-cover" onError={() => setBroken(true)} />
      ) : (
        <div className="w-full h-full flex items-center justify-center">
          <ImageOff size={20} style={{ color: "var(--text-tertiary)" }} />
        </div>
      )}
      <span
        className="absolute bottom-2 left-2 rounded-md px-2 py-1 text-xs font-semibold"
        style={{ background: "rgba(0,0,0,0.62)", color: "#fff" }}
      >
        {name}
      </span>
    </div>
  );
}

function AnchorGateFull({ videoId }: { videoId: string }) {
  const { data: castData } = useQuery({
    queryKey: ["videoCharacters", videoId],
    queryFn: () => getVideoCharacters(videoId),
    enabled: !!videoId,
  });
  const { data: envData } = useQuery({
    queryKey: ["videoEnvironments", videoId],
    queryFn: () => getEnvironments(videoId),
    enabled: !!videoId,
  });
  const characters: VideoCharacter[] = [...(castData?.characters ?? [])].sort((a, b) => a.sort - b.sort);
  const environments: VideoEnvironment[] = [...(envData?.environments ?? [])].sort((a, b) => a.sort - b.sort);

  return (
    <div className="flex flex-col gap-8">
      {characters.length > 0 && (
        <section>
          <h3 className="text-xs font-bold uppercase tracking-[0.14em] mb-3" style={{ color: "var(--turquoise)" }}>
            CHARACTERS · {characters.length}
          </h3>
          {/* grid-cols-1/2 (not 3/4): a character sheet can be dense — up
              to 15 poses/expressions baked into one image (see
              AnchorHeroTile's comment) — a narrower 4-up grid would shrink
              that detail past legible. Matches the LOCATIONS grid below. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {characters.map((c) => (
              <AnchorHeroTile key={c.id} name={c.name} refUrl={c.reference_url} />
            ))}
          </div>
        </section>
      )}
      {environments.length > 0 && (
        <section>
          <h3 className="text-xs font-bold uppercase tracking-[0.14em] mb-3" style={{ color: "var(--turquoise)" }}>
            LOCATIONS · {environments.length}
          </h3>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {environments.map((e) => (
              <LocationPlate key={e.id} name={e.name} refUrl={e.reference_url} />
            ))}
          </div>
        </section>
      )}
      {characters.length === 0 && environments.length === 0 && (
        <p className="text-sm" style={{ color: "var(--text-tertiary)" }}>
          Nothing drawn yet.
        </p>
      )}
    </div>
  );
}

// The side panel: "opens alongside" per DIRECTOR-CHAT-PLAN.md Task 5.2. Honest
// divergence from the reference: OpenArt's panel is a fixed-width column that
// literally sits beside the chat inside one shared app shell. StoryEngine's
// Director surface already spends its horizontal space on chat + canvas +
// media rail (DirectorSurface.tsx), so there is no free column left for a
// fourth. This renders as a full-height overlay instead — same header (title,
// Save when there's something to save, X), same named/grouped content
// underneath — rather than warping the three-column layout to make room for
// a permanent fourth pane for what is a rare, one-time review moment.
export function ApprovalGatePanel({
  card,
  videoId,
  onClose,
  onApprove,
}: {
  card: ChatCard;
  videoId: string;
  onClose: () => void;
  onApprove: () => void;
}) {
  const isScript = card.gate_kind === "script";
  // Portal to document.body (not a plain fixed div in place): the chat
  // column that hosts this card is itself a CSS containing block
  // (DirectorSurface.tsx's `transform-gpu` on the chat column, added so
  // ChatCore's OWN fixed backdrop resolves against the column instead of the
  // viewport) — a `position: fixed` element without a portal would be
  // clipped to that ~412px column instead of covering the screen. Rendered
  // only client-side (`document` guard) since this file has no SSR path
  // that would hit it regardless (the panel only mounts after a click).
  if (typeof document === "undefined") return null;
  return createPortal(
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="fixed inset-0 z-40 flex justify-end"
      style={{ background: "rgba(0,0,0,0.55)" }}
      onClick={onClose}
      role="dialog"
      aria-modal="true"
      aria-label={isScript ? card.label || "Script" : "Review Anchors"}
    >
      <motion.div
        initial={{ x: 48, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 48, opacity: 0 }}
        transition={{ duration: 0.22, ease: "easeOut" }}
        className="flex h-full w-full max-w-3xl flex-col"
        style={{ background: "var(--bg-void)", borderLeft: "1px solid var(--border-subtle)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between gap-3 px-5 py-4 shrink-0"
          style={{ borderBottom: "1px solid var(--border-subtle)" }}
        >
          <h2 className="text-base font-display font-bold truncate" style={{ color: "var(--text-primary)" }}>
            {isScript ? card.label || "Untitled" : "Review Anchors"}
          </h2>
          <div className="flex items-center gap-2 shrink-0">
            {isScript && (
              <button
                onClick={onApprove}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold transition-all active:scale-[0.98]"
                style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
              >
                Save
              </button>
            )}
            <button
              onClick={onClose}
              aria-label="Close"
              className="p-1.5 rounded-lg transition-colors hover:brightness-125"
              style={{ color: "var(--text-tertiary)" }}
            >
              <X size={18} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-5">
          {isScript ? <ScriptGateFull videoId={videoId} /> : <AnchorGateFull videoId={videoId} />}
        </div>
        {isScript && (
          <div
            className="flex items-center justify-end px-5 py-4 shrink-0"
            style={{ borderTop: "1px solid var(--border-subtle)" }}
          >
            <button
              onClick={onApprove}
              className="px-5 py-2.5 rounded-xl text-sm font-semibold transition-all active:scale-[0.98]"
              style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
            >
              Save and confirm
            </button>
          </div>
        )}
      </motion.div>
    </motion.div>,
    document.body,
  );
}

// The compact chat card — the ONE reusable component both gates render
// through (card.gate_kind picks the variant; the panel above does the same).
// After the creator taps "Looks good!", ChatCore's normal transcript
// mechanics take over: the tap becomes an ordinary user bubble ("Looks
// good!") and this card is simply not the active card on the next render —
// same collapse-to-chip behavior every other action card already has
// (custom_film_approval, confirm_action), not something this card
// special-cases.
export function ApprovalGateCard({
  card,
  videoId,
  onChoose,
}: {
  card: ChatCard;
  videoId: string;
  onChoose: (value: string, label: string) => void;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const isScript = card.gate_kind === "script";
  const Icon = isScript ? PencilLine : Images;
  const title = isScript ? card.label || "Untitled" : "Review Anchors";
  const secondaryLabel = isScript ? "Edit" : "View";

  return (
    <>
      <GlassCard className="flex flex-col gap-3 p-3.5" style={{ borderColor: "rgba(0, 212, 170, 0.30)" }}>
        <div className="flex items-center gap-2">
          <div
            className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg"
            style={{ background: "var(--turquoise-dim)", color: "var(--turquoise)" }}
          >
            <Icon size={14} />
          </div>
          <span className="text-sm font-semibold truncate" style={{ color: "var(--text-primary)" }}>{title}</span>
        </div>

        {isScript ? (
          <ScriptGatePreview videoId={videoId} card={card} />
        ) : (
          <AnchorGatePreview videoId={videoId} card={card} />
        )}

        {costLineFor(card)}

        <div className="flex items-center gap-2">
          <button
            onClick={() => setPanelOpen(true)}
            className="px-4 py-2 rounded-xl text-sm font-medium transition-all active:scale-[0.98]"
            style={{ background: "var(--bg-deep)", color: "var(--text-secondary)", border: "1px solid var(--border-subtle)" }}
          >
            {secondaryLabel}
          </button>
          <button
            onClick={() => onChoose("yes", "Looks good!")}
            className="flex-1 px-4 py-2 rounded-xl text-sm font-semibold transition-all active:scale-[0.98]"
            style={{ background: "var(--turquoise)", color: "var(--bg-void)" }}
          >
            Looks good!
          </button>
        </div>
      </GlassCard>

      <AnimatePresence>
        {panelOpen && (
          <ApprovalGatePanel
            card={card}
            videoId={videoId}
            onClose={() => setPanelOpen(false)}
            onApprove={() => {
              setPanelOpen(false);
              onChoose("yes", "Looks good!");
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}
