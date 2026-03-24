"""Tests for production readiness validation."""

import pytest
from brief_translator.validator import (
    parse_validation_xml,
    evaluate_validation,
    build_validation_prompt,
    format_validation_summary,
    CRITERIA_NAMES,
)


# --- Sample validation XML responses ---

SAMPLE_PASS_RESPONSE = """
<validation>
  <criterion name="hook_strength" score="PASS">
    Strong opening with specific $1.25 trillion merger event.
  </criterion>
  <criterion name="fact_density" score="PASS">
    18 verified data points spanning corporate structure, financials, and timeline.
  </criterion>
  <criterion name="framework_depth" score="PASS">
    Four Machiavellian principles mapped to specific corporate moves.
  </criterion>
  <criterion name="historical_parallel_richness" score="PASS">
    East India Company and Standard Oil parallels with detailed point-by-point mappings.
  </criterion>
  <criterion name="character_visualizability" score="PASS">
    Clear central figure with multiple visual settings available.
  </criterion>
  <criterion name="implication_specificity" score="PASS">
    Three concrete scenarios with specific timelines and measurable outcomes.
  </criterion>
  <criterion name="visual_variety" score="WEAK">
    5 visual seeds present but only 1 maps to Schema style.
  </criterion>
  <criterion name="structural_completeness" score="PASS">
    All six acts can be filled with substantial content.
  </criterion>
  <overall_verdict>READY</overall_verdict>
  <gaps></gaps>
</validation>
"""

SAMPLE_NEEDS_SUPPLEMENT_RESPONSE = """
<validation>
  <criterion name="hook_strength" score="PASS">
    Good opening hook with specific event.
  </criterion>
  <criterion name="fact_density" score="WEAK">
    Only 10 data points found, need at least 15.
  </criterion>
  <criterion name="framework_depth" score="PASS">
    Three framework mappings present.
  </criterion>
  <criterion name="historical_parallel_richness" score="FAIL">
    Only one historical parallel with vague details.
  </criterion>
  <criterion name="character_visualizability" score="PASS">
    Central figure clearly identified.
  </criterion>
  <criterion name="implication_specificity" score="WEAK">
    Implications are somewhat vague.
  </criterion>
  <criterion name="visual_variety" score="PASS">
    Good variety across all three styles.
  </criterion>
  <criterion name="structural_completeness" score="WEAK">
    Act 4 is thin without a strong second historical parallel.
  </criterion>
  <overall_verdict>NEEDS_SUPPLEMENT</overall_verdict>
  <gaps>
    1. Historical parallels lack specific visualizable scenes. Need concrete settings, dates, and figures for a second historical parallel.
    2. Fact density needs 5+ additional data points with specific dates and figures.
    3. Implication section needs concrete future scenarios with measurable predictions.
  </gaps>
</validation>
"""

SAMPLE_REJECT_RESPONSE = """
<validation>
  <criterion name="hook_strength" score="FAIL">
    No specific opening event or statistic provided.
  </criterion>
  <criterion name="fact_density" score="FAIL">
    Only 5 data points, severely insufficient.
  </criterion>
  <criterion name="framework_depth" score="FAIL">
    No clear framework identified.
  </criterion>
  <criterion name="historical_parallel_richness" score="FAIL">
    No historical parallels provided.
  </criterion>
  <criterion name="character_visualizability" score="WEAK">
    Topic is systemic with no clear visual proxy.
  </criterion>
  <criterion name="implication_specificity" score="FAIL">
    Only vague statements about potential consequences.
  </criterion>
  <criterion name="visual_variety" score="FAIL">
    Only 2 visual seeds, none map to Echo style.
  </criterion>
  <criterion name="structural_completeness" score="FAIL">
    Acts 3, 4, and 5 cannot be filled.
  </criterion>
  <overall_verdict>REJECT</overall_verdict>
  <gaps>
    This brief is fundamentally insufficient for video production.
  </gaps>
</validation>
"""


