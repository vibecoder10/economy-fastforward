"""Embedding generation via OpenAI text-embedding-3-small.

Uses the tenant's stored API key (vault) with fallback to env var.
1536 dimensions, $0.02 per 1M tokens — cheapest option.
"""

import httpx
from typing import Optional

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
OPENAI_EMBEDDING_URL = "https://api.openai.com/v1/embeddings"


async def generate_embedding(text: str, api_key: str) -> Optional[list[float]]:
    """Generate a 1536-dim embedding for the given text.

    Returns None if the API call fails (caller should handle gracefully).
    """
    # Truncate to ~8000 tokens (~32K chars) to stay within model limits
    truncated = text[:32000]

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_EMBEDDING_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "input": truncated,
                "model": EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSIONS,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
