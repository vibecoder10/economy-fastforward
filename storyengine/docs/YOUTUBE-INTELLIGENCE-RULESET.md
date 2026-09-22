# StoryEngine YouTube Intelligence Ruleset

**What this is:** the real intelligence behind StoryEngine's chat agent. It is what a world-class YouTube strategist knows, turned into hard rules a machine can enforce. The goal is that StoryEngine cannot make a generic video by accident. Every idea, title, thumbnail, hook, and script gets measured against what actually wins on YouTube, and the weak ones get fixed or rejected before a creator ever wastes a generation credit on them.

**How it is built:** two halves in one file.
- **The Playbook** (Parts 1 to 7): the craft and the why, in plain language. This is the knowledge.
- **The Hard-Rule Layer** (Part 8): GATES (pass/fail checks), RUBRICS (0 to 100 scores per dimension), and ready-to-drop-in PROMPTS. This is what the agent runs.
- **Implementation** (Part 9): exactly where this wires into the current StoryEngine code, phased, lazy-first.

**Scope:** StoryEngine makes faceless, AI-generated story videos (script then voice then images then clips then stitch). So every section has a **universal core** (the laws that apply to every great YouTube video) and a **faceless overlay** (what changes when there is no human face on camera). The faceless overlay is where the money and the demonetization risk both live, so it is weighted heavily.

**Confidence flags:** numbers marked `[official]` come from YouTube directly. `[consensus]` means multiple independent sources agree. `[vendor]` means one tool's model, directionally sound but not law. `[rule-of-thumb]` means useful but unverified, use as an internal target, not a stated fact. Do not let the agent quote a `[rule-of-thumb]` number to a creator as if YouTube published it.

---

## Part 0: The Operating Model (read this first)

Everything below reduces to one funnel. A video has to survive every stage in order. Fail one and the rest does not matter.

```
NICHE        does this topic-space even have reachable demand + money?
  └─ IDEA    is this specific idea proven to be wanted? (sets the CEILING)
      └─ PACKAGE   title + thumbnail: does it win the CLICK?
          └─ HOOK      first 30s: does it confirm the promise + open a loop?
              └─ HOLD      story + retention: does it keep them to the payoff?
                  └─ PAYOFF    does it deliver on the promise? (drives the NEXT click)
                      └─ LOOP   does it hand the viewer to the next video? (session time)
```

### The five laws everything hangs on

1. **The idea sets the ceiling; execution only fills it.** (Paddy Galloway, verbatim.) A great idea made badly can still hit. A bad idea made perfectly cannot. Production quality is a multiplier on a number the idea already capped. This is why the agent must score the **idea** hardest, before a single image is generated.

2. **YouTube is a click-and-watch machine.** The algorithm is a per-viewer prediction engine ("automated word of mouth"). It measures two things: did the right person **click** (CTR), and did they **stay and feel satisfied** (retention + satisfaction). Every rule serves one of those two numbers.

3. **The leverage is in the first 5% of the work.** Small creators spend ~95% of their effort on filming and editing. Top creators spend ~30% on **idea + packaging + first 30 seconds**. That pre-production 20% is the entire 80/20 of growth. StoryEngine automates production, so for our users the idea+package+hook is the *only* remaining moat. The gates must be strict there.

4. **The package and the content are one promise, scored together.** Title, thumbnail, and the first 30 seconds must all promise the same thing, and the video must deliver it. A click the video does not pay off ("broken promise") gets the video throttled and the disappointment can spread to the whole channel. Clickbait is not the problem. Broken promises are.

5. **For faceless/AI, originality is the price of monetization, not a bonus.** YouTube did not ban AI or faceless content. It bans **mass-produced + templated + no added human value**, all three together. The exact bar: "an average viewer can clearly tell that each video on the channel is different." StoryEngine's existing originality engine already enforces this. This ruleset extends it.

### The single most important rule for StoryEngine specifically

> **Never produce a batch of videos that differ only by names or topic on a fixed template.**

That is the exact pattern that wiped channels with 5M+ subscribers and $30K/month in 2025-2026 (CuentosFacianantes 5.95M, a Bible-story channel at 588K / $30K/mo, and an exam-prep channel at $7,500/mo where a human *was* fact-checking and it still got hit, because the *pipeline* was templated). Light human touch does not save a templated pipeline. Output must be materially varied. This is the prime directive.

---

## Part 1: Niche and Sub-Niche Selection

### The laws

1. **No niche is too small, but every niche has a views-ceiling. Size it before you commit.** The top long-form videos in a niche ARE the empirical ceiling. If the best videos do 1M and you do 10k, that is an execution gap, not a niche problem. If the best top out at 50k, the niche is genuinely small. Price that in.
2. **Demand must be proven, not assumed.** Passion with no demand is a vanity channel nobody watches. The niche must sit where interest, measurable demand, monetization, and beatable competition overlap.
3. **A niche must be packageable for Core, Casual, and New viewers (CCN).** The channel-killer is making videos only Core insiders understand. The algorithm grows you through Casual and New. If you cannot make a thumbnail a stranger would click, the ceiling is low.
4. **Go narrow first, then expand. The direction is one-way.** You can go narrow then broad, but not broad then narrow. Dominate a small niche, then swing to adjacent topics like monkey bars, not far jumps. Expansion threshold is roughly **10,000 subs** before testing complementary topics.
5. **Monetization is a separate axis from views.** Read ceiling as `views-ceiling x value-per-view`, never views alone. A small audience at high RPM can beat a big audience at low RPM.

### The why (briefly)

The algorithm clusters viewers by behavior. A focused channel sends one clean signal; a scattered one sends noise. A tight catalog also turns your *own* videos into each other's "suggested" feed (a compounding flywheel). A broad channel hands that suggested slot to a competitor.

### The numbers

- **Outlier definition** `[vendor, vidIQ]`: a video doing far more than its OWN channel's average. Brackets: under 2x = normal, 2x-5x = solid, 5x-10x = strong, over 10x = exceptional.
- **Live-niche signal**: a cluster of 3+ outliers (5x or more) from channels under ~50k subs in the last 90 days = real, reachable demand.
- **Small-channel breakthrough**: channels under 10,000 subs regularly hitting 50,000+ views (a ~5:1 view-to-sub ratio) = the niche is open.
- **Search-volume floor** `[vendor]`: at least ~15,000 monthly searches to bother; strong cases run 25k-1.5M.
- **Sub-niche depth test (must pass all three)**: (1) Can I make 50+ unique videos here? (2) Is there an active community discussing it? (3) Do related searches return results? Any "no" = too narrow.
- **Traffic concentration ceiling**: no single traffic source should exceed ~60% of total. Above that is a structural dependency that caps growth.

