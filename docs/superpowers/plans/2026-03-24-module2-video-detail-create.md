# Module 2: Video Detail View + Create New Video

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 6-tab video detail page (`/pipeline/[videoId]`) and the Create New Video form (`/create`), replacing the current detail panel overlay with a dedicated full-page view.

**Architecture:** Create a new dynamic route at `/pipeline/[videoId]/page.tsx` with a tab container. Each tab is a separate component in `components/video-detail/`. The pipeline list page links to this route instead of opening the overlay panel. The Create page is a simple form that calls `createIdea()`. All data comes from existing API endpoints (`getVideo`, `getVideoAssets`, `getVideoScript`).

**Tech Stack:** Next.js 16 (App Router), React 19, Tailwind CSS 4.2, Framer Motion, React Query, Lucide icons

**Design Spec:** `docs/superpowers/specs/2026-03-23-storyengine-ui-ux-addendum.md` — Screens 3 and 4

**Scope:** This is a **read-only V1** — all tabs display data but don't yet support editing, generation, or regeneration. Interactive features (script editing, image generation triggers, thumbnail variants, storyboard panel review) will be added in Module 3. The existing `/pipeline/[videoId]/storyboards/page.tsx` route is kept alongside the new Storyboard tab — both will coexist until Module 3 consolidates them.

---

## Pre-Task: Update API Types

Before implementing tabs, add the missing fields to the `VideoDetail` and `ScriptScene` interfaces in `api.ts`. These fields exist in Supabase (added in Module 0) but aren't in the TypeScript types yet.

**Add to `VideoDetail` interface:**
```typescript
// Performance snapshots
avg_view_duration_seconds: number | null;
views_24h: number | null;
views_48h: number | null;
views_7d: number | null;
views_30d: number | null;
ctr_12h: number | null;
ctr_24h: number | null;
ctr_48h: number | null;
retention_48h: number | null;
// Post-mortem
post_mortem_48h: string | null;
post_mortem_7d: string | null;
// Cost
total_cost: number | null;
```

**Add to `ScriptScene` interface:**
```typescript
storyboard_1_url: string | null;
storyboard_2_url: string | null;
storyboard_3_url: string | null;
storyboard_prompts: string | null;
storyboard_beat_count: number | null;
storyboard_status: string | null;
```

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `src/app/pipeline/[videoId]/page.tsx` | Video detail page — header + 6-tab container |
| `src/components/video-detail/info-tab.tsx` | Info tab: Story DNA, Story Bible, Research, Actions |
| `src/components/video-detail/script-tab.tsx` | Script tab: scene-by-scene viewer with navigation |
| `src/components/video-detail/visuals-tab.tsx` | Visuals tab: image prompts + generated images per scene |
| `src/components/video-detail/storyboard-tab.tsx` | Storyboard tab: 3x3 grids with panel review |
| `src/components/video-detail/thumbnail-tab.tsx` | Thumbnail tab: current + variants + prompt |
| `src/components/video-detail/performance-tab.tsx` | Performance tab: metrics, timeline, cost breakdown |
| `src/app/create/page.tsx` | Create New Video form |

### Modified Files
| File | Changes |
|------|---------|
| `src/lib/api.ts` | Add missing fields to VideoDetail and ScriptScene interfaces |
| `src/app/pipeline/page.tsx` | Video cards link to `/pipeline/[videoId]` instead of opening detail panel |
| `src/components/video-card.tsx` | Wrap in `<Link>` to video detail page |

---

## Task 1: Video Detail Page Shell (Tab Container)

**Files:**
- Create: `storyengine/frontend/src/app/pipeline/[videoId]/page.tsx`

- [ ] **Step 1: Create the video detail page with tab navigation**

This page fetches the video data and renders a tab container. Mobile: swipeable tabs. Desktop: horizontal tab bar.

