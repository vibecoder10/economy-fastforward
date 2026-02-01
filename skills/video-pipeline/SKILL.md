---
name: Video Production Pipeline
description: End-to-end video production from YouTube URL to Remotion-ready assets
---

# Video Production Pipeline Skill

This skill runs the complete **Economy Fast-Forward** video production pipeline, taking a YouTube URL and generating all assets needed for video creation.

## What This Skill Does

When invoked, this skill executes a 6-step pipeline:

1. **Idea Bot** - Analyzes the source YouTube video and generates 3 video concept ideas
2. **Script Bot** - Writes a 20-scene documentary script (180-200 words per scene)
3. **Voice Bot** - Generates voice-over audio for each scene using ElevenLabs
4. **Image Prompt Bot** - Creates 6 cinematic image prompts per scene
5. **Image Bot** - Generates images from the prompts using Kie.ai
6. **Export** - Packages all assets into a Remotion-compatible format

## Prerequisites

### Environment Setup

Create a `.env` file in the `Economy Fastforward` folder with these credentials:

```bash
# Copy from .env.example and fill in your values
ANTHROPIC_API_KEY=sk-ant-xxxxx
AIRTABLE_API_KEY=patxxxxx
AIRTABLE_BASE_ID=appCIcC58YSTwK3CE
GOOGLE_CLIENT_ID=xxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxxx
GOOGLE_REFRESH_TOKEN=xxxxx
GOOGLE_DRIVE_FOLDER_ID=1zqsSvdyLWTRIt-Ri8VQELbYHhJihn6YD
SLACK_BOT_TOKEN=xoxb-xxxxx
SLACK_CHANNEL_ID=C0A9U1X8NSW
ELEVENLABS_API_KEY=xxxxx
ELEVENLABS_VOICE_ID=G17SuINrv2H9FC6nvetn
KIE_AI_API_KEY=xxxxx
```

### Install Dependencies

```bash
cd /Users/ryanayler/Desktop/Economy\ Fastforward/skills/video-pipeline
pip install -r requirements.txt
```

## How to Use This Skill

### Option 1: Run Full Pipeline

```bash
python pipeline.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

This runs the complete pipeline and generates all assets.

### Option 2: Run Individual Steps

You can also run individual bots if you need to re-run a specific step:

```python
from pipeline import VideoPipeline
import asyncio

pipeline = VideoPipeline()

# Run just the script bot (requires an idea in Airtable)
asyncio.run(pipeline.run_script_bot())

# Run just the voice bot (requires scripts in Airtable)
asyncio.run(pipeline.run_voice_bot())

# Run just the image prompt bot
asyncio.run(pipeline.run_image_prompt_bot())

# Run just the image bot
asyncio.run(pipeline.run_image_bot())
```

## Slack Integration

The pipeline sends notifications to the `production-agent` Slack channel at each step:

- 🚀 Pipeline started
- 💡 Ideas generated (with 3 options)
- 📝 Script writing started/complete
- 🗣️ Voice generation started/complete
- 🌉 Image prompts started/complete
- 🖼️ Image generation started/complete
- 🎉 Pipeline complete with Google Drive link

## Output Structure

After the pipeline completes, you'll have:

### Google Drive Folder
```
Economy Fastforward/
└── [Video Title]/
    ├── [Video Title] (Google Doc with full script)
    ├── Scene 1.mp3
    ├── Scene 2.mp3
    ├── ...
    ├── Scene 20.mp3
    ├── 000_Image.png
    ├── 001_Image.png
    ├── ...
    └── 119_Image.png (6 images × 20 scenes)
```

### Airtable Records
- **Ideas table**: Video concept with all narrative DNA
- **Script table**: 20 records (one per scene) with text and voice URLs
- **Images table**: 120 records (6 per scene) with prompts and image URLs

### Remotion Props
The pipeline returns a `remotion_package` dict that can be passed directly to Remotion:

```json
{
  "videoTitle": "Why AI's \"Fake Bubble\" Will Make You RICH",
  "folderId": "1abc...",
  "docId": "12xyz...",
  "scenes": [
    {
      "sceneNumber": 1,
      "text": "Everyone's screaming AI bubble...",
      "voiceUrl": "https://...",
      "images": [
        {"index": 1, "url": "https://..."},
        {"index": 2, "url": "https://..."},
        ...
      ]
    },
    ...
  ]
}
```

## Architecture & Workflow

The pipeline is now **Status-Driven** and **Resume-Capable**:

### 1. Status-Driven Data Flow
The pipeline strictly follows the status of the **Ideas** table in Airtable to decide what to do next. It processes one video at a time based on this lifecycle:

| Status | Bot Triggered | Action | Updates Status To |
|--------|---------------|--------|-------------------|
| `Idea Logged` | *(Manual)* | Idea waiting for approval | `Ready For Scripting` |
| `Ready For Scripting` | **Script Bot** | Writes 20-scene script | `Ready For Voice` |
| `Ready For Voice` | **Voice Bot** | Generates voice overs | `Ready For Visuals` |
| `Ready For Visuals` | **Visuals Pipeline** | 1. Generates Prompts<br>2. Generates Images | `Ready For Thumbnail` |
| `Ready For Thumbnail` | **Thumbnail Bot** | Creates thumbnail | `Done` |
| `Done` | *(None)* | Completed video | - |

### 2. Resume & Smart Skipping
The pipeline is designed to save cost and time by checking for existing work before running:
- **Scripts:** Checks if scenes in Airtable are marked "Finished". Skips generation if found.
- **Voice:** Checks if voice-over URL exists. Skips if found.
- **Images:** Checks if prompts or images exist for each scene. Skips if found.

This means you can stop the pipeline at any time and restart it later using `python pipeline.py`, and it will pick up exactly where it left off without duplicating work.

### 3. Client Modules
The system is modularized into specialized clients in the `clients/` directory:
- `anthropic_client.py`: Claude AI logic (Scripts, Prompts)
- `airtable_client.py`: Database management (Status, Records)
- `elevenlabs_client.py`: Voice generation
- `image_client.py`: Image generation (Kie.ai)
- `google_client.py`: Drive & Docs integration
- `slack_client.py`: Notifications

## Troubleshooting

### API Rate Limits
If you hit rate limits, the pipeline will notify you via Slack. You can re-run the specific step that failed.

### Missing Credentials
Check that all environment variables are set correctly in `.env`

### Airtable Sync Issues
Make sure the Airtable table IDs match your base. The defaults are:
- Ideas: `tblrAsJglokZSkC8m`
- Script: `tbluGSepeZNgb0NxG`
- Images: `tbl3luJ0zsWu0MYYz`

## Source Workflows

This skill was ported from the following n8n workflows:
- `Idea Bot.json` - Video analysis and idea generation
- `Script Bot.json` - Beat sheet and scene writing
- `Voice Bot.json` - ElevenLabs voice synthesis
- `Image Prompt Bot.json` - Claude-powered prompt generation
- `Image Bot.json` - Kie.ai image generation
- `Router Bot.json` - Slack command routing (now handled by Antigravity)
