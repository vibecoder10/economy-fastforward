# Intelligence-teaser strategy — should the first distill be free?

**Question (Ryan, 2026-04-19 02:52 UTC):** "do we want to allow an inital intelligence pass for these people to get hooked immediately and want to upgrade etc?"

**TL;DR recommendation — no-ops today, decide in 2 weeks once we have data.**

BYOK (the user pays the upstream directly with their own keys) already gives us "free first distill" economics without building paywall plumbing. Today's WelcomeQuest lets a new user run an intelligence pass using their own Anthropic + Kie credit — costs them <$0.50, costs StoryEngine nothing. That IS the hook. The strategic question is whether to layer a StoryEngine-funded pass on TOP of that for users who haven't entered keys yet. That's a different decision and it's premature.

## The three architectures

| # | Model | Who pays the upstream | StoryEngine cost | Friction | Conversion pitch |
|---|-------|----------------------|------------------|----------|------------------|
| A | Pure BYOK (today) | User's own keys, always | $0 | Keys required before first distill | "Bring your keys, start shipping" |
| B | One free distill on signup (StoryEngine-funded) | StoryEngine up to a cap | ~$0.50/signup × conversion rate | Zero. Email + password = full-value teaser | "Show you the product before you commit a dollar" |
| C | Trial credits | StoryEngine caps a $ amount of use | Variable, caps known | Zero | "First $5 on us" |

## Why I don't think it's urgent

1. **We already have a 13-day Pro trial.** That's the existing conversion engine — "here's the whole product for free for two weeks." A separate intelligence-teaser sits on top of or duplicates that.
2. **Trial doesn't cover BYOK credit — that's the point.** Users already have to connect their keys to run anything, trial or not. The teaser would bypass that, but that means StoryEngine is absorbing upstream costs on strangers.
3. **We have zero conversion data.** We don't yet know where users drop off. It could be the TOOLS step (fixed tonight), it could be dashboard dump (fixed tonight), it could be "distilling feels abstract." Solving a guess with money on the line is bad sequencing.
4. **Attack surface.** A free-distill endpoint called by a brand-new account is a spam/abuse vector. Mitigation (rate limit per IP, require email verification, etc.) is real engineering work — worth it if the conversion lift is known, premature if it's speculative.

## What I'd do instead, in order

1. **(Shipped)** Fix the TOOLS counter so the key-entry step stops feeling broken. Done tonight — cycle 17.
2. **(Shipped)** Ship the WelcomeQuest so the post-keys experience is guided instead of a dump. Done tonight — cycle 18.
3. **Measure.** Add event tracking on: (a) onboarding-completed, (b) first-competitor-added, (c) first-distill-run, (d) first-video-created, (e) 7-day return. Two weeks of data.
4. **THEN decide.** If dropoff is at step 2 (distill) and users who DO distill convert at materially higher rates, a free-teaser is the right play. If dropoff is elsewhere, spend the money there.

## If we do add a teaser, the cleanest design

Gate it on the WelcomeQuest step 2 specifically:
- If tenant has BYOK keys → normal distill flow (step 2 works today).
- If tenant does NOT have BYOK keys yet → show a "Try one distill on us, no credit card" button that calls a StoryEngine-funded distill on ONE competitor video the user picks. Rate-limit to 1 call per tenant per lifetime. Cap total StoryEngine-funded distills per day (circuit breaker).
- Make the teaser use the SAME distillation output component as the paid flow — seeing the structured DNA breakdown IS the hook.

Roughly 2 days of engineering work: new endpoint with tenant-scoped rate limit, new CTA variant in WelcomeQuest, abuse mitigations.

## Bottom line

Ship the measurements now. Don't spend engineering time on a teaser until we can prove it'd move the number. The BYOK model already gives us a near-free hook — let's see if the UX changes tonight are enough before paying to solve a problem we haven't seen.
