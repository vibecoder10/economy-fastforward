# Module 5: Niche Selection + Topic Discovery

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the autopilot page into a niche intelligence hub with playing card competitor videos, a thumbnail workshop with prompt iteration carousel, and a niche setup flow for new tenants.

**Architecture:** Add niche columns to `autopilot_config`, create backend niche/thumbnail endpoints, then rebuild the autopilot page frontend with playing cards that expand into side-by-side comparison + thumbnail workshop. The existing candidate scoring and data fetching remain — we're upgrading the UI and adding niche context.

**Tech Stack:** Next.js 16, React 19, Tailwind 4.2, Framer Motion (card animations), FastAPI (backend), Supabase PostgreSQL

**Design Spec:** `docs/superpowers/specs/2026-03-24-module5-niche-discovery-design.md`

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `storyengine/backend/migrations/006_niche_columns.sql` | Add niche_category + sub_niche to autopilot_config |
| `storyengine/backend/routes/niche.py` | Niche setup + channel management endpoints |
| `storyengine/frontend/src/components/autopilot/playing-card.tsx` | Front of card (thumbnail, stats, confidence) |
| `storyengine/frontend/src/components/autopilot/card-expanded.tsx` | Back of card (theirs vs yours + thumbnail workshop) |
| `storyengine/frontend/src/components/autopilot/thumbnail-workshop.tsx` | Prompt iteration carousel |
| `storyengine/frontend/src/components/autopilot/niche-setup.tsx` | Onboarding wizard (category, sub-niche, channels) |

### Modified Files
| File | Changes |
|------|---------|
| `storyengine/schema.sql` | Add niche columns |
| `storyengine/backend/main.py` | Register niche router |
| `storyengine/frontend/src/lib/api.ts` | Add niche + thumbnail types and functions |
| `storyengine/frontend/src/app/autopilot/page.tsx` | Replace candidates with playing cards, add niche setup |

---

## Task 1: Migration 006 — Niche Columns

**Files:**
- Create: `storyengine/backend/migrations/006_niche_columns.sql`
- Modify: `storyengine/schema.sql`

- [ ] **Step 1: Create migration**

```sql
-- 006_niche_columns.sql
-- Adds niche configuration to autopilot_config
-- All statements idempotent

ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS niche_category TEXT;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS sub_niche TEXT;
```

- [ ] **Step 2: Update schema.sql**

Add `niche_category TEXT` and `sub_niche TEXT` to the `autopilot_config` CREATE TABLE definition.

- [ ] **Step 3: Commit**

```bash
git add storyengine/backend/migrations/006_niche_columns.sql storyengine/schema.sql
git commit -m "feat(storyengine): Add migration 006 — niche columns on autopilot_config"
```

---

## Task 2: Backend — Niche Routes

**Files:**
- Create: `storyengine/backend/routes/niche.py`
- Modify: `storyengine/backend/main.py`

- [ ] **Step 1: Create niche route file**

