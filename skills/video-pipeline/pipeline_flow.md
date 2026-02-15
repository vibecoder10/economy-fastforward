# Unified Pipeline Flow

## Complete Pipeline: Discovery → Entry → Render

```
[Discovery Scanner] (Slack: `discover` / `scan`)
    │
    ├── Scans: geopolitics, finance, tech, economic policy headlines
    ├── Filters: Machiavellian lens (power dynamics, hidden systems)
    ├── Formats: Maps to proven title patterns (title_patterns.json)
    └── Outputs: 2-3 curated ideas to Slack for approval
          │
          ▼
    Ryan picks one via Slack emoji reaction (1️⃣ 2️⃣ 3️⃣)
          │
          ▼
    Auto-writes to Idea Concepts → Status: "Approved"
          │
          ▼
    Auto-triggers Deep Research Agent
          │
          ▼

[All Entry Points]
    │
    ├── discover / scan          → DiscoveryScanner → source: discovery_scanner
    ├── --idea "URL/concept"     → IdeaBot          → source: url_analysis
    ├── --trending               → TrendingIdeaBot   → source: trending
    ├── --more-ideas             → IdeaModeling      → source: format_library
    └── --research "topic"       → ResearchAgent     → source: research_agent
    │
    ▼
┌─────────────────────────────┐
│  Idea Concepts Tab          │  ← Single source of truth for ALL ideas
│  Status: "Idea Logged"      │
│  Fields: title, hook,       │
│    source, research_payload  │
└──────────┬──────────────────┘
           │  (Ryan approves in Airtable OR via Slack reaction)
           ▼
┌─────────────────────────────┐
│  Status: "Approved"         │  ← NEW: auto-triggers research
│  (ApprovalWatcher polls)    │
└──────────┬──────────────────┘
           │  Deep research runs automatically
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
| *(New)* | Discovery Scanner | Scan headlines, filter, generate titles | Idea Logged |
| Idea Logged | *(Manual/Slack)* | Ryan reviews and approves | Approved |
| Approved | ApprovalWatcher | Auto-trigger deep research | Ready For Scripting |
| Ready For Scripting | Brief Translator | Validate → Script → Scenes | Ready For Voice |
| Ready For Voice | Voice Bot | TTS generation per scene | Ready For Image Prompts |
| Ready For Image Prompts | Styled Image Prompts | Visual Identity prompts | Ready For Images |
| Ready For Images | Image Bot | AI image generation | Ready For Thumbnail |
| Ready For Thumbnail | Thumbnail Bot | Generate thumbnail | Ready To Render |
| Ready To Render | Remotion | Video composition | Done |

## Module Locations

| Module | File | Type |
|--------|------|------|
| DiscoveryScanner | `discovery_scanner.py` | Python (standalone) |
| ApprovalWatcher | `approval_watcher.py` | Python (standalone/daemon) |
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
# === Discovery Scanner (NEW) ===
# Scan headlines and generate 2-3 video ideas
python discovery_scanner.py
python discovery_scanner.py --focus "BRICS currency"
python discovery_scanner.py --output discoveries.json

# === Slack Commands (NEW) ===
# discover / scan          → Scan headlines, present ideas in Slack
# discover [focus]         → Scan with focus keyword
# research                 → Research next approved idea
# research "topic"         → Research a specific topic

# === Approval Watcher (NEW) ===
# Auto-trigger research when ideas are approved in Airtable
python approval_watcher.py                # Poll once
python approval_watcher.py --daemon       # Continuous polling

# === Existing Entry Points ===
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

## Discovery Scanner Flow

```
Slack: `discover` or `scan`
    │
    ├── 1. Gather headlines (Sonnet 4.5, ~$0.01-0.03)
    │      Sources: Reuters, AP, Bloomberg, FT, WSJ, IMF, Fed
    │
    ├── 2. Filter through Machiavellian lens
    │      Criteria: power dynamics, hidden systems, historical parallels
    │
    ├── 3. Generate title variants using title_patterns.json
    │      EFF-1 through EFF-9 hybrid formulas (Economy Rewind + Mindplicit)
    │
    └── 4. Post 2-3 ideas to Slack with emoji reactions
           │
           ▼
    Ryan reacts with 1️⃣ 2️⃣ or 3️⃣
           │
           ▼
    Approved idea → Airtable (status: Approved)
           │
           ▼
    Auto-triggers deep research (Sonnet 4.5, ~$0.05-0.15)
           │
           ▼
    Research payload written back → Status: Ready For Scripting
           │
           ▼
    Pipeline continues: Script → Voice → Images → Render
```
