"""Tests for entity consistency checker — false positive reduction."""

from script.brief_translator.scene_validator import (
    _extract_entities_from_text,
    check_entity_consistency,
)


class TestExtractEntities:
    """Tests for _extract_entities_from_text."""

    def test_cold_war_not_flagged(self):
        entities = _extract_entities_from_text("The Cold War shaped geopolitics.")
        assert "cold war" not in entities
        assert "the cold war" not in entities

    def test_the_house_not_flagged(self):
        entities = _extract_entities_from_text("The House passed the bill.")
        assert "the house" not in entities

    def test_wall_street_not_flagged(self):
        entities = _extract_entities_from_text("Wall Street panicked.")
        assert "wall street" not in entities

    def test_white_house_not_flagged(self):
        entities = _extract_entities_from_text("The White House issued a statement.")
        assert "white house" not in entities
        assert "the white house" not in entities

    def test_real_entity_goldman_sachs_flagged(self):
        entities = _extract_entities_from_text("Goldman Sachs reported earnings.")
        assert "goldman sachs" in entities

    def test_real_entity_sam_altman_flagged(self):
        entities = _extract_entities_from_text("Sam Altman announced changes.")
        assert "sam altman" in entities

    def test_acronyms_still_flagged(self):
        entities = _extract_entities_from_text("NATO issued a warning.")
        assert "nato" in entities

    def test_camelcase_still_flagged(self):
        entities = _extract_entities_from_text("DeepSeek released a new model.")
        assert "deepseek" in entities

    def test_single_short_word_not_flagged(self):
        """Words under 6 chars should not be flagged as entities."""
        entities = _extract_entities_from_text("The Plan was simple.")
        assert "plan" not in entities


class TestCheckEntityConsistency:
    """End-to-end tests for entity consistency checking."""

    def test_entity_in_research_not_flagged(self):
        script = "The Iraq War cost trillions."
        brief = {
            "fact_sheet": "The Iraq War began in 2003.",
            "headline": "Costs of War",
        }
        warnings = check_entity_consistency(script, brief)
        assert len(warnings) == 0

    def test_entity_only_in_script_flagged(self):
        script = "Goldman Sachs led the bailout negotiations."
        brief = {
            "fact_sheet": "Banks received government aid.",
            "headline": "Financial Crisis",
        }
        warnings = check_entity_consistency(script, brief)
        assert any("goldman sachs" in w.lower() for w in warnings)

    def test_common_phrases_never_flag_regardless(self):
        """Common geopolitical phrases should never produce warnings."""
        script = (
            "The Cold War ended. The White House responded. "
            "Wall Street crashed. The House voted."
        )
        brief = {
            "fact_sheet": "Economic analysis of policy impacts.",
            "headline": "Policy Analysis",
        }
        warnings = check_entity_consistency(script, brief)
        flagged_entities = " ".join(warnings).lower()
        assert "cold war" not in flagged_entities
        assert "white house" not in flagged_entities
        assert "wall street" not in flagged_entities
        assert "the house" not in flagged_entities