```python
"""Niche selection + competitor channel management."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from typing import Optional
from database import fetch_one, fetch_all, execute
from auth import get_tenant_id

router = APIRouter(prefix="/api/niche", tags=["niche"])


class NicheSetup(BaseModel):
    niche_category: str
    sub_niche: str


class ChannelAdd(BaseModel):
    channel_url: str
    channel_name: str
    category: Optional[str] = None


@router.get("/config")
async def get_niche_config(tenant_id: str = Depends(get_tenant_id)):
    """Get current niche configuration."""
    row = await fetch_one(
        "SELECT niche_category, sub_niche FROM autopilot_config WHERE tenant_id = $1",
        tenant_id,
    )
    if not row:
        return {"niche_category": None, "sub_niche": None, "has_channels": False}

    channel_count = await fetch_one(
        "SELECT count(*) as cnt FROM competitor_channels WHERE tenant_id = $1",
        tenant_id,
    )
    return {
        "niche_category": row.get("niche_category"),
        "sub_niche": row.get("sub_niche"),
        "has_channels": (channel_count or {}).get("cnt", 0) > 0,
    }


@router.post("/setup")
async def setup_niche(body: NicheSetup, tenant_id: str = Depends(get_tenant_id)):
    """Save niche category and sub-niche."""
    existing = await fetch_one(
        "SELECT id FROM autopilot_config WHERE tenant_id = $1", tenant_id
    )
    if existing:
        await execute(
            """UPDATE autopilot_config
               SET niche_category = $1, sub_niche = $2, updated_at = NOW()
               WHERE tenant_id = $3""",
            body.niche_category, body.sub_niche, tenant_id,
        )
    else:
        await execute(
            """INSERT INTO autopilot_config (tenant_id, niche_category, sub_niche)
               VALUES ($1, $2, $3)""",
            tenant_id, body.niche_category, body.sub_niche,
        )
    return {"status": "ok"}


@router.get("/channels")
async def list_channels(tenant_id: str = Depends(get_tenant_id)):
    """List competitor channels."""
    rows = await fetch_all(
        """SELECT id, channel_name, channel_url, category, active, last_scraped
           FROM competitor_channels
           WHERE tenant_id = $1
           ORDER BY channel_name""",
        tenant_id,
    )
    return rows or []


@router.post("/channels")
async def add_channel(body: ChannelAdd, tenant_id: str = Depends(get_tenant_id)):
    """Add a competitor channel."""
    await execute(
        """INSERT INTO competitor_channels (tenant_id, channel_name, channel_url, category, active)
           VALUES ($1, $2, $3, $4, true)""",
        tenant_id, body.channel_name, body.channel_url, body.category,
    )
    return {"status": "ok", "channel_name": body.channel_name}


@router.delete("/channels/{channel_id}")
async def remove_channel(channel_id: str, tenant_id: str = Depends(get_tenant_id)):
    """Remove a competitor channel."""
    await execute(
        "DELETE FROM competitor_channels WHERE id = $1 AND tenant_id = $2",
        channel_id, tenant_id,
    )
    return {"status": "ok"}
```

- [ ] **Step 2: Register niche router in main.py**

Read `storyengine/backend/main.py`. Add to the imports:
```python
from routes import niche
```
And add to the router includes:
```python
app.include_router(niche.router)
```

- [ ] **Step 3: Commit**

```bash
git add storyengine/backend/routes/niche.py storyengine/backend/main.py
git commit -m "feat(storyengine): Add niche setup + channel management API routes"
```

---

## Task 3: Frontend API Types + Functions

**Files:**
- Modify: `storyengine/frontend/src/lib/api.ts`

- [ ] **Step 1: Add niche and thumbnail types + functions**

Add these interfaces:
```typescript
// Niche
export interface NicheConfig {
  niche_category: string | null;
  sub_niche: string | null;
  has_channels: boolean;
}

export interface CompetitorChannel {
  id: string;
  channel_name: string;
  channel_url: string;
  category: string | null;
  active: boolean;
  last_scraped: string | null;
}

// Thumbnail iteration
export interface ThumbnailVersion {
  prompt: string;
  image_url: string | null;
  created_at: string;
}
```

Add these API functions:
```typescript
// Niche
export const getNicheConfig = () =>
  fetchApi<NicheConfig>("/api/niche/config");

export const setupNiche = (niche_category: string, sub_niche: string) =>
  fetchApi<{ status: string }>("/api/niche/setup", {
    method: "POST",
    body: JSON.stringify({ niche_category, sub_niche }),
  });

export const getNicheChannels = () =>
  fetchApi<CompetitorChannel[]>("/api/niche/channels");

export const addNicheChannel = (channel_name: string, channel_url: string) =>
  fetchApi<{ status: string }>("/api/niche/channels", {
    method: "POST",
    body: JSON.stringify({ channel_name, channel_url }),
  });

export const removeNicheChannel = (channelId: string) =>
  fetchApi<{ status: string }>(`/api/niche/channels/${channelId}`, {
    method: "DELETE",
  });
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/lib/api.ts
git commit -m "feat(storyengine): Add niche + thumbnail API types and functions"
```

---

## Task 4: Niche Setup Component

**Files:**
- Create: `storyengine/frontend/src/components/autopilot/niche-setup.tsx`

- [ ] **Step 1: Create the setup wizard**

Three-step onboarding shown when no niche is configured:

