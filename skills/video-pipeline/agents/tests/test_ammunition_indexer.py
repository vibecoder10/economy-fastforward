"""Tests for ammunition_indexer — pure function, no async needed."""

import pytest

from agents.ammunition_indexer import index_ammunition


def _make_payload(**overrides) -> dict:
    """Build a realistic research payload with optional overrides."""
    base = {
        "headline": "China's $3T Dollar Trap",
        "thesis": "China's $3.2 trillion in US Treasuries gives Beijing leverage, but selling would crash their own reserves.",
        "executive_hook": "The largest creditor-debtor standoff in history is playing out in slow motion.",
        "fact_sheet": (
            "- China holds $3.2 trillion in foreign reserves, with ~$800 billion in US Treasuries\n"
            "- In 2023, China sold $53 billion in Treasuries — the largest sell-off since 2016\n"
            "- The yuan depreciated 8% against the dollar in 2023\n"
            "- US debt-to-GDP ratio hit 123% in 2024\n"
            "- Japan surpassed China as the largest foreign holder of US Treasuries in 2023\n"
        ),
        "historical_parallels": (
            "- In 1971, Nixon ended the gold standard when France demanded gold for dollars\n"
            "- The 1997 Asian Financial Crisis showed how currency pegs collapse under pressure\n"
            "- Britain lost reserve currency status over 30 years (1920s-1950s)\n"
        ),
        "framework_analysis": (
            "- China's incentive: maintain export competitiveness while reducing dollar exposure\n"
            "- US incentive: keep borrowing costs low by maintaining Treasury demand\n"
            "- Mutual assured financial destruction prevents sudden moves\n"
        ),
        "character_dossier": (
            "- Yi Gang, PBOC Governor: orchestrated gradual reserve diversification\n"
            "- Janet Yellen: repeatedly warned about debt ceiling risks\n"
            "- Xi Jinping: publicly pushed for yuan internationalization since 2015\n"
        ),
        "narrative_arc": (
            "What happened: China accumulated $3T+ in reserves through decades of trade surpluses.\n"
            "Why it matters: This creates a financial weapon that neither side can safely use.\n"
            "What's next: Watch for accelerated BRICS currency discussions and gold purchases.\n"
        ),
        "counter_arguments": (
            "- Bears say: China can't sell without crashing their own reserves\n"
            "- Bulls say: The dollar's network effects make it irreplaceable for decades\n"
            "- Watch for: Central bank gold purchases exceeding 1000 tonnes/year as a signal\n"
        ),
        "visual_seeds": "Treasury bond certificates, PBOC headquarters, gold bars, currency trading floor",
        "source_bibliography": "IMF World Economic Outlook 2024, PBOC Annual Report",
        "themes": "Financial warfare, currency hegemony, great power competition",
        "psychological_angles": "Fear of economic collapse, curiosity about hidden leverage",
        "narrative_arc_suggestion": "6-act structure: Hook with the $3.2T number...",
    }
    base.update(overrides)
    return base


class TestHookAmmunition:
    """Test hook ammunition extraction."""

    def test_indexes_hook_ammunition(self):
        """Should extract top facts from fact_sheet and historical_parallels."""
        payload = _make_payload()
        ammo = index_ammunition(payload)

        assert len(ammo["hook_ammunition"]) > 0
        assert len(ammo["hook_ammunition"]) <= 5
        # Should prioritize lines with numbers
        assert any("$" in fact or "%" in fact or "trillion" in fact.lower()
                    for fact in ammo["hook_ammunition"])

    def test_hook_ammunition_prioritizes_numbers(self):
        """Facts with specific numbers should rank higher."""
        payload = _make_payload(
            fact_sheet="- A vague observation about economics\n- China holds $3.2 trillion in reserves\n",
            historical_parallels="",
        )
        ammo = index_ammunition(payload)

        # The numbered fact should appear first
        assert len(ammo["hook_ammunition"]) >= 1
        assert "$3.2 trillion" in ammo["hook_ammunition"][0]


