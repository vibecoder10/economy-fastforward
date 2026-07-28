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
} from "lucide-react";
import { GlassCard } from "@/components/ui/GlassCard";
import { BoardLightbox } from "@/components/canvas-shared/BoardLightbox";
import {
  getVideoScript,
  getVideoCharacters,
  getEnvironments,
  type VideoCharacter,
  type VideoEnvironment,
} from "@/lib/api";
import { toDisplayImageUrl } from "@/lib/utils";

// Click-to-expand for these co-pilot tiles (storyboards, cast, locations):
// during a real production run these were the ONLY place a creator could see
// what they'd already paid for, and they weren't clickable at all (cast/
// locations) or opened the raw storage URL in a new tab (storyboards, via a
// bare <a href target="_blank">) instead of the in-app viewer every other
// board surface uses. Reuses BoardLightbox as-is (same component
// ScenesWorkspaceTab.tsx's full Scenes tab already uses) rather than
// building a second lightbox — same Esc/←/→/backdrop behavior, same look.
type LightboxState = { items: { url: string; label: string }[]; index: number } | null;

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
function CastTile({ name, refUrl, onOpen }: {
  name: string;
  refUrl: string | null | undefined;
  onOpen: () => void;
}) {
  const [broken, setBroken] = useState(false);
  // Reference images are stored as raw Google Drive links (`drive.google.com/
  // uc?...`) as often as backend-proxied ones — a bare Drive link doesn't
  // render in an <img> tag at all (redirect interstitial, no CORS). Route
  // through the same conversion the rest of the app uses (toDisplayImageUrl:
  // Drive -> media-proxy URL + auth token; anything else passes through +
  // gets the token attached), instead of just tacking a token onto whatever
  // URL shape happened to be stored.
  const displaySrc = toDisplayImageUrl(refUrl);
  const canOpen = !!displaySrc && !broken;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.85 }}
      transition={{ duration: 0.25 }}
      className="flex flex-col items-center gap-1 w-16"
    >
      <button
        type="button"
        onClick={canOpen ? onOpen : undefined}
        disabled={!canOpen}
        title={canOpen ? `View ${name} full size` : name}
        className="w-16 h-16 rounded-xl overflow-hidden flex items-center justify-center transition-all"
        style={{
          background: "var(--bg-deep)",
          border: "1px solid var(--border-subtle)",
          cursor: canOpen ? "pointer" : "default",
        }}
        onMouseEnter={(e) => { if (canOpen) e.currentTarget.style.borderColor = "var(--turquoise)"; }}
        onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border-subtle)"; }}
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
      </button>
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
  const [lightbox, setLightbox] = useState<LightboxState>(null);
  if (characters.length === 0 && environments.length === 0) return null;

  // One shared lightbox for the whole card — characters first, then
  // locations, in the same order the tiles render — so ←/→ can browse the
  // full cast + location set (BoardLightbox handles a single-item list fine,
  // it just hides the nav arrows).
  const lightboxItems = [
    ...characters.map((c) => ({ url: toDisplayImageUrl(c.reference_url) ?? "", label: c.name })),
    ...environments.map((e) => ({ url: toDisplayImageUrl(e.reference_url) ?? "", label: e.name })),
  ].filter((item) => !!item.url);
  const openAt = (name: string) => {
    const index = lightboxItems.findIndex((item) => item.label === name);
    if (index >= 0) setLightbox({ items: lightboxItems, index });
  };

  return (
    <>
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
                <CastTile key={c.id} name={c.name} refUrl={c.reference_url} onOpen={() => openAt(c.name)} />
              ))}
            </AnimatePresence>
          </div>
        )}
        {environments.length > 0 && (
          <div className="flex flex-wrap gap-2.5">
            <AnimatePresence>
              {environments.map((e) => (
                <CastTile key={e.id} name={e.name} refUrl={e.reference_url} onOpen={() => openAt(e.name)} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </GlassCard>
      {/* Rendered as a SIBLING of GlassCard, not nested inside it — a
          framer-motion ancestor (GlassCard/AnimatePresence here both use
          transforms) becomes the containing block for `position: fixed`
          descendants per the CSS spec, which clipped this lightbox to the
          chat column instead of covering the viewport when it was nested
          inside. ScenesWorkspaceTab.tsx's own BoardLightbox usage renders it
          the same way, as a top-level sibling — matched here, not guessed. */}
      {lightbox && (
        <BoardLightbox
          items={lightbox.items}
          index={lightbox.index}
          onNavigate={(i) => setLightbox({ ...lightbox, index: i })}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}

// A single scene's board thumbnail — its own `broken` state so a dead
// asset URL (verified against this real video: scene 1's board 404s straight
// from Supabase storage, an existing data issue, not something introduced
// here) falls back to the same honest ImageOff icon a truly undrawn scene
// gets, instead of the browser's default broken-image glyph.
//
// Was a bare `<a href target="_blank">` — clicking a board downloaded/opened
// the raw storage URL in a new tab instead of showing it. Now opens the same
// in-app BoardLightbox the Scenes tab uses, starting at this scene's own
// boards (onOpen is wired by the parent, which owns the shared lightbox
// state and knows every scene's board list).
function StoryboardTile({ scene, boards, onOpen }: {
  scene: number | null;
  boards: string[];
  onOpen: () => void;
}) {
  const [broken, setBroken] = useState(false);
  const first = toDisplayImageUrl(boards[0]);
  const showImage = first && !broken;
  const canOpen = showImage;
  return (
    <motion.button
      type="button"
      onClick={canOpen ? onOpen : undefined}
      disabled={!canOpen}
      title={canOpen ? `View Scene ${scene} boards full size` : `Scene ${scene} — not drawn yet`}
      initial={{ opacity: 0, scale: 0.9 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      className="relative aspect-video rounded-lg overflow-hidden flex items-center justify-center transition-all"
      style={{
        background: "var(--bg-deep)",
        border: "1px solid var(--border-subtle)",
        cursor: canOpen ? "pointer" : "default",
      }}
      onMouseEnter={(e) => { if (canOpen) e.currentTarget.style.borderColor = "var(--turquoise)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "var(--border-subtle)"; }}
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
    </motion.button>
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
  const [lightbox, setLightbox] = useState<LightboxState>(null);
  if (!anyBoards) return null;
  const drawnCount = rows.filter((s) => s.storyboard_1_url).length;

  return (
    <>
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
              return (
                <StoryboardTile
                  key={s.id}
                  scene={s.scene}
                  boards={boards}
                  onOpen={() => {
                    const items = boards
                      .map((url, i) => ({ url: toDisplayImageUrl(url) ?? "", label: `Scene ${s.scene} · Board ${i + 1}` }))
                      .filter((item) => !!item.url);
                    if (items.length > 0) setLightbox({ items, index: 0 });
                  }}
                />
              );
            })}
          </AnimatePresence>
        </div>
      </GlassCard>
      {/* Sibling of GlassCard, not nested — see the matching comment in
          CastLocationsCard above for why (framer-motion transform ancestors
          break `position: fixed`). */}
      {lightbox && (
        <BoardLightbox
          items={lightbox.items}
          index={lightbox.index}
          onNavigate={(i) => setLightbox({ ...lightbox, index: i })}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  );
}