### Faceless / AI-story overlay: best niches and death traps

Faceless wins where the value is the **original story + voice**, not reused footage. The images are illustration, so AI generation is a feature and there is no copyright source to trip the reused-content policy.

**Best niches for an AI-story pipeline** (high RPM AND defensibly original AND proven demand):
- **True crime / legal-court drama narration** - highest-RPM narrative cluster (~$7-13 RPM), highest retention, strong Patreon. Keep it dramatized and non-graphic.
- **History / documentary / "history to sleep to"** - the biggest proven money case (a creator at ~$700K/yr, 85%+ margins: AI script, AI voice, AI visuals, public-domain imagery). Each episode is naturally a different topic, which auto-passes the originality bar.
- **Scary / horror story narration** - the proven anchor format (Mr. Nightmare model), AI imagery helps mood.
- **Mythology / folklore** - endless public-domain source, every myth genuinely distinct.
- **Business "win/lose" case studies** - premium sponsors, RPM $10-25.
- **Mystery / "what if" / sci-fi, fables / karma-justice tales, biographies, English-learning story podcasts.**

**Saturated death traps (reject or hard-warn):**
- Generic motivation / Stoicism / "high-value-man" clips - crowded, zero differentiation, prime inauthentic-flag target.
- AI-narrated "Top 10 facts" listicles - named in YouTube's own non-compliant examples.
- Generic Reddit-story re-uploads (AI voice over Minecraft/Subway Surfers gameplay) - most saturated AI format + reused-content exposure.
- AI slideshow / scrolling-text channels - named verbatim in the policy as demonetized.
- Movie/TV/manhwa recaps, clip compilations, dubbed shows - reused-content + copyright exposure.
- Quiz/trivia, celebrity gossip - low RPM ($1-6), high competition, legal risk.

**RPM reference (US-weighted, creator-tool aggregates, `[vendor]` so treat ordering as reliable, exact figures as ballpark):** Finance $10-35 RPM, Business $10-30, Real estate $8-20, Legal $8-16, Tech $4-15, True crime $7-13, History $6-12, Horror narration $8-15, Motivation $5-8. Bottom tier: vlogs $2-6, gaming $0.50-5, entertainment $0.50-3, music $1-3. Finance RPM is ~10-20x music. Same 100k views: finance ~$1,000-3,500, entertainment ~$200-500.

---

## Part 2: Video Idea Generation and Selection

This is the single highest-leverage lever in YouTube growth. Since AI makes production nearly free, **idea selection is StoryEngine's only real moat.** Score it the hardest.

### The laws

1. **The idea contains the thumbnail, or it is not an idea.** MrBeast's example: "I Spent 50 Hours In My Front Yard" is unclickable; "I Spent 50 Hours In Ketchup" is "easily 100x more viral" because the thumbnail image is exponentially more interesting. Same effort, different idea, 100x outcome. If you cannot picture the thumbnail, kill the idea.
2. **Proven-then-fresh beats novel.** Pure originality is the riskiest play. The reliable path is a **proven format** (demonstrated demand) given a **fresh angle**. The format is the safety; the twist is the freshness.
3. **Volume in, quality out.** Generate ~100 ideas, whittle to ~10, develop 1. Never commit to the first idea.
4. **An outlier is pre-validated demand.** A 10x video means the algorithm already tested that topic against real viewers and it won. Modeling it is buying a proven ticket instead of printing a new one.

### The named methods (from the Grow Channels Accelerator course), each as a real technique

