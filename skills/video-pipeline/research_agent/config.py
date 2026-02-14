"""Research Intelligence Agent Configuration.

Contains source lists, scoring weights, competitor channels, and framework library.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SourceCategory(str, Enum):
    """Categories for research sources."""
    BREAKING_NEWS = "breaking_news"
    GEOPOLITICAL = "geopolitical"
    PSYCHOLOGY_TREND = "psychology_trend"
    COMPETITOR_GAP = "competitor_gap"
    ECONOMIC = "economic"
    AI_TECH = "ai_tech"


@dataclass
class ScoringWeights:
    """Weights for composite score calculation."""
    timeliness: float = 0.3
    audience_fit: float = 0.4
    content_gap: float = 0.3


@dataclass
class CompetitorChannel:
    """YouTube competitor channel configuration."""
    name: str
    channel_id: str
    subscriber_range: str
    content_focus: str
    upload_frequency: str


# ============================================================
# RESEARCH SOURCE CONFIGURATION
# ============================================================

RESEARCH_CONFIG = {
    # Scoring weights
    "scoring_weights": ScoringWeights(),

    # Web search queries by category
    "search_queries": {
        SourceCategory.BREAKING_NEWS: [
            "breaking economic news today",
            "major geopolitical events this week",
            "power shifts politics today",
            "billionaire news moves this week",
            "central bank policy changes",
            "currency crisis news",
        ],
        SourceCategory.GEOPOLITICAL: [
            "geopolitical analysis power dynamics",
            "strategic intelligence report",
            "international relations power shift",
            "global trade war developments",
            "sanctions economic warfare",
        ],
        SourceCategory.PSYCHOLOGY_TREND: [
            "dark psychology trending",
            "manipulation tactics psychology",
            "power dynamics relationships",
            "stoicism modern application",
            "Machiavelli modern leadership",
            "48 laws of power examples",
        ],
        SourceCategory.ECONOMIC: [
            "wealth transfer economic news",
            "market manipulation investigation",
            "economic collapse warning signs",
            "inflation wealth inequality",
            "corporate power consolidation",
        ],
        SourceCategory.AI_TECH: [
            "AI power consolidation big tech",
            "artificial intelligence regulation",
            "tech monopoly antitrust",
            "AI surveillance capitalism",
            "automation job displacement",
        ],
    },

    # Trusted source domains for filtering
    "trusted_domains": {
        "tier_1_wire": [
            "reuters.com",
            "apnews.com",
            "bloomberg.com",
        ],
        "tier_2_major": [
            "bbc.com",
            "cnbc.com",
            "ft.com",
            "wsj.com",
            "economist.com",
            "aljazeera.com",
            "nytimes.com",
            "theguardian.com",
        ],
        "tier_3_analysis": [
            "foreignaffairs.com",
            "brookings.edu",
            "csis.org",
            "cfr.org",
            "eurasiagroup.net",
            "zerohedge.com",
            "naked capitalism",
        ],
        "psychology_philosophy": [
            "psychologytoday.com",
            "aeon.co",
            "bigthink.com",
            "dailystoic.com",
        ],
    },

    # Competitor YouTube channels to monitor
    "competitor_channels": [
        CompetitorChannel(
            name="Mindplicit",
            channel_id="UCqIoq4HVrwHYf6j_YXYZ5OQ",  # Example ID
            subscriber_range="200K-500K",
            content_focus="Machiavelli, Stoicism, dark psychology, self-improvement",
            upload_frequency="Daily",
        ),
        CompetitorChannel(
            name="Academy of Ideas",
            channel_id="UCiRiQGCHGjDLT9FQXFW0I3A",
            subscriber_range="1M+",
            content_focus="Philosophy, psychology, social criticism",
            upload_frequency="Bi-weekly",
        ),
        CompetitorChannel(
            name="Einzelgänger",
            channel_id="UCo7lq93IQSN7aJUhVbdU_Vg",
            subscriber_range="1M+",
            content_focus="Stoicism, philosophy, Eastern thought",
            upload_frequency="Weekly",
        ),
        CompetitorChannel(
            name="After Skool",
            channel_id="UC1KmNKYC1l0stjctkGswl6g",
            subscriber_range="3M+",
            content_focus="Animated philosophy and psychology",
            upload_frequency="Weekly",
        ),
        CompetitorChannel(
            name="Pursuit of Wonder",
            channel_id="UCz12JQ98gA_3P0l1LuvmHog",
            subscriber_range="2M+",
            content_focus="Existential philosophy, thought experiments",
            upload_frequency="Bi-weekly",
        ),
        CompetitorChannel(
            name="CaspianReport",
            channel_id="UCwnKziETDbHJtx78nIkfYug",
            subscriber_range="1M+",
            content_focus="Geopolitics, strategic analysis",
            upload_frequency="Weekly",
        ),
        CompetitorChannel(
            name="Peter Zeihan",
            channel_id="UCfBjrpZDRIuZfWFWHhtGdDA",
            subscriber_range="500K+",
            content_focus="Geopolitics, demographics, economic forecasting",
            upload_frequency="2-3x/week",
        ),
        CompetitorChannel(
            name="VisualPolitik",
            channel_id="UCT3v6vL2H5xvJ4m98KkPXOA",
            subscriber_range="2M+",
            content_focus="Geopolitics with visual storytelling",
            upload_frequency="2-3x/week",
        ),
    ],

    # Framework library for analysis
    "framework_library": {
        "the_prince": {
            "source": "Machiavelli",
            "best_for": "Political power consolidation, ruthless pragmatism, state-craft",
            "keywords": ["power", "prince", "ruler", "state", "politics", "control"],
        },
        "48_laws_of_power": {
            "source": "Robert Greene",
            "best_for": "Personal power dynamics, manipulation tactics, strategic positioning",
            "keywords": ["law", "power", "strategy", "manipulation", "influence"],
        },
        "art_of_war": {
            "source": "Sun Tzu",
            "best_for": "Competitive strategy, asymmetric warfare, indirect approaches",
            "keywords": ["war", "strategy", "enemy", "battle", "victory", "defeat"],
        },
        "shadow_work": {
            "source": "Carl Jung",
            "best_for": "Hidden motivations, collective unconscious, projection, persona vs. self",
            "keywords": ["shadow", "unconscious", "persona", "projection", "psyche"],
        },
        "game_theory": {
            "source": "Nash, Von Neumann",
            "best_for": "Strategic interaction, prisoner's dilemma, brinkmanship, Nash equilibrium",
            "keywords": ["game", "strategy", "equilibrium", "rational", "payoff"],
        },
        "behavioral_economics": {
            "source": "Kahneman, Thaler",
            "best_for": "Cognitive biases, loss aversion, framing effects, nudge theory",
            "keywords": ["bias", "decision", "heuristic", "irrational", "choice"],
        },
        "stoic_philosophy": {
            "source": "Marcus Aurelius, Epictetus",
            "best_for": "Emotional resilience, dichotomy of control, virtue ethics under pressure",
            "keywords": ["stoic", "control", "virtue", "resilience", "acceptance"],
        },
        "systems_thinking": {
            "source": "Meadows, Senge",
            "best_for": "Feedback loops, leverage points, unintended consequences",
            "keywords": ["system", "feedback", "loop", "leverage", "emergence"],
        },
        "propaganda_persuasion": {
            "source": "Bernays, Cialdini",
            "best_for": "Mass influence, social proof, manufactured consent, persuasion architecture",
            "keywords": ["propaganda", "persuasion", "influence", "manipulation", "consent"],
        },
        "evolutionary_psychology": {
            "source": "Dawkins, Pinker",
            "best_for": "Status hierarchies, tribal dynamics, in-group/out-group, dominance signals",
            "keywords": ["evolution", "tribal", "status", "dominance", "hierarchy"],
        },
    },

    # Audience profile for scoring
    "audience_profile": {
        "demographics": {
            "gender_male_pct": 75,
            "age_range": "18-35",
            "language": "English",
            "education": "Above average",
        },
        "psychographics": {
            "values": [
                "Intelligence over brute force",
                "Strategic thinking",
                "Understanding hidden power dynamics",
            ],
            "drawn_to": [
                "Dark or contrarian framing",
                "How power really works",
                "Skepticism of mainstream narratives",
                "Depth over surface coverage",
            ],
        },
        "content_triggers": [
            "power consolidation",
            "hidden manipulation",
            "strategic genius",
            "historical parallels",
            "forbidden knowledge",
            "what they don't want you to know",
        ],
        "content_avoidance": [
            "overt political partisanship",
            "motivational fluff",
            "recycled quotes without depth",
            "clickbait without substance",
        ],
    },

    # Scan configuration
    "scan_config": {
        "max_candidates": 12,
        "min_candidates": 8,
        "searches_per_category": 3,
        "results_per_search": 5,
        "lookback_hours": 72,
    },

    # API configuration
    "api_config": {
        "tavily_search_depth": "advanced",
        "tavily_include_domains": [],  # Empty = no filter
        "tavily_exclude_domains": ["pinterest.com", "facebook.com", "instagram.com"],
    },
}


# ============================================================
# SCORING SYSTEM PROMPTS
# ============================================================

SCAN_SYNTHESIZER_PROMPT = """You are a research analyst for a dark psychology / strategic power YouTube channel.

