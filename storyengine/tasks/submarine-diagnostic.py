"""Capture one production research response without saving pipeline state."""

import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path("/home/clawd/projects/economy-fastforward")
STORYENGINE = ROOT / "storyengine"
VIDEO_ID = "44dbf2b2-a27a-47ea-a608-4c31c906be9a"
TENANT_ID = "561b872d-7b73-45e3-9c44-7f30c3566eda"
TITLE = "Every US Submarine Class Ever Built (2026)"
OUTPUT_DIR = STORYENGINE / "tasks" / "submarine-diagnostic"

sys.path[:0] = [str(STORYENGINE / "backend"), str(ROOT / "skills" / "video-pipeline")]

from dotenv import load_dotenv

load_dotenv(STORYENGINE / ".env")

from pipeline_executor import PipelineExecutor
from research.agent import ResearchAgent
from roster_coverage import title_scope_policy


class CapturedProviderResponse(BaseException):
    """Stop control flow before parsing, repair, or persistence."""

    def __init__(self, summary):
        super().__init__("first provider response captured")
        self.summary = summary


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


async def main():
    old_umask = os.umask(0o077)
    try:
        OUTPUT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(OUTPUT_DIR, 0o700)

        executor = PipelineExecutor(TENANT_ID)
        await executor._ensure_initialized()
        video = await executor._get_video(VIDEO_ID)
        if not video:
            raise RuntimeError("target video not found")
        if (video.get("video_title") or video.get("headline")) != TITLE:
            raise RuntimeError("target video title does not match approved diagnostic title")
        await executor._load_prompt_overrides(video)

        client = executor._pipeline.anthropic
        if client is None:
            raise RuntimeError("research client unavailable")
        if getattr(client, "_gateway_mode", False):
            raise RuntimeError("gateway mode detected; stream interception requires Astra review")

        messages = client.client.messages
        original_create = messages.create

        def capture_create(**kwargs):
            request_path = OUTPUT_DIR / "request.json"
            response_path = OUTPUT_DIR / "response.json"
            request_path.write_text(json.dumps(kwargs, indent=2, default=_jsonable))
            os.chmod(request_path, 0o600)

            response = original_create(**kwargs)
            response_dump = response.model_dump(mode="json")
            response_path.write_text(json.dumps(response_dump, indent=2))
            os.chmod(response_path, 0o600)

            text_blocks = [
                block.text for block in response.content
                if getattr(block, "type", None) == "text" and hasattr(block, "text")
            ]
            usage = getattr(response, "usage", None)
            summary = {
                "stop_reason": getattr(response, "stop_reason", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "text_length": len("\n".join(text_blocks)),
                "request_path": str(request_path),
                "response_path": str(response_path),
            }
            raise CapturedProviderResponse(summary)

        messages.create = capture_create
        agent = ResearchAgent(
            client,
            system_prompt_override=executor._pipeline.research_system_prompt,
        )
        try:
            await agent.research(TITLE, context=title_scope_policy(TITLE))
        except CapturedProviderResponse as captured:
            print(json.dumps(captured.summary))
            return
        raise RuntimeError("diagnostic did not stop after the first provider response")
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    asyncio.run(main())
