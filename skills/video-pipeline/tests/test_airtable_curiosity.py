"""Tests for Airtable curiosity structure methods."""

import os
import pytest
from unittest.mock import Mock, patch
from clients.airtable_client import AirtableClient
from pipeline_constants import IdeaFields


class TestIdeaFieldsConstants:
    """Test curiosity gap field constants exist."""

    def test_curiosity_structure_field_exists(self):
        """Should have CURIOSITY_STRUCTURE constant."""
        assert hasattr(IdeaFields, 'CURIOSITY_STRUCTURE')
        assert IdeaFields.CURIOSITY_STRUCTURE == "Curiosity Structure"

    def test_structure_confidence_field_exists(self):
        """Should have STRUCTURE_CONFIDENCE constant."""
        assert hasattr(IdeaFields, 'STRUCTURE_CONFIDENCE')
        assert IdeaFields.STRUCTURE_CONFIDENCE == "Structure Confidence"

    def test_thumbnail_text_field_exists(self):
        """Should have THUMBNAIL_TEXT constant."""
        assert hasattr(IdeaFields, 'THUMBNAIL_TEXT')
        assert IdeaFields.THUMBNAIL_TEXT == "Thumbnail Text"

    def test_thumbnail_approach_field_exists(self):
        """Should have THUMBNAIL_APPROACH constant."""
        assert hasattr(IdeaFields, 'THUMBNAIL_APPROACH')
        assert IdeaFields.THUMBNAIL_APPROACH == "Thumbnail Approach"


class TestUpdateIdeaCuriosityStructure:
    """Test suite for update_idea_curiosity_structure method."""

    @pytest.fixture
    def mock_airtable(self):
        """Create AirtableClient with mocked tables."""
        with patch('clients.airtable_client.Api') as mock_api:
            with patch.dict('os.environ', {'AIRTABLE_API_KEY': 'test_key'}):
                mock_table = Mock()
                mock_api.return_value.table.return_value = mock_table
                client = AirtableClient()
                client._idea_concepts_table = mock_table
                yield client, mock_table

    def test_updates_all_fields(self, mock_airtable):
        """Should update all curiosity gap fields."""
        client, mock_table = mock_airtable
        mock_table.update.return_value = {"id": "rec123", "fields": {}}

        result = client.update_idea_curiosity_structure(
            record_id="rec123",
            structure="hidden_flaw",
            confidence=85,
            thumbnail_text="WORTHLESS PIPELINES",
            thumbnail_approach="from_gap",
        )

        mock_table.update.assert_called_once()
        call_args = mock_table.update.call_args
        assert call_args[0][0] == "rec123"
        fields = call_args[0][1]
        assert fields[IdeaFields.CURIOSITY_STRUCTURE] == "hidden_flaw"
        assert fields[IdeaFields.STRUCTURE_CONFIDENCE] == 85
        assert fields[IdeaFields.THUMBNAIL_TEXT] == "WORTHLESS PIPELINES"
        assert fields[IdeaFields.THUMBNAIL_APPROACH] == "from_gap"

    def test_omits_empty_thumbnail_text(self, mock_airtable):
        """Should not include thumbnail_text if empty."""
        client, mock_table = mock_airtable
        mock_table.update.return_value = {"id": "rec123", "fields": {}}

        client.update_idea_curiosity_structure(
            record_id="rec123",
            structure="time_bomb",
            confidence=72,
            thumbnail_text="",  # Empty
        )

        call_args = mock_table.update.call_args
        fields = call_args[0][1]
        assert IdeaFields.THUMBNAIL_TEXT not in fields

    def test_default_thumbnail_approach(self, mock_airtable):
        """Should default to 'from_gap' approach."""
        client, mock_table = mock_airtable
        mock_table.update.return_value = {"id": "rec123", "fields": {}}

        client.update_idea_curiosity_structure(
            record_id="rec123",
            structure="paradigm_shift",
            confidence=65,
        )

        call_args = mock_table.update.call_args
        fields = call_args[0][1]
        assert fields[IdeaFields.THUMBNAIL_APPROACH] == "from_gap"
