"""AgentRelayClient - an AnthropicClient whose model calls are answered by the MCP agent.

Overrides only `generate()`, the single choke point every higher-level method and every
DVSU call goes through, with the same signature and the same return (the text). Instead of
calling a provider it parks the request in `agent_llm_requests` and waits, exactly like a
slow API call, until the agent answers it. See agent_relay.py and
docs/agent-llm-relay-2026-09-21/DESIGN.md.

Only valid where a background worker can wait: the pipeline executor. A request-scoped MCP
call would block its own answer (the agent can't call answer_llm_request mid-call).
"""
from __future__ import annotations

import asyncio
import sys
import time
from typing import Any, Awaitable, Callable, Optional

import agent_relay
from orchestrator.pipeline_constants import Models
from shared import research_response
from shared.clients.anthropic_client import AnthropicClient


class AgentRelayTimeout(RuntimeError):
    """No answer arrived in time. The request row stays pending; a later run of the same
    stage replays any answers already given and picks up where it stopped."""


class AgentRelayCancelled(RuntimeError):
    """The run was cancelled while waiting for the agent."""


class AgentRelayClient(AnthropicClient):
    def __init__(
        self, tenant_id, video_id: Optional[str] = None, *,
        should_cancel: Optional[Callable[[], Awaitable[bool]]] = None,
        poll_seconds: Optional[float] = None, timeout_seconds: Optional[float] = None,
    ):
        # Deliberately no super().__init__: there is no key and no SDK client. The
        # attributes stage code reads off a client are set here instead.
        self.api_key = None
        self.client = None
        self._gateway_mode = False  # DVSU refuses gateway clients; the agent CAN web-search
        self.tenant_id = tenant_id
        self.video_id = video_id
        self.should_cancel = should_cancel
        self._poll_seconds = poll_seconds
        self._timeout_seconds = timeout_seconds

    def bind(self, video_id: Optional[str], should_cancel: Optional[Callable[[], Awaitable[bool]]] = None) -> None:
        """Scope subsequent calls to one video (the executor calls this per run)."""
        self.video_id = video_id
        if should_cancel is not None:
            self.should_cancel = should_cancel

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = Models.CLAUDE_SONNET,
        max_tokens: int = 4096,
        temperature: float = 1.0,
        tools: list = None,
        complete_response: bool = False,
        checkpoint_path=None,
        no_resubmit: bool = False,
    ) -> str:
        # complete_response / checkpoint_path / no_resubmit exist to manage a provider's
        # continuations and uncertain submissions; the agent returns the finished text in
        # one answer, and the request row is itself the durable checkpoint.
        fingerprint = research_response.request_fingerprint(
            prompt=prompt, system_prompt=system_prompt, model=model, tools=tools,
            max_tokens=max_tokens, temperature=temperature,
        )
        row = await agent_relay.get_or_create_request(
            self.tenant_id, self.video_id, fingerprint=fingerprint, stage=_caller_name(),
            model=model, system_prompt=system_prompt, prompt=prompt, tools=tools,
            max_tokens=max_tokens, temperature=temperature,
        )
        if row["status"] == "answered":
            return row["response_text"]

        poll = self._poll_seconds if self._poll_seconds is not None else agent_relay.poll_seconds()
        limit = self._timeout_seconds if self._timeout_seconds is not None else agent_relay.timeout_seconds()
        print(
            f"    ⏳ Waiting for the agent to answer LLM request {row['id']} "
            f"(stage {row.get('stage')}, {len(prompt)} prompt chars)", flush=True,
        )
        deadline = time.monotonic() + limit
        while True:
            await asyncio.sleep(poll)
            current = await agent_relay.get_request(self.tenant_id, row["id"])
            if current is not None and current["status"] == "answered":
                return current["response_text"]
            if self.should_cancel is not None and await self.should_cancel():
                raise AgentRelayCancelled(f"Run cancelled while waiting for the agent to answer request {row['id']}")
            if time.monotonic() >= deadline:
                raise AgentRelayTimeout(
                    f"The agent did not answer LLM request {row['id']} within {int(limit)}s. "
                    "It is still pending - answer it, then re-run the stage to continue."
                )


def _caller_name() -> Optional[str]:
    """Name of the function that awaited generate(), as a human-readable stage label."""
    try:
        return sys._getframe(2).f_code.co_name
    except (AttributeError, ValueError):
        return None