```tsx
"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { setupNiche, addNicheChannel } from "@/lib/api";
import { Globe, Plus, ArrowRight, Check } from "lucide-react";

const YOUTUBE_CATEGORIES = [
  "Education",
  "News & Politics",
  "Science & Technology",
  "Entertainment",
  "People & Blogs",
  "Film & Animation",
  "Gaming",
  "Music",
  "Sports",
  "How-to & Style",
  "Comedy",
  "Autos & Vehicles",
];

interface NicheSetupProps {
  onComplete: () => void;
}

export function NicheSetup({ onComplete }: NicheSetupProps) {
  const [step, setStep] = useState(1);
  const [category, setCategory] = useState("");
  const [subNiche, setSubNiche] = useState("");
  const [channels, setChannels] = useState<{ name: string; url: string }[]>([]);
  const [channelUrl, setChannelUrl] = useState("");
  const [channelName, setChannelName] = useState("");
  const queryClient = useQueryClient();

  const saveMutation = useMutation({
    mutationFn: async () => {
      await setupNiche(category, subNiche);
      for (const ch of channels) {
        await addNicheChannel(ch.name, ch.url);
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["niche-config"] });
      queryClient.invalidateQueries({ queryKey: ["niche-channels"] });
      onComplete();
    },
  });

  const addChannel = () => {
    if (channelUrl.trim() && channelName.trim()) {
      setChannels([...channels, { name: channelName.trim(), url: channelUrl.trim() }]);
      setChannelUrl("");
      setChannelName("");
    }
  };

  return (
    <div className="max-w-lg mx-auto py-12">
      <div className="text-center mb-8">
        <Globe size={48} className="mx-auto mb-4" style={{ color: "var(--amber)" }} />
        <h1 className="text-2xl font-bold" style={{ color: "var(--text-primary)" }}>
          Set Up Your Niche
        </h1>
        <p className="mt-2" style={{ color: "var(--text-secondary)" }}>
          Tell us what you create so we can find the best topics for you.
        </p>
      </div>

      {/* Step indicators */}
      <div className="flex items-center justify-center gap-2 mb-8">
        {[1, 2, 3].map((s) => (
          <div
            key={s}
            className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold"
            style={{
              background: step >= s ? "var(--amber)" : "var(--bg-card)",
              color: step >= s ? "var(--bg-primary)" : "var(--text-muted)",
              border: `1px solid ${step >= s ? "var(--amber)" : "var(--border)"}`,
            }}
          >
            {step > s ? <Check size={14} /> : s}
          </div>
        ))}
      </div>

      {/* Step 1: Category */}
      {step === 1 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            YouTube Category
          </h2>
          <div className="grid grid-cols-2 gap-2">
            {YOUTUBE_CATEGORIES.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                className="px-4 py-3 rounded-lg text-sm font-medium text-left transition-colors"
                style={{
                  background: category === cat ? "rgba(212, 168, 68, 0.15)" : "var(--bg-card)",
                  color: category === cat ? "var(--amber)" : "var(--text-secondary)",
                  border: `1px solid ${category === cat ? "var(--amber)" : "var(--border)"}`,
                }}
              >
                {cat}
              </button>
            ))}
          </div>
          <button
            onClick={() => category && setStep(2)}
            disabled={!category}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            Next <ArrowRight size={16} />
          </button>
        </div>
      )}

      {/* Step 2: Sub-niche */}
      {step === 2 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Your Specific Focus
          </h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Within {category}, what's your niche?
          </p>
          <input
            type="text"
            value={subNiche}
            onChange={(e) => setSubNiche(e.target.value)}
            placeholder="e.g., Geopolitics, Personal Finance, AI Explained"
            className="w-full rounded-lg px-4 py-3 text-sm outline-none"
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              color: "var(--text-primary)",
            }}
          />
          <button
            onClick={() => subNiche.trim() && setStep(3)}
            disabled={!subNiche.trim()}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40 flex items-center justify-center gap-2"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            Next <ArrowRight size={16} />
          </button>
        </div>
      )}

      {/* Step 3: Competitor channels */}
      {step === 3 && (
        <div className="space-y-4">
          <h2 className="text-sm font-semibold uppercase tracking-wider" style={{ color: "var(--text-muted)" }}>
            Add Competitor Channels
          </h2>
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            Paste YouTube channel URLs you want to track.
          </p>

          {/* Added channels */}
          {channels.map((ch, i) => (
            <div
              key={i}
              className="flex items-center gap-3 px-3 py-2 rounded-lg"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
            >
              <Check size={14} style={{ color: "var(--green)" }} />
              <span className="text-sm flex-1" style={{ color: "var(--text-primary)" }}>
                {ch.name}
              </span>
            </div>
          ))}

          {/* Add channel form */}
          <div className="space-y-2">
            <input
              type="text"
              value={channelName}
              onChange={(e) => setChannelName(e.target.value)}
              placeholder="Channel name (e.g., CaspianReport)"
              className="w-full rounded-lg px-4 py-2.5 text-sm outline-none"
              style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
            />
            <div className="flex gap-2">
              <input
                type="text"
                value={channelUrl}
                onChange={(e) => setChannelUrl(e.target.value)}
                placeholder="https://youtube.com/@channel"
                className="flex-1 rounded-lg px-4 py-2.5 text-sm outline-none"
                style={{ background: "var(--bg-card)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
                onKeyDown={(e) => e.key === "Enter" && addChannel()}
              />
              <button
                onClick={addChannel}
                disabled={!channelUrl.trim() || !channelName.trim()}
                className="px-4 py-2.5 rounded-lg disabled:opacity-40"
                style={{ background: "var(--bg-card-hover)", color: "var(--text-primary)", border: "1px solid var(--border)" }}
              >
                <Plus size={16} />
              </button>
            </div>
          </div>

          <button
            onClick={() => saveMutation.mutate()}
            disabled={channels.length === 0 || saveMutation.isPending}
            className="w-full py-3 rounded-lg text-sm font-semibold disabled:opacity-40"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {saveMutation.isPending ? "Setting up..." : `Start Scanning ${channels.length} Channel${channels.length !== 1 ? "s" : ""} →`}
          </button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/autopilot/niche-setup.tsx
git commit -m "feat(storyengine): Add NicheSetup wizard component"
```

