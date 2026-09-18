"""Continue the retained submarine research response with one provider call."""

import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path("/home/clawd/projects/economy-fastforward")
STORYENGINE = ROOT / "storyengine"
TENANT_ID = "561b872d-7b73-45e3-9c44-7f30c3566eda"
CAPTURE_DIR = STORYENGINE / "tasks" / "submarine-diagnostic"
REQUEST_PATH = CAPTURE_DIR / "request.json"
RESPONSE_PATH = CAPTURE_DIR / "response.json"
CONTINUATION_PATH = CAPTURE_DIR / "continuation-response.json"
SUFFIX_INSTRUCTION = (
    "The previous response hit the output limit. Continue from exactly the last "
    "character. Return only the missing suffix, no repetition, commentary, markdown "
    "fences, or new research."
)

sys.path[:0] = [str(STORYENGINE / "backend"), str(ROOT / "skills" / "video-pipeline")]

from dotenv import load_dotenv

load_dotenv(STORYENGINE / ".env")

from pipeline_executor import PipelineExecutor


def text_from_content(content):
    return "\n".join(
        block.get("text", "")
        for block in content
        if block.get("type") == "text"
    )


async def main():
    old_umask = os.umask(0o077)
    try:
        CAPTURE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(CAPTURE_DIR, 0o700)
        if CONTINUATION_PATH.exists():
            raise RuntimeError("continuation canary already attempted; inspect retained response")

        retained_request = json.loads(REQUEST_PATH.read_text())
        retained_response = json.loads(RESPONSE_PATH.read_text())

        executor = PipelineExecutor(TENANT_ID)
        await executor._ensure_initialized()
        client = executor._pipeline.anthropic
        if client is None:
            raise RuntimeError("research client unavailable")
        if getattr(client, "_gateway_mode", False):
            raise RuntimeError("gateway mode detected; continuation protocol is not authorized")

        kwargs = {
            key: value for key, value in retained_request.items()
            if key != "tools"
        }
        kwargs["messages"] = [
            *retained_request["messages"],
            {"role": "assistant", "content": retained_response["content"]},
            {"role": "user", "content": SUFFIX_INSTRUCTION},
        ]

        response = await asyncio.to_thread(client.client.messages.create, **kwargs)
        response_dump = response.model_dump(mode="json")
        CONTINUATION_PATH.write_text(json.dumps(response_dump, indent=2))
        os.chmod(CONTINUATION_PATH, 0o600)

        original_text = text_from_content(retained_response["content"])
        continuation_text = text_from_content(response_dump["content"])
        combined = original_text + continuation_text
        try:
            parsed = json.loads(combined)
            parse_result = {
                "parsed": True,
                "json_type": type(parsed).__name__,
                "field_count": len(parsed) if isinstance(parsed, dict) else None,
            }
        except json.JSONDecodeError as exc:
            parse_result = {
                "parsed": False,
                "error": exc.msg,
                "position": exc.pos,
            }

        usage = getattr(response, "usage", None)
        print(json.dumps({
            "stop_reason": getattr(response, "stop_reason", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "continuation_text_length": len(continuation_text),
            "combined_text_length": len(combined),
            "combined_json": parse_result,
            "response_path": str(CONTINUATION_PATH),
        }))
    finally:
        os.umask(old_umask)


if __name__ == "__main__":
    asyncio.run(main())