- **The Outliers Method** - find videos that massively beat their own channel's baseline. When YouTube pushes one video 10x harder than a channel's norm, something in the topic/packaging worked. Filter for *small-channel* outliers (proves the idea, not an existing audience carried it) and *recent* ones (proves live demand). Tools: vidIQ Outliers, 1of10, OutlierKit.
- **The Double Down Method** - double down on YOUR OWN proven winners. Once a video beats your baseline, make more of that thing: same format, adjacent topics, sequels, a series. Mine the vein you already struck.
- **The Past Success Method** - audit your back catalog (and competitors') for patterns that historically over-delivered, abstract each to its underlying format/hook, and re-run that template on new topics. Past Success is the retrospective audit; Double Down is the forward bet you place on what it surfaces.
- **The Suggested Videos Method** - open a niche outlier and harvest the "up next" sidebar. Those are pre-clustered, demand-adjacent ideas the algorithm believes that same audience wants next. Repeated suggestions = a heat map of live appetite.
- **The Similar Niche Method** - transplant a proven format from an adjacent niche your audience has not seen it in yet. Canonical example: Red Bull's drone-vs-F1 video borrowed Carwow's drag-race format. Proven structure + automatic novelty.
- **The Internet Method** - source from off YouTube: Reddit (story subs especially), news cycles, trends, forums. Demand visible off-platform (upvotes, comments) is demand you can be first to serve on YouTube. This is the primary raw-material engine for faceless story channels.
- **Model, Not Copy** - copy the *format/structure* (not ownable, the proven part), change the *specifics* (topic, angle, characters, scale, perspective). The test: would a viewer who saw the original feel they got *new* value, not a rerun? Modeling = same skeleton, new flesh. Copying = same skeleton AND same flesh.

### The outlier math (the exact thresholds to encode)

```
Outlier score = video views / that channel's median views for similar-aged videos
  under 2x  = noise, ignore
  2x - 5x   = minimum bar to use as an idea source
  5x - 10x  = proven format, worth modeling
  over 10x  = priority target, especially from a SMALL and RECENT channel
```
It is a ratio to the channel's own baseline. Not raw views. Not views-divided-by-subscribers.

### Faceless / AI-story overlay

- The premise must be **bingeable and series-able**, not a one-off. Faceless winners (true crime, horror, mystery, Reddit stories) share high average-view-duration and repeat viewing.
- **Specialize**: "unsolved disappearances," not "true crime broadly." Narrow premise = cleaner clustering + sharper packaging.
- The Internet Method is the faceless engine: Reddit + news + forums give you a demand signal (upvotes/comments) *before* you produce.

---

## Part 3: Packaging (Title + Thumbnail + CTR)

Packaging is the biggest controllable lever. Changing only the title or only the thumbnail can be the difference between ~500k and ~12M views on the same video. A 2% absolute CTR gain can roughly double lifetime views.

### The laws

1. **Package first, before producing.** Decide the title and thumbnail before the script's hook is written, so the hook can mirror them.
2. **Title + thumbnail = 1 + 1 = 3.** They must combine into one idea without repeating each other. The thumbnail carries the emotional/visual hook; the title carries context, specificity, and searchable words.
3. **One burning question.** The package must put a single question in the viewer's mind. Clarity beats cleverness.
4. **"Click to unpause."** The strongest packages depict a scene paused mid-action, something about to happen, in progress, or just happened. The only way to unpause it is to click.
5. **The thumbnail usually carries more of the click than the title.** Viewers see the image first, then decide whether to even read the title.

### Title rules (hard numbers)

- Length **40-65 characters**; keep the most impactful phrase in the **first ~40 chars** (mobile truncates); aim under 50 when possible.
- Front-load the hook in the first 4-5 words. Use Title Case.
- Must carry at least one of: a **number**, a **stake**, a **curiosity gap / open loop**, or a **negative/loss frame**.
- Negativity bias is real: warning/negative framing ("mistake," "stop," "wrong," "killing") tests ~60% higher than positive `[consensus]`. Odd numbers often beat even.
- Swap weak verbs for high-stakes ones ("I Spent" then "I Survived").
- Never spoil the payoff in the title (do not close the loop before the click).

**Title templates that work:** Number + concrete outcome ("7 Investing Mistakes That Cost Beginners $10,000") - Curiosity gap ("The One Mistake Everyone Makes When...") - Transformation ("Zero to 100K: What Actually Worked") - Warning ("Stop Doing This If You Want X") - Contrarian ("Why Posting Daily Is Ruining Your Channel") - Secret ("The Algorithm Secret YouTube Won't Tell You") - Story hook with stakes ("I Almost Quit. Then This Happened.") - Versus ("$1 vs $1,000,000").

### Thumbnail rules (hard numbers)

- **3 or fewer distinct elements** (>3 tests ~23% lower CTR `[vendor]`). Exactly **one focal point**.
- Text **4 words or fewer** (ideal 3), heavy sans-serif, must NOT duplicate the title's words.
- **Bright** (60-70% of users browse in dark mode, so bright pops).
- **Extreme contrast** (bright-vs-dark, warm-vs-cool).
- Pass the **120px legibility test** (~70% of views are mobile; thumbnails render ~120-160px). If text is not readable at 120px, it fails.
- Specs: 1280x720, 16:9, under 2MB. Keep content in the center safe zone, clear of the bottom-right ~20% (timestamp overlay).
- Faces with exaggerated emotion lift CTR ~20-30% `[consensus]`. Faceless channels lose this, so packaging must work harder (see overlay).

### CTR benchmarks (judge against these)

- YouTube-official band: **2% to 10%** `[official]`. Half of all videos sit here.
- By source `[vendor]`: Browse ~3-7% (lowest, viewers are scrolling), Suggested ~5-10%, Search highest (intent).
- By channel size: under 1k subs often 6-10% (shown to loyal subs first); over 100k drops to 3-5%. Small channels LOOK better, do not be fooled.
- **Danger**: below 3% on a new upload, YouTube cuts distribution within ~24-48h. Replace the package below 4%.
- Faceless data-driven target `[vendor]`: aim 15%+ CTR with 50%+ retention.

### Faceless / AI overlay (the face substitute)

With no face to carry facial emotion, substitute three things:
1. **Show an EVENT, not an object or emotion** - the moment just before/after something strange, tragic, or shocking, with the outcome withheld. Make the viewer ask "what is happening here?"
2. **Extreme contrast + instantly-readable iconography** - arrows, danger signs, glowing charts, split-screen conflict, color-coded good-vs-bad lighting.
3. **Custom AI scenes, never generic stock** - specify the exact dramatic moment, angle, cinematic lighting. AI lets you manufacture the precise unpause moment a stock library cannot.

Three proven faceless looks: **documentary** (dark, gritty, cinematic for crime/history), **versus split-screen** (diagonal split for tech/finance), **abstract vector** (flat bright shapes for explainers, the Kurzgesagt signal). Pick one and keep it consistent; consistency compounds recognition.

---

## Part 4: The Hook (First 30 Seconds)

This is where most videos die. The steepest single drop in nearly every video is 0:00 to 0:30, with the biggest cliff at 30s. The algorithm reads a fast exit as "bad content" and throttles reach. Retention is reach.

### The laws

1. **The first 30 seconds decides the video's fate.** An extra ~10% retention can be the difference between 100k and 1M views.
2. **A hook does three jobs at once, in under 15 seconds:** (1) confirm the viewer is in the right place (restate the title's promise), (2) raise the stakes / state why this matters now, (3) open a curiosity loop (hint at the payoff without giving it).
3. **Front-load value.** Put the single most interesting thing first, not context or backstory. Lead with the best moment.
4. **The hook must mirror the package.** The title's key claim must appear or be directly implied in the first 1-2 sentences. A 0-30s cliff is the signature of a promise mismatch.

### Hook frameworks (the agent picks one per script)

Curiosity gap / open loop - Bold claim / contrarian - Result/proof-first - Story cold open / in-medias-res (drop mid-action, then "...36 hours earlier") - Stakes declaration - Question - Pattern interrupt - Empathy mirror ("You've tried X, Y, Z and none worked") - Specific promise.

### The numbers

- **30-second retention target: 70%+ is strong** `[consensus]`; under 50% by 15s = broken hook. MrBeast benchmarks ~90% through the first 30s. (Average YouTube video retains only ~23.7% overall, so 50%+ is well above average.)
- Deliver a specific value claim **within 15 seconds** (scripts that do retained ~52% vs ~44% `[vendor]`).
- Hook segment **under 45 seconds** before the body begins.
- **Re-hook / micro-hook every 30-60 seconds** thereafter. Each is a pattern interrupt: new stat, question, tone shift, scene change. Transitions are the danger zone, make each one pull forward.

### Banned hook patterns (auto-reject)

Greetings ("hey guys," "welcome back," "what's up") - logo/intro animation before content (costs ~8-15% of the audience) - topic-defining without tension ("today we're going to talk about...") - backstory before stakes (buried lede) - slow b-roll with no voiceover - hook over 45s - slow delivery (over ~5s to the point).

### Faceless / AI-narration overlay

- The hook lives entirely in the **opening line** and the **cold-open visual**, and they must reinforce each other. Never open on an abstract image while the voice says something specific.
- **Open on the peak visual, not an establishing shot.** Smash-cut to the most charged moment, then rewind.
- Narration: slightly faster than normal pace, urgent, confident. Read every hook aloud before locking it. Use "you" where it fits. Specificity is the faceless superpower (a hard number, name, or date lands where vague claims die).

---

## Part 5: Storytelling, Script, and Retention

The body of the video. This is what holds people from the hook to the payoff. For faceless content the script carries everything, because there is no host to bond with. Weak structure is exactly why generic AI video feels like slop.

### The laws

1. **Causality is the spine. Use "but" and "therefore," never "and then."** (Trey Parker / Matt Stone.) Between any two beats you must be able to say BUT (conflict) or THEREFORE (consequence). If the only word that fits is AND THEN, the story is dead. This is the #1 enforceable story rule.
2. **Win the first half and you win the whole.** "If we can get them to watch the first half there's a very high chance they watch to the end."
3. **Stakes must escalate.** Interest rises when what is at risk rises. Static stakes = drop-off.
4. **Emotion drives retention.** The best scripts oscillate between emotional states. Flat emotion = flat curve.
5. **No dead air.** Every second earns its place. Any scene that could be cut without breaking causality is a tangent, cut it.
6. **Manage open loops.** Open the first loop in the first ~20 seconds. Never close a loop without opening the next. (Zeigarnik effect: the brain fixates on unfinished things.)

### Story structures that work (pick one per video)

- **Three-Act**: Setup ~25% (inciting incident inside the first 10-15% of runtime), Confrontation ~50% (midpoint twist that raises stakes), Resolution ~25% (payoff that delivers the setup).
- **Dan Harmon Story Circle (8 steps)**: comfort then need then go then search then find then take then return then change. Best for character-driven AI stories. The fall-before-rise IS the tension.
- **Pixar Story Spine**: "Once upon a time... Every day... One day... **Because of that...** **Because of that...** Until finally..." The repeated "because of that" is the but/therefore engine built into a template. Great default for a short narrated story.
- **MrBeast escalation engines**: stair-step ($1 then $10 then $1k then world record), winner-unknown (outcome withheld to the end), crazy progression (cover multiple beats in the first 3 minutes so viewers invest fast).

### Pacing and density (hard numbers)

- **Narration 150-160 wpm** baseline (130-160 acceptable), and **vary the rate within a video** (constant wpm is a robot tell). Speed up for action/climax, slow down for emotion. Trim TTS silences over ~0.5s.
- **One complete idea every 60-90 seconds**; a pattern interrupt every 60-90s.
- **Inciting incident in the first 10-15% of runtime**; midpoint escalation at ~50% (the second-biggest drop point); payoff lands **3-5 seconds before the end** (rewatch + subscribe window).
- **Word count by length** (at ~150 wpm): 5 min ~= 700-800 words, 10 min ~= 1,400-1,600 words.
- **Do not pad runtime to hit 8-10 min for ad eligibility.** It creates a retention cliff at the 5-6 min mark.

### Script craft (sentence-level)

Write for one person, second person ("you") - vary sentence length deliberately (short = tension, long = reflection; uniform length = monotony = flat curve) - bucket brigades ("But here's the thing." "It gets worse." "And that's when everything changed.") to hand attention forward - read it aloud and rewrite what stumbles - add brief commentary asides ("which is insane, because...") which for faceless channels are the single biggest original-value signal to the algorithm.

### Banned story patterns (auto-reject)

"And then" plotting with no causal link - stakes not set in the first 10-20s - static (non-escalating) stakes - meandering/tangents - monotonous pacing (uniform sentence and section length) - signaling the end early ("so to wrap up...") before the payoff - clickbait with no delivered payoff - padding to hit monetization length.

### Faceless / AI-story overlay (the anti-slop fix is structural, not cosmetic)

Slop is repetitive, low-stakes, generic, no authorial intent. The cure is not prettier visuals. It is: a **named protagonist with a real NEED**, **concrete specific stakes that escalate**, **but/therefore causality**, and an **earned payoff**. Force those four and the slop feeling largely disappears. Keep narrated AI stories to **4-8 minutes** for a single story unless the escalation genuinely sustains longer. Every narration beat should pair with a visual change that *advances* the story, not decorates it.

---

## Part 6: Faceless / AI-Video Craft (the StoryEngine core)

This is the most StoryEngine-specific section. It is what separates a faceless channel that grows and monetizes from AI slop that gets ignored or demonetized.

### The laws

1. **Faceless never means low-effort.** Every six- and seven-figure faceless channel front-loads research, scripting, and editing. The policy line is not face-vs-no-face. It is human creative direction vs mass-produced template.
2. **One video must be defensibly different from the last.** YouTube's literal bar: "an average viewer can clearly tell that each video on the channel is different."
3. **Every shot must earn its place.** Generic "wallpaper" b-roll (anything that could appear in any video on any topic) is the visual signature of slop. A shot must illustrate, prove, or advance the specific sentence it sits under.
4. **Consistency is the trust signal AI breaks by default.** Characters morphing between shots (face, hair, outfit changing) instantly reads as cheap. Fix structurally: lock identity (reference images) separately from action.

### Narration and voice rules

- 150-160 wpm, varied within the video. Master/EQ the output, never ship raw TTS (flat).
- Eliminate the four robotic causes: run-on sentences with no breath cues, unmastered TTS, one voice for everything, skipped pronunciation setup for names/jargon/acronyms.
- Match voice to content (an upbeat voice on a somber true-crime story breaks immersion as badly as a robotic one).
- Audio mix: music -5 to -25 dB under voice. Trim silences over ~0.5s.
- **The acceptability line:** listeners do NOT mind AI narration if quality is high. The turn-off is poor enunciation, monotone, and mispronunciation, not the AI-ness itself.

### Visual storytelling rules

- **Relevance** is load-bearing: each shot must prove the specific narration line it sits under. No contradiction (a visual that contradicts the voice destroys credibility faster than no visual).
- **Variety**: change visuals every **3-5s** for dense content, every **15-25s** for narrative. Holds of 20-40s only when the message carries itself. Never reuse a clip/scene across videos (the bulk-demonetization pattern).
- **Character consistency**: lock appearance across every shot via reference images. **Scene continuity**: stable lighting/layout within a scene.
- **Motion with purpose** (subtle push-ins, parallax) so frames are not static slideshows, but avoid AI artifacts (warping, morphing, flicker, melting hands). Resolution 720p minimum, prefer 1080p+.

### AI-slop failure modes (these become the banned-pattern list)

Template repetition across 5+ videos - TTS + slideshow with no story - no stakes/no open loop - no payoff - robotic/mismatched voice - wallpaper b-roll - repetitive visuals - inconsistent characters/scenes - AI artifacts - mismatched visual-to-voice - too long with no density - weak/late hook - batch/daily mass uploads - fully automated zero-human-judgment pipeline - no disclosure when realistic - deceptive/fake content.

### Monetization and policy safety (current, 2025-2026, critical)

- **July 15, 2025**: YouTube renamed "repetitious content" to **"inauthentic content."** Definition: content that "follows a template with minimal variation," "is easy to reproduce at scale," or "lacks clear author input." It explicitly names "AI-generated content made with generic templates giving the impression of mass production without adding the creator's original, authentic insights." `[official]`
- **AI itself is explicitly fine**: "Creators are welcome to use AI tools for storytelling and production, as long as their content adheres to monetization guidelines." `[official]`
- **Reused content (separate, unchanged policy)**: clips/readings/recaps need "significant original commentary, substantive modifications, or educational or entertainment value." "Content that exclusively features readings of other materials you did not originally create" is not eligible. `[official]`
- **Disclosure**: toggle "altered or synthetic content" when content realistically depicts real-looking people/places/events or could mislead. Skip for clearly animated/fantastical. **Disclosing is free** and does not limit reach or monetization. When in doubt, disclose. `[official]`
- **The takedowns were under existing spam/deception rules, not a new anti-AI rule.** Screen Culture and KH Studio (2M+ subs each) were banned for deceptive fake trailers and metadata manipulation, NOT for being AI or faceless.
- **The hard caveat**: "20% script variation" and "5+ same-template videos" circulate in creator coverage but are NOT published YouTube numbers. Encode them as conservative internal targets `[rule-of-thumb]`, never quote them to a creator as policy.

### Length by format

Documentary / true-crime / history: 10-30 min (sweet spot 15-25). Finance/explainer: 6-15. Reddit/story long-form: 8-12. Shorts: 30-60s. Upload cadence: 2-4 quality videos/week is sustainable; daily near-identical uploads is a flag.

---

## Part 7: Algorithm, Metrics, and the Growth Flywheel

### How it actually works

YouTube is a **per-viewer pull, not a per-video push.** It assembles each person's feed by predicting what they will watch and be satisfied by, then matches your video to viewer clusters that behave similarly. A video does not "go viral," it gets matched to more and bigger clusters as it proves itself.

**The flywheel**: upload then small test pool then measure CTR + early retention against what the system *expected* for that audience then beat expectation = pool widens to colder clusters then repeat. To keep expanding you must keep over-delivering as the audience gets colder (which is harder each round, because cold viewers click less, so packaging must carry more). Most videos plateau when a pool regresses to expectation.

**The two failure modes the loop punishes:**
- High CTR + low retention = "the packaging lied" = distribution cut, disappointment can spread channel-wide.
- Great retention + low CTR = nobody enters the funnel.

### Metrics that matter, ranked (gate against the channel's own median, not one universal number)

1. **First-30s retention** `[consensus]`: 70%+ strong, under 50% = broken hook.
2. **Average Percentage Viewed (length-dependent)**: under 50% weak, 50-60% good, 60-70% very good, 70%+ excellent. 65% on a 5-min video is solid; 65% on a 20-min is exceptional.
3. **CTR**: official 2-10% band. Falls as impressions rise. Judge only after substantial impressions.
4. **Valued watch time**: the objective the system optimizes (quality-weighted by post-watch satisfaction surveys).
5. **Satisfaction signals**: surveys, likes, shares, returning viewers.

**Do not hard-gate on**: absolute views-per-hour, subscriber-to-view ratio, raw subscriber count (too noisy/size-dependent). Subscribers are a weak signal now: only ~5-10% of a typical video's views come from the subs feed.

### Myths to not repeat to creators

- "Wait 24-48h before publishing so YouTube understands the video." **False, stated by YouTube directly**: the system starts understanding the moment you publish; "waiting 24-48 hours is no different than waiting 24-48 seconds." The only reason to delay is to let copyright/monetization checks clear.
- "Best time to post" is a major lever - minor.
- The notification bell / subscriber count drives distribution - small early input only.
- High posting frequency itself ranks you - it speeds iteration, it does not rank.

### How NOT to grow (anti-patterns)

Chasing subs/views as the goal (lagging vanity metrics) - clickbait that does not deliver - ignoring CTR/retention while filming more - inconsistent packaging/identity (blurs the cluster signal) - niche-hopping - sub-for-sub or buying views - burying the payoff - generic titles.

---

# Part 8: The Hard-Rule Layer (what the agent runs)

This is the machine-usable half. Three components: **GATES** (pass/fail), **RUBRICS** (0-100 scores), and **PROMPTS** (drop-in). The design philosophy matches StoryEngine's existing `originality.py`: fail open (never crash a creator's run), nudge-don't-block where possible, and inject the rules into generation prompts so output is good *by design* before any grading is even needed.

## 8.1 The GATES (pass/fail, enforced per stage)

A GATE is a hard check. `REJECT` = block and fix/regenerate. `WARN` = surface a nudge but allow "make it anyway." Gates run *before* scoring; a gate fail is not rescued by a high score.

### Stage A - Niche gates (run once at channel setup / onboarding)
- `REJECT` if zero recent demand: fewer than 3 outliers (5x+ over the channel's own baseline) from sub-50k channels in the niche in the last 90 days.
- `REJECT` if not thumbnail-able: the niche's ideas cannot produce visually distinct, clickable thumbnails.
- `REJECT` if not CCN-packageable: it can only be served to Core insiders.
- `REJECT` (too narrow) if it fails the depth test (under 50 unique videos, no community, or no related searches).
- `REJECT` for templated-format risk: the niche IS a named non-compliant format (AI listicles, slideshows, scrolling-text, verbatim re-uploads).
- `REJECT` if the format depends on reused source material (recaps, compilations, dubbed shows).
- `WARN` if RPM is bottom-tier and the user needs revenue early; `WARN` if advertiser-unfriendly by nature (graphic violence/tragedy).

### Stage B - Idea gates (run on every proposed idea before it reaches the producer)
- `REJECT` (no proven analog) if you cannot point to at least one outlier (2x+, ideally 5x+) proving live demand. Exception: pure search-intent ideas backed by real search-volume data.
- `REJECT` (not packageable) if you cannot write a 65-char-or-less curiosity title AND describe a 3-element-or-less thumbnail with a clear visual.
- `REJECT` (no screenshot moment) if the idea contains no single visual moment that makes a compelling thumbnail.
- `REJECT` (would I click) if, shown only as title+thumbnail in a feed of competitors, it would not be clicked over the neighbors.
- `REJECT` (copy, not model) if a viewer who saw the source video would feel they got nothing new.
- `REJECT` (one-off) for story channels if the premise has no series/repeat-viewing potential.

### Stage C - Package gates (run on title + thumbnail concept)
- `REJECT` title over 65 chars; `WARN` over 50.
- `REJECT` title with no hook element (must have a number, stake, curiosity gap, or negative frame).
- `REJECT` title that spoils the payoff.
- `REJECT` thumbnail with over 3 focal elements or over 4 words of text.
- `REJECT` thumbnail whose text duplicates the title.
- `REJECT` thumbnail that fails the 120px legibility test.
- `REJECT` package where title and thumbnail say the same thing (no 1+1=3) or where the thumbnail does not support the title's promise.
- `REJECT` faceless thumbnail showing a static object/generic stock instead of an event/moment.

### Stage D - Hook gates (run on the script's first ~45 seconds)
- `REJECT` if the first spoken sentence is a greeting or self-intro ("hey guys," "welcome back," "in this video," "today we're going to talk about").
- `REJECT` if there is a logo/intro card before the first content line.
- `REJECT` if the core stake/promise/curiosity gap is not landed within 15 seconds (hard fail at 30s).
- `REJECT` if the hook line does not echo the title's core promise (continuity check).
- `REJECT` if the cold-open visual does not depict the subject of the hook line (visual-audio mismatch).
- `REJECT` if backstory precedes the most interesting moment (buried lede).
- `REJECT` if the hook segment runs over 45 seconds, or if no open loop exists in the opening.

### Stage E - Script / story gates (run on the full script)
- `REJECT` if any beat transition is pure "and then" with no but/therefore link. (Run the test on every adjacent beat pair.)
- `REJECT` if stakes are not established within the first ~15% of runtime.
- `REJECT` if stakes do not escalate (end risk > midpoint > start).
- `REJECT` if there is no inciting incident by ~15% or no midpoint twist near ~50%.
- `REJECT` if the payoff does not deliver on the hook/title promise.
- `REJECT` if any scene does not advance the arc (cuttable without breaking causality = tangent).
- `REJECT` if there is no identifiable single protagonist with a clear NEED (anti-slop).
- `REJECT` for monotonous pacing (sentence-length variance below threshold; uniform section lengths).
- `REJECT` if runtime is padded beyond the story's natural length.

### Stage F - Monetization-safety gates (run before publish, non-negotiable, hard block)
- `REJECT` (raw reading) if the video is essentially reading third-party material with no original commentary.
- `REJECT` (no original value) if it fails the "meaningful difference / original insight" test.
- `REJECT` (template-identical) if this video differs from the channel's recent videos only by names/topic on a fixed template. *(This is the prime directive. It already maps to `originality.py` Wall 2.)*
- `FORCE` the synthetic-content disclosure flag when output realistically depicts real-looking people/places/events; skip for clearly animated.
- `REJECT` (deceptive) for fake trailers, fake news, or misleading-as-reality framing or metadata.

### Stage G - Voice + Visual gates (run on assets)
- `REJECT` narration outside 130-160 wpm or with no intra-video variation; require a pronunciation map for names/jargon.
- `REJECT` if tone does not match content; `REJECT` run-on lines / raw unmastered TTS.
- `REJECT` (relevance) any shot that could appear in any other video (wallpaper b-roll); `REJECT` reused clips/scenes.
- `REJECT` characters that morph across shots (require reference-lock); `REJECT` shots that contradict the narration; `REJECT` visible AI artifacts or sub-720p output.

## 8.2 The RUBRICS (0-100 scoring)

Two layers: a **Master Video Score** (the one number that decides go/revise/regenerate) built from six weighted pillars, and **per-stage sub-rubrics** the agent uses to score and improve each piece.

### Master Video Score (weights tuned to where leverage actually is)

| Pillar | Weight | What it measures |
|---|---|---|
| **1. Idea** | 25 | Outlier proof strength, CCN appeal, novelty ("familiar but unexpected"), demand evidence |
| **2. Packaging** | 25 | Title (curiosity + specificity + length) and thumbnail (1 focal point, <=3 elements, contrast, 120px-legible) as a matched 1+1=3 unit |
| **3. Hook** | 20 | First 30s restates the promise, lands value within ~10-15s, leads with the best moment, no banned patterns |
| **4. Retention / Story** | 15 | But/therefore causality, escalating stakes, open-loop management, structural timing, pacing variety, earned payoff |
| **5. Originality + Policy Safety** | 10 | Materially varied vs the channel's other videos, added human value, correct disclosure (also a hard gate; low score blocks, not just docks) |
| **6. Niche Coherence** | 5 | Fits and extends the channel's established cluster/identity |

**Decision thresholds:**
```
Pass ALL applicable gates  AND  Master Score >= 70   -> proceed
Pass gates  AND  55 <= Master Score < 70             -> auto-revise with the rubric's specific feedback, then re-score (max 1-2 re-rolls)
Master Score < 55  OR  any gate REJECT               -> regenerate the failing stage (or surface to creator if it is an idea/niche choice)
```

### Per-stage sub-rubrics (the dimensions to score 0-100, for targeted feedback)

**Idea (pillar 1):** outlier proof strength - click potential / packageability - curiosity gap - visual/thumbnail moment - broad appeal - trend/timeliness - novelty-within-freshness - audience fit - retention/payoff potential - differentiation/"wow" - search/demand signal - production feasibility.

**Packaging (pillar 2):** curiosity/open-loop strength - clarity of single idea - stakes/emotional charge - specificity/credibility - title-thumbnail synergy (1+1=3) - thumbnail contrast & focal clarity - 120px legibility - promise-delivery alignment - negativity leverage - faceless event-conveyance - scroll-stop/pattern-interrupt.

**Hook (pillar 3):** speed-to-point - curiosity/open-loop strength - promise-hook continuity - visual-audio match (faceless) - stakes/specificity - pattern-interrupt presence - cleanliness (no banned patterns) - re-hook cadence - delivery-pace fit - emotional pull - direct address.

**Retention/Story (pillar 4):** but/therefore density (most important) - hook strength - stakes & escalation - open-loop management - structural integrity (inciting ~15%, midpoint ~50%, payoff 85-100%) - emotional range - pacing variety - payoff quality - specificity/anti-slop - scene efficiency - narration craft - ending/session hand-off.

**Faceless production (feeds pillars 4-5):** originality/non-template (highest) - narration quality (wpm, variation, pronunciation, tone, mastered) - visual relevance - visual variety - character consistency - scene continuity - motion & artifact-freeness - length fit - audio mix - policy safety (multiplier/gate).

## 8.3 The PROMPTS (drop-in)

These are written to plug into StoryEngine's existing direct-Anthropic, fail-open pattern (see `originality.py:assess_draft`). All return JSON. All fail open (on error, return a pass verdict so a transient outage never blocks a creator).

### Prompt 1 - Idea Scorer (runs in chat, before ideas reach the producer)

```
SYSTEM:
You are a ruthless YouTube head of programming. You score video IDEAS for a
{niche} channel against what actually wins on YouTube. You are not nice. The
idea sets the ceiling, so a weak idea wastes everything downstream.

For each idea, first run the hard GATES. If any gate fails, verdict = "reject"
with the specific reason. If all pass, score the rubric.

GATES (any fail = reject):
- proven_analog: is there a real outlier (2x+ over its channel baseline)
  proving this topic/format is wanted? (You are given competitor data.)
- packageable: can you write a <=65-char curiosity title AND a <=3-element
  thumbnail concept with one clear visual moment?
- not_copy: would a viewer who saw the source feel they got something NEW?
- series_able: (story channels) does this have repeat-viewing potential?

RUBRIC (0-100 each): outlier_proof, click_potential, curiosity_gap,
visual_moment, broad_appeal, novelty, differentiation.

Return JSON:
{ "verdict": "strong" | "ok" | "reject",
  "score": <weighted 0-100>,
  "title_suggestion": "<=65 chars",
  "thumbnail_concept": "one sentence, the unpause moment",
  "reasons": ["..."],
  "fix": "one concrete change that would raise the score" }

INPUT: idea = {idea}; channel_brief = {brief}; competitor_outliers = {data}
```

### Prompt 2 - Script Grader (runs after script generation, before voice)

```
SYSTEM:
You grade a YouTube SCRIPT for a faceless {niche} story channel against
retention science. Run the GATES, then score.

GATES (any fail = reject, return the failing beat):
- hook: stake/promise/curiosity landed within 15s; no greeting/logo/buried lede;
  hook echoes the title "{title}".
- causality: every beat transition is "but" or "therefore", never "and then".
- escalation: stakes at the end > midpoint > start.
- structure: inciting incident by ~15% of runtime; midpoint twist near ~50%.
- payoff: the ending delivers on the title/hook promise, lands near the end.
- protagonist: one identifiable subject with a clear NEED (anti-slop).
- no_tangent: every scene advances the arc.

RUBRIC (0-100): but_therefore_density, hook_strength, stakes_escalation,
open_loop_mgmt, structural_timing, pacing_variety, payoff_quality,
specificity_anti_slop, scene_efficiency, narration_craft.

Also flag: any scene with no but/therefore link, any monotonous run of
uniform-length sentences, any padding.

Return JSON:
{ "verdict": "pass" | "revise" | "regenerate",
  "score": <weighted 0-100>,
  "failing_gates": ["..."],
  "weakest_beats": [ {"beat": <n>, "problem": "...", "fix": "..."} ],
  "rewrite_guidance": "specific instructions to feed back into the writer" }

INPUT: script = {script}; title = {title}; target_minutes = {len}
```

### Prompt 3 - Package Grader (runs on title + thumbnail concept)

```
SYSTEM:
You grade a YouTube PACKAGE (title + thumbnail) for a faceless channel. The
package wins or loses the click. Run GATES, then score.

GATES (any fail = reject):
- title_len: <=65 chars (warn >50); has a number/stake/curiosity-gap/negative
  frame; does not spoil the payoff.
- thumb_elements: <=3 focal elements, one focal point, <=4 words of text.
- no_dup: thumbnail text does not repeat the title.
- synergy: title + thumbnail combine into ONE idea (1+1=3), not the same idea
  twice; thumbnail visually supports the title's promise.
- faceless_event: thumbnail shows a high-tension MOMENT, not a static object or
  generic stock; substitutes for a face via event + contrast + iconography.
- legible_120: readable at 120px.

RUBRIC (0-100): curiosity, single_idea_clarity, stakes, specificity, synergy,
contrast_focal, legibility, promise_alignment, faceless_event_conveyance.

Return JSON:
{ "verdict": "pass" | "revise" | "reject", "score": <0-100>,
  "reasons": ["..."],
  "better_title": "<=65 chars", "better_thumbnail": "one sentence" }

INPUT: title = {title}; thumbnail_concept = {concept}; niche = {niche}
```

### Prompt 4 - The Rubric Block (inject into the SCRIPT system prompt so output is good by design)

This is the highest-leverage and laziest move: bake the rules into generation so most videos pass the grader on the first try. Add to `engine_templates.py` `"script"` template via a `{youtube_rubrics}` slot:

```
=== YOUTUBE RETENTION RULES (non-negotiable) ===
- HOOK: open with the single most interesting moment. State the stake or open a
  curiosity loop in the FIRST sentence and fully land it within 15 seconds.
  Never open with a greeting, a logo, or "in this video". The first line must
  echo the title's promise: "{title}".
- CAUSALITY: connect every beat with "but" or "therefore". If two beats only
  connect with "and then", rewrite them. This is the #1 rule.
- STAKES: establish what is at risk in the first 15% of the runtime, and make
  the risk RISE toward the end. Never let stakes go flat.
- STRUCTURE: inciting incident by ~15%, a twist that raises stakes near ~50%,
  a payoff that delivers on the title in the final 10%.
- OPEN LOOPS: open a question early, hold it through the middle, pay it off near
  the end. Never close a loop without opening the next.
- ANTI-SLOP: one named protagonist with a clear need. Concrete, specific details
  (names, numbers, places). No generic abstractions. Every scene must advance
  the story or be cut.
- PACING: vary sentence length (short for tension, long for reflection). One
  complete idea every 60-90 seconds. ~150 words per minute. Do NOT pad to hit a
  runtime. {target_minutes} minutes is the target, not a floor to fill.
- VOICE: write to be spoken, not read. Short sentences. Active voice. Use "you".
  Brief reactive asides are encouraged ("which should have been impossible").
```

> Note: this block is universal craft. It belongs in the neutral engine template, identity-injected, so it stays separate from any one channel's voice (consistent with the engine/identity split already in `engine_templates.py`).

---

# Part 9: Implementation into StoryEngine

The code mapper confirmed the real surfaces. This section says exactly where the ruleset wires in, phased lazy-first. The pattern to copy everywhere is `backend/originality.py`: direct Anthropic call, fail-open, internal verdicts, and (most importantly) **inject the rules into prompts** so generation is good before grading is ever needed.

### The integration points (real files)

| Where | File | What goes there |
|---|---|---|
| **Generation (do this first)** | `backend/engine_templates.py` (`"script"` template, ~line 89+) | Inject the **Rubric Block (Prompt 4)** via a `{youtube_rubrics}` slot. Most videos then pass by design. Identity-injected, stays neutral. |
| **Idea gate** | `backend/routes/chat.py` -> `_generate_competitor_ideas()` (~line 400) | Run **Prompt 1 (Idea Scorer)** on the 3 proposed ideas before they reach the producer. Reorder/badge by score; silently drop rejects. |
| **Script gate** | `backend/pipeline_executor.py` -> `run_script()` (after `run_brief_translator`, ~line 1281) | Run **Prompt 2 (Script Grader)**. pass -> continue to voice; revise -> re-run the writer with `rewrite_guidance` (cap 1-2 re-rolls); regenerate -> flag. |
| **Package gate** | title skill / producer plan (`producer_prompt.py` returns 3 titles) | Run **Prompt 3 (Package Grader)** on candidate titles+thumbnail concepts; only surface high scorers. |
| **The scoring engine** | extend `backend/originality.py` | Add `assess_youtube_viability()` / `grade_script()` beside the existing `assess_draft()`. Same client, same fail-open. |

### Why extend `originality.py` and not build new

It already has: the direct-Anthropic client wrapper, the fail-open judge pattern, the "summarize recent videos so generation diverges by design" mechanism, and Walls 1 and 2 (point-of-view + distinct-plot) which ARE Stage F's template-identical gate. This ruleset is the same shape, pointed at retention/packaging instead of just originality. Reuse it.

### Phased build (lazy-first, each phase ships value alone)

- **Phase 1 - Rules in the prompt (highest ROI, smallest diff).** Add the Rubric Block (Prompt 4) to the script engine template, plus the equivalent hook/package craft lines to the producer prompt. No new LLM calls, no gates. Most output gets better immediately. *This alone is most of the win.*
- **Phase 2 - The script grader gate.** Add `grade_script()` to `originality.py`, call it in `run_script()` after generation, auto-revise once on a `revise` verdict. This is the single most enforceable gate (the but/therefore test).
- **Phase 3 - The idea scorer.** Score the 3 chat ideas before the producer shows them. Surfaces a "strong YouTube potential" badge or silently reorders. Catches weak ideas at the ceiling-setting stage.
- **Phase 4 - Package grader + learned per-channel rubrics.** Grade titles/thumbnails; and feed each channel's own top-performer patterns back in (the competitor analyzer already pulls this data) so the rubric becomes channel-specific over time.

**Lazy notes (what to NOT build yet):**
- Do not build a config UI for rubric weights. Hardcode the weights from Part 8.2; revisit only if a real channel's data says they are wrong.
- Do not build a separate rubric microservice or new tables in Phase 1-2. The prompt block needs no storage; the graders reuse `originality.py`. Add a `youtube_rubrics` per-tenant config only in Phase 4 when learned rules actually exist.
- Keep every gate **fail-open and nudge-first**, exactly like `originality.py`. Never hard-block a creator's run on a transient model error. The only true hard blocks are the Stage F monetization-safety gates (template-identical, raw-reading, deceptive), because shipping those gets the channel demonetized, which is worse than a blocked run.

### How this maps to GOAL.md

This is the substance of **Phase 4 (channel intelligence in the producer)** already named in `storyengine/GOAL.md`. The producer stops being a generic question-asker and becomes a head of programming that knows what wins. Update GOAL.md Phase 4 to point at this file when you start the build.

---

# Appendix: Sources

**Strategy / packaging / ideation:** Paddy Galloway (Creator Science podcast, Colin & Samir "New Rules of YouTube," Marketing Examined, his Accelerator) - MrBeast leaked production document (Simon Willison, Creator Handbook, Tubefilter, Daniel Scrivner summaries) - vidIQ Outliers docs (the 2x/5x/10x brackets) - 1of10, OutlierKit, Overseeros (outlier analysis).

**Retention / hooks / story:** Retention Rabbit 2025 benchmark report - SocialRails / Humble&Brag retention benchmarks - the but/therefore rule (South Park / Parker-Stone via Selfstorming, Storytelling Edge) - Dan Harmon Story Circle (StudioBinder, Reedsy) - Pixar Story Spine (Aerogramme, Kindlepreneur) - Save the Cat (StudioBinder) - Zeigarnik effect / bucket brigades (Copyhackers, Skill Arbitrage) - TubeAI script-for-retention.

**Algorithm / metrics:** YouTube official (recommendation system blog, impressions & CTR help, monetization policies, AI disclosure, YPP thresholds, Creator Insider on the publish-delay myth) - Todd Beaupré via Search Engine Journal - vidIQ algorithm guide - Dataslayer, Miraflow traffic-source breakdowns - SociaVault 75k-channel engagement study.

**Faceless / AI policy:** support.google.com/youtube/answer/1311392 (inauthentic + reused content) and /15447836 (synthetic disclosure) - Social Media Today and Search Engine Journal on the July 2025 clarification - Dexerto and Deadline on the 2025-2026 terminations (Screen Culture, KH Studio) - OutlierKit AI-slop crackdown report - Vozo, Metricool, Fluxnote faceless guides - SubSub / Knolli inauthentic-policy explainers.

**Confidence reminder:** only the YouTube-official items (`[official]`: CTR 2-10% band, YPP thresholds, policy text, disclosure rules, the publish-delay debunk) are law. Outlier brackets and retention targets are strong consensus. RPM figures and the "competition ratio" numbers are vendor models (reliable ordering, ballpark magnitudes). The "20% variation / 5+ template" numbers are rules of thumb, never quote them as policy.

---

*Built from 7 parallel research sweeps (niche, ideas, packaging, hooks, story, algorithm, faceless craft) cross-checked against primary sources, plus a code map of the live StoryEngine chat-first pipeline. 2026-06-22.*