```tsx
"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { getVideo } from "@/lib/api";
import { ProgressDots } from "@/components/progress-dots";
import { getStageLabel } from "@/lib/constants";
import { ArrowLeft } from "lucide-react";
import { InfoTab } from "@/components/video-detail/info-tab";
import { ScriptTab } from "@/components/video-detail/script-tab";
import { VisualsTab } from "@/components/video-detail/visuals-tab";
import { StoryboardTab } from "@/components/video-detail/storyboard-tab";
import { ThumbnailTab } from "@/components/video-detail/thumbnail-tab";
import { PerformanceTab } from "@/components/video-detail/performance-tab";

const TABS = [
  { id: "info", label: "Info" },
  { id: "script", label: "Script" },
  { id: "visuals", label: "Visuals" },
  { id: "storyboard", label: "Board" },
  { id: "thumbnail", label: "Thumb" },
  { id: "performance", label: "Perf" },
];

export default function VideoDetailPage({
  params,
}: {
  params: Promise<{ videoId: string }>;
}) {
  const { videoId } = use(params);
  const [activeTab, setActiveTab] = useState("info");

  const { data: video, isLoading } = useQuery({
    queryKey: ["video", videoId],
    queryFn: () => getVideo(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="h-8 w-48 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="h-4 w-32 rounded animate-pulse" style={{ background: "var(--border)" }} />
        <div className="h-64 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
      </div>
    );
  }

  if (!video) {
    return (
      <div className="text-center py-20" style={{ color: "var(--text-muted)" }}>
        Video not found
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-1 text-sm mb-4 transition-colors hover:opacity-80"
          style={{ color: "var(--text-muted)" }}
        >
          <ArrowLeft size={16} />
          Back
        </Link>

        <h1 className="text-xl font-bold" style={{ color: "var(--text-primary)" }}>
          {video.video_title}
        </h1>
        <div className="flex items-center gap-3 mt-2">
          <span
            className="text-sm px-2 py-0.5 rounded"
            style={{
              color: "var(--amber)",
              background: "rgba(212, 168, 68, 0.1)",
            }}
          >
            {getStageLabel(video.status)}
          </span>
        </div>
        <div className="mt-3">
          <ProgressDots status={video.status} size="md" />
        </div>
      </div>

      {/* Tab bar */}
      <div
        className="flex gap-1 p-1 rounded-xl overflow-x-auto scrollbar-hide"
        style={{ background: "var(--bg-card)" }}
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className="px-4 py-2 text-sm font-medium rounded-lg whitespace-nowrap transition-colors"
            style={{
              background: activeTab === tab.id ? "var(--bg-card-hover)" : "transparent",
              color: activeTab === tab.id ? "var(--text-primary)" : "var(--text-muted)",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "info" && <InfoTab video={video} />}
        {activeTab === "script" && <ScriptTab videoId={videoId} video={video} />}
        {activeTab === "visuals" && <VisualsTab videoId={videoId} />}
        {activeTab === "storyboard" && <StoryboardTab videoId={videoId} />}
        {activeTab === "thumbnail" && <ThumbnailTab video={video} />}
        {activeTab === "performance" && <PerformanceTab video={video} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the route exists**

```bash
cd storyengine/frontend && npx tsc --noEmit 2>&1 | head -20
```

This will fail because tab components don't exist yet. Expected — we'll create them next.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/pipeline/\[videoId\]/page.tsx
git commit -m "feat(storyengine): Add video detail page shell with 6-tab navigation"
```

---

## Task 2: Info Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/info-tab.tsx`

- [ ] **Step 1: Create the Info tab component**

Shows: Story DNA (angle, thesis, past/present/future, hook), Story Bible (characters, locations, visual arc), Research (collapsible), and Action buttons (advance, reject, force stage, delete).

