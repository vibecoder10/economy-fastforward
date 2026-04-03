# PRD: Storyboard Extraction Pipeline (V2 — Fix the Foundation)

**Priority:** HIGH — blocks video clip generation for all storyboard-mode videos
**Video for testing:** "Why America Can't Stop $50,000 Drones"

---

## Root Problem

Storyboard extraction doesn't work because:

1. **Grid URLs expire.** Kie.ai tempfile URLs (`tempfile.aiquickdraw.com`) return 403 after hours. Storyboard grid URLs in Supabase `scripts.storyboard_1_url` etc. are all expired. Same problem affects `assets.image_url`.

2. **Extraction code is Airtable-only.** `storyboard/bot.py:run_storyboard_extract()` reads from Airtable Scripts table. StoryEngine uses Supabase. The endpoint returns 200 but does nothing.

3. **No image persistence.** Generated images are stored as temp URLs, not permanent storage (Google Drive or Supabase Storage). When URLs expire, images are lost.

---

## Fix 1: Permanent Image Storage (do this FIRST — blocks everything else)

**Problem:** Every generated image URL expires within hours. This breaks:
- Storyboard grid display (grids load from cache only)
- Image display in asset cards
- Extraction (can't download expired URLs)
- Video clip generation (needs source images)
- Rendering (needs final images)

**Solution:** When any image is generated (storyboard grid, scene image, thumbnail), immediately upload to Supabase Storage and store the permanent URL.

**Implementation:**
1. Create a Supabase Storage bucket: `storyengine-assets` (public read)
2. After Kie.ai returns a tempfile URL, download the image bytes
3. Upload to Supabase Storage: `{video_id}/grids/scene-{N}-beat-{M}.png` for grids, `{video_id}/images/S-{scene}-{index}.png` for assets
4. Store the Supabase Storage URL (permanent) in the database, not the tempfile URL
5. For existing videos: add a "Re-download & persist" utility that re-generates expired images

**Files:**
- `storyengine/backend/storage.py` — NEW: Supabase Storage upload helper
- `storyengine/backend/pipeline_executor.py` — After each image generation step, persist to storage
- `skills/video-pipeline/shared/clients/image_client.py` — Add post-generation upload step

**Acceptance:**
- [ ] New images get permanent Supabase Storage URLs
- [ ] URLs survive indefinitely (not tempfile)
- [ ] Grid images accessible 24h+ after generation

---

## Fix 2: Supabase-Native Extraction Endpoint

**Problem:** `POST /api/pipeline/storyboard-extract/{video_id}` delegates to `storyboard/bot.py` which reads from Airtable. For Supabase videos, it silently does nothing.

**Solution:** Build a new extraction function that reads grids from Supabase, crops panels, and writes back to Supabase.

**Implementation:**

```python
# storyengine/backend/routes/pipeline.py — new or modified endpoint

async def extract_storyboard_panels(video_id: str, tenant_id: str):
    """Extract individual panels from storyboard grids."""
    
    # 1. Read grid URLs from scripts table
    scripts = await db.fetch(
        "SELECT scene, storyboard_1_url, storyboard_2_url, storyboard_3_url, "
        "storyboard_beat_count FROM scripts WHERE video_id = $1 ORDER BY scene",
        video_id
    )
    
    # 2. For each grid:
    for script in scripts:
        for beat_num in [1, 2, 3]:
            grid_url = script[f"storyboard_{beat_num}_url"]
            if not grid_url:
                continue
            
            # Download grid image
            img = download_image(grid_url)  # PIL Image
            
            # Determine grid layout from image dimensions
            # 3x3 = 9 panels, 2x3 = 6 panels, 1x3 = 3 panels
            cols, rows = detect_grid_layout(img)
            
            # Crop each panel
            panel_w = img.width // cols
            panel_h = img.height // rows
            
            panel_index = 0
            for row in range(rows):
                for col in range(cols):
                    x = col * panel_w
                    y = row * panel_h
                    panel = img.crop((x, y, x + panel_w, y + panel_h))
                    
                    # Upload to permanent storage
                    panel_url = await upload_to_storage(
                        video_id, f"extracted/S-{scene}-B{beat_num}-P{panel_index}.png", panel
                    )
                    
                    # Map to correct asset by scene + image_index
                    asset_index = calculate_asset_index(beat_num, panel_index, cols)
                    
                    # Update asset with extracted image
                    await db.execute(
                        "UPDATE assets SET image_url = $1 WHERE video_id = $2 "
                        "AND scene = $3 AND image_index = $4",
                        panel_url, video_id, scene, asset_index
                    )
                    panel_index += 1
    
    # 3. Advance video status
    await db.execute(
        "UPDATE videos SET status = 'ready_for_video_scripts' WHERE id = $1",
        video_id
    )
```

**Grid layout detection:**
- 3x3 grid: aspect ratio ~1:1 (1024x1024 or similar)
- 3x2 grid: aspect ratio ~3:2
- Use image dimensions to determine cols x rows
- Standard Kie.ai grids are 1024x1024 (3x3 = 9 panels of ~341x341 each)

**Panel-to-asset mapping:**
- Beat 1 panels map to the first N assets for that scene
- Beat 2 panels map to the next N assets
- Reading order: left-to-right, top-to-bottom within each grid

**Files:**
- `storyengine/backend/routes/pipeline.py` — Rewrite the `storyboard-extract` endpoint
- `storyengine/backend/extraction.py` — NEW: Grid download, crop, upload logic
- Dependencies: `Pillow` (PIL) — already in requirements

**Acceptance:**
- [ ] Clicking "Extract & Upscale Panels" crops grids into individual panels
- [ ] Each panel is stored with a permanent URL
- [ ] Assets table updated with extracted panel URLs (replacing old temp URLs)
- [ ] Filmstrip on frontend shows extracted panels (not old generated images)
- [ ] Panel order matches storyboard reading order (left→right, top→bottom)

---

## Fix 3: Clear Old Generated Images Before Extraction

**Problem:** Assets already have `image_url` from regular image generation. Extraction should replace these with storyboard-extracted panels.

**Solution:** Before writing extracted panels, clear existing `image_url` on all assets for this video:

```sql
UPDATE assets SET image_url = NULL WHERE video_id = $1;
```

Then write the extracted panel URLs.

**Acceptance:**
- [ ] After extraction, filmstrip shows ONLY extracted storyboard panels
- [ ] Old generated images are cleared
- [ ] Asset count matches number of extracted panels

---

## Fix 4: Re-generate Expired Grids (for the test video)

**Problem:** The Drones test video has expired grid URLs. We can't extract from 403 URLs.

**Options:**
A. Re-generate storyboard grids (costs ~$0.50, takes 2 min)
B. Check if grids are cached in Google Drive (the pipeline may have uploaded them)

**Implementation:**
1. Check Google Drive for existing grids: `"Why America Can't Stop $50,000 Drones"` folder
2. If found: update `scripts.storyboard_N_url` with Drive URLs
3. If not found: re-run storyboard grid generation for this video (`POST /api/pipeline/storyboard-images/{video_id}`)
4. After regeneration: URLs will be fresh tempfile URLs — run extraction IMMEDIATELY before they expire
5. Long-term: Fix 1 (permanent storage) prevents this from happening again

---

## Task Breakdown

| # | Task | Role | Depends | Priority |
|---|------|------|---------|----------|
| T1 | Create Supabase Storage bucket + upload helper | backend | — | P0 |
| T2 | Build grid cropping + panel extraction logic (PIL) | backend | — | P0 |
| T3 | Rewrite storyboard-extract endpoint for Supabase | backend | T1, T2 | P0 |
| T4 | Clear old asset images before extraction | backend | T3 | P0 |
| T5 | Re-generate or recover grids for test video | backend | — | P0 |
| T6 | Run extraction on test video end-to-end | qa | T3, T5 | P0 |
| T7 | Verify filmstrip shows extracted panels only | qa | T6 | P0 |
| T8 | Add permanent storage to image generation pipeline | backend | T1 | P1 |
| T9 | Add permanent storage to storyboard grid generation | backend | T1 | P1 |

**P0 = must do now (extraction pipeline)**
**P1 = must do before launch (prevents URL expiry across all images)**

---

## Definition of Done

After all P0 tasks:
1. Click "Extract & Upscale Panels" on the Drones video
2. Grids are downloaded and cropped into individual panels
3. Panels stored with permanent URLs
4. Old generated images cleared
5. Filmstrip shows extracted storyboard panels in correct order
6. Video Clips tab shows extracted panels in clip cards
