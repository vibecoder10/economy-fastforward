# skills/video-pipeline/curiosity_gap/tests/test_structures.py
"""Tests for curiosity gap structures."""

import pytest
from curiosity_gap.structures import (
    CuriosityStructure,
    STRUCTURE_DEFINITIONS,
    get_structure_prompt,
    validate_structure,
)


class TestCuriosityStructure:
    """Test suite for CuriosityStructure enum."""

    def test_all_structures_defined(self):
        """Should have all 6 structures including 'other'."""
        structures = list(CuriosityStructure)
        assert len(structures) == 6
        assert CuriosityStructure.HIDDEN_FLAW in structures
        assert CuriosityStructure.ASYMMETRIC_DG in structures
        assert CuriosityStructure.TIME_BOMB in structures
        assert CuriosityStructure.PARADIGM_SHIFT in structures
        assert CuriosityStructure.ILLUSION_CONTROL in structures
        assert CuriosityStructure.OTHER in structures

    def test_structure_string_values(self):
        """Structure values should be snake_case strings."""
        assert CuriosityStructure.HIDDEN_FLAW.value == "hidden_flaw"
        assert CuriosityStructure.ASYMMETRIC_DG.value == "asymmetric_dg"
        assert CuriosityStructure.TIME_BOMB.value == "time_bomb"
        assert CuriosityStructure.PARADIGM_SHIFT.value == "paradigm_shift"
        assert CuriosityStructure.ILLUSION_CONTROL.value == "illusion_control"
        assert CuriosityStructure.OTHER.value == "other"


class TestStructureDefinitions:
    """Test suite for structure definitions."""

    def test_all_structures_have_definitions(self):
        """Every structure should have a definition."""
        for structure in CuriosityStructure:
            assert structure in STRUCTURE_DEFINITIONS
            defn = STRUCTURE_DEFINITIONS[structure]
            assert "gap_mechanism" in defn
            assert "when_to_use" in defn
            assert "example" in defn

    def test_hidden_flaw_definition(self):
        """Hidden flaw should have correct gap mechanism."""
        defn = STRUCTURE_DEFINITIONS[CuriosityStructure.HIDDEN_FLAW]
        assert "mistake" in defn["gap_mechanism"].lower() or "hiding" in defn["gap_mechanism"].lower()

    def test_asymmetric_dg_definition(self):
        """Asymmetric David/Goliath should reference small vs big."""
        defn = STRUCTURE_DEFINITIONS[CuriosityStructure.ASYMMETRIC_DG]
        assert "small" in defn["gap_mechanism"].lower() or "big" in defn["gap_mechanism"].lower()


class TestGetStructurePrompt:
    """Test suite for prompt generation."""

    def test_prompt_contains_all_structures(self):
        """Generated prompt should list all 5 main structures."""
        prompt = get_structure_prompt()
        assert "hidden_flaw" in prompt
        assert "asymmetric_dg" in prompt
        assert "time_bomb" in prompt
        assert "paradigm_shift" in prompt
        assert "illusion_control" in prompt
        assert "other" in prompt

    def test_prompt_contains_gap_mechanisms(self):
        """Generated prompt should include gap mechanisms."""
        prompt = get_structure_prompt()
        assert "mistake" in prompt.lower() or "hiding" in prompt.lower()


class TestValidateStructure:
    """Test suite for structure validation."""

    def test_valid_structure(self):
        """Should accept valid structure strings."""
        assert validate_structure("hidden_flaw") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("other") == CuriosityStructure.OTHER

    def test_case_insensitive(self):
        """Should handle case variations."""
        assert validate_structure("HIDDEN_FLAW") == CuriosityStructure.HIDDEN_FLAW
        assert validate_structure("Hidden_Flaw") == CuriosityStructure.HIDDEN_FLAW

    def test_invalid_structure_returns_other(self):
        """Invalid structures should return OTHER."""
        assert validate_structure("unknown_structure") == CuriosityStructure.OTHER
        assert validate_structure("") == CuriosityStructure.OTHER
        assert validate_structure("gibberish") == CuriosityStructure.OTHER


class TestGetMainStructures:
    """Test suite for get_main_structures helper."""

    def test_excludes_other(self):
        """get_main_structures should return 5 structures, excluding OTHER."""
        from curiosity_gap.structures import get_main_structures
        main = get_main_structures()
        assert len(main) == 5
        assert CuriosityStructure.OTHER not in main

    def test_includes_all_main_structures(self):
        """Should include all 5 main curiosity gap structures."""
        from curiosity_gap.structures import get_main_structures
        main = get_main_structures()
        assert CuriosityStructure.HIDDEN_FLAW in main
        assert CuriosityStructure.ASYMMETRIC_DG in main
        assert CuriosityStructure.TIME_BOMB in main
        assert CuriosityStructure.PARADIGM_SHIFT in main
        assert CuriosityStructure.ILLUSION_CONTROL in main
