# Social Hook Formulas

> These are SOCIAL hooks — adapted for text feeds, not video intros.
> Video hooks are 15-second spoken openers optimized for retention.
> Social hooks are 1-2 line text openers optimized for scroll-stopping.
>
> Cross-reference with Osiris learnings (`analytics/osiris/learnings_engine.py`)
> for which curiosity gap structures drive best CTR on YouTube —
> the same patterns tend to work on social when adapted.

## Hook ↔ Curiosity Gap Mapping

Each hook type maps to one of the 5 cognitive dissonance patterns
from `title_idea/curiosity_gap/structures.py`. Use the pattern that
matches your video's title structure for consistency.

### 1. The Hidden Flaw Hook (→ HIDDEN_FLAW structure)
**Mechanism:** "What's the mistake they're hiding?"

Social formula: "[Entity] just [did/announced something].
here's what they're not telling you about the [specific flaw]:"

- Best on: X (short take), LinkedIn (investigation opener)
- Examples:
  - "the IMF just approved a $15.6B loan to argentina. nobody is
    reading clause 47. here's what it actually says:"
  - "saudi arabia announced $500B for NEOM. the engineering reports
    say something different. follow the money:"

### 2. The Asymmetric Power Hook (→ ASYMMETRIC_DG structure)
**Mechanism:** "How does small beat big?"

Social formula: "[Small thing] just [threatened/disrupted/defeated]
[big thing]. here's the $[X] reason why:"

- Best on: X (proof post), LinkedIn (case study)
- Examples:
  - "a $500 plastic drone just sank a $2B warship. the navy's
    entire fleet strategy is obsolete. here's why:"
  - "one taiwanese company controls 92% of advanced chips.
    that's more leverage than any military in history"

### 3. The Time Bomb Hook (→ TIME_BOMB structure)
**Mechanism:** "What trap was set? When does it trigger?"

Social formula: "[X years ago], [entity] made a decision.
the consequences arrive in [timeframe]. here's the chain:"

- Best on: X (thread), Newsletter (deep dive opener)
- Examples:
  - "in 2015, china started buying african ports. in 2026,
    they control 47% of global shipping chokepoints. the trap
    is already sprung:"
  - "the fed made one decision in 2020 that created a $4.6T
    time bomb. it detonates when rates stay above 5% for
    18 months. we're at month 14"

### 4. The Paradigm Shift Hook (→ PARADIGM_SHIFT structure)
**Mechanism:** "What reality am I missing?"

Social formula: "everything you know about [topic] is based on
[assumption]. the actual data shows [contradicting reality]:"

- Best on: X (contrarian take), LinkedIn (framework post)
- Examples:
  - "everyone thinks the dollar is strong because of US
    economics. the actual reason is that 83 countries have
    no alternative. that's changing. here's the data:"
  - "the map your news uses is wrong. here's the one that
    shows where power actually flows:"

### 5. The Personal Stakes Hook (→ ILLUSION_CONTROL structure)
**Mechanism:** "How does this affect ME personally?"

Social formula: "[Geopolitical event] sounds distant.
it [specific personal impact]. here's the chain from
[event] → your [wallet/grocery bill/job/retirement]:"

- Best on: X (data drop), Newsletter (briefing opener)
- Examples:
  - "a pipeline in the strait of hormuz sounds like someone
    else's problem. it sets the price of everything in your
    grocery cart. here's the chain:"
  - "china just sold $53B in US treasuries. that decision
    will hit your mortgage rate in 90 days. here's why:"

## Platform-Specific Hook Rules

### X Hooks
- Under 280 chars for the hook line (even in long-form tweets)
- Lowercase everything
- End hook with a colon ":" — signals "thread incoming"
- Lead with the NUMBER, not the context
- "47% of global shipping" hits harder than "china's port strategy"

### LinkedIn Hooks
- Must fit in the first 210 chars (before "see more" truncation)
- "I" framing: "I spent 3 weeks tracking..." / "I found something..."
- Professional but not dry: conviction, not neutrality
- The hook should make a VP of Strategy click "see more"

### Newsletter Subject Lines
- Under 50 chars ideal, max 60
- Curiosity gap WITHOUT clickbait: promise specific value
- "The $47B Fund Flow Nobody Is Tracking" → good
- "You Won't Believe What I Found" → garbage
- Test: would a smart person open this? or roll their eyes?

## Performance Feedback Loop

This file should be updated based on Osiris learnings:

```
When Osiris reports CTR data:
├── Hook type X got >6% CTR → mark as HIGH PERFORMER, use more
├── Hook type Y got <3% CTR → mark as UNDERPERFORMER, use less
├── New pattern emerged → add to this file with source video
└── Seasonal patterns → note which hooks work better in news cycles
     vs. slow news periods
```

Track which social hooks drove the most YouTube clicks.
The social hook → YouTube click → retention chain is the key metric.