```tsx
"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { advanceVideo, rejectVideo } from "@/lib/api";
import { ChevronDown, ChevronRight } from "lucide-react";

interface InfoTabProps {
  video: any;
}

export function InfoTab({ video }: InfoTabProps) {
  const [researchOpen, setResearchOpen] = useState(false);
  const queryClient = useQueryClient();

  const advanceMutation = useMutation({
    mutationFn: () => advanceVideo(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  const rejectMutation = useMutation({
    mutationFn: () => rejectVideo(video.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["video", video.id] }),
  });

  // Parse Story Bible JSON
  let storyBible: any = null;
  if (video.story_bible) {
    try {
      storyBible = typeof video.story_bible === "string"
        ? JSON.parse(video.story_bible)
        : video.story_bible;
    } catch { /* ignore parse errors */ }
  }

  return (
    <div className="space-y-6">
      {/* Story DNA */}
      <Section title="Story DNA">
        <Field label="Framework" value={video.framework_angle} />
        <Field label="Thesis" value={video.thesis} />
        <Field label="Opening Hook" value={video.hook_script} />
        <Field label="Past Context" value={video.past_context} />
        <Field label="Present Parallel" value={video.present_parallel} />
        <Field label="Future Prediction" value={video.future_prediction} />
        {video.writer_guidance && (
          <Field label="Writer Guidance" value={video.writer_guidance} />
        )}
      </Section>

      {/* Story Bible */}
      {storyBible && (
        <Section title="Story Bible">
          {storyBible.characters?.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Characters
              </h4>
              <div className="space-y-2">
                {storyBible.characters.map((c: any, i: number) => (
                  <div key={i} className="flex items-start gap-3">
                    <div
                      className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold shrink-0"
                      style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
                    >
                      {(c.name || "?")[0]}
                    </div>
                    <div>
                      <p className="text-sm font-medium" style={{ color: "var(--text-primary)" }}>
                        {c.name} <span style={{ color: "var(--text-muted)" }}>({c.role || c.archetype || "Character"})</span>
                      </p>
                      {c.visual && (
                        <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                          {c.visual}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {storyBible.locations?.length > 0 && (
            <div className="mb-4">
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Locations
              </h4>
              <ul className="space-y-1">
                {storyBible.locations.map((loc: any, i: number) => (
                  <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    {typeof loc === "string" ? loc : loc.name || loc.location}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {storyBible.visual_arc?.length > 0 && (
            <div>
              <h4 className="text-xs uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
                Visual Arc
              </h4>
              <ul className="space-y-1">
                {storyBible.visual_arc.map((arc: any, i: number) => (
                  <li key={i} className="text-sm" style={{ color: "var(--text-secondary)" }}>
                    Act {i + 1}: {typeof arc === "string" ? arc : arc.description || JSON.stringify(arc)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Section>
      )}

      {/* Research (collapsible) */}
      {video.research_payload && (
        <div
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <button
            onClick={() => setResearchOpen(!researchOpen)}
            className="flex items-center justify-between w-full p-4 text-left"
          >
            <span className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Research Payload
            </span>
            {researchOpen ? (
              <ChevronDown size={16} style={{ color: "var(--text-muted)" }} />
            ) : (
              <ChevronRight size={16} style={{ color: "var(--text-muted)" }} />
            )}
          </button>
          {researchOpen && (
            <div className="px-4 pb-4">
              <pre
                className="text-xs overflow-x-auto whitespace-pre-wrap"
                style={{ color: "var(--text-secondary)" }}
              >
                {typeof video.research_payload === "string"
                  ? video.research_payload
                  : JSON.stringify(video.research_payload, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Actions */}
      <Section title="Actions">
        <div className="flex flex-wrap gap-3">
          <button
            onClick={() => advanceMutation.mutate()}
            disabled={advanceMutation.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {advanceMutation.isPending ? "Advancing..." : "Approve & Advance →"}
          </button>
          <button
            onClick={() => rejectMutation.mutate()}
            disabled={rejectMutation.isPending}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
            style={{
              background: "transparent",
              color: "var(--red)",
              border: "1px solid var(--red)",
            }}
          >
            {rejectMutation.isPending ? "Rejecting..." : "Reject & Regenerate"}
          </button>
        </div>
        {(advanceMutation.isError || rejectMutation.isError) && (
          <p className="text-sm mt-2" style={{ color: "var(--red)" }}>
            Action failed. Please try again.
          </p>
        )}
      </Section>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <h3
        className="text-sm font-semibold uppercase tracking-wider mb-3"
        style={{ color: "var(--text-muted)" }}
      >
        {title}
      </h3>
      {children}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null;
  return (
    <div className="mb-3 last:mb-0">
      <dt className="text-xs font-medium mb-0.5" style={{ color: "var(--text-muted)" }}>
        {label}
      </dt>
      <dd className="text-sm" style={{ color: "var(--text-primary)" }}>
        {value}
      </dd>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/info-tab.tsx
git commit -m "feat(storyengine): Add Info tab — Story DNA, Story Bible, Research, Actions"
```

---

## Task 3: Script Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/script-tab.tsx`

- [ ] **Step 1: Create the Script tab component**

Shows scenes one at a time (mobile) with prev/next navigation. Displays scene text, word count, and visual direction. Desktop shows scrollable list of all scenes.

```tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getVideoScript } from "@/lib/api";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface ScriptTabProps {
  videoId: string;
  video: any;
}

export function ScriptTab({ videoId, video }: ScriptTabProps) {
  const [currentScene, setCurrentScene] = useState(0);

  const { data: scenes, isLoading } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-32 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  const sortedScenes = (scenes || [])
    .filter((s: any) => s.scene_text)
    .sort((a: any, b: any) => (a.scene || 0) - (b.scene || 0));

  if (sortedScenes.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No script scenes yet. Script will appear after the scripting stage.
      </div>
    );
  }

  const totalWords = sortedScenes.reduce((sum: number, s: any) => {
    return sum + (s.scene_text?.split(/\s+/).length || 0);
  }, 0);

  const scene = sortedScenes[currentScene];
  const sceneWords = scene?.scene_text?.split(/\s+/).length || 0;

  return (
    <div className="space-y-4">
      {/* Script stats */}
      <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-muted)" }}>
        <span>{totalWords.toLocaleString()} words</span>
        <span>~{Math.round(totalWords / 150)} min</span>
        <span>{sortedScenes.length} scenes</span>
      </div>

      {/* Mobile: single scene view */}
      <div className="md:hidden">
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
              Scene {scene?.scene || currentScene + 1} of {sortedScenes.length}
            </span>
            <span className="text-xs" style={{ color: "var(--text-muted)" }}>
              {sceneWords}w
            </span>
          </div>
          <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
            {scene?.scene_text}
          </p>
          {scene?.sources && currentScene === 0 && (
            <div className="mt-4 pt-3" style={{ borderTop: "1px solid var(--border)" }}>
              <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                Sources: {scene.sources}
              </p>
            </div>
          )}
        </div>

        {/* Navigation */}
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setCurrentScene(Math.max(0, currentScene - 1))}
            disabled={currentScene === 0}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={16} /> Prev
          </button>
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            {currentScene + 1} / {sortedScenes.length}
          </span>
          <button
            onClick={() => setCurrentScene(Math.min(sortedScenes.length - 1, currentScene + 1))}
            disabled={currentScene === sortedScenes.length - 1}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            Next <ChevronRight size={16} />
          </button>
        </div>
      </div>

      {/* Desktop: scrollable list */}
      <div className="hidden md:block space-y-3">
        {sortedScenes.map((s: any, i: number) => (
          <div
            key={s.id}
            className="rounded-xl p-4"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                Scene {s.scene || i + 1}
              </span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                {s.scene_text?.split(/\s+/).length || 0}w
              </span>
            </div>
            <p className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: "var(--text-primary)" }}>
              {s.scene_text}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/script-tab.tsx
git commit -m "feat(storyengine): Add Script tab — scene-by-scene viewer with navigation"
```

---

## Task 4: Visuals Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/visuals-tab.tsx`

- [ ] **Step 1: Create the Visuals tab component**

Shows image prompts and generated images grouped by scene. Each segment shows the script text, prompt, and image (or generate placeholder).

```tsx
"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getVideoAssets } from "@/lib/api";
import { ChevronLeft, ChevronRight, Star, Download } from "lucide-react";
import { formatCost } from "@/lib/utils";

interface VisualsTabProps {
  videoId: string;
}

export function VisualsTab({ videoId }: VisualsTabProps) {
  const [currentScene, setCurrentScene] = useState(1);

  const { data: assets, isLoading } = useQuery({
    queryKey: ["video-assets", videoId],
    queryFn: () => getVideoAssets(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-48 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  if (!assets || assets.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No images yet. Images will appear after the image prompts stage.
      </div>
    );
  }

  // Group assets by scene
  const scenes = new Map<number, any[]>();
  assets.forEach((a: any) => {
    const scene = a.scene || 1;
    if (!scenes.has(scene)) scenes.set(scene, []);
    scenes.get(scene)!.push(a);
  });

  const sceneNumbers = Array.from(scenes.keys()).sort((a, b) => a - b);
  const sceneAssets = scenes.get(currentScene) || [];
  const totalImages = assets.length;
  const generatedImages = assets.filter((a: any) => a.image_url).length;

  // Sort by image_index within scene
  sceneAssets.sort((a: any, b: any) => (a.image_index || 0) - (b.image_index || 0));

  return (
    <div className="space-y-4">
      {/* Stats */}
      <div className="flex items-center gap-4 text-sm" style={{ color: "var(--text-muted)" }}>
        <span>{generatedImages}/{totalImages} images generated</span>
        <span>{sceneNumbers.length} scenes</span>
        <span>~{formatCost(totalImages * 0.045)} estimated</span>
      </div>

      {/* Scene segments */}
      <div className="space-y-3">
        {sceneAssets.map((asset: any) => (
          <div
            key={asset.id}
            className="rounded-xl overflow-hidden"
            style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
          >
            {/* Script text */}
            {asset.sentence_text && (
              <div className="p-4 pb-2">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
                    Segment {asset.image_index || "?"}
                  </span>
                  {asset.shot_type && (
                    <span
                      className="text-xs px-1.5 py-0.5 rounded"
                      style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}
                    >
                      {asset.shot_type}
                    </span>
                  )}
                  {asset.hero_shot && (
                    <Star size={12} style={{ color: "var(--amber)" }} fill="var(--amber)" />
                  )}
                </div>
                <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                  {asset.sentence_text}
                </p>
              </div>
            )}

            {/* Prompt */}
            {asset.image_prompt && (
              <div className="px-4 pb-2">
                <p className="text-xs italic" style={{ color: "var(--text-muted)" }}>
                  {asset.image_prompt.length > 150
                    ? asset.image_prompt.slice(0, 150) + "..."
                    : asset.image_prompt}
                </p>
              </div>
            )}

            {/* Image or placeholder */}
            <div className="px-4 pb-4">
              {asset.image_url ? (
                <div className="relative group">
                  <img
                    src={asset.image_url}
                    alt={asset.sentence_text || "Scene image"}
                    className="w-full rounded-lg aspect-video object-cover"
                  />
                  <div className="absolute bottom-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                    <a
                      href={asset.image_url}
                      target="_blank"
                      rel="noopener"
                      className="p-1.5 rounded-lg"
                      style={{ background: "rgba(0,0,0,0.7)" }}
                    >
                      <Download size={14} style={{ color: "var(--text-primary)" }} />
                    </a>
                  </div>
                </div>
              ) : (
                <div
                  className="w-full rounded-lg aspect-video flex items-center justify-center"
                  style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
                >
                  <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                    Not generated
                  </span>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Scene navigation */}
      {sceneNumbers.length > 1 && (
        <div className="flex items-center justify-between">
          <button
            onClick={() => {
              const idx = sceneNumbers.indexOf(currentScene);
              if (idx > 0) setCurrentScene(sceneNumbers[idx - 1]);
            }}
            disabled={sceneNumbers.indexOf(currentScene) === 0}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            <ChevronLeft size={16} /> Prev Scene
          </button>
          <span className="text-sm" style={{ color: "var(--text-muted)" }}>
            Scene {currentScene} / {sceneNumbers.length}
          </span>
          <button
            onClick={() => {
              const idx = sceneNumbers.indexOf(currentScene);
              if (idx < sceneNumbers.length - 1) setCurrentScene(sceneNumbers[idx + 1]);
            }}
            disabled={sceneNumbers.indexOf(currentScene) === sceneNumbers.length - 1}
            className="flex items-center gap-1 px-3 py-2 rounded-lg text-sm disabled:opacity-30"
            style={{ color: "var(--text-secondary)" }}
          >
            Next Scene <ChevronRight size={16} />
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/visuals-tab.tsx
git commit -m "feat(storyengine): Add Visuals tab — image prompts and generated images by scene"
```