class TestBodyAmmunition:
    """Test body ammunition extraction."""

    def test_indexes_body_ammunition(self):
        """Should organize facts by narrative purpose."""
        payload = _make_payload()
        ammo = index_ammunition(payload)
        body = ammo["body_ammunition"]

        assert "incentive_chain" in body
        assert "money_trail" in body
        assert "proof_points" in body
        assert "character_facts" in body

        # Incentive chain from framework_analysis
        assert len(body["incentive_chain"]) > 0

        # Money trail should have dollar amounts
        assert any("$" in fact for fact in body["money_trail"])

        # Character facts from dossier
        assert len(body["character_facts"]) > 0

    def test_money_trail_has_dollar_amounts(self):
        """Money trail should only contain lines with $ amounts."""
        payload = _make_payload()
        ammo = index_ammunition(payload)

        for fact in ammo["body_ammunition"]["money_trail"]:
            assert "$" in fact


class TestCTAAmmunition:
    """Test CTA ammunition extraction."""

    def test_indexes_cta_ammunition(self):
        """Should extract actionable data from counter_arguments and narrative_arc."""
        payload = _make_payload()
        ammo = index_ammunition(payload)

        assert len(ammo["cta_ammunition"]) > 0
        assert len(ammo["cta_ammunition"]) <= 5

    def test_cta_prefers_forward_looking(self):
        """Lines with action words should be prioritized."""
        payload = _make_payload(
            counter_arguments="- Watch for: gold purchases exceeding 1000 tonnes\n- Some people disagree\n",
            narrative_arc="- Track the yuan-dollar spread for signals\n- History happened\n",
        )
        ammo = index_ammunition(payload)

        # Forward-looking lines should appear
        assert any("watch" in fact.lower() or "track" in fact.lower()
                    for fact in ammo["cta_ammunition"])


class TestWeaponsAmmunition:
    """Test weapons ammunition extraction."""

    def test_indexes_weapons_ammunition(self):
        """Should extract strongest claims from thesis, hook, and fact_sheet."""
        payload = _make_payload()
        ammo = index_ammunition(payload)

        assert len(ammo["weapons_ammunition"]) > 0
        assert len(ammo["weapons_ammunition"]) <= 5

    def test_thesis_is_always_a_weapon(self):
        """The thesis should always appear in weapons ammunition."""
        payload = _make_payload()
        ammo = index_ammunition(payload)

        assert any("3.2 trillion" in w or "leverage" in w.lower()
                    for w in ammo["weapons_ammunition"])


class TestEdgeCases:
    """Test handling of empty and partial payloads."""

    def test_handles_empty_payload(self):
        """Empty dict should return empty lists, no crash."""
        ammo = index_ammunition({})

        assert ammo["hook_ammunition"] == []
        assert ammo["body_ammunition"]["incentive_chain"] == []
        assert ammo["body_ammunition"]["money_trail"] == []
        assert ammo["body_ammunition"]["proof_points"] == []
        assert ammo["body_ammunition"]["character_facts"] == []
        assert ammo["cta_ammunition"] == []
        assert ammo["weapons_ammunition"] == []

    def test_handles_none_payload(self):
        """None should return empty lists, no crash."""
        ammo = index_ammunition(None)
        assert ammo["hook_ammunition"] == []

    def test_handles_missing_fields(self):
        """Partial payload should work for present fields, skip missing."""
        partial = {
            "fact_sheet": "- China holds $3.2 trillion in reserves\n",
            "thesis": "A strong thesis about economics.",
        }
        ammo = index_ammunition(partial)

        assert len(ammo["hook_ammunition"]) >= 1
        assert len(ammo["weapons_ammunition"]) >= 1
        # Missing fields should produce empty results
        assert ammo["body_ammunition"]["character_facts"] == []
        assert ammo["body_ammunition"]["incentive_chain"] == []

    def test_handles_non_string_fields(self):
        """Fields that are not strings should not crash."""
        payload = {
            "fact_sheet": 12345,
            "thesis": None,
            "character_dossier": ["not", "a", "string"],
        }
        ammo = index_ammunition(payload)
        # Should not crash, just return empty
        assert isinstance(ammo["hook_ammunition"], list)