Your task is to analyze search results and extract potential video topic candidates.

TARGET AUDIENCE:
- Male 70-80%, age 18-35, above-average education
- Values strategic thinking over brute force
- Drawn to "dark" or contrarian framing
- Wants to understand how power really works
- Prefers depth over surface-level coverage

CONTENT TRIGGERS that resonate:
- Power consolidation
- Hidden manipulation tactics
- Strategic genius analysis
- Historical parallels to current events
- "Forbidden knowledge" framing

For each potential topic, provide:
1. headline: A compelling one-line topic description
2. source_category: breaking_news | geopolitical | psychology_trend | competitor_gap | economic | ai_tech
3. timeliness_score (1-10): How time-sensitive? 10 = breaking now, 1 = evergreen
4. audience_fit_score (1-10): How well does this match our dark psychology / strategy audience?
5. content_gap_score (1-10): How underserved is this topic from our specific angle on YouTube?
6. framework_hint: Which psychology/strategy lens would work best? (e.g., "48 Laws of Power - Law 3", "Jungian Shadow", "Game Theory")
7. source_urls: The URLs where you found this topic

OUTPUT FORMAT (JSON):
{
  "candidates": [
    {
      "headline": "string",
      "source_category": "string",
      "timeliness_score": 1-10,
      "audience_fit_score": 1-10,
      "content_gap_score": 1-10,
      "framework_hint": "string",
      "source_urls": ["url1", "url2"],
      "reasoning": "Brief explanation of why this topic fits"
    }
  ]
}