---

## Task 5: Storyboard Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/storyboard-tab.tsx`

- [ ] **Step 1: Create the Storyboard tab**

Reuses the existing SceneGrid component pattern. Fetches script records (which have storyboard URLs) and displays them.

```tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { getVideoScript } from "@/lib/api";

interface StoryboardTabProps {
  videoId: string;
}

export function StoryboardTab({ videoId }: StoryboardTabProps) {
  const { data: scenes, isLoading } = useQuery({
    queryKey: ["video-script", videoId],
    queryFn: () => getVideoScript(videoId),
  });

  if (isLoading) {
    return (
      <div className="space-y-4">
        {[1, 2].map((i) => (
          <div key={i} className="h-64 rounded-xl animate-pulse" style={{ background: "var(--bg-card)" }} />
        ))}
      </div>
    );
  }

  // Find scenes with storyboard data
  const storyboardScenes = (scenes || []).filter(
    (s: any) => s.storyboard_on_off === "On" || s.storyboard_1_url || s.storyboard_2_url || s.storyboard_3_url
  );

  // Collect all storyboard grid URLs
  const grids: { sceneNum: number; gridNum: number; url: string; narration: string }[] = [];
  storyboardScenes.forEach((s: any) => {
    const urls = [s.storyboard_1_url, s.storyboard_2_url, s.storyboard_3_url];
    urls.forEach((url, i) => {
      if (url) {
        grids.push({
          sceneNum: s.scene || 0,
          gridNum: i + 1,
          url,
          narration: s.scene_text || "",
        });
      }
    });
  });

  if (grids.length === 0) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No storyboards yet. Storyboards will appear after the storyboard generation stage.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="text-sm" style={{ color: "var(--text-muted)" }}>
        {grids.length} storyboard grid{grids.length !== 1 ? "s" : ""}
      </div>

      {grids.map((grid) => (
        <div
          key={`${grid.sceneNum}-${grid.gridNum}`}
          className="rounded-xl overflow-hidden"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <div className="p-4 pb-2">
            <h3 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
              Grid {grid.gridNum} (Scene {grid.sceneNum})
            </h3>
          </div>
          <div className="px-4 pb-4">
            <img
              src={grid.url}
              alt={`Storyboard grid ${grid.gridNum} for scene ${grid.sceneNum}`}
              className="w-full rounded-lg"
            />
          </div>
          {grid.narration && (
            <div className="px-4 pb-4">
              <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                {grid.narration.length > 200
                  ? grid.narration.slice(0, 200) + "..."
                  : grid.narration}
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/storyboard-tab.tsx
git commit -m "feat(storyengine): Add Storyboard tab — grid display from script records"
```

---

## Task 6: Thumbnail Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/thumbnail-tab.tsx`

- [ ] **Step 1: Create the Thumbnail tab**

