"""
TrendingIdeaBot - Generates video ideas based on trending YouTube content.

This bot:
1. Scrapes trending videos in the finance/economy niche via Apify
2. Analyzes title patterns, keywords, and performance metrics
3. Uses Claude to model new ideas based on what's working NOW
4. Generates clickbait-worthy titles that fit the channel's style
5. Injects channel-specific learnings from Osiris performance analysis (Phase 2)
"""

from typing import Optional
import json
import os

from title_idea.idea_modeling import decompose_title, extract_format, generate_modeled_ideas
from shared.clients.narrative_extractor import extract_narrative_fields_from_concept
from orchestrator.pipeline_constants import Models, CURIOSITY_GAP_ENABLED

# Curiosity gap imports (lazy loaded to avoid circular deps)
if CURIOSITY_GAP_ENABLED:
    from title_idea.curiosity_gap.gap_title_engine import GapTitleEngine
    from autopilot.learning.pattern_library import PatternLibrary




def load_modeling_config():
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "idea_modeling_config.json")
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            return json.load(f)
    return {"format_library": [], "niche_variables": {}}


def save_modeling_config(config):
    config_path = os.path.join(os.path.dirname(__file__), "..", "config", "idea_modeling_config.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)


def update_format_library(config, new_formats):
    library = config.get("format_library", [])
    existing_formulas = {f["formula"]: i for i, f in enumerate(library)}
    for fmt in new_formats:
        formula = fmt["formula"]
        if formula in existing_formulas:
            idx = existing_formulas[formula]
            library[idx]["times_seen"] += fmt["times_seen"]
            for title in fmt["example_titles"]:
                if title not in library[idx]["example_titles"]:
                    library[idx]["example_titles"].append(title)
        else:
            library.append(fmt)
            existing_formulas[formula] = len(library) - 1
    config["format_library"] = library
    return config

class TrendingIdeaBot:
    """Generates video ideas by analyzing trending content.

    Channel: Economy Fast-Forward
    Angle: Futuristic predictions using past → present → future narrative
    Style: Dramatic, urgent, predictive documentary-style content
    """

    # Focused search queries - top performers only
    DEFAULT_SEARCH_QUERIES = [
        # Core economy topics (high performers)
        "economy collapse 2025",
        "stock market crash prediction",
        "recession warning 2025",
        # AI & Tech disruption
        "AI bubble burst",
        "AI replacing jobs 2025",
        # Macro/Geopolitics
        "dollar collapse prediction",
        "china economy collapse",
        "tariff war economic impact",
    ]

    # Competitor channels - similar futuristic/documentary style
    COMPETITOR_CHANNELS = [
        # Direct competitors (same style niche)
        "https://www.youtube.com/@EconomyRewind",
        "https://www.youtube.com/@chillfinancialhistorian",
        "https://www.youtube.com/@IndependentFinancialHistorian",
        # Broader finance/economy channels
        "https://www.youtube.com/@Heresy_Financial",
        "https://www.youtube.com/@StevenVanMetre",
        "https://www.youtube.com/@MoneyGPS",
        "https://www.youtube.com/@EconomicsExplained",
    ]

    def __init__(
        self,
        apify_client,
        anthropic_client,
        airtable_client,
        gemini_client=None,
        slack_client=None,
        use_learnings: bool = True,
    ):
        """Initialize with required clients.

        Args:
            apify_client: For scraping YouTube trending videos
            anthropic_client: For generating ideas with Claude
            airtable_client: For saving ideas to Airtable
            gemini_client: Optional, for thumbnail analysis
            slack_client: Optional, for notifications
            use_learnings: Inject Osiris learnings into prompts (default True)
        """
        self.apify = apify_client
        self.anthropic = anthropic_client
        self.airtable = airtable_client
        self.gemini = gemini_client
        self.slack = slack_client

        # Initialize Osiris learnings engine (Phase 2 performance learning)
        self._learnings_engine = None
        if use_learnings:
            try:
                from analytics.osiris.learnings_engine import LearningsEngine
                self._learnings_engine = LearningsEngine(airtable_client)
            except ImportError:
                pass  # Osiris not installed, skip learnings

        # Curiosity gap engine (lazy initialized)
        self._gap_engine = None
        self._pattern_library = None

    async def _enhance_title_with_curiosity_gap(self, idea: dict) -> dict:
        """Enhance idea with curiosity gap optimized title.

        Args:
            idea: Idea dict with viral_title, hook_script, narrative_logic

        Returns:
            Enhanced idea dict with structure metadata
        """
        if not CURIOSITY_GAP_ENABLED:
            return idea

        # Lazy initialize engine
        if self._gap_engine is None:
            self._gap_engine = GapTitleEngine(self.anthropic)
        if self._pattern_library is None:
            self._pattern_library = PatternLibrary()

        # Build story context from idea
        narrative = idea.get("narrative_logic", {})
        story_context = {
            "hook": idea.get("hook_script", ""),
            "thesis": narrative.get("present_parallel", ""),
            "facts": [],
        }

        try:
            titles = await self._gap_engine.generate_titles(
                story_context,
                pattern_library=self._pattern_library,
                target_count=1,
            )

            if titles:
                best = titles[0]
                idea["viral_title"] = best.text
                idea["curiosity_structure"] = best.structure.value
                idea["structure_confidence"] = best.structure_confidence
                idea["thumbnail_text"] = best.thumbnail_text
                idea["thumbnail_approach"] = best.thumbnail_approach
                print(f"    Enhanced: {best.text}")
                print(f"    Structure: {best.structure.value} ({best.structure_confidence}%)")

        except Exception as e:
            print(f"    Curiosity gap enhancement failed: {e}")
            # Non-blocking - keep original title

        return idea

    async def scrape_trending(
        self,
        search_queries: Optional[list[str]] = None,
        max_results_per_query: int = 5,
        upload_date: str = "month",
        top_n: int = 15,
    ) -> dict:
        """Scrape and analyze trending videos.

        Args:
            search_queries: Custom search terms, or use defaults
            max_results_per_query: Videos per search query (default 5)
            upload_date: Recency filter - "week", "month", "year"
            top_n: Only analyze top N videos by views (default 15)

        Returns:
            Analysis dict with trends, patterns, top performers
        """
        queries = search_queries or self.DEFAULT_SEARCH_QUERIES

        print(f"\n🔍 SCRAPING: {len(queries)} queries × {max_results_per_query} results = ~{len(queries) * max_results_per_query} videos")

        videos = await self.apify.search_trending_videos(
            search_queries=queries,
            max_results_per_query=max_results_per_query,
            sort_by="viewCount",  # Sort by most viewed
            upload_date=upload_date,
        )

        print(f"  Scraped {len(videos)} videos total")

        # Sort by views and keep only top N
        videos_sorted = sorted(videos, key=lambda x: x.get("views", 0), reverse=True)
        top_videos = videos_sorted[:top_n]

        print(f"\n📊 ANALYZING: Top {len(top_videos)} videos by views...")
        for i, v in enumerate(top_videos[:5], 1):
            print(f"  {i}. {v.get('title', '')[:50]}... ({v.get('views', 0):,} views)")

        analysis = self.apify.analyze_trending_patterns(top_videos)

        return {
            "videos": top_videos,
            "analysis": analysis,
        }

    async def generate_ideas_from_trends(
        self,
        trending_data: dict,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> list[dict]:
        """Generate video ideas based on trending analysis.

        Args:
            trending_data: Output from scrape_trending()
            num_ideas: Number of ideas to generate
            save_to_airtable: Whether to save to Airtable
            notify_slack: Whether to send Slack notification

        Returns:
            List of generated video concept dicts
        """
        analysis = trending_data.get("analysis", {})

        # Build context for Claude
        top_videos = analysis.get("top_10_by_views", [])
        top_keywords = analysis.get("top_keywords", [])[:15]
        all_titles = analysis.get("all_titles", [])[:30]
        patterns = analysis.get("title_patterns", {})

        print(f"\n💡 GENERATING {num_ideas} ideas from trends...")

        # Create the prompt for Claude
        system_prompt = """You are the Executive Producer for 'Economy Fast-Forward', a faceless YouTube channel that projects current events into dramatic future scenarios.

CHANNEL IDENTITY:
- Style: Documentary-style, dramatic narration, futuristic projections
- Topics: Economy, finance, AI/tech, robotics, macroeconomics, geopolitics
- Angle: "What history teaches us about what's coming next"
- Narrative: Always use PAST → PRESENT → FUTURE structure

Your job is to analyze trending video titles and patterns, then CREATE ORIGINAL video concepts that:
1. MODEL the successful patterns (title structure, keywords, emotional hooks)
2. DO NOT COPY - create unique FUTURE-FOCUSED angles
3. Connect current events to historical parallels AND future predictions

=== MANDATORY TITLE PATTERNS (DATA-DRIVEN - 3-5x HIGHER ENGAGEMENT) ===

**PRIMARY PATTERN (Use for majority of titles):**
"Why [Major Power/Entity] Can't/Won't/Didn't [Strategic Action]"
- Impossibility framing drives maximum curiosity (avg 1073 VPH, 6.89% CTR)
- Examples: "Why Saudi Arabia Can't Retaliate", "Why China Can't Stop the Dollar"
- This pattern MUST be your default choice

**SECONDARY PATTERN:**
"How Would [Major Event/Operation] Actually Happen?"
- Scenario framing with "Actually" adds authority
- Example: "How Would a Taiwan Invasion Actually Happen?"

**TERTIARY PATTERN:**
"The $[Amount] [Noun]: Why [X] Can't [Y]"
- Combine money hook with impossibility framing
- Example: "The $400 Billion Hostage: Why Saudi Arabia Can't Retaliate"

ADDITIONAL TITLE ELEMENTS:
- Use specific numbers, years, or dollar amounts ($2.7 Trillion, 2027, 89%)
- ALL CAPS for 1-2 words max (COLLAPSE, CRASH, EXPOSED, WARNING)
- Colons work well with the patterns above
- Future dates perform well (2025, 2026, 2027, 2030)

AVOID: Generic titles without impossibility/scenario framing

TOPIC MIX - Generate ideas across these categories:
- Financial crises & market predictions
- AI/Tech disruption & job displacement
- Geopolitical shifts & their economic impact
- Historical parallels to current events

OUTPUT FORMAT:
Return a JSON object with a "concepts" array containing exactly {num_ideas} video concepts:
{{
  "concepts": [
    {{
      "viral_title": "The actual YouTube title",
      "source_title": "The EXACT title from the trending list that inspired this (copy-paste)",
      "modeled_from": "WHY this works: What pattern, psychology, or hook makes this title effective. Be specific about the emotional triggers and title mechanics.",
      "thumbnail_visual": "Thumbnail concept description",
      "hook_script": "First 15 seconds of the video script",
      "narrative_logic": {{
        "past_context": "Historical event this relates to",
        "present_parallel": "What's happening NOW",
        "future_prediction": "What this means for the future"
      }},
      "writer_guidance": "Key points for the scriptwriter"
    }}
  ]
}}"""

        # Inject Osiris learnings if available (Phase 2 performance learning)
        if self._learnings_engine:
            try:
                learnings_text = self._learnings_engine.get_all_learnings_for_ideation()
                if learnings_text:
                    system_prompt += learnings_text
                    print("  [Osiris] Injected channel learnings into prompt")
            except Exception as e:
                print(f"  [Osiris] Learnings injection failed (non-blocking): {e}")

        user_prompt = f"""Analyze these TRENDING video patterns and generate {num_ideas} ORIGINAL video concepts:

## TOP PERFORMING TITLES (by views):
{chr(10).join(f'- "{v["title"]}" ({v["views"]:,} views) - {v["channel"]}' for v in top_videos[:10])}

## TOP KEYWORDS IN TRENDING TITLES:
{', '.join(f'{word} ({count})' for word, count in top_keywords)}

## TITLE PATTERN ANALYSIS:
- Titles with numbers: {patterns.get('has_number', 0)}/{len(all_titles)}
- Titles with questions: {patterns.get('has_question', 0)}/{len(all_titles)}
- Titles with colons: {patterns.get('has_colon', 0)}/{len(all_titles)}
- Titles with ALL CAPS words: {patterns.get('has_caps_word', 0)}/{len(all_titles)}
- Titles with year references: {patterns.get('has_year', 0)}/{len(all_titles)}

## SAMPLE OF ALL TRENDING TITLES:
{chr(10).join(f'- {title}' for title in all_titles[:20])}

---
Generate {num_ideas} ORIGINAL concepts that MODEL these successful patterns.
Each concept should feel like it could be the #1 trending video tomorrow.
Return ONLY the JSON object, no other text."""

        response = await self.anthropic.generate(
            prompt=user_prompt,
            system_prompt=system_prompt.format(num_ideas=num_ideas),
            model=Models.CLAUDE_SONNET,
        )

        # Parse response
        import json
        clean_response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_response)

        ideas = data.get("concepts", [])

        print(f"  Generated {len(ideas)} ideas:")
        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            modeled = idea.get("modeled_from", "")[:50]
            print(f"    {i}. {title}")
            print(f"       (modeled from: {modeled}...)")

        # Match each idea's source_title to the scraped videos for URL + metrics
        all_videos = trending_data.get("videos", [])
        top_videos = analysis.get("top_10_by_views", [])

        for idea in ideas:
            idea["original_dna"] = f"Trending analysis: {len(all_videos)} videos analyzed"

            # Try to find the source video by matching title
            source_title = idea.get("source_title", "")
            matched_video = None

            if source_title:
                # Try exact match first
                for v in all_videos:
                    if v.get("title", "").lower() == source_title.lower():
                        matched_video = v
                        break
                # Try partial match if no exact match
                if not matched_video:
                    for v in all_videos:
                        if source_title.lower() in v.get("title", "").lower() or v.get("title", "").lower() in source_title.lower():
                            matched_video = v
                            break

            # Attach source video info
            if matched_video:
                idea["reference_url"] = matched_video.get("url", "")
                idea["source_views"] = matched_video.get("views", 0)
                idea["source_channel"] = matched_video.get("channel", "")
                print(f"       → Matched to: {matched_video.get('title', '')[:40]}... ({matched_video.get('views', 0):,} views)")
            elif top_videos:
                # Fallback to top video if no match
                idea["reference_url"] = top_videos[0].get("url", "")
                idea["source_views"] = top_videos[0].get("views", 0)
                idea["source_channel"] = top_videos[0].get("channel", "")

            # Ensure narrative_logic is properly populated using shared extraction
            idea["narrative_logic"] = extract_narrative_fields_from_concept(idea)

        # Enhance with curiosity gap titles (if enabled)
        if CURIOSITY_GAP_ENABLED:
            print("  Enhancing with curiosity gap structures...")
            enhanced_ideas = []
            for idea in ideas:
                enhanced = await self._enhance_title_with_curiosity_gap(idea)
                enhanced_ideas.append(enhanced)
            ideas = enhanced_ideas

        # Save to Airtable (Idea Concepts table)
        if save_to_airtable:
            print("  Saving to Airtable (Idea Concepts)...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea, source="trending")
                    print(f"    ✅ Saved idea {i}: {record.get('id')}")

                    # Save curiosity structure metadata if present
                    if idea.get("curiosity_structure"):
                        try:
                            self.airtable.update_idea_curiosity_structure(
                                record_id=record.get("id"),
                                structure=idea.get("curiosity_structure"),
                                confidence=idea.get("structure_confidence", 0),
                                thumbnail_text=idea.get("thumbnail_text", ""),
                                thumbnail_approach=idea.get("thumbnail_approach", "from_gap"),
                            )
                        except Exception as e:
                            print(f"    Warning: Could not save structure metadata: {e}")
                except Exception as e:
                    print(f"    ❌ Failed to save idea {i}: {e}")

        # Notify Slack
        if notify_slack and self.slack:
            try:
                self.slack.notify_idea_generated(ideas)
                print("  ✅ Slack notification sent")
            except Exception as e:
                print(f"  ⚠️ Slack notification failed: {e}")

        return ideas


    async def generate_ideas_v2(
        self,
        trending_data: dict,
        num_ideas: int = 5,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> list[dict]:
        """Generate video ideas using Idea Engine v2 format modeling."""
        analysis = trending_data.get("analysis", {})
        all_titles = analysis.get("all_titles", [])[:30]
        top_videos = analysis.get("top_10_by_views", [])
        
        print("\n" + "=" * 50)
        print("IDEA ENGINE v2 - Format Modeling")
        print("=" * 50)
        print(f"Analyzing {len(all_titles)} trending titles...")
        
        # Step 1: Decompose each title
        decomposed = []
        for title in all_titles:
            result = await decompose_title(title, self.anthropic)
            if result:
                decomposed.append(result)
        
        print(f"Decomposed {len(decomposed)}/{len(all_titles)} titles")
        
        # Step 2: Extract formats
        formats = extract_format(decomposed)
        print(f"Extracted {len(formats)} unique formats")
        
        for fmt in formats[:5]:
            formula_short = fmt["formula"][:60] + "..." if len(fmt["formula"]) > 60 else fmt["formula"]
            print(f"  - {formula_short} (seen {fmt[times_seen]}x)")
        
        # Step 3: Update persistent format library
        config = load_modeling_config()
        config = update_format_library(config, formats)
        save_modeling_config(config)
        library_size = len(config.get("format_library", []))
        print(f"Format library now has {library_size} formats")
        
        # Step 4: Generate ideas using top formats
        top_formats = formats[:5] if formats else config.get("format_library", [])[:5]
        
        if not top_formats:
            print("No formats available, falling back to v1")
            return await self.generate_ideas_from_trends(trending_data, num_ideas, save_to_airtable, notify_slack)
        
        ideas = await generate_modeled_ideas(top_formats, config, self.anthropic, num_ideas)
        
        print(f"\nGenerated {len(ideas)} modeled ideas:")
        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            fmt_id = idea.get("based_on_format", "unknown")
            print(f"  {i}. {title}")
            print(f"     Format: {fmt_id}")
        
        # Map to expected format for Airtable
        for idea in ideas:
            swapped = idea.get("variables_swapped", [])
            idea["modeled_from"] = f"Format: {idea.get(based_on_format, )} | Swapped: {swapped}"
            idea["source_title"] = idea.get("original_example", "")
            idea["original_dna"] = f"Idea Engine v2: {len(decomposed)} titles analyzed"
            
            # Try to find source video
            matched_video = None
            source_title = idea.get("original_example", "")
            for v in trending_data.get("videos", []):
                if source_title and source_title.lower() in v.get("title", "").lower():
                    matched_video = v
                    break
            
            if matched_video:
                idea["reference_url"] = matched_video.get("url", "")
                idea["source_views"] = matched_video.get("views", 0)
                idea["source_channel"] = matched_video.get("channel", "")
            elif top_videos:
                idea["reference_url"] = top_videos[0].get("url", "")
                idea["source_views"] = top_videos[0].get("views", 0)
                idea["source_channel"] = top_videos[0].get("channel", "")

            # Ensure narrative_logic is properly populated using shared extraction
            idea["narrative_logic"] = extract_narrative_fields_from_concept(idea)

        # Enhance with curiosity gap titles (if enabled)
        if CURIOSITY_GAP_ENABLED:
            print("Enhancing with curiosity gap structures...")
            enhanced_ideas = []
            for idea in ideas:
                enhanced = await self._enhance_title_with_curiosity_gap(idea)
                enhanced_ideas.append(enhanced)
            ideas = enhanced_ideas

        # Save to Airtable (Idea Concepts table)
        if save_to_airtable:
            print("Saving to Airtable (Idea Concepts)...")
            for i, idea in enumerate(ideas, 1):
                try:
                    record = self.airtable.create_idea(idea, source="trending")
                    print(f"  Saved idea {i}: {record.get('id')}")

                    # Save curiosity structure metadata if present
                    if idea.get("curiosity_structure"):
                        try:
                            self.airtable.update_idea_curiosity_structure(
                                record_id=record.get("id"),
                                structure=idea.get("curiosity_structure"),
                                confidence=idea.get("structure_confidence", 0),
                                thumbnail_text=idea.get("thumbnail_text", ""),
                                thumbnail_approach=idea.get("thumbnail_approach", "from_gap"),
                            )
                        except Exception as e:
                            print(f"  Warning: Could not save structure metadata: {e}")
                except Exception as e:
                    print(f"  Failed to save idea {i}: {e}")

        # Notify Slack with v2 format
        if notify_slack and self.slack:
            try:
                self._send_v2_slack_notification(ideas, len(all_titles), len(formats))
                print("Slack notification sent")
            except Exception as e:
                print(f"Slack notification failed: {e}")
        
        return ideas
    
    def _send_v2_slack_notification(self, ideas: list, titles_analyzed: int, formats_found: int):
        """Send Slack notification in v2 format."""
        header = f"IDEA ENGINE v2 - Format-Modeled Ideas\n"
        header += f"Analyzed {titles_analyzed} trending videos -> Extracted {formats_found} reusable formats\n"
        header += "-" * 40 + "\n"
        
        idea_texts = []
        for i, idea in enumerate(ideas, 1):
            title = idea.get("viral_title", "Untitled")
            format_id = idea.get("based_on_format", "unknown")
            original = idea.get("original_example", "")[:50]
            swapped = ", ".join(str(s) for s in idea.get("variables_swapped", [])[:2])
            triggers = ", ".join(idea.get("psychological_triggers", []))
            
            text = f"Idea {i}: {title}\n"
            text += f"  Format: {format_id}\n"
            text += f"  Based on: {original}...\n"
            text += f"  Swapped: {swapped}\n"
            text += f"  Triggers: {triggers}\n"
            idea_texts.append(text)
        
        full_message = header + "\n".join(idea_texts)
        
        self.slack.notify(full_message)

    async def generate_from_trending(
        self,
        search_queries: Optional[list[str]] = None,
        max_results_per_query: int = 10,
        num_ideas: int = 3,
        save_to_airtable: bool = True,
        notify_slack: bool = True,
    ) -> dict:
        """Full pipeline: scrape trends → analyze → generate ideas.

        Args:
            search_queries: Custom search terms
            max_results_per_query: Videos per query
            num_ideas: Number of ideas to generate
            save_to_airtable: Save to Airtable
            notify_slack: Send Slack notification

        Returns:
            Dict with trending_data and generated ideas
        """
        print("\n" + "=" * 60)
        print("📈 TRENDING IDEA BOT - Analyzing What's Working NOW")
        print("=" * 60)

        # Step 1: Scrape trending videos
        trending_data = await self.scrape_trending(
            search_queries=search_queries,
            max_results_per_query=max_results_per_query,
        )

        # Step 2: Generate ideas from analysis
        ideas = await self.generate_ideas_from_trends(
            trending_data=trending_data,
            num_ideas=num_ideas,
            save_to_airtable=save_to_airtable,
            notify_slack=notify_slack,
        )

        print("\n" + "=" * 60)
        print("✅ TRENDING IDEA BOT COMPLETE")
        print("=" * 60)
        print(f"Analyzed: {len(trending_data.get('videos', []))} trending videos")
        print(f"Generated: {len(ideas)} original concepts")
        print("\nNext steps:")
        print("  1. Review ideas in Airtable")
        print("  2. Set your chosen idea's status to 'Ready For Scripting'")
        print("  3. Run: python pipeline.py")

        return {
            "trending_data": trending_data,
            "ideas": ideas,
        }
