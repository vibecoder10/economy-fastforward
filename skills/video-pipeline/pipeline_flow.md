# Unified Pipeline Flow

## Complete Pipeline: Entry → Render

```
[All Entry Points]
    │
    ├── --idea "URL/concept"     → IdeaBot        → source: url_analysis
    ├── --trending               → TrendingIdeaBot → source: trending
    ├── --more-ideas             → IdeaModeling    → source: format_library
    └── --research "topic"       → ResearchAgent   → source: research_agent
    │
    ▼
┌─────────────────────────────┐
│  Idea Concepts Tab          │  ← Single source of truth for ALL ideas
│  Status: "Idea Logged"      │
│  Fields: title, hook,       │
│    source, research_payload  │
└──────────┬──────────────────┘
           │  (Ryan approves manually in Airtable)
           ▼
┌─────────────────────────────┐
│  Status: "Ready For Scripting" │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Brief Translator           │
│  1. Validate production     │
│     readiness               │
│  2. Supplemental research   │
│     (if gaps found)         │
│  3. Generate 6-act script   │
│     (~3750 words)           │
│  4. Expand to 20-30 scenes  │
│     (nested within acts)    │
│  5. Save scene JSON         │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Status: "Ready For Voice"  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Voice Bot                  │
│  - ElevenLabs TTS per scene │
│  - Upload to Google Drive   │
│  - Update Script table      │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Status: "Ready For Image   │
│  Prompts"                   │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Styled Image Prompts       │
│  (Visual Identity System)   │
│  - Read scene JSON          │
│  - Expand to ~150+ images   │
│    (~1 per 9s of narration) │
│  - Apply Dossier/Schema/    │
│    Echo styles              │
│  - Enforce sequencing rules │
│  - Write to Images table    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Status: "Ready For Images" │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Image Bot                  │
│  - Kie.ai / NanoBanana      │
│  - Generate from prompts    │
│  - Save URLs to Airtable    │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Status: "Ready To Render"  │
└──────────┬──────────────────┘
           │
           ▼
┌─────────────────────────────┐
│  Remotion Render             │
│  - Export props JSON         │
│  - Render video              │
│  - Upload to Google Drive    │
└─────────────────────────────┘
```

## Status Transitions

| Status | Module | Action | Next Status |
|--------|--------|--------|-------------|
| Idea Logged | *(Manual)* | Ryan reviews and approves | Ready For Scripting |
| Ready For Scripting | Brief Translator | Validate → Script → Scenes | Ready For Voice |
| Ready For Voice | Voice Bot | TTS generation per scene | Ready For Image Prompts |
| Ready For Image Prompts | Styled Image Prompts | Visual Identity prompts | Ready For Images |
| Ready For Images | Image Bot | AI image generation | Ready For Thumbnail |
| Ready For Thumbnail | Thumbnail Bot | Generate thumbnail | Ready To Render |
| Ready To Render | Remotion | Video composition | Done |

## Module Locations

| Module | File | Type |
|--------|------|------|
| IdeaBot | `bots/idea_bot.py` | Python |
| TrendingIdeaBot | `bots/trending_idea_bot.py` | Python |
| IdeaModeling | `bots/idea_modeling.py` | Python |
| ResearchAgent | `research_agent.py` | Python (standalone) |
| BriefTranslator | `brief_translator/` | Python |
| Voice Bot | `pipeline.py::run_voice_bot` | Python + ElevenLabs |
| Styled Image Prompts | `image_prompt_engine/` + `pipeline.py` | Python |
| Image Bot | `pipeline.py::run_image_bot` | Python + Kie.ai |
| Remotion Render | `remotion-video/` | TypeScript |

## Airtable Tables

| Table | Purpose | Active? |
|-------|---------|---------|
| **Idea Concepts** | All new ideas (unified entry) | Yes — primary |
| Ideas (legacy) | Archive of pre-unification ideas | Read-only archive |
| Script | Scene-level script records with voice | Yes |
| Images | Image prompts and generated images | Yes |

## Entry Points

```bash
# Generate ideas from URL or concept
python pipeline.py --idea "https://youtu.be/VIDEO_ID"
python pipeline.py --idea "Why AI could crash the economy"

# Generate ideas from trending videos
python pipeline.py --trending

# Generate ideas from format library
python pipeline.py --more-ideas

# Deep research on a topic
python pipeline.py --research "The Federal Reserve's hidden strategy"

# Translate a brief to script + scenes
python pipeline.py --translate

# Generate styled image prompts
python pipeline.py --styled-prompts

# Run next available step automatically
python pipeline.py

# Full pipeline for a queued idea
python pipeline.py --produce
```