```tsx
"use client";

interface ThumbnailTabProps {
  video: any;
}

export function ThumbnailTab({ video }: ThumbnailTabProps) {
  return (
    <div className="space-y-6">
      {/* Current thumbnail */}
      <div
        className="rounded-xl overflow-hidden"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <div className="p-4 pb-2">
          <h3 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Current Thumbnail
          </h3>
        </div>
        <div className="px-4 pb-4">
          {video.thumbnail_url ? (
            <img
              src={video.thumbnail_url}
              alt="Current thumbnail"
              className="w-full rounded-lg aspect-video object-cover"
            />
          ) : (
            <div
              className="w-full rounded-lg aspect-video flex items-center justify-center"
              style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
            >
              <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                No thumbnail generated
              </span>
            </div>
          )}
        </div>

        {/* CTR indicator */}
        {video.ctr != null && (
          <div className="px-4 pb-4">
            <div className="flex items-center gap-2">
              <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
                CTR:
              </span>
              <span
                className="text-sm font-bold"
                style={{
                  color: video.ctr >= 3 ? "var(--green)" : video.ctr >= 2 ? "var(--amber)" : "var(--red)",
                }}
              >
                {video.ctr.toFixed(1)}%
              </span>
              {video.ctr < 3 && (
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  (below 3% threshold)
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Prompt */}
      {video.thumbnail_prompt && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
            Prompt
          </h3>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
            {video.thumbnail_prompt}
          </p>
        </div>
      )}

      {/* Style override */}
      {video.thumbnail_style_override && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-2" style={{ color: "var(--text-muted)" }}>
            Style Override
          </h3>
          <p className="text-sm whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
            {video.thumbnail_style_override}
          </p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/thumbnail-tab.tsx
git commit -m "feat(storyengine): Add Thumbnail tab — current thumbnail, CTR indicator, prompt"
```

---

## Task 7: Performance Tab

**Files:**
- Create: `storyengine/frontend/src/components/video-detail/performance-tab.tsx`

- [ ] **Step 1: Create the Performance tab**

```tsx
"use client";

import { formatNumber, formatCost } from "@/lib/utils";

interface PerformanceTabProps {
  video: any;
}

export function PerformanceTab({ video }: PerformanceTabProps) {
  const hasPerformanceData = video.views > 0 || video.ctr != null;

  if (!hasPerformanceData) {
    return (
      <div className="text-center py-12" style={{ color: "var(--text-muted)" }}>
        No performance data yet. Metrics will appear after the video is published on YouTube.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top metrics */}
      <div className="grid grid-cols-2 gap-3">
        <MetricCard label="Views" value={formatNumber(video.views || 0)} />
        <MetricCard
          label="CTR"
          value={video.ctr != null ? `${video.ctr.toFixed(1)}%` : "—"}
          alert={video.ctr != null && video.ctr < 3}
        />
        <MetricCard
          label="Retention"
          value={video.avg_retention != null ? `${video.avg_retention.toFixed(0)}%` : "—"}
        />
        <MetricCard
          label="Watch Time"
          value={
            video.avg_view_duration_seconds != null
              ? `${(video.avg_view_duration_seconds / 60).toFixed(1)} min`
              : "—"
          }
        />
      </div>

      {/* Timeline */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
          Timeline
        </h3>
        <div className="space-y-2">
          <TimelineRow label="24h" views={video.views_24h} ctr={video.ctr_24h} />
          <TimelineRow label="48h" views={video.views_48h} ctr={video.ctr_48h} />
          <TimelineRow label="7d" views={video.views_7d} />
          <TimelineRow label="30d" views={video.views_30d} />
        </div>
      </div>

      {/* Post-mortem */}
      {(video.post_mortem_48h || video.post_mortem_7d) && (
        <div
          className="rounded-xl p-4"
          style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        >
          <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
            Post-Mortem
          </h3>
          {video.post_mortem_48h && (
            <div className="mb-3">
              <span className="text-xs font-medium" style={{ color: "var(--amber)" }}>48h</span>
              <p className="text-sm mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {typeof video.post_mortem_48h === "string"
                  ? video.post_mortem_48h
                  : JSON.stringify(video.post_mortem_48h, null, 2)}
              </p>
            </div>
          )}
          {video.post_mortem_7d && (
            <div>
              <span className="text-xs font-medium" style={{ color: "var(--green)" }}>7d</span>
              <p className="text-sm mt-1 whitespace-pre-wrap" style={{ color: "var(--text-secondary)" }}>
                {typeof video.post_mortem_7d === "string"
                  ? video.post_mortem_7d
                  : JSON.stringify(video.post_mortem_7d, null, 2)}
              </p>
            </div>
          )}
        </div>
      )}

      {/* Production cost */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
      >
        <h3 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
          Production Cost
        </h3>
        <p className="text-lg font-bold" style={{ color: "var(--text-primary)" }}>
          {formatCost(video.total_cost || 0)}
        </p>
        {video.performance_verdict && (
          <div className="mt-2">
            <span
              className="text-xs px-2 py-0.5 rounded"
              style={{
                background:
                  video.performance_verdict === "strong"
                    ? "rgba(58, 154, 90, 0.15)"
                    : video.performance_verdict === "weak"
                    ? "rgba(196, 69, 69, 0.15)"
                    : "rgba(212, 168, 68, 0.15)",
                color:
                  video.performance_verdict === "strong"
                    ? "var(--green)"
                    : video.performance_verdict === "weak"
                    ? "var(--red)"
                    : "var(--amber)",
              }}
            >
              {video.performance_verdict}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  alert,
}: {
  label: string;
  value: string;
  alert?: boolean;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
    >
      <span className="text-xs uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <p
        className="text-xl font-bold mt-1"
        style={{ color: alert ? "var(--red)" : "var(--text-primary)" }}
      >
        {value}
      </p>
    </div>
  );
}

function TimelineRow({
  label,
  views,
  ctr,
}: {
  label: string;
  views?: number | null;
  ctr?: number | null;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm font-medium w-10" style={{ color: "var(--text-muted)" }}>
        {label}
      </span>
      <span className="text-sm" style={{ color: "var(--text-primary)" }}>
        {views != null ? formatNumber(views) : "—"} views
      </span>
      {ctr != null && (
        <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
          CTR: {ctr.toFixed(1)}%
        </span>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/video-detail/performance-tab.tsx
git commit -m "feat(storyengine): Add Performance tab — metrics, timeline, post-mortem, cost"
```