class TestParseValidationXML:
    def test_parses_pass_response(self):
        result = parse_validation_xml(SAMPLE_PASS_RESPONSE)
        assert len(result["criteria"]) == 8
        assert result["overall_verdict"] == "READY"
        assert result["gaps"] == ""

    def test_parses_needs_supplement_response(self):
        result = parse_validation_xml(SAMPLE_NEEDS_SUPPLEMENT_RESPONSE)
        assert len(result["criteria"]) == 8
        assert result["overall_verdict"] == "NEEDS_SUPPLEMENT"
        assert "Historical parallels" in result["gaps"]

    def test_parses_reject_response(self):
        result = parse_validation_xml(SAMPLE_REJECT_RESPONSE)
        assert len(result["criteria"]) == 8
        assert result["overall_verdict"] == "REJECT"

    def test_extracts_criterion_names(self):
        result = parse_validation_xml(SAMPLE_PASS_RESPONSE)
        names = [c["name"] for c in result["criteria"]]
        assert names == CRITERIA_NAMES

    def test_extracts_scores(self):
        result = parse_validation_xml(SAMPLE_PASS_RESPONSE)
        scores = [c["score"] for c in result["criteria"]]
        assert scores.count("PASS") == 7
        assert scores.count("WEAK") == 1

    def test_raises_on_missing_validation_block(self):
        with pytest.raises(ValueError, match="Could not find"):
            parse_validation_xml("no validation here")


class TestEvaluateValidation:
    def test_ready_when_no_fails_and_few_weaks(self):
        result = {"criteria": [
            {"name": "a", "score": "PASS"},
            {"name": "b", "score": "PASS"},
            {"name": "c", "score": "WEAK"},
            {"name": "d", "score": "PASS"},
            {"name": "e", "score": "PASS"},
            {"name": "f", "score": "WEAK"},
            {"name": "g", "score": "PASS"},
            {"name": "h", "score": "PASS"},
        ]}
        assert evaluate_validation(result) == "READY"

    def test_needs_supplement_with_one_fail(self):
        result = {"criteria": [
            {"name": "a", "score": "PASS"},
            {"name": "b", "score": "FAIL"},
            {"name": "c", "score": "PASS"},
            {"name": "d", "score": "PASS"},
            {"name": "e", "score": "PASS"},
            {"name": "f", "score": "PASS"},
            {"name": "g", "score": "PASS"},
            {"name": "h", "score": "PASS"},
        ]}
        assert evaluate_validation(result) == "NEEDS_SUPPLEMENT"

    def test_needs_supplement_with_many_weaks(self):
        result = {"criteria": [
            {"name": "a", "score": "WEAK"},
            {"name": "b", "score": "WEAK"},
            {"name": "c", "score": "WEAK"},
            {"name": "d", "score": "PASS"},
            {"name": "e", "score": "PASS"},
            {"name": "f", "score": "PASS"},
            {"name": "g", "score": "PASS"},
            {"name": "h", "score": "PASS"},
        ]}
        assert evaluate_validation(result) == "NEEDS_SUPPLEMENT"

    def test_reject_with_many_fails(self):
        result = {"criteria": [
            {"name": "a", "score": "FAIL"},
            {"name": "b", "score": "FAIL"},
            {"name": "c", "score": "FAIL"},
            {"name": "d", "score": "PASS"},
            {"name": "e", "score": "PASS"},
            {"name": "f", "score": "PASS"},
            {"name": "g", "score": "PASS"},
            {"name": "h", "score": "PASS"},
        ]}
        assert evaluate_validation(result) == "REJECT"

    def test_all_pass_is_ready(self):
        result = {"criteria": [{"name": f"c{i}", "score": "PASS"} for i in range(8)]}
        assert evaluate_validation(result) == "READY"


class TestBuildValidationPrompt:
    def test_fills_all_fields(self):
        brief = {
            "headline": "Test Headline",
            "thesis": "Test Thesis",
            "executive_hook": "Test Hook",
            "fact_sheet": "Test Facts",
            "historical_parallels": "Test History",
            "framework_analysis": "Test Framework",
            "character_dossier": "Test Characters",
            "narrative_arc": "Test Narrative",
            "counter_arguments": "Test Counter",
            "visual_seeds": "Test Seeds",
            "source_bibliography": "Test Sources",
        }
        prompt = build_validation_prompt(brief)
        assert "Test Headline" in prompt
        assert "Test Thesis" in prompt
        assert "Test Hook" in prompt
        assert "Test Facts" in prompt

    def test_handles_missing_fields(self):
        brief = {"headline": "Test"}
        prompt = build_validation_prompt(brief)
        assert "Test" in prompt


class TestFormatValidationSummary:
    def test_formats_summary(self):
        result = {
            "decision": "READY",
            "criteria": [
                {"name": "hook_strength", "score": "PASS", "assessment": "Good"},
                {"name": "fact_density", "score": "WEAK", "assessment": "Thin"},
            ],
            "gaps": "",
        }
        summary = format_validation_summary(result)
        assert "READY" in summary
        assert "✅" in summary
        assert "⚠️" in summary
