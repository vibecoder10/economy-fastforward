"""Extract theme, angle, and emotional hooks from competitor titles using Claude."""

import json
import re
from dataclasses import dataclass, field
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class ThemeAnalysis:
    """Extracted theme and angle from a competitor title."""
    primary_theme: str = ""              # "US-Iran conflict", "China economic crisis"
    secondary_themes: List[str] = field(default_factory=list)  # ["regime change", "sanctions"]
    angle_type: str = ""                 # "hidden_truth", "impossibility", "countdown", "warning", "revelation"
    emotional_hooks: List[str] = field(default_factory=list)   # ["curiosity_gap", "fear", "outrage"]
    topic_category: str = ""             # "geopolitics", "economy", "tech", "finance"
    title_formula: str = ""              # "How [Power] [Verb] the [Event]"
    formula_variables: dict = field(default_factory=dict)      # {"power": "US", "verb": "Engineered"}
    confidence: float = 0.0              # 0-1


# Valid angle types for classification
ANGLE_TYPES = [
    "hidden_truth",      # Exposing what's really happening ("How X Engineered Y")
    "impossibility",     # Why something can't happen ("Why X Can't Y")
    "countdown",         # Time-sensitive ("X Has Y Days Left")
    "warning",           # Alert about danger ("The X That Will Y")
    "revelation",        # Uncovering secrets ("The Secret X Nobody Knows")
    "scenario",          # What-if exploration ("What If X Did Y")
    "explanation",       # How something works ("How X Actually Works")
    "comparison",        # X vs Y analysis
]

# Emotional hooks to detect
EMOTIONAL_HOOKS = [
    "curiosity_gap",     # Creates desire to know more
    "fear",              # Danger, collapse, crisis
    "outrage",           # Injustice, scandal, corruption
    "aspiration",        # Success, wealth, power
    "urgency",           # Time-sensitive, NOW
    "authority",         # Expert, insider knowledge
    "scale",             # Trillion, every, all
    "contrarian",        # Actually, really, the truth
]

# Topic categories
TOPIC_CATEGORIES = [
    "geopolitics",       # Wars, conflicts, international relations
    "economy",           # Economic policy, markets, recession
    "finance",           # Money, banking, currencies
    "tech",              # AI, technology, innovation
    "energy",            # Oil, renewables, resources
    "military",          # Defense, weapons, strategy
]


