"""House-template application remains safe when a linked video is resumed."""

from __future__ import annotations

import pytest

from routes import script_templates


class TemplateState:
    def __init__(self, *, prompt=None, tenant_prompt="Tenant writing rules"):
        self.prompt = prompt
        self.tenant_prompt = tenant_prompt
        self.structure = "Open with a concrete contradiction."
        self.update_calls = 0

    async def fetch_one(self, query, *args):
        assert "FROM script_templates" in query
        return {"structure": self.structure}

    async def execute(self, query, block, video_id, tenant_id):
        assert video_id == "video-1"
        assert tenant_id == "tenant-1"
        # The production UPDATE must retain atomic duplicate prevention; a
        # read-before-write-only implementation would race two resume calls.
        assert "strpos(" in query
        assert "script_system_prompt IS NULL" in query
        assert "tenant_prompt_defaults" in query
        framed_prompt = f"\n\n{self.prompt}\n\n" if self.prompt is not None else ""
        framed_block = f"\n\n{block}\n\n"
        if self.prompt is not None and framed_block in framed_prompt:
            return "UPDATE 0"
        self.prompt = block + (
            f"\n\n{self.prompt}" if self.prompt is not None
            else f"\n\n{self.tenant_prompt}" if self.tenant_prompt else ""
        )
        self.update_calls += 1
        return "UPDATE 1"


@pytest.mark.asyncio
async def test_saved_video_resume_does_not_prepend_exact_house_block_twice(monkeypatch):
    state = TemplateState()
    monkeypatch.setattr(script_templates, "fetch_one", state.fetch_one)
    monkeypatch.setattr(script_templates, "execute", state.execute)

    assert await script_templates.apply_default_template("tenant-1", "video-1") is True
    first_prompt = state.prompt
    assert await script_templates.apply_default_template("tenant-1", "video-1") is False

    assert state.prompt == first_prompt
    assert state.update_calls == 1
    assert state.prompt.endswith("\n\nTenant writing rules")


@pytest.mark.asyncio
async def test_crash_after_video_link_still_applies_missing_template(monkeypatch):
    state = TemplateState(prompt=None, tenant_prompt=None)
    monkeypatch.setattr(script_templates, "fetch_one", state.fetch_one)
    monkeypatch.setattr(script_templates, "execute", state.execute)

    assert await script_templates.apply_default_template("tenant-1", "video-1") is True
    assert state.prompt == (
        "## The channel's house script format (follow this)\n"
        "Open with a concrete contradiction."
    )


@pytest.mark.asyncio
async def test_changed_house_template_keeps_override_prepend_semantics(monkeypatch):
    state = TemplateState()
    monkeypatch.setattr(script_templates, "fetch_one", state.fetch_one)
    monkeypatch.setattr(script_templates, "execute", state.execute)
    await script_templates.apply_default_template("tenant-1", "video-1")
    old_prompt = state.prompt

    state.structure = "Begin with the outcome, then explain how it happened."
    assert await script_templates.apply_default_template("tenant-1", "video-1") is True

    assert state.prompt.startswith(
        "## The channel's house script format (follow this)\n"
        "Begin with the outcome, then explain how it happened.\n\n"
    )
    assert state.prompt.endswith(old_prompt)