---

## Task 5: Playing Card Component (Front)

**Files:**
- Create: `storyengine/frontend/src/components/autopilot/playing-card.tsx`

- [ ] **Step 1: Create the playing card front**

```tsx
"use client";

import { motion } from "framer-motion";
import { formatNumber } from "@/lib/utils";
import type { CompetitorCandidate } from "@/lib/api";

interface PlayingCardProps {
  candidate: CompetitorCandidate;
  onModel: (candidate: CompetitorCandidate) => void;
}

export function PlayingCard({ candidate, onModel }: PlayingCardProps) {
  // Build YouTube thumbnail URL from video URL
  const videoId = candidate.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
  const thumbnailUrl = videoId
    ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`
    : null;

  return (
    <motion.div
      whileHover={{ scale: 1.02, y: -4 }}
      transition={{ type: "spring", stiffness: 300, damping: 25 }}
      className="rounded-xl overflow-hidden cursor-pointer"
      style={{
        background: "var(--bg-card)",
        border: "1px solid var(--border)",
      }}
      onClick={() => onModel(candidate)}
    >
      {/* Thumbnail */}
      {thumbnailUrl ? (
        <img
          src={thumbnailUrl}
          alt={candidate.title}
          className="w-full aspect-video object-cover"
        />
      ) : (
        <div
          className="w-full aspect-video flex items-center justify-center"
          style={{ background: "var(--bg-card-hover)" }}
        >
          <span className="text-3xl font-bold" style={{ color: "var(--text-muted)" }}>
            {candidate.title?.[0] || "?"}
          </span>
        </div>
      )}

      {/* Content */}
      <div className="p-4 space-y-3">
        {/* Title */}
        <h3
          className="text-sm font-semibold leading-tight line-clamp-2"
          style={{ color: "var(--text-primary)" }}
        >
          {candidate.title}
        </h3>

        {/* Stats row */}
        <div className="flex gap-2">
          <div
            className="px-2.5 py-1 rounded-md text-xs font-bold"
            style={{ background: "rgba(212, 168, 68, 0.15)", color: "var(--amber)" }}
          >
            {formatNumber(candidate.vph)} VPH
          </div>
          <div
            className="px-2.5 py-1 rounded-md text-xs font-medium"
            style={{ background: "rgba(26, 138, 122, 0.15)", color: "var(--teal)" }}
          >
            {Math.round(candidate.hours_old)}h fresh
          </div>
        </div>

        {/* Channel + confidence */}
        <div className="flex items-center justify-between">
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {candidate.source}
          </span>
          <div className="flex items-center gap-2">
            <div
              className="h-1.5 w-16 rounded-full overflow-hidden"
              style={{ background: "var(--bg-card-hover)" }}
            >
              <div
                className="h-full rounded-full"
                style={{
                  width: `${Math.min(100, candidate.confidence)}%`,
                  background: "var(--amber)",
                }}
              />
            </div>
            <span className="text-xs font-bold" style={{ color: "var(--amber)" }}>
              {candidate.confidence.toFixed(0)}
            </span>
          </div>
        </div>

        {/* Model button */}
        <button
          className="w-full py-2 rounded-lg text-sm font-medium transition-colors"
          style={{
            background: "rgba(212, 168, 68, 0.1)",
            color: "var(--amber)",
            border: "1px solid rgba(212, 168, 68, 0.3)",
          }}
          onClick={(e) => {
            e.stopPropagation();
            onModel(candidate);
          }}
        >
          Model This →
        </button>
      </div>
    </motion.div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/autopilot/playing-card.tsx
git commit -m "feat(storyengine): Add PlayingCard component for competitor videos"
```

---

## Task 6: Thumbnail Workshop Component

**Files:**
- Create: `storyengine/frontend/src/components/autopilot/thumbnail-workshop.tsx`

- [ ] **Step 1: Create the thumbnail workshop with iteration carousel**

```tsx
"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight, Lock } from "lucide-react";

export interface ThumbnailVersion {
  prompt: string;
  imageUrl: string | null;
}

interface ThumbnailWorkshopProps {
  initialPrompt: string;
  versions: ThumbnailVersion[];
  onGenerate: (prompt: string) => void;
  onLock: (version: ThumbnailVersion) => void;
  isGenerating?: boolean;
}

export function ThumbnailWorkshop({
  initialPrompt,
  versions,
  onGenerate,
  onLock,
  isGenerating,
}: ThumbnailWorkshopProps) {
  const [currentIndex, setCurrentIndex] = useState(versions.length > 0 ? versions.length - 1 : 0);
  const [editPrompt, setEditPrompt] = useState(
    versions.length > 0 ? versions[versions.length - 1].prompt : initialPrompt
  );

  const hasVersions = versions.length > 0;
  const currentVersion = hasVersions ? versions[currentIndex] : null;
  const costPerGen = 0.075;
  const totalSpent = versions.filter((v) => v.imageUrl).length * costPerGen;

  const goNext = () => setCurrentIndex(Math.min(versions.length - 1, currentIndex + 1));
  const goPrev = () => setCurrentIndex(Math.max(0, currentIndex - 1));

  return (
    <div className="space-y-4">
      <h4
        className="text-xs font-semibold uppercase tracking-wider"
        style={{ color: "var(--text-muted)" }}
      >
        Thumbnail Workshop
      </h4>

      {/* Carousel */}
      {hasVersions && (
        <div>
          {/* Image with arrows */}
          <div className="relative">
            {currentVersion?.imageUrl ? (
              <img
                src={currentVersion.imageUrl}
                alt={`Version ${currentIndex + 1}`}
                className="w-full rounded-lg aspect-video object-cover"
              />
            ) : (
              <div
                className="w-full rounded-lg aspect-video flex items-center justify-center"
                style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
              >
                <span className="text-sm" style={{ color: "var(--text-muted)" }}>
                  {isGenerating ? "Generating..." : "Not generated"}
                </span>
              </div>
            )}

            {/* Navigation arrows */}
            {versions.length > 1 && (
              <>
                <button
                  onClick={goPrev}
                  disabled={currentIndex === 0}
                  className="absolute left-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center disabled:opacity-20"
                  style={{ background: "rgba(0,0,0,0.6)" }}
                >
                  <ChevronLeft size={16} style={{ color: "var(--text-primary)" }} />
                </button>
                <button
                  onClick={goNext}
                  disabled={currentIndex === versions.length - 1}
                  className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-full flex items-center justify-center disabled:opacity-20"
                  style={{ background: "rgba(0,0,0,0.6)" }}
                >
                  <ChevronRight size={16} style={{ color: "var(--text-primary)" }} />
                </button>
              </>
            )}
          </div>

          {/* Dot indicators */}
          {versions.length > 1 && (
            <div className="flex items-center justify-center gap-1.5 mt-2">
              {versions.map((_, i) => (
                <button
                  key={i}
                  onClick={() => setCurrentIndex(i)}
                  className="w-2 h-2 rounded-full transition-colors"
                  style={{
                    background: i === currentIndex ? "var(--amber)" : "var(--text-muted)",
                  }}
                />
              ))}
              <span className="text-xs ml-2" style={{ color: "var(--text-muted)" }}>
                v{currentIndex + 1} of {versions.length}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Prompt editor */}
      <textarea
        value={editPrompt}
        onChange={(e) => setEditPrompt(e.target.value)}
        rows={3}
        className="w-full rounded-lg px-3 py-2 text-xs outline-none resize-none"
        style={{
          background: "var(--bg-card-hover)",
          border: "1px solid var(--border)",
          color: "var(--text-primary)",
        }}
      />

      {/* Actions */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => onGenerate(editPrompt)}
          disabled={isGenerating || !editPrompt.trim()}
          className="px-4 py-2 rounded-lg text-xs font-medium disabled:opacity-40"
          style={{
            background: "var(--bg-card-hover)",
            color: "var(--text-primary)",
            border: "1px solid var(--border)",
          }}
        >
          {isGenerating ? "Generating..." : `Generate $${costPerGen.toFixed(3)}`}
        </button>

        {totalSpent > 0 && (
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {versions.filter((v) => v.imageUrl).length} versions · ${totalSpent.toFixed(3)}
          </span>
        )}
      </div>

      {/* Lock button */}
      {currentVersion?.imageUrl && (
        <button
          onClick={() => onLock(currentVersion)}
          className="w-full py-2.5 rounded-lg text-sm font-semibold flex items-center justify-center gap-2"
          style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
        >
          <Lock size={14} />
          Lock This Version
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/autopilot/thumbnail-workshop.tsx
git commit -m "feat(storyengine): Add ThumbnailWorkshop with prompt iteration carousel"
```

---

## Task 7: Card Expanded Component (Back)

**Files:**
- Create: `storyengine/frontend/src/components/autopilot/card-expanded.tsx`

- [ ] **Step 1: Create the expanded card view**

```tsx
"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import { X } from "lucide-react";
import { ThumbnailWorkshop, ThumbnailVersion } from "./thumbnail-workshop";
import { formatNumber } from "@/lib/utils";
import type { CompetitorCandidate } from "@/lib/api";

interface CardExpandedProps {
  candidate: CompetitorCandidate;
  onClose: () => void;
  onProduce: (candidate: CompetitorCandidate, thumbnailVersion: ThumbnailVersion | null) => void;
}

export function CardExpanded({ candidate, onClose, onProduce }: CardExpandedProps) {
  const [versions, setVersions] = useState<ThumbnailVersion[]>([]);
  const [lockedVersion, setLockedVersion] = useState<ThumbnailVersion | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);

  const videoId = candidate.url?.match(/(?:v=|youtu\.be\/)([a-zA-Z0-9_-]{11})/)?.[1];
  const theirThumbnail = videoId
    ? `https://img.youtube.com/vi/${videoId}/hqdefault.jpg`
    : null;

  // Initial thumbnail prompt based on competitor
  const initialPrompt = `Bold editorial illustration, dramatic lighting. Topic: "${candidate.title}". High contrast, large text overlay, attention-grabbing composition. 16:9 aspect ratio.`;

  const handleGenerate = async (prompt: string) => {
    setIsGenerating(true);
    // For now, add version with no image (backend thumbnail generation not wired yet)
    // When wired: call POST /api/thumbnails/generate with prompt
    const newVersion: ThumbnailVersion = {
      prompt,
      imageUrl: null, // Will be populated when backend thumbnail endpoint exists
    };
    setVersions((prev) => [...prev, newVersion]);
    setIsGenerating(false);
  };

  const handleLock = (version: ThumbnailVersion) => {
    setLockedVersion(version);
  };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(0,0,0,0.8)" }}
      onClick={onClose}
    >
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        exit={{ scale: 0.9, opacity: 0 }}
        className="rounded-xl overflow-hidden w-full max-w-3xl max-h-[90vh] overflow-y-auto"
        style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between p-4"
          style={{ borderBottom: "1px solid var(--border)" }}
        >
          <h2 className="text-sm font-semibold" style={{ color: "var(--text-primary)" }}>
            Model Competitor Video
          </h2>
          <button onClick={onClose} style={{ color: "var(--text-muted)" }}>
            <X size={20} />
          </button>
        </div>

        {/* Side by side */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-0">
          {/* THEIRS */}
          <div className="p-4" style={{ borderRight: "1px solid var(--border)" }}>
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--text-muted)" }}
            >
              Theirs
            </h3>
            {theirThumbnail && (
              <img
                src={theirThumbnail}
                alt={candidate.title}
                className="w-full rounded-lg aspect-video object-cover mb-3"
              />
            )}
            <p className="text-sm font-medium mb-3" style={{ color: "var(--text-primary)" }}>
              {candidate.title}
            </p>
            <div className="space-y-1 text-xs" style={{ color: "var(--text-secondary)" }}>
              <p>VPH: <span className="font-bold" style={{ color: "var(--amber)" }}>{formatNumber(candidate.vph)}</span></p>
              <p>Channel: {candidate.source}</p>
              <p>Age: {Math.round(candidate.hours_old)}h</p>
              <p>Confidence: {candidate.confidence.toFixed(0)}/100</p>
            </div>
          </div>

          {/* YOURS */}
          <div className="p-4">
            <h3
              className="text-xs font-semibold uppercase tracking-wider mb-3"
              style={{ color: "var(--amber)" }}
            >
              Yours
            </h3>
            {lockedVersion?.imageUrl ? (
              <img
                src={lockedVersion.imageUrl}
                alt="Your version"
                className="w-full rounded-lg aspect-video object-cover mb-3"
              />
            ) : (
              <div
                className="w-full rounded-lg aspect-video flex items-center justify-center mb-3"
                style={{ background: "var(--bg-card-hover)", border: "2px dashed var(--border)" }}
              >
                <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                  Generate below
                </span>
              </div>
            )}
            <p className="text-sm mb-2" style={{ color: "var(--text-secondary)" }}>
              Your version will use data-driven patterns to outperform.
            </p>
            {candidate.confidence_breakdown && (
              <div className="space-y-1 text-xs" style={{ color: "var(--text-muted)" }}>
                <p>{candidate.confidence_breakdown.vph_reasoning}</p>
                <p>{candidate.confidence_breakdown.freshness_reasoning}</p>
              </div>
            )}
          </div>
        </div>

        {/* Thumbnail Workshop */}
        <div className="p-4" style={{ borderTop: "1px solid var(--border)" }}>
          <ThumbnailWorkshop
            initialPrompt={initialPrompt}
            versions={versions}
            onGenerate={handleGenerate}
            onLock={handleLock}
            isGenerating={isGenerating}
          />
        </div>

        {/* Footer actions */}
        <div
          className="flex gap-3 p-4"
          style={{ borderTop: "1px solid var(--border)" }}
        >
          <button
            onClick={onClose}
            className="px-4 py-2.5 rounded-lg text-sm font-medium"
            style={{ color: "var(--text-secondary)", border: "1px solid var(--border)" }}
          >
            Cancel
          </button>
          <button
            onClick={() => onProduce(candidate, lockedVersion)}
            className="flex-1 py-2.5 rounded-lg text-sm font-semibold"
            style={{ background: "var(--amber)", color: "var(--bg-primary)" }}
          >
            {lockedVersion ? "Lock & Produce →" : "Produce →"}
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add storyengine/frontend/src/components/autopilot/card-expanded.tsx
git commit -m "feat(storyengine): Add CardExpanded — side-by-side comparison + thumbnail workshop"
```

---

## Task 8: Rebuild Autopilot Page

**Files:**
- Modify: `storyengine/frontend/src/app/autopilot/page.tsx`

- [ ] **Step 1: Replace candidates section with playing cards + add niche setup**

Read the current autopilot page. Make these changes:

1. Add imports at top:
```tsx
import { useQuery } from "@tanstack/react-query";
import { getNicheConfig } from "@/lib/api";
import { NicheSetup } from "@/components/autopilot/niche-setup";
import { PlayingCard } from "@/components/autopilot/playing-card";
import { CardExpanded } from "@/components/autopilot/card-expanded";
import { AnimatePresence } from "framer-motion";
```

2. Add state and queries inside the component:
```tsx
const [selectedCandidate, setSelectedCandidate] = useState<CompetitorCandidate | null>(null);
const [nicheConfigured, setNicheConfigured] = useState(true); // assume configured until proven otherwise

const { data: nicheConfig } = useQuery({
  queryKey: ["niche-config"],
  queryFn: getNicheConfig,
});

// After nicheConfig loads, check if setup is needed
useEffect(() => {
  if (nicheConfig && !nicheConfig.niche_category) {
    setNicheConfigured(false);
  } else if (nicheConfig) {
    setNicheConfigured(true);
  }
}, [nicheConfig]);
```

3. At the top of the JSX return, before the header, add niche setup check:
```tsx
if (!nicheConfigured) {
  return <NicheSetup onComplete={() => setNicheConfigured(true)} />;
}
```

4. Replace the existing "Top Candidates" section (the list with expandable confidence breakdown) with a playing card grid:
```tsx
{/* Topic Discovery — Playing Cards */}
{data?.candidates && data.candidates.length > 0 && (
  <div>
    <h2 className="text-sm font-semibold uppercase tracking-wider mb-4"
        style={{ color: "var(--text-muted)" }}>
      Topic Discovery
      {nicheConfig?.sub_niche && (
        <span style={{ color: "var(--text-secondary)" }}> · {nicheConfig.sub_niche}</span>
      )}
    </h2>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {data.candidates.map((candidate) => (
        <PlayingCard
          key={candidate.id}
          candidate={candidate}
          onModel={setSelectedCandidate}
        />
      ))}
    </div>
  </div>
)}

{/* Expanded card modal */}
<AnimatePresence>
  {selectedCandidate && (
    <CardExpanded
      candidate={selectedCandidate}
      onClose={() => setSelectedCandidate(null)}
      onProduce={async (candidate, thumbnailVersion) => {
        try {
          await launchCandidate(candidate.id);
          setSelectedCandidate(null);
          // Refresh data
          const summary = await getAutopilotSummary();
          setData(summary);
        } catch (err) {
          console.error("Failed to launch:", err);
        }
      }}
    />
  )}
</AnimatePresence>
```

5. Remove the old candidates section code (the expandable list with confidence breakdown bars). Keep everything else: status card, script quality, learnings, cadence, thresholds.

6. Add a niche settings collapsible at the bottom (after thresholds):
```tsx
{/* Niche Settings */}
{nicheConfig && nicheConfig.niche_category && (
  <div className="rounded-xl p-4" style={{ background: "var(--bg-card)", border: "1px solid var(--border)" }}>
    <h2 className="text-sm font-semibold uppercase tracking-wider mb-3" style={{ color: "var(--text-muted)" }}>
      Niche Settings
    </h2>
    <div className="space-y-1 text-sm" style={{ color: "var(--text-secondary)" }}>
      <p>Category: <span style={{ color: "var(--text-primary)" }}>{nicheConfig.niche_category}</span></p>
      <p>Sub-niche: <span style={{ color: "var(--text-primary)" }}>{nicheConfig.sub_niche}</span></p>
    </div>
  </div>
)}
```

- [ ] **Step 2: Verify the page renders**

```bash
cd storyengine/frontend && npm run dev
```

Check `/autopilot` — should show playing cards in a grid instead of the old list. Clicking a card opens the expanded modal.

- [ ] **Step 3: Commit**

```bash
git add storyengine/frontend/src/app/autopilot/page.tsx
git commit -m "feat(storyengine): Rebuild autopilot with playing cards + niche setup + expanded modal"
```

---

## Task 9: Typecheck + Build + Push

- [ ] **Step 1: Typecheck**

```bash
cd storyengine/frontend && npx tsc --noEmit
```

- [ ] **Step 2: Build**

```bash
npm run build
```

- [ ] **Step 3: Push**

```bash
cd /Users/ryanayler/economy-fastforward
git push origin main
```

- [ ] **Step 4: User runs migration 006 on Supabase**

Paste in Supabase SQL Editor:
```sql
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS niche_category TEXT;
ALTER TABLE autopilot_config ADD COLUMN IF NOT EXISTS sub_niche TEXT;
```

---

## Completion Criteria

- [ ] Niche setup wizard shows when no niche configured (3 steps: category, sub-niche, channels)
- [ ] Playing cards display competitor videos with thumbnails, VPH, freshness, confidence
- [ ] "Model This" expands card to side-by-side comparison modal
- [ ] Thumbnail workshop has prompt editor + iteration carousel with version dots
- [ ] "Lock & Produce" sends video into pipeline
- [ ] Niche settings section shows current config
- [ ] Backend niche routes work (setup, channels CRUD)
- [ ] TypeScript compiles, Next.js builds
- [ ] Pushed to GitHub for auto-deploy

**Total: 9 tasks, 6 new files, 4 modified files**