Return 8-12 candidates, ranked by estimated composite score.
Be selective - only include topics that have genuine potential for the dark psychology / strategic power angle."""

TOPIC_SCORER_PROMPT = """You are evaluating video topic candidates for a dark psychology / strategic power YouTube channel.

Score each candidate on three dimensions:

1. TIMELINESS (1-10):
   - 10: Breaking in the last 24 hours, urgent relevance
   - 7-9: Developing story, still in news cycle
   - 4-6: Recent but not urgent
   - 1-3: Evergreen, no time pressure

2. AUDIENCE FIT (1-10):
   - 10: Perfect match - power dynamics, manipulation, strategic genius
   - 7-9: Strong fit - can easily apply dark psychology lens
   - 4-6: Moderate fit - requires creative framing
   - 1-3: Weak fit - mainstream/motivational angle

3. CONTENT GAP (1-10):
   - 10: No one has covered this angle on YouTube
   - 7-9: Competitors touched it but missed key insights
   - 4-6: Some coverage exists but room for our unique take
   - 1-3: Heavily covered, saturated topic

Also flag any KILL FILTERS:
- Monetization risk (violence, hate speech, etc.)
- Oversaturated (3+ competitors in last 7 days)
- Weak 25-minute potential (can't sustain narrative arc)

OUTPUT FORMAT (JSON):
{
  "scored_candidates": [
    {
      "headline": "string",
      "timeliness_score": 1-10,
      "audience_fit_score": 1-10,
      "content_gap_score": 1-10,
      "composite_score": float (calculated),
      "kill_flags": ["flag1", "flag2"] or [],
      "selection_recommendation": "primary" | "secondary" | "backlog" | "reject"
    }
  ]
}"""