class ThemeExtractor:
    """Extract themes and angles from competitor titles using Claude Sonnet."""

    EXTRACTION_PROMPT = '''Analyze this YouTube video title and extract the following elements.

TITLE: "{title}"

Extract:

1. **Primary Theme**: The main topic (e.g., "US-Iran conflict", "China economic crisis", "AI disruption")

2. **Secondary Themes**: 2-3 supporting topics (e.g., ["regime change", "sanctions", "oil prices"])

3. **Angle Type**: How the story is framed. Choose ONE from:
   - "hidden_truth" — Exposing what's really happening ("How X Engineered Y")
   - "impossibility" — Why something can't happen ("Why X Can't Y")
   - "countdown" — Time-sensitive threat ("X Has Y Days Left")
   - "warning" — Alert about danger ("The X That Will Destroy Y")
   - "revelation" — Uncovering secrets ("The Secret X Nobody Knows")
   - "scenario" — What-if exploration ("What If X Did Y")
   - "explanation" — How something works ("How X Actually Works")
   - "comparison" — X vs Y analysis

4. **Emotional Hooks**: Which emotions does this title trigger? Choose ALL that apply:
   - "curiosity_gap" — Creates desire to know more
   - "fear" — Danger, collapse, crisis
   - "outrage" — Injustice, scandal, corruption
   - "aspiration" — Success, wealth, power
   - "urgency" — Time-sensitive, NOW
   - "authority" — Expert, insider knowledge
   - "scale" — Trillion, every, all
   - "contrarian" — Actually, really, the truth

5. **Topic Category**: The broad category. Choose ONE:
   - "geopolitics", "economy", "finance", "tech", "energy", "military"

6. **Title Formula**: Abstract the title into a reusable formula with [PLACEHOLDERS]
   Example: "How the US Engineered the Iran War" → "How [Major Power] [Deliberate Verb] the [Major Event]"

7. **Formula Variables**: Map the placeholders to actual values
   Example: {{"major_power": "US", "deliberate_verb": "Engineered", "major_event": "Iran War"}}

Return ONLY valid JSON in this exact format:
{{
  "primary_theme": "...",
  "secondary_themes": ["...", "..."],
  "angle_type": "...",
  "emotional_hooks": ["...", "..."],
  "topic_category": "...",
  "title_formula": "...",
  "formula_variables": {{"...": "..."}},
  "confidence": 0.0-1.0
}}

Set confidence based on how clearly you can identify these elements.'''

    def __init__(self, anthropic_client=None):
        """Initialize extractor.

        Args:
            anthropic_client: Anthropic client instance. If None, will import.
        """
        self.client = anthropic_client

    def _get_client(self):
        """Get or create Anthropic client."""
        if self.client is None:
            import anthropic
            self.client = anthropic.Anthropic()
        return self.client

    def _parse_response(self, response_text: str) -> Optional[ThemeAnalysis]:
        """Parse Claude response into ThemeAnalysis.

        Args:
            response_text: Raw text from Claude

        Returns:
            ThemeAnalysis or None if parsing fails
        """
        try:
            # Try direct JSON parse
            data = json.loads(response_text)
            return ThemeAnalysis(**data)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code block
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    return ThemeAnalysis(**data)
                except:
                    pass
            # Try to find raw JSON object
            json_match = re.search(r'\{[^{}]*"primary_theme"[^{}]*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(0))
                    return ThemeAnalysis(**data)
                except:
                    pass
        except Exception as e:
            print(f"Error parsing theme extraction response: {e}")

        return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def extract(self, title: str, description: Optional[str] = None) -> Optional[ThemeAnalysis]:
        """Extract theme analysis from a competitor title.

        Args:
            title: The competitor video title
            description: Optional video description for additional context

        Returns:
            ThemeAnalysis or None if extraction fails
        """
        if not title or not title.strip():
            return None

        prompt = self.EXTRACTION_PROMPT.format(title=title)

        # Add description context if provided
        if description:
            prompt += f"\n\nADDITIONAL CONTEXT (video description):\n{description[:500]}"

        try:
            client = self._get_client()
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Parse response
            response_text = response.content[0].text
            analysis = self._parse_response(response_text)

            if analysis:
                # Validate angle_type
                if analysis.angle_type not in ANGLE_TYPES:
                    analysis.angle_type = "hidden_truth"  # Default fallback

                # Validate emotional_hooks
                analysis.emotional_hooks = [h for h in analysis.emotional_hooks if h in EMOTIONAL_HOOKS]

                # Validate topic_category
                if analysis.topic_category not in TOPIC_CATEGORIES:
                    analysis.topic_category = "geopolitics"  # Default fallback

                if analysis.confidence < 0.6:
                    print(f"Low confidence theme extraction ({analysis.confidence})")

            return analysis

        except Exception as e:
            print(f"Theme extraction failed: {e}")
            raise  # Let tenacity handle retry

    def extract_sync(self, title: str, description: Optional[str] = None) -> Optional[ThemeAnalysis]:
        """Synchronous wrapper for extract().

        Args:
            title: The competitor video title
            description: Optional video description

        Returns:
            ThemeAnalysis or None
        """
        import asyncio
        return asyncio.run(self.extract(title, description))

    @staticmethod
    def quick_extract_topic_category(title: str) -> str:
        """Quick regex-based topic category extraction (no API call).

        Args:
            title: Video title

        Returns:
            Topic category string
        """
        title_lower = title.lower()

        # Keyword matching for quick categorization
        # Order matters - more specific checks first
        if any(kw in title_lower for kw in ["war", "military", "invasion", "nato", "army", "troops"]):
            return "military"
        if any(kw in title_lower for kw in ["ai", "robot", "tech", "digital", "cyber"]):
            return "tech"
        if any(kw in title_lower for kw in ["russia", "china", "iran", "israel", "ukraine", "taiwan", "conflict"]):
            return "geopolitics"
        if any(kw in title_lower for kw in ["dollar", "currency", "fed", "bank", "debt", "trillion"]):
            return "finance"
        if any(kw in title_lower for kw in ["oil", "gas", "energy", "solar", "nuclear"]):
            return "energy"
        if any(kw in title_lower for kw in ["economy", "recession", "gdp", "inflation", "jobs"]):
            return "economy"

        return "geopolitics"  # Default for this channel

    @staticmethod
    def quick_extract_angle(title: str) -> str:
        """Quick regex-based angle extraction (no API call).

        Args:
            title: Video title

        Returns:
            Angle type string
        """
        title_lower = title.lower()

        if title_lower.startswith("how ") and " actually " not in title_lower:
            return "hidden_truth"
        if title_lower.startswith("why ") and ("can't" in title_lower or "won't" in title_lower):
            return "impossibility"
        if "days" in title_lower or "hours" in title_lower or "deadline" in title_lower:
            return "countdown"
        if "will" in title_lower and any(kw in title_lower for kw in ["collapse", "crash", "destroy", "end"]):
            return "warning"
        if "secret" in title_lower or "nobody" in title_lower or "hidden" in title_lower:
            return "revelation"
        if title_lower.startswith("what if") or "would" in title_lower:
            return "scenario"
        if "actually" in title_lower or title_lower.startswith("how "):
            return "explanation"
        if " vs " in title_lower or " versus " in title_lower:
            return "comparison"

        return "hidden_truth"  # Default
