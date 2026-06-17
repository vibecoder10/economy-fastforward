"""Tests for post-generation script validation (editorial voice v2)."""

import pytest
from script.brief_translator.script_validator import (
    ScriptValidationConfig,
    ScriptValidationResult,
    validate_script_editorial,
    build_retry_prompt,
    _count_specific_numbers,
    _measure_framework_density,
    _score_personal_stakes,
    _score_actionable_close,
    _count_cliffhangers_at_transitions,
    _extract_numbers_from_research,
    _extract_promises,
    _check_promise_payoff,
    _extract_topics_from_act,
    _check_act_coherence,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_brief(**overrides):
    """Create a minimal research brief dict."""
    brief = {
        "headline": "How Iran's Drone Strike Broke the AI Economy",
        "thesis": "Iran targeted Gulf capital flows funding US AI infrastructure.",
        "fact_sheet": (
            "54% of PE funding comes from Gulf sovereign wealth funds. "
            "$2 trillion in deployable capital. 33% of S&P 500 is AI exposure. "
            "Gas could hit $9/gallon within 60 days. 401k drops 15-22%. "
            "$847 billion reallocated in 18 months. 7 million barrels per day. "
            "$14 billion insurance premium. Lloyd's of London. "
            "3 trade agreements to 17 in four years. "
            "$12 billion annual trade flow. 14 Iranian targets struck. "
            "20,000 dollar drone cost. Pearl Harbor comparison. "
            "11-14 day repricing window. $500 billion defense spending."
        ),
        "historical_parallels": (
            "1973 Oil Embargo: OPEC cut production 25%, gas prices quadrupled. "
            "2008 Financial Crisis: Lehman Brothers collapsed September 15, 2008."
        ),
        "character_dossier": "Trump, MBS, Khamenei, Lloyd Austin.",
        "narrative_arc": "Trade flows disrupted, capital redirected.",
        "counter_arguments": "Gulf states may not redirect spending.",
        "framework_analysis": "Game theory applies to deterrence.",
    }
    brief.update(overrides)
    return brief


def _make_good_script():
    """Create a script that should pass all checks."""
    return """
[ACT 1 — THE LIE | 0:00-2:00 | ~350 words]
Three weeks ago, the Pentagon hit 14 Iranian targets. Not one was a nuclear
site. CNN called it a response to nuclear threats. The official story says
this was about preventing weapons of mass destruction. But here's what
doesn't add up: the targets weren't nuclear facilities. They were logistics
corridors worth $12 billion in annual trade flow. When you follow the money
instead of the missiles, you find an entirely different war. And that's
exactly what Act 3 reveals about Iran's asymmetric strategy.

[ACT 2 — THE SETUP | 2:00-6:00 | ~500 words]
To understand what's really happening, you need to know three players and
what they actually need. Trump faces prosecution if the economy falters.
He needs foreign capital — specifically, the $2 trillion in deployable
capital sitting in Gulf sovereign wealth funds. According to the
Congressional Budget Office, 54% of all private equity funding for the top
30 US AI companies comes from three Gulf sovereign wealth funds. Saudi
Arabia's PIF alone deployed $847 billion in 18 months. MBS needs US
military protection. And Iran? Tehran's entire strategy costs less than a
single US aircraft carrier group. But here's what none of this explains —
why would Iran strike oil infrastructure instead of military targets? And
that's where the insurance repricing mechanism comes in.

[ACT 3 — THE HIDDEN MECHANISM | 6:00-11:00 | ~550 words]
Iran didn't strike Ras Tanura to destroy it. They struck it to prove that
every dollar of Saudi oil wealth now exists at their mercy. One $20,000
drone against a facility processing 7 million barrels a day. That's the
asymmetry. The goal isn't destruction — it's insurance repricing. When
Lloyd's of London raises the $14 billion premium for Strait shipping, the
cost falls on every barrel. Gas prices don't rise because of a war — they
rise because of a spreadsheet calculation in London. In 1973, OPEC cut
production by 25% and gas prices quadrupled within 90 days. And that's
where historical proof of this pattern appears.

[ACT 4 — THE PROOF | 11:00-15:00 | ~500 words]
This pattern has played out five times in the last 200 years. Every time,
the attacker won. In 1973, OPEC weaponized oil and gas prices quadrupled.
Saudi Arabia's revenue jumped 300% in one year. In 2008, when Lehman
Brothers collapsed on September 15, Gulf sovereign wealth funds pulled
$340 billion from Western markets in 14 days. What you're watching is what
game theorists call a commitment device — deliberately creating shared risk
to force the other side's hand. The historical record shows what comes next:
a repricing window opens 11-14 days after the shock. And that's where your
wallet gets hit directly.

[ACT 5 — THE PERSONAL STAKES | 15:00-18:00 | ~500 words]
Here's what this means for your wallet. If this plays out the way the last
three times did, gas hits $9 within 60 days and your 401k drops 15-22%.
33% of the S&P 500 is AI exposure. Your retirement fund has more exposure
to Gulf capital flows than you think. The strongest case against this? Gulf
states won't redirect $500 billion in defense spending because the returns
on US tech investments are too high. But the evidence says otherwise — in
every previous case, security spending won over investment returns. And
that's where the specific play comes in.

[ACT 6 — THE PLAY | 18:00-20:00 | ~400 words]
So what do you actually do with this information? The repricing window opens
11-14 days after the shock. That's when smart money has moved in every
conflict since Pearl Harbor. Position your wallet before the repricing, not
during it. Watch for the Lloyd's premium announcement — when insurance
costs spike, energy stocks follow within 48 hours. Here's the play: watch
the energy sector ETFs and the VIX. When you see insurance premiums cross
the $15 billion threshold, that's your signal. You now know what a
commitment device looks like in real time. When you see asymmetric strikes
on economic infrastructure, ask who benefits from the insurance repricing.
When Gulf sovereign wealth funds start moving, look for the 11-14 day
pattern. The question isn't whether the system works this way. You just
watched it happen. The question is whether you position yourself before or
after everyone else figures it out.
"""


def _make_bad_script():
    """Create a script that should fail most checks — framework-heavy, no numbers."""
    return """
[ACT 1 — THE LIE | 0:00-2:00 | ~350 words]
In the world of geopolitics, power is rarely what it seems. The recent
events in the Middle East demonstrate a complex web of alliances and
rivalries that most people don't understand. The official narrative tells
us one thing, but the deeper dynamics reveal something far more
significant.

[ACT 2 — THE SETUP | 2:00-6:00 | ~500 words]
To understand this situation, we must examine the Machiavellian dynamics at
play. Machiavelli wrote in The Prince that consolidating power requires
eliminating rival factions. The game theory framework shows us that this is
a classic prisoner's dilemma. Sun Tzu's Art of War teaches that the supreme
art of war is to subdue the enemy without fighting. Thucydides identified
the trap where a rising power threatens an established one.

[ACT 3 — THE MECHANISM | 6:00-11:00 | ~550 words]
The Thucydides Trap framework explains the fundamental tension at work.
When we apply Brzezinski's Grand Chessboard analysis, we see that the
geographic control of the region is paramount. Kindleberger's theory of
hegemonic stability suggests that the withdrawal of the stabilizer creates
chaos. Systems thinking reveals feedback loops that amplify the crisis.
Behavioral economics shows us the sunk cost fallacy at work.

[ACT 4 — THE MIRROR | 11:00-15:00 | ~500 words]
Throughout history, similar patterns have emerged. The balance of power
doctrine explains the shifting alliances. Schelling's focal point theory
shows how adversaries coordinate. The collective action problem identified
by Mancur Olson demonstrates why organized minorities prevail over
disorganized majorities. Evolutionary psychology shows the tribal instincts
driving these decisions.

[ACT 5 — THE STAKES | 15:00-18:00 | ~500 words]
This situation affects ordinary citizens in several ways. The implications
are far-reaching and significant. Many experts believe that the
consequences will be substantial. It's important to understand that these
dynamics shape our world in profound ways. Throughout history, similar
situations have led to important changes.

[ACT 6 — THE LESSON | 18:00-20:00 | ~400 words]
Understanding these dynamics helps us navigate an uncertain world. The
frameworks we've discussed — Machiavelli, Thucydides, game theory, Sun
Tzu, and systems thinking — provide a comprehensive lens for understanding
power. In conclusion, being aware of these power dynamics is essential for
any informed citizen. The patterns will continue to unfold as history
marches on.
"""


# ---------------------------------------------------------------------------
# Test: Number density counting
# ---------------------------------------------------------------------------

class TestNumberDensity:
    def test_dollar_amounts(self):
        text = "Cost was $12 billion. Revenue hit $3.5 million."
        count, found = _count_specific_numbers(text)
        assert count >= 2
        assert any("$12" in n for n in found)

    def test_percentages(self):
        text = "Growth was 54%. Decline was 3.5%."
        count, found = _count_specific_numbers(text)
        assert count >= 2

    def test_dates(self):
        text = "On January 14, 2024 the crisis began. By March 2026 it ended."
        count, found = _count_specific_numbers(text)
        assert count >= 2

    def test_years(self):
        text = "In 1973 the embargo started. By 2008 it had collapsed."
        count, found = _count_specific_numbers(text)
        assert count >= 2

    def test_counts_with_units(self):
        text = "14 targets were struck by 120 missiles."
        count, found = _count_specific_numbers(text)
        assert count >= 2

    def test_act_markers_excluded(self):
        text = "[ACT 1 — THE LIE | 0:00-2:00 | ~350 words] The cost was $12."
        count, found = _count_specific_numbers(text)
        # Should count $12 but not "1", "350"
        assert any("$12" in n for n in found)

    def test_good_script_meets_minimum(self):
        script = _make_good_script()
        count, found = _count_specific_numbers(script)
        assert count >= 19, f"Good script only has {count} numbers: {found}"

    def test_bad_script_below_minimum(self):
        script = _make_bad_script()
        count, _ = _count_specific_numbers(script)
        assert count < 19, f"Bad script should have fewer than 19 numbers, got {count}"

    def test_extract_from_research(self):
        brief = _make_brief()
        numbers = _extract_numbers_from_research(brief)
        assert len(numbers) >= 10, f"Expected 10+ numbers in research, got {len(numbers)}"


# ---------------------------------------------------------------------------
# Test: Framework density
# ---------------------------------------------------------------------------

class TestFrameworkDensity:
    def test_clean_script_low_density(self):
        text = (
            "Iran struck the facility. The cost was minimal. "
            "Gulf states redirected capital. Markets responded. "
            "Insurance premiums spiked. Energy stocks followed."
        )
        pct, fw, total = _measure_framework_density(text)
        assert pct < 0.15

    def test_framework_heavy_script(self):
        text = (
            "Machiavelli wrote about power consolidation. "
            "The Thucydides Trap explains this dynamic. "
            "Sun Tzu's Art of War applies here. "
            "Game theory shows the Nash equilibrium. "
            "Kindleberger's theory predicts collapse. "
            "Behavioral economics explains the bias."
        )
        pct, fw, total = _measure_framework_density(text)
        assert pct > 0.50  # Most sentences have framework refs

    def test_bad_script_exceeds_max(self):
        script = _make_bad_script()
        pct, _, _ = _measure_framework_density(script)
        assert pct > 0.15, f"Bad script should exceed 15% framework density, got {pct:.0%}"


# ---------------------------------------------------------------------------
# Test: Personal stakes
# ---------------------------------------------------------------------------

class TestPersonalStakes:
    def test_good_stakes_language(self):
        text = (
            "Here's what this means for your wallet. Your 401k drops 15%. "
            "Gas hits $9 per gallon. You pay more at the pump."
        )
        score, matches = _score_personal_stakes(text)
        assert score >= 3

    def test_no_stakes_language(self):
        text = (
            "The situation affects geopolitical dynamics. "
            "Markets may respond to these developments. "
            "Experts predict significant changes ahead."
        )
        score, _ = _score_personal_stakes(text)
        assert score == 0

    def test_good_script_has_stakes(self):
        script = _make_good_script()
        score, _ = _score_personal_stakes(script)
        assert score >= 3

    def test_bad_script_lacks_stakes(self):
        script = _make_bad_script()
        score, _ = _score_personal_stakes(script)
        assert score < 3


# ---------------------------------------------------------------------------
# Test: Actionable close
# ---------------------------------------------------------------------------

class TestActionableClose:
    def test_strong_close(self):
        text = (
            "So what do you actually do with this? Position yourself before "
            "the repricing. Watch for the Lloyd's announcement. Smart money "
            "moved 11 days after similar events."
        )
        score, matches = _score_actionable_close(text)
        assert score >= 2

    def test_weak_close(self):
        text = (
            "Understanding these dynamics helps us navigate. "
            "In conclusion, awareness is key. "
            "The world continues to evolve."
        )
        score, _ = _score_actionable_close(text)
        assert score < 2

    def test_good_script_close(self):
        script = _make_good_script()
        words = script.split()
        final = " ".join(words[int(len(words) * 0.80):])
        score, _ = _score_actionable_close(final)
        assert score >= 2

    def test_bad_script_close(self):
        script = _make_bad_script()
        words = script.split()
        final = " ".join(words[int(len(words) * 0.80):])
        score, _ = _score_actionable_close(final)
        assert score < 2


# ---------------------------------------------------------------------------
# Test: Cliffhangers
# ---------------------------------------------------------------------------

class TestCliffhangers:
    def test_good_script_has_cliffhangers(self):
        script = _make_good_script()
        # Parse acts manually (simplified)
        acts = {}
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        found, expected = _count_cliffhangers_at_transitions(script, acts)
        assert found >= 3, f"Expected 3+ cliffhangers, found {found}"

    def test_no_cliffhangers(self):
        acts = {
            1: "The official story is simple. Nothing more to see here.",
            2: "The background is straightforward. Moving on.",
            3: "The mechanism is clear. That's all.",
            4: "The proof is evident.",
        }
        found, expected = _count_cliffhangers_at_transitions("", acts)
        assert found == 0
        assert expected == 3


# ---------------------------------------------------------------------------
# Test: Full validation
# ---------------------------------------------------------------------------

class TestFullValidation:
    def test_good_script_passes(self):
        script = _make_good_script()
        brief = _make_brief()
        # Parse acts
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        result = validate_script_editorial(script, brief, acts)
        assert result.passed, f"Good script should pass:\n{result.summary}"

    def test_bad_script_default_only_runs_universal_checks(self):
        """By default (no profile), only the universal craft checks run.

        The identity-specific checks (number_density, framework_density,
        personal_stakes, actionable_close) are OFF by default so a non-Power-
        Doctrine script is never failed for failing to sound like Power
        Doctrine. The bad script still fails on a universal check (it has no
        cliffhangers), but NOT on any identity check.
        """
        script = _make_bad_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        result = validate_script_editorial(script, brief, acts)
        ran = {c.name for c in result.checks}
        # Identity checks must NOT run by default
        assert "number_density" not in ran
        assert "framework_density" not in ran
        assert "personal_stakes" not in ran
        assert "actionable_close" not in ran
        # Universal checks DO run
        assert "cliffhanger_presence" in ran
        assert "promise_payoff" in ran
        assert "act_coherence" in ran

    def test_bad_script_fails_identity_checks_when_enabled(self):
        """When a profile re-enables the identity checks (as Power Doctrine
        does), the bad script fails them exactly as before."""
        script = _make_bad_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        config = ScriptValidationConfig(
            number_density_check=True,
            framework_density_check=True,
            personal_stakes_check=True,
            actionable_close_check=True,
        )
        result = validate_script_editorial(script, brief, acts, config=config)
        assert not result.passed, "Bad script should fail validation"
        failed_names = [c.name for c in result.failed_checks]
        assert "number_density" in failed_names
        assert "framework_density" in failed_names
        assert "personal_stakes" in failed_names
        assert "actionable_close" in failed_names

    def test_config_disables_checks(self):
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(
            number_density_check=False,
            framework_density_check=False,
            personal_stakes_check=False,
            actionable_close_check=False,
            cliffhanger_check=False,
            promise_payoff_check=False,
            act_coherence_check=False,
        )
        result = validate_script_editorial(script, brief, {}, config=config)
        assert result.passed  # No checks = passes
        assert len(result.checks) == 0

    def test_to_dict(self):
        script = _make_good_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        result = validate_script_editorial(script, brief, acts)
        d = result.to_dict()
        assert "passed" in d
        assert "checks" in d
        assert isinstance(d["checks"], list)


# ---------------------------------------------------------------------------
# Test: Retry prompt builder
# ---------------------------------------------------------------------------

class TestRetryPrompt:
    def test_builds_prompt_with_failed_checks(self):
        script = _make_bad_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            act_num = int(parts[i])
            act_text = parts[i + 1] if i + 1 < len(parts) else ""
            acts[act_num] = act_text

        result = validate_script_editorial(script, brief, acts)
        retry = build_retry_prompt("Original prompt here", script, result)

        assert "REVISION REQUIRED" in retry
        assert "PREVIOUS SCRIPT" in retry
        assert "ISSUES TO FIX" in retry
        assert "Original prompt here" in retry

    def test_includes_specific_number_from_research(self):
        # Number density is an opt-in (identity) check — enable it explicitly
        # to exercise the retry-prompt machinery.
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(number_density_check=True)
        result = validate_script_editorial(script, brief, {}, config=config)
        retry = build_retry_prompt("Prompt", script, result)
        # Should suggest unused numbers from research
        assert "$" in retry or "%" in retry

    def test_number_retry_lists_unused_research_numbers(self):
        """Number density retry should list specific unused numbers from research.

        Number density is an opt-in (identity) check, so enable it explicitly.
        """
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(number_density_check=True)
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""

        result = validate_script_editorial(script, brief, acts, config=config)
        number_check = next(c for c in result.checks if c.name == "number_density")
        assert not number_check.passed
        # Retry should contain actual dollar amounts from research
        assert "$2 trillion" in number_check.retry_prompt or "$847 billion" in number_check.retry_prompt
        assert "UNUSED NUMBERS FROM RESEARCH" in number_check.retry_prompt
        assert "ALREADY IN SCRIPT" in number_check.retry_prompt

    def test_framework_retry_identifies_heavy_acts(self):
        """Framework density retry should name specific acts that are heavy.

        Framework density is an opt-in (identity) check, so enable it explicitly.
        """
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(framework_density_check=True)
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""

        result = validate_script_editorial(script, brief, acts, config=config)
        fw_check = next(c for c in result.checks if c.name == "framework_density")
        assert not fw_check.passed
        assert "WORST OFFENDERS" in fw_check.retry_prompt
        # Acts 2, 3, 4 are all framework-heavy in the bad script
        assert "Act 2" in fw_check.retry_prompt or "Act 3" in fw_check.retry_prompt

    def test_personal_stakes_retry_includes_research_figures(self):
        """Personal stakes retry should pull actual figures from research.

        Personal stakes is an opt-in (identity) check, so enable it explicitly.
        The retry no longer hard-requires Power-Doctrine phrasing (e.g.
        'your wallet'); it just surfaces real figures and asks for direct,
        topic-appropriate stakes.
        """
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(personal_stakes_check=True)
        result = validate_script_editorial(script, brief, {}, config=config)
        stakes_check = next(c for c in result.checks if c.name == "personal_stakes")
        assert not stakes_check.passed
        # Should surface actual prices/percentages from research
        assert "Prices/amounts:" in stakes_check.retry_prompt
        assert "Percentages:" in stakes_check.retry_prompt
        assert "$" in stakes_check.retry_prompt
        # Neutral: addresses the viewer directly, but no fixed PD finance phrase
        assert "your" in stakes_check.retry_prompt.lower()
        assert "your wallet" not in stakes_check.retry_prompt
        assert "401k" not in stakes_check.retry_prompt

    def test_actionable_close_retry_has_3_phase_structure(self):
        """Actionable close retry should include 3-phase market template.

        Actionable close is an opt-in (identity) check, so enable it explicitly.
        """
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(actionable_close_check=True)
        result = validate_script_editorial(script, brief, {}, config=config)
        close_check = next(c for c in result.checks if c.name == "actionable_close")
        assert not close_check.passed
        assert "Phase 1" in close_check.retry_prompt
        assert "Phase 2" in close_check.retry_prompt
        assert "Phase 3" in close_check.retry_prompt
        assert "HISTORICAL DATA FROM RESEARCH" in close_check.retry_prompt

    def test_cliffhanger_retry_names_specific_acts(self):
        """Cliffhanger retry should identify exact acts missing cliffhangers."""
        acts = {
            1: "The official story is simple. Nothing more to see here.",
            2: "The background is straightforward. Moving on.",
            3: "The mechanism is clear. That's all.",
            4: "The proof is evident.",
        }
        brief = _make_brief()
        result = validate_script_editorial("", brief, acts)
        cliff_check = next(c for c in result.checks if c.name == "cliffhanger_presence")
        assert not cliff_check.passed
        assert "Missing after Acts" in cliff_check.retry_prompt
        # All non-final acts should be listed
        assert "Act 1" in cliff_check.retry_prompt
        assert "Act 2" in cliff_check.retry_prompt
        assert "Act 3" in cliff_check.retry_prompt
        # Should include next-act content for teasers
        assert "Next act opens with" in cliff_check.retry_prompt


# ---------------------------------------------------------------------------
# Test: Promise-Payoff Tracking (Check 6)
# ---------------------------------------------------------------------------

class TestPromisePayoff:
    def test_extracts_act_references(self):
        """Should extract promises that reference specific acts."""
        acts = {
            1: "That's exactly what Act 3 reveals about the money trail.",
            2: "Building context here.",
            3: "The money trail shows $500M moved offshore.",
        }
        script = "\n".join(f"[ACT {i}]\n{t}" for i, t in acts.items())
        promises = _extract_promises(script, acts)
        assert len(promises) >= 1
        target_3 = [p for p in promises if p.get("target_act") == 3]
        assert len(target_3) >= 1

    def test_extracts_forward_teases(self):
        """Should extract forward-looking promises."""
        acts = {
            1: "What you'll see in the next section changes everything.",
            2: "The hidden mechanism revealed.",
        }
        script = "\n".join(f"[ACT {i}]\n{t}" for i, t in acts.items())
        promises = _extract_promises(script, acts)
        assert len(promises) >= 1

    def test_resolved_promise_passes(self):
        """Promise should pass if content appears in target act."""
        acts = {
            1: "What you'll see next is the money trail.",
            2: "The money trail leads to offshore accounts.",
        }
        script = "\n".join(f"[ACT {i}]\n{t}" for i, t in acts.items())
        passed, broken, detail = _check_promise_payoff(script, acts)
        assert passed
        assert len(broken) == 0

    def test_broken_promise_fails(self):
        """Promise should fail if content doesn't appear."""
        acts = {
            1: "That's exactly what Act 3 reveals about the conspiracy.",
            2: "Building context.",
            3: "Completely unrelated content about weather patterns.",
        }
        script = "\n".join(f"[ACT {i}]\n{t}" for i, t in acts.items())
        passed, broken, detail = _check_promise_payoff(script, acts)
        assert not passed
        assert len(broken) >= 1

    def test_nonexistent_act_reference_fails(self):
        """Promise referencing non-existent act should fail."""
        acts = {
            1: "That's exactly what Act 7 covers in detail.",
            2: "More content here.",
        }
        script = "\n".join(f"[ACT {i}]\n{t}" for i, t in acts.items())
        passed, broken, detail = _check_promise_payoff(script, acts)
        assert not passed
        # Act 7 doesn't exist, so the promise can't be resolved
        assert any("Act 7" in b["resolution_detail"] for b in broken)

    def test_good_script_passes_promise_check(self):
        """Good script should have all promises resolved."""
        script = _make_good_script()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""

        passed, broken, detail = _check_promise_payoff(script, acts)
        # Good script has cliffhangers but they should be resolvable
        if not passed:
            for b in broken:
                print(f"Broken: {b}")
        assert passed, f"Good script promises should be resolved: {detail}"


# ---------------------------------------------------------------------------
# Test: Act Coherence / Topic Drift (Check 7)
# ---------------------------------------------------------------------------

class TestActCoherence:
    def test_detects_topic_drift(self):
        """Should detect multiple distinct topics in one act."""
        drift_text = """
        Apple's iPhone sales dropped 20% in America. Tim Cook blamed inflation.

        Vladimir Putin met with Kim Jong Un in Moscow. Russia and North Korea
        signed defense agreements.

        Bitcoin crashed to $40,000. Crypto investors panicked.

        SpaceX launched its Starship rocket. Elon Musk celebrated.
        """
        topics = _extract_topics_from_act(drift_text)
        assert len(topics) >= 3, f"Expected 3+ topic shifts, got {len(topics)}"

    def test_coherent_act_passes(self):
        """Single-topic act should pass coherence check."""
        coherent_text = """
        Apple's iPhone market in China is collapsing. The company reported a 20%
        drop in quarterly revenue. Tim Cook blamed local competition.

        The iPhone 15 was supposed to reverse the trend. But Chinese consumers
        prefer domestic brands like Huawei and Xiaomi.

        Analysts predict further decline for Apple in the Chinese market. The
        company's China strategy needs a complete overhaul.
        """
        topics = _extract_topics_from_act(coherent_text)
        # Should have fewer than 3 topic shifts
        assert len(topics) < 3

    def test_check_act_coherence_flags_drifting(self):
        """Full check should flag acts with 3+ topics."""
        drift_text = """
        Apple's iPhone dropped. Tim Cook blamed inflation.

        Putin met with Kim Jong Un. Russia and North Korea signed deals.

        Bitcoin crashed. Crypto investors panicked.

        SpaceX launched Starship. Elon Musk celebrated.
        """
        acts = {1: drift_text}
        passed, drifting, detail = _check_act_coherence(acts, max_topics_per_act=3)
        assert not passed
        assert 1 in drifting

    def test_check_act_coherence_passes_coherent(self):
        """Acts with focused content should pass."""
        acts = {
            1: "Iran struck the oil facility. Saudi Arabia responded. Oil prices rose.",
            2: "The insurance industry calculated the risk. Lloyd's raised premiums.",
        }
        passed, drifting, detail = _check_act_coherence(acts, max_topics_per_act=3)
        assert passed
        assert len(drifting) == 0


# ---------------------------------------------------------------------------
# Test: Config defaults
# ---------------------------------------------------------------------------

class TestConfig:
    def test_default_values(self):
        config = ScriptValidationConfig()
        # Thresholds are unchanged (still used when a profile opts the
        # corresponding check in)…
        assert config.number_density_min == 19
        assert config.framework_max_pct == 0.15
        assert config.personal_stakes_min_score == 1  # lowered: one match is enough
        assert config.actionable_close_min_score == 2
        # …but the identity-specific CHECKS are OFF by default so a non-Power-
        # Doctrine channel is never gated on PD voice.
        assert config.number_density_check is False
        assert config.framework_density_check is False
        assert config.personal_stakes_check is False
        assert config.actionable_close_check is False
        # New defaults: validation is blocking
        assert config.max_retries == 1
        assert config.retry_on_fail is True
        # Universal craft checks enabled by default
        assert config.cliffhanger_check is True
        assert config.promise_payoff_check is True
        assert config.act_coherence_check is True
        assert config.act_coherence_max_topics == 6  # lenient: multi-subject acts

    def test_custom_values(self):
        config = ScriptValidationConfig(
            number_density_min=10,
            framework_max_pct=0.25,
            max_retries=1,
        )
        assert config.number_density_min == 10
        assert config.framework_max_pct == 0.25
        assert config.max_retries == 1

    def test_from_profile(self):
        from shared.profiles.script.schema import (
            ScriptProfile,
            ValidationConfig,
            NumberDensityConfig,
            FrameworkIntegrationConfig,
        )

        profile = ScriptProfile(
            validation=ValidationConfig(
                number_density_check=True,
                framework_max_pct_check=False,
                personal_stakes_presence=True,
                actionable_ending_check=False,
                cliffhanger_check=True,
                retry_on_fail=False,
                max_retries=5,
            ),
            number_density=NumberDensityConfig(minimum_total=25),
            framework_integration=FrameworkIntegrationConfig(max_runtime_pct=0.10),
        )

        config = ScriptValidationConfig.from_profile(profile)
        assert config.number_density_check is True
        assert config.number_density_min == 25
        assert config.framework_density_check is False
        assert config.framework_max_pct == 0.10
        assert config.personal_stakes_check is True
        assert config.actionable_close_check is False
        assert config.cliffhanger_check is True
        # New checks always enabled for profiles
        assert config.promise_payoff_check is True
        assert config.act_coherence_check is True
        # Validation is blocking (override profile setting)
        assert config.retry_on_fail is True
        assert config.max_retries == 1

    def test_from_production_profile(self):
        """Ensure the production power_doctrine_v2 profile loads correctly."""
        from shared.profiles.script import load_script_profile

        profile = load_script_profile("power_doctrine_v2")
        assert profile is not None
        config = ScriptValidationConfig.from_profile(profile)
        assert config.number_density_min == 19
        assert config.framework_max_pct == 0.15
        # Validation is now blocking
        assert config.retry_on_fail is True
        assert config.max_retries == 1
        # New checks enabled
        assert config.promise_payoff_check is True
        assert config.act_coherence_check is True


# ---------------------------------------------------------------------------
# Test: Full validation with new checks
# ---------------------------------------------------------------------------

class TestFullValidationWithNewChecks:
    def test_good_script_passes_default_universal_checks(self):
        """By default only the 3 universal checks run, and a good script passes."""
        script = _make_good_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""

        result = validate_script_editorial(script, brief, acts)

        check_names = [c.name for c in result.checks]
        # Default = universal craft checks only
        assert set(check_names) == {
            "cliffhanger_presence", "promise_payoff", "act_coherence",
        }

        if not result.passed:
            failed = [c for c in result.checks if not c.passed]
            for c in failed:
                print(f"FAILED: {c.name}: {c.detail}")
        assert result.passed, f"Good script should pass all checks:\n{result.summary}"

    def test_good_pd_script_passes_all_7_checks_when_enabled(self):
        """When all checks are enabled (Power Doctrine profile), the
        Power-Doctrine-style good script still passes all 7 checks."""
        script = _make_good_script()
        brief = _make_brief()
        import re
        act_pattern = re.compile(r"\[ACT\s+(\d+).*?\]")
        parts = act_pattern.split(script)
        acts = {}
        for i in range(1, len(parts), 2):
            acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""

        config = ScriptValidationConfig(
            number_density_check=True,
            framework_density_check=True,
            personal_stakes_check=True,
            actionable_close_check=True,
        )
        result = validate_script_editorial(script, brief, acts, config=config)

        check_names = [c.name for c in result.checks]
        assert "promise_payoff" in check_names
        assert "act_coherence" in check_names
        assert len(check_names) == 7

        if not result.passed:
            failed = [c for c in result.checks if not c.passed]
            for c in failed:
                print(f"FAILED: {c.name}: {c.detail}")
        assert result.passed, f"Good script should pass all checks:\n{result.summary}"

    def test_disabling_new_checks(self):
        """New checks can be disabled via config."""
        script = _make_bad_script()
        brief = _make_brief()
        config = ScriptValidationConfig(
            number_density_check=False,
            framework_density_check=False,
            personal_stakes_check=False,
            actionable_close_check=False,
            cliffhanger_check=False,
            promise_payoff_check=False,
            act_coherence_check=False,
        )
        result = validate_script_editorial(script, brief, {}, config=config)
        assert result.passed  # No checks = passes
        assert len(result.checks) == 0


# ---------------------------------------------------------------------------
# Test: Non-Power-Doctrine scripts pass the (now identity-neutral) validator
# ---------------------------------------------------------------------------

def _parse_acts(script):
    """Parse [ACT N ...] markers into {act_num: text}."""
    import re
    acts = {}
    parts = re.compile(r"\[ACT\s+(\d+).*?\]").split(script)
    for i in range(1, len(parts), 2):
        acts[int(parts[i])] = parts[i + 1] if i + 1 < len(parts) else ""
    return acts


def _make_esl_story_script():
    """A simple ESL kids' story: NO statistics, NO historical parallels,
    NO 'your 401k' / 'position yourself', NO framework names.

    It uses gentle, story-appropriate forward pulls at act transitions so the
    universal retention checks are satisfied — without any Power Doctrine voice.
    """
    return """
[ACT 1 — THE NEW SCHOOL]
Mia was the new girl at Sunny Hill School. On her first morning she stood by
the gate and felt very shy. She did not know anyone, and her tummy felt full
of butterflies. A friendly dog named Pip sat near the gate and wagged his
tail. And what you'll see next is how a lost lunchbox at lunchtime gave shy
Mia her first chance to help.

[ACT 2 — THE LOST LUNCHBOX]
At lunchtime, a boy named Sam could not find his red lunchbox. He looked sad,
and his eyes filled with tears. Mia remembered seeing a red lunchbox by the
gate where Pip was sitting. She wanted to help, but she was still too shy to
speak. What you'll see next is the brave moment when shy Mia finally used her
voice to help Sam.

[ACT 3 — THE BRAVE VOICE]
Mia took a brave breath and used her voice. "I think I saw your red lunchbox
by the gate," she said to Sam softly. Sam smiled a big bright smile. Together
they ran to the gate, and there was the red lunchbox, safe with Pip. Sam was
so happy that he asked Mia to sit with him at lunch.

[ACT 4 — A NEW FRIEND]
From that day on, Mia and Sam ate lunch together every day. The butterflies
in her tummy were gone. Now you know that being kind, even when you feel shy,
can turn a scary day into a happy one. When you feel nervous, take a brave
breath and try one small kind thing. That is how shy Mia used her voice and
made her very first friend.
"""


def _make_esl_brief():
    """A simple research brief for the ESL story — no fact sheet stats,
    no historical parallels, no character dossier, no framework analysis."""
    return {
        "headline": "Mia's First Day: A Story About Kindness",
        "thesis": "A shy new student learns that small acts of kindness make friends.",
        "narrative_arc": (
            "Mia is shy on her first day. She helps a classmate find his lost "
            "lunchbox and makes her first friend, learning to be brave and kind."
        ),
    }


def _make_cooking_script():
    """A cooking how-to: amounts appear but there is no PD finance/markets
    framing, no framework names, no 'your 401k' / 'position yourself'."""
    return """
[ACT 1 — WHAT YOU'LL MAKE]
Today we are making soft, fluffy pancakes from scratch. They are golden on
the outside and light on the inside, and you only need a handful of simple
ingredients. What you'll see next is how to mix the batter so it stays light
and never turns out tough.

[ACT 2 — THE BATTER]
Whisk the flour, baking powder, and a pinch of salt in a bowl. In another
bowl, beat the eggs with the milk and a little melted butter. Pour the wet
batter into the dry mix and stir gently — just until it comes together, so it
stays light and not tough. In the next part you'll see the resting trick that
makes the batter rise.

[ACT 3 — THE REST]
Let the batter rest for ten minutes. This is the resting trick: resting lets
the flour relax and the bubbles settle, so the batter will rise and the
pancakes turn out tender. While it rests, warm your pan over medium heat. What
you'll see next is how to cook and flip them so each one turns golden.

[ACT 4 — COOKING AND SERVING]
Pour a small ladle of batter into the warm pan. When you see little bubbles
form on top, it's time to flip and cook the other side until golden. Now you
know how to make tender pancakes at home. Stack them up, add your favorite
topping, and enjoy.
"""


class TestNonPowerDoctrineScriptsPass:
    """A non-PD script must PASS the validator under default (no-profile)
    settings — proving the validator no longer enforces Power Doctrine
    identity (statistics, historical parallels, '401k', framework names)."""

    def test_esl_story_has_no_pd_identity_markers(self):
        """Sanity check: the ESL story genuinely lacks PD identity markers."""
        script = _make_esl_story_script()
        # No statistics-as-identity: well below the PD number-density floor
        count, _ = _count_specific_numbers(script)
        assert count < ScriptValidationConfig().number_density_min
        # No framework-author voice
        pct, _, _ = _measure_framework_density(script)
        assert pct == 0.0
        # No Power-Doctrine personal-finance framing
        lower = script.lower()
        assert "401k" not in lower
        assert "your wallet" not in lower
        assert "position yourself" not in lower
        assert "smart money" not in lower

    def test_esl_story_passes_default_validator(self):
        """The ESL story PASSES the validator with default settings."""
        script = _make_esl_story_script()
        brief = _make_esl_brief()
        acts = _parse_acts(script)

        result = validate_script_editorial(script, brief, acts)

        # Only universal craft checks run — no identity checks
        ran = {c.name for c in result.checks}
        assert "number_density" not in ran
        assert "framework_density" not in ran
        assert "personal_stakes" not in ran
        assert "actionable_close" not in ran

        if not result.passed:
            for c in result.failed_checks:
                print(f"FAILED: {c.name}: {c.detail}")
        assert result.passed, (
            "A simple ESL kids' story (no stats, no parallels, no '401k') must "
            f"PASS the neutralized validator:\n{result.summary}"
        )

    def test_cooking_script_passes_default_validator(self):
        """A cooking how-to also PASSES the validator with default settings."""
        script = _make_cooking_script()
        brief = {
            "headline": "Fluffy Pancakes From Scratch",
            "thesis": "Resting the batter makes tender pancakes.",
            "narrative_arc": "Mix, rest, cook, serve fluffy pancakes.",
        }
        acts = _parse_acts(script)

        result = validate_script_editorial(script, brief, acts)
        if not result.passed:
            for c in result.failed_checks:
                print(f"FAILED: {c.name}: {c.detail}")
        assert result.passed, (
            f"A cooking how-to must PASS the neutralized validator:\n{result.summary}"
        )

    def test_esl_story_would_have_failed_under_pd_gates(self):
        """Proof of WHY this matters: with the old Power Doctrine gates turned
        ON, the very same ESL story is REJECTED — for lacking statistics,
        finance stakes, and an investment-style close it has no business
        containing. The neutral default is what unblocks it."""
        script = _make_esl_story_script()
        brief = _make_esl_brief()
        acts = _parse_acts(script)

        pd_config = ScriptValidationConfig(
            number_density_check=True,
            framework_density_check=True,
            personal_stakes_check=True,
            actionable_close_check=True,
        )
        result = validate_script_editorial(script, brief, acts, config=pd_config)
        assert not result.passed
        failed = {c.name for c in result.failed_checks}
        # It fails the identity gates it should never have been held to
        assert "number_density" in failed
        assert "personal_stakes" in failed
        assert "actionable_close" in failed
