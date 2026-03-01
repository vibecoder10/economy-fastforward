# Airtable Schema

## Idea Concepts Table (Source of Truth for NEW ideas)

Core fields (always written):
- `Status`, `Video Title`, `Hook Script`, `Past Context`, `Present Parallel`, `Future Prediction`
- `Thumbnail Prompt`, `Writer Guidance`, `Original DNA` (JSON backup), `Source`

Rich fields (written by research):
- `Framework Angle`, `Headline`, `Timeliness Score`, `Audience Fit Score`, `Content Gap Score`
- `Source URLs`, `Executive Hook`, `Thesis`, `Date Surfaced`
- `Research Payload` (JSON), `Thematic Framework`

Optional fields:
- `Reference URL`, `Idea Reasoning`, `Source Views`, `Source Channel`
- `Google Drive Folder ID`, `Thumbnail`, `Pipeline Mode`, `Notes`
- `Upload Status`, `YouTube Video ID`, `YouTube URL`

Performance fields (written by `performance_tracker.py`, daily cron):
- Lifetime: `Views`, `Likes`, `Comments`, `Subscribers Gained`
- Analytics (YouTube Analytics API): `Avg View Duration (s)`, `Avg Retention (%)`, `Watch Time (hours)`
- Reporting (YouTube Reporting API bulk CSV): `Impressions`, `CTR (%)`
- Snapshots (written once): `Views 24h`, `Views 48h`, `Views 7d`, `Views 30d`, `CTR 48h (%)`, `Retention 48h (%)`
- Metadata: `Last Analytics Sync`, `Upload Date`

## Scripts Table

- `Scene`, `Scene text`, `Title`, `Voice ID`
- `Script Status`: "Create" → "Finished"
- `Voice Status`, `Voice Over` (attachment URL)
- `Sources` (show notes for YouTube description)

## Images Table

- `Scene`, `Image Index`, `Sentence Text`, `Image Prompt`, `Shot Type`
- `Video Title`, `Aspect Ratio`, `Status`: "Pending" → "Done"
- `Image` (attachment), `Video`, `Video Prompt`
- Animation: `Hero Shot`, `Video Clip URL`, `Animation Status`, `Video Duration`

## Known Schema Issues (See ANIMATION_SYSTEM_REVIEW.md Feature 4)

- **CRITICAL**: Tables joined by string matching (`Title` = `Video Title`), NOT linked records. Typos break relationships.
- Images table has 3 overlapping status fields (`Status`, `Video Status`, `Animation Status`). Update ALL relevant ones.
- `Sentence Index` and `Image Index` are the same value with different names.
- Thumbnail field format is inconsistent - code tries 3 field name/format combos as fallbacks.

## Airtable Error Recovery Pattern (Used Everywhere)

The codebase uses graceful field degradation when writing to Airtable:
```
Try: Create with all fields
Catch UnknownField → extract bad field from error → retry without it (loop)
Finally: If still failing → create with core fields only → update rich fields individually
```
**Follow this pattern** when adding new Airtable writes. Never let a single bad field kill the whole record creation.