---

## Task 8: Wire Pipeline → Video Detail

**Files:**
- Modify: `storyengine/frontend/src/components/video-card.tsx`
- Modify: `storyengine/frontend/src/app/pipeline/page.tsx`

- [ ] **Step 1: Make VideoCard link to detail page**

Read `storyengine/frontend/src/components/video-card.tsx`. Change it from a `<button>` with `onClick` to a `<Link>` pointing to `/pipeline/${video.id}`. Keep the same visual styling. Add `import Link from "next/link"`.

The card should link to `/pipeline/${video.id}` where `video.id` is the Supabase UUID.

- [ ] **Step 2: Update pipeline page**

Read `storyengine/frontend/src/app/pipeline/page.tsx`. Remove the detail panel overlay (the `DetailPanel` component and all its contents). Video cards now navigate to the detail page instead. Remove the `selectedId` state and the `getVideo` query for the selected video. Keep the list, filters, search, and [+ New] button.

- [ ] **Step 3: Verify navigation works**

Click a video card → should navigate to `/pipeline/[videoId]` showing the 6-tab detail view.

- [ ] **Step 4: Commit**

```bash
git add storyengine/frontend/src/components/video-card.tsx storyengine/frontend/src/app/pipeline/page.tsx
git commit -m "feat(storyengine): Wire pipeline cards to video detail page, remove overlay panel"
```

---

## Task 9: Create New Video Page

**Files:**
- Create: `storyengine/frontend/src/app/create/page.tsx`
- Modify: `storyengine/frontend/src/app/pipeline/page.tsx` (update [+ New] link)

- [ ] **Step 1: Create the form page**

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { createIdea } from "@/lib/api";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";

