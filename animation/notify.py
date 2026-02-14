"""Slack notification helpers for the animation pipeline."""

import os
from typing import Optional

from animation.config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ID


class AnimationNotifier:
    """Sends Slack notifications for animation pipeline events."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or SLACK_BOT_TOKEN
        self.channel_id = channel_id or SLACK_CHANNEL_ID

        # Lazy-load to avoid import error if slack_sdk not needed
        self._client = None

    @property
    def client(self):
        """Lazy-initialize the Slack WebClient."""
        if self._client is None:
            if not self.bot_token:
                print("    \u26a0\ufe0f SLACK_BOT_TOKEN not configured, notifications disabled")
                return None
            from slack_sdk import WebClient
            self._client = WebClient(token=self.bot_token)
        return self._client

    def send_message(self, text: str, channel_id: Optional[str] = None) -> dict:
        """Send a message to a Slack channel.

        Args:
            text: Message text (supports Slack markdown)
            channel_id: Channel to send to (uses default if not specified)

        Returns:
            Slack API response dict
        """
        if not self.client:
            print(f"    [SLACK] {text}")
            return {"ok": False, "error": "No Slack client configured"}

        target_channel = channel_id or self.channel_id

        try:
            from slack_sdk.errors import SlackApiError
            response = self.client.chat_postMessage(
                channel=target_channel,
                text=text,
            )
            return {
                "ok": response["ok"],
                "ts": response["ts"],
                "channel": response["channel"],
            }
        except Exception as e:
            print(f"    \u26a0\ufe0f Slack notification failed: {e}")
            return {"ok": False, "error": str(e)}

    # ==================== ANIMATION PIPELINE NOTIFICATIONS ====================

    def notify_pipeline_start(self, project_name: str, total_scenes: int) -> dict:
        """Notify that the animation pipeline has started."""
        return self.send_message(
            f"\U0001f3ac *Animation Pipeline Started*\n\n"
            f"\U0001f4f9 Project: {project_name}\n"
            f"\U0001f3ac Total scenes: {total_scenes}\n\n"
            f"I'll notify you as each phase completes."
        )

    def notify_scene_planning_done(
        self,
        project_name: str,
        total_scenes: int,
        animated: int,
        ken_burns: int,
        static: int,
        estimated_cost: float,
    ) -> dict:
        """Notify that scene planning is complete."""
        return self.send_message(
            f"\u2705 *Scene Planning Complete*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"\U0001f3ac {total_scenes} scenes planned:\n"
            f"  \u2022 {animated} animated (Veo 3.1)\n"
            f"  \u2022 {ken_burns} ken burns\n"
            f"  \u2022 {static} static\n"
            f"\U0001f4b0 Estimated cost: ${estimated_cost:.2f}\n\n"
            f"Starting frame generation..."
        )

    def notify_frames_done(self, project_name: str, frames_generated: int) -> dict:
        """Notify that frame generation is complete."""
        return self.send_message(
            f"\U0001f5bc\ufe0f *Frame Generation Complete*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"\u2705 {frames_generated} frame pairs generated\n\n"
            f"Starting animation..."
        )

    def notify_animation_progress(
        self,
        project_name: str,
        completed: int,
        total: int,
        spend: float,
    ) -> dict:
        """Notify animation progress."""
        return self.send_message(
            f"\U0001f3ac *Animation Progress*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"\u2705 {completed}/{total} clips complete\n"
            f"\U0001f4b0 Spend so far: ${spend:.2f}"
        )

    def notify_budget_alert(
        self,
        project_name: str,
        spend: float,
        budget: float,
        scenes_remaining: int,
    ) -> dict:
        """Alert that budget is nearing the limit."""
        return self.send_message(
            f"\u26a0\ufe0f *BUDGET ALERT*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"\U0001f4b0 Spend: ${spend:.2f} / ${budget:.2f} ({spend/budget*100:.0f}%)\n"
            f"\U0001f3ac {scenes_remaining} scenes still remaining\n\n"
            f"Budget threshold crossed. Review needed."
        )

    def notify_budget_exceeded(self, project_name: str, spend: float, budget: float) -> dict:
        """Alert that budget has been exceeded — generation stopped."""
        return self.send_message(
            f"\U0001f6d1 *BUDGET EXCEEDED — GENERATION STOPPED*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"\U0001f4b0 Spend: ${spend:.2f} / ${budget:.2f}\n\n"
            f"Animation generation has been halted. Manual review required."
        )

    def notify_qc_failures(
        self,
        project_name: str,
        failed_scenes: list[dict],
    ) -> dict:
        """Notify of scenes that failed QC and need manual review."""
        scene_list = "\n".join(
            f"  \u2022 Scene {s.get('scene_order', '?')}: {s.get('qc_notes', 'No notes')[:80]}"
            for s in failed_scenes
        )
        return self.send_message(
            f"\u274c *QC Failures — Manual Review Needed*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"{scene_list}"
        )

    def notify_pipeline_complete(
        self,
        project_name: str,
        total_scenes: int,
        scenes_complete: int,
        total_cost: float,
        failures: int,
    ) -> dict:
        """Notify that the animation pipeline is complete."""
        status = "\U0001f389" if failures == 0 else "\u26a0\ufe0f"
        return self.send_message(
            f"{status} *Animation Pipeline Complete*\n\n"
            f"\U0001f4f9 *{project_name}*\n"
            f"\U0001f3ac Scenes: {scenes_complete}/{total_scenes} complete\n"
            f"\U0001f4b0 Total cost: ${total_cost:.2f}\n"
            f"\u274c Failures: {failures}\n\n"
            f"Ready for final assembly!"
        )

    def notify_error(self, project_name: str, step: str, error: str) -> dict:
        """Notify of an error in the pipeline."""
        return self.send_message(
            f"\u274c *Animation Error in {step}*\n\n"
            f"\U0001f4f9 {project_name}\n"
            f"```{error}```\n\n"
            f"Please check and retry."
        )
