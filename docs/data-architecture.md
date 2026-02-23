# Data Architecture

## Video DNA (Core Data Structure)

Every idea carries metadata DNA that flows through the entire pipeline:
```python
{
    "source_type": "youtube_url" | "concept" | "trending",
    "original_dna": str,          # JSON snapshot of source data
    "reference_url": str,          # Source URL
    "viral_title": str,
    "hook_script": str,            # First 15 seconds
    "narrative_logic": {
        "past_context": str,       # Historical setup
        "present_parallel": str,   # Current situation
        "future_prediction": str   # What happens next
    },
    "thumbnail_visual": str,
    "writer_guidance": str         # Tone and approach notes
}
```
**All content uses Past → Present → Future framing.** This is the Economy FastForward brand voice. Don't break this structure.

## Research Payload (14-Field JSON)

Output by `research_agent.py`, stored in `Research Payload` field, consumed by brief_translator:
```python
{
    "headline": str,              # Compelling video title
    "thesis": str,                # Core argument (2-3 sentences)
    "executive_hook": str,        # 15-second opening hook
    "fact_sheet": str,            # 10+ specific facts with numbers/dates
    "historical_parallels": str,  # 3+ events with dates, figures, outcomes
    "framework_analysis": str,    # Analytical lens (Machiavellian, systems thinking, etc.)
    "character_dossier": str,     # 3+ key figures (name, role, actions, visuals)
    "narrative_arc": str,         # What happened → Why matters → What's next
    "counter_arguments": str,     # Strongest opposing arguments + rebuttals
    "visual_seeds": str,          # 5+ visual concepts for image generation
    "source_bibliography": str,   # Key sources and reports
    "themes": str,                # 3+ intellectual frameworks
    "psychological_angles": str,  # Viewer hooks (fears, aspirations, curiosities)
    "narrative_arc_suggestion": str  # 6-act structure with emotional arcs
}
```

## Brief Translator Validation

Before scripting, the brief translator validates research across 8 criteria:
- Hook strength, Fact density, Framework depth, Historical parallel richness
- Character visualizability, Implication specificity, Visual variety, Structural completeness
- Tolerance: Up to 1 FAIL + 4 WEAK still passes (if research_enriched=true)
- Runs targeted gap-filling via `supplementer.py` if validation fails

## Scene JSON Structure

Output by brief_translator, defines every scene for downstream consumption:
```python
{
    "total_acts": 6, "total_scenes": 25,
    "acts": [{
        "act_number": 1, "act_title": "The Hook",
        "time_range": "0:00-1:30", "word_target": 225,
        "scenes": [{
            "scene_number": 1, "narration_text": "...",
            "duration_seconds": 36,
            "visual_style": "dossier|schema|echo",
            "composition": "wide|medium|closeup|...",
            "ken_burns": "slow zoom in|out|pan left|right|...",
            "mood": "tension|revelation|urgency"
        }]
    }]
}
```
Duration calculation: `word_count / 2.5 wps = seconds`. Images per scene: `ceil(duration / 9)`.

## Trending Idea Format Library

The v2 idea engine decomposes viral titles into typed variables:
- `number`, `authority_qualifier`, `core_topic`, `extreme_benefit`, `specific_mechanism`, `time_anchor`, `target_audience`
- 10 psychological triggers: longevity, fear, practical_value, curiosity_gap, authority, urgency, contrarian, aspiration, outrage, scale
- Format library is **persisted across runs** in a config file. New formats accumulate over time.

## Slack Notifications

Every pipeline stage sends Slack notifications. They are **non-blocking** (wrapped in try/except). Never let a Slack failure kill a pipeline run. The notification methods are:
`notify_pipeline_start()`, `notify_idea_generated()`, `notify_script_start/done()`, `notify_voice_start/done()`, `notify_image_prompts_start/done()`, `notify_images_start/done()`, `notify_thumbnail_done()`, `notify_pipeline_complete()`, `notify_youtube_draft_ready()`, `notify_error()`