export default function CreateVideoPage() {
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [angle, setAngle] = useState("");
  const [thesis, setThesis] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [pastContext, setPastContext] = useState("");
  const [futurePrediction, setFuturePrediction] = useState("");
  const [openingHook, setOpeningHook] = useState("");
  const [targetLength, setTargetLength] = useState(15);

  const createMutation = useMutation({
    mutationFn: () => {
      // Build topic string from form fields
      const topic = [
        `Title: ${title}`,
        `Angle: ${angle}`,
        `Thesis: ${thesis}`,
        pastContext ? `Past Context: ${pastContext}` : "",
        futurePrediction ? `Future Prediction: ${futurePrediction}` : "",
        openingHook ? `Opening Hook: ${openingHook}` : "",
        `Target Length: ${targetLength} minutes`,
      ]
        .filter(Boolean)
        .join("\n");
      return createIdea(topic, "web_ui");
    },
    onSuccess: () => {
      router.push("/pipeline");
    },
  });

  const isValid = title.trim() && angle.trim() && thesis.trim();

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      {/* Header */}
      <div>
        <Link
          href="/pipeline"
          className="inline-flex items-center gap-1 text-sm mb-4 transition-colors hover:opacity-80"
          style={{ color: "var(--text-muted)" }}
        >
          <ArrowLeft size={16} />
          Back
        </Link>

        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          What's Your Story?
        </h1>
        <p className="mt-1" style={{ color: "var(--text-secondary)" }}>
          Every great video starts with a compelling idea.
        </p>
      </div>

      {/* Form */}
      <div className="space-y-5">
        <FormField label="Title" required>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="The AI Chip Shortage That Could Crash the Economy"
            className="w-full rounded-lg px-4 py-3 text-sm outline-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        <FormField label="Angle" required>
          <textarea
            value={angle}
            onChange={(e) => setAngle(e.target.value)}
            placeholder="Most people think AI is just software, but the real bottleneck is hardware"
            rows={2}
            className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        <FormField label="Thesis" required>
          <textarea
            value={thesis}
            onChange={(e) => setThesis(e.target.value)}
            placeholder="The global AI boom depends on a handful of chip fabs..."
            rows={3}
            className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none transition-colors"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
        </FormField>

        {/* Advanced options */}
        <button
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-sm font-medium"
          style={{ color: "var(--amber)" }}
        >
          {showAdvanced ? "▲ Hide" : "▼ Show"} Advanced Options
        </button>

        {showAdvanced && (
          <div className="space-y-5 pl-4" style={{ borderLeft: "2px solid var(--border)" }}>
            <FormField label="Past Context">
              <textarea
                value={pastContext}
                onChange={(e) => setPastContext(e.target.value)}
                placeholder="Historical context..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Future Prediction">
              <textarea
                value={futurePrediction}
                onChange={(e) => setFuturePrediction(e.target.value)}
                placeholder="What happens next..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Opening Hook">
              <textarea
                value={openingHook}
                onChange={(e) => setOpeningHook(e.target.value)}
                placeholder="The first 15 seconds..."
                rows={2}
                className="w-full rounded-lg px-4 py-3 text-sm outline-none resize-none"
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  color: "var(--text-primary)",
                }}
              />
            </FormField>

            <FormField label="Target Length">
              <div className="flex gap-2">
                {[5, 10, 15, 20].map((mins) => (
                  <button
                    key={mins}
                    onClick={() => setTargetLength(mins)}
                    className="px-4 py-2 rounded-lg text-sm font-medium transition-colors"
                    style={{
                      background: targetLength === mins ? "var(--amber)" : "var(--bg-card)",
                      color: targetLength === mins ? "var(--bg-primary)" : "var(--text-secondary)",
                      border: `1px solid ${targetLength === mins ? "var(--amber)" : "var(--border)"}`,
                    }}
                  >
                    {mins} min
                  </button>
                ))}
              </div>
            </FormField>
          </div>
        )}
      </div>

      {/* Submit */}
      <button
        onClick={() => createMutation.mutate()}
        disabled={!isValid || createMutation.isPending}
        className="w-full py-3 rounded-lg text-sm font-semibold transition-colors disabled:opacity-50"
        style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
      >
        {createMutation.isPending ? "Creating..." : "Generate Story →"}
      </button>

      {createMutation.isError && (
        <p className="text-sm text-center" style={{ color: "var(--red)" }}>
          Failed to create video. Please try again.
        </p>
      )}
    </div>
  );
}

function FormField({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="text-sm font-medium mb-2 block" style={{ color: "var(--text-primary)" }}>
        {label}
        {required && <span style={{ color: "var(--amber)" }}> *</span>}
      </label>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Update [+ New] link on pipeline page**

In `storyengine/frontend/src/app/pipeline/page.tsx`, find the `[+ New]` button and change its `href` from `"#"` to `"/create"`.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/create/page.tsx storyengine/frontend/src/app/pipeline/page.tsx
git commit -m "feat(storyengine): Add Create New Video page with form + link from pipeline"
```

---

## Task 10: Typecheck and Build

- [ ] **Step 1: Run typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

Fix any errors.

- [ ] **Step 2: Run build**

```bash
cd storyengine/frontend && npm run build
```

Fix any build errors.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A storyengine/frontend/
git commit -m "fix(storyengine): Fix typecheck and build errors from Module 2"
```

---

## Completion Criteria

- [ ] `/pipeline/[videoId]` route works with 6 tabs
- [ ] Info tab shows Story DNA, Story Bible, Research, Actions
- [ ] Script tab shows scenes with mobile prev/next and desktop scroll
- [ ] Visuals tab shows images grouped by scene with prompts
- [ ] Storyboard tab shows 3x3 grids from script records
- [ ] Thumbnail tab shows current thumbnail, CTR, prompt
- [ ] Performance tab shows metrics, timeline, post-mortem, cost
- [ ] Pipeline cards link to detail page (no overlay panel)
- [ ] Create page (`/create`) has form with title/angle/thesis + advanced options
- [ ] [+ New] on pipeline links to `/create`
- [ ] TypeScript compiles, Next.js builds

**Total: 10 tasks, 10 files created/modified**
