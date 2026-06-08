"""Slack API client for notifications."""

import os
import time
from typing import Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


# Transient Slack error codes that are safe to retry.
_RETRYABLE_ERRORS = {"ratelimited", "service_unavailable", "internal_error", "request_timeout"}


class SlackClient:
    """Client for Slack API operations."""

    # Default channel from n8n workflow
    DEFAULT_CHANNEL_ID = "C0A9U1X8NSW"  # production-agent channel

    def __init__(
        self,
        bot_token: Optional[str] = None,
        channel_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or os.getenv("SLACK_BOT_TOKEN")
        # Neutered mode: with no token, this client is a silent no-op instead of
        # raising. Required for customer-facing / non-Slack channels.
        self.enabled = bool(self.bot_token)

        self.channel_id = channel_id or os.getenv("SLACK_CHANNEL_ID", self.DEFAULT_CHANNEL_ID)
        self.client = WebClient(token=self.bot_token) if self.enabled else None

    def send_message(self, text: str, channel_id: Optional[str] = None) -> dict:
        """Send a message to a Slack channel with retry on transient errors.

        Args:
            text: Message text (supports Slack markdown)
            channel_id: Channel to send to (uses default if not specified)

        Returns:
            Slack API response dict with ok, ts, channel

        Raises:
            SlackApiError: On permanent API errors (invalid token, channel not found, etc.)
        """
        if not self.enabled:
            return None
        target_channel = channel_id or self.channel_id

        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat_postMessage(
                    channel=target_channel,
                    text=text,
                )
                return {
                    "ok": response["ok"],
                    "ts": response["ts"],
                    "channel": response["channel"],
                }
            except SlackApiError as e:
                last_error = e
                error_code = e.response.get("error", "") if e.response else ""
                if error_code in _RETRYABLE_ERRORS and attempt < 2:
                    wait = (attempt + 1) * 2  # 2s, 4s
                    if error_code == "ratelimited":
                        wait = int(e.response.headers.get("Retry-After", wait))
                    print(f"    Slack {error_code}, retrying in {wait}s (attempt {attempt + 1}/3)...")
                    time.sleep(wait)
                    continue
                raise

    def add_reaction(self, emoji: str, message_ts: str, channel_id: Optional[str] = None) -> dict:
        """Add an emoji reaction to a message.

        Args:
            emoji: Emoji name (without colons, e.g., "one", "white_check_mark")
            message_ts: Timestamp of the message to react to
            channel_id: Channel (uses default if not specified)

        Returns:
            Slack API response dict

        Raises:
            SlackApiError: On API errors
        """
        if not self.enabled:
            return None
        target_channel = channel_id or self.channel_id

        response = self.client.reactions_add(
            channel=target_channel,
            name=emoji,
            timestamp=message_ts,
        )
        return {"ok": response["ok"]}

    def get_message(self, message_ts: str, channel_id: Optional[str] = None) -> Optional[dict]:
        """Retrieve a specific message by timestamp.

        Args:
            message_ts: Timestamp of the message
            channel_id: Channel (uses default if not specified)

        Returns:
            Message dict if found, None otherwise
        """
        if not self.enabled:
            return None
        target_channel = channel_id or self.channel_id

        try:
            response = self.client.conversations_history(
                channel=target_channel,
                latest=message_ts,
                limit=1,
                inclusive=True,
            )
            messages = response.get("messages", [])
            return messages[0] if messages else None
        except SlackApiError:
            return None

    def notify(self, text: str, channel_id: Optional[str] = None) -> None:
        """Fire-and-forget notification. Never raises — Slack failures must not kill the pipeline."""
        try:
            self.send_message(text, channel_id)
        except Exception:
            pass

    def send_blocks(
        self,
        text: str,
        blocks: list[dict],
        channel_id: Optional[str] = None,
    ) -> dict:
        """Send a message with Block Kit blocks (supports inline images).

        Args:
            text: Fallback text for notifications/accessibility.
            blocks: List of Slack Block Kit block dicts.
            channel_id: Channel to send to (uses default if not specified).

        Returns:
            Slack API response dict with ok, ts, channel.
        """
        if not self.enabled:
            return None
        target_channel = channel_id or self.channel_id

        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat_postMessage(
                    channel=target_channel,
                    text=text,
                    blocks=blocks,
                )
                return {
                    "ok": response["ok"],
                    "ts": response["ts"],
                    "channel": response["channel"],
                }
            except SlackApiError as e:
                last_error = e
                error_code = e.response.get("error", "") if e.response else ""
                if error_code in _RETRYABLE_ERRORS and attempt < 2:
                    wait = (attempt + 1) * 2
                    if error_code == "ratelimited":
                        wait = int(e.response.headers.get("Retry-After", wait))
                    print(f"    Slack {error_code}, retrying in {wait}s (attempt {attempt + 1}/3)...")
                    time.sleep(wait)
                    continue
                raise

    def notify_blocks(
        self,
        text: str,
        blocks: list[dict],
        channel_id: Optional[str] = None,
    ) -> None:
        """Fire-and-forget block notification. Never raises."""
        try:
            self.send_blocks(text, blocks, channel_id)
        except Exception:
            pass

    # ==================== PIPELINE NOTIFICATIONS ====================
    
    def notify_pipeline_start(self, youtube_url: str) -> dict:
        """Notify that the pipeline has started."""
        return self.send_message(
            f"🚀 Starting video production pipeline!\n\n"
            f"📹 Source: {youtube_url}\n\n"
            f"I'll notify you when each step completes."
        )
    
    def notify_idea_generated(self, ideas: list[dict]) -> dict:
        """Notify that ideas have been generated."""
        message = "💡 *Ideas Generated!*\n\n"
        for i, idea in enumerate(ideas, 1):
            message += f"*Option {i}:* {idea.get('viral_title', 'Untitled')}\n"
            message += f"🪝 Hook: {idea.get('hook_script', '')[:100]}...\n\n"
        return self.send_message(message)
    
    def notify_script_start(self) -> dict:
        """Notify that script writing has started."""
        return self.send_message("📝 Starting to make the script 🏁!")
    
    def notify_script_done(self, doc_url: Optional[str] = None) -> dict:
        """Notify that the script is complete."""
        if doc_url:
            return self.send_message(
                f"✅ Script is Done!\n\n"
                f"📄 View your script: {doc_url}\n\n"
                f"Now generating voice overs... 🗣️"
            )
        else:
            return self.send_message(
                f"✅ Script is Done!\n\n"
                f"⚠️ Google Docs unavailable - script saved to Airtable\n\n"
                f"Now generating voice overs... 🗣️"
            )
    
    def notify_voice_start(self) -> dict:
        """Notify that voice generation has started."""
        return self.send_message("🗣️ Starting to make the Voice Over!")
    
    def notify_voice_done(self) -> dict:
        """Notify that voice overs are complete."""
        return self.send_message(
            "✅ Voice Over Done!\n\n"
            "Now designing sound... 🎧"
        )

    def notify_sound_design_done(self, title: str, scene_count: int, total_sounds: int) -> dict:
        """Notify that sound design maps are complete."""
        return self.send_message(
            f"✅ Sound design complete: {total_sounds} sounds across {scene_count} scenes\n\n"
            f"Now generating sound effects... 🔊"
        )

    def notify_sound_effects_done(
        self, title: str, scene_count: int, total_generated: int, estimated_cost: float
    ) -> dict:
        """Notify that sound effect audio files have been generated."""
        return self.send_message(
            f"✅ Generated {total_generated} sound effects (~${estimated_cost:.2f})\n\n"
            f"Now generating image prompts... 🌉"
        )

    def notify_image_prompts_start(self) -> dict:
        """Notify that image prompt generation has started."""
        return self.send_message("🌉 Starting to make the image prompts!")
    
    def notify_image_prompts_done(self) -> dict:
        """Notify that image prompts are complete."""
        return self.send_message(
            "✅ Image prompts are Done!\n\n"
            "Now generating images... 🖼️"
        )

    def notify_prompt_validation(self, report: str) -> dict:
        """Notify prompt validation results.

        Args:
            report: Formatted validation report from prompt_validator.format_validation_report()
        """
        return self.send_message(f"🔍 {report}")
    
    def notify_images_start(self) -> dict:
        """Notify that image generation has started."""
        return self.send_message("🖼️ Starting to make the images!")
    
    def notify_images_done(self) -> dict:
        """Notify that images are complete."""
        return self.send_message(
            "✅ Images have been created!\n\n"
            "Now creating thumbnail... 🎨"
        )
    
    def notify_thumbnail_done(self) -> dict:
        """Notify that thumbnail is complete."""
        return self.send_message(
            "✅ Thumbnail created!\n\n"
            "🎬 All assets ready for video editing!"
        )

    def notify_music_selected(self, music_beds: list[dict]) -> dict:
        """Notify which background music was selected for each act."""
        if not music_beds:
            return self.send_message("🎵 No background music selected (no acts found)")

        lines = ["🎵 *Background Music Selected:*\n"]
        for bed in sorted(music_beds, key=lambda b: b.get("act", 0)):
            act = bed.get("act", "?")
            mood = bed.get("mood", "unknown")
            track = bed.get("file", "none")
            # Extract just the filename from the path
            track_name = track.split("/")[-1] if track else "none"
            emoji = {"tension": "😰", "strategic": "♟️", "revelation": "💡"}.get(mood, "🎵")
            lines.append(f"  Act {act}: {emoji} {mood} → `{track_name}`")

        return self.send_message("\n".join(lines))

    def notify_sfx_loaded(self, sfx_count: int, total_images: int) -> dict:
        """Notify how many sound effects were loaded for rendering."""
        if sfx_count == 0:
            return self.send_message("🔇 No sound effects for this video")
        return self.send_message(
            f"🔊 *Sound Effects Loaded:* {sfx_count}/{total_images} images have SFX"
        )

    def notify_pipeline_complete(self, video_title: str, folder_url: str) -> dict:
        """Notify that the entire pipeline is complete."""
        return self.send_message(
            f"🎉 *Video Production Complete!*\n\n"
            f"📹 *{video_title}*\n\n"
            f"📁 All assets: {folder_url}\n\n"
            f"Ready for final video assembly in Remotion!"
        )
    
    def notify_youtube_draft_ready(
        self,
        video_title: str,
        youtube_url: str,
        drive_folder_url: str,
        description_preview: str,
    ) -> dict:
        """Notify that a video is uploaded as an unlisted YouTube draft."""
        return self.send_message(
            f"📺 *Video Ready for Review!*\n\n"
            f'"{video_title}"\n\n'
            f"🎬 *YouTube Draft:* {youtube_url}\n"
            f"📁 *Drive Folder:* {drive_folder_url}\n"
            f"📝 *Description preview:* {description_preview}...\n\n"
            f"When ready, open YouTube Studio and set to Public."
        )

    def notify_error(self, step: str, error: str) -> dict:
        """Notify of an error in the pipeline."""
        return self.send_message(
            f"❌ *Error in {step}*\n\n"
            f"```{error}```\n\n"
            f"Please check and retry."
        )

    # --- Storyboard notifications ---

    def notify_storyboard_plan(self, title: str, plan: dict) -> dict:
        """Send storyboard plan with cost estimate."""
        return self.send_message(
            f"🎬 *STORYBOARD PLAN* — \"{title}\"\n\n"
            f"📝 Script: {plan.get('total_words', 0)} words | "
            f"{plan.get('scene_count', 0)} scenes\n"
            f"🎞️ Beats: {plan.get('beat_count', 0)} × 9 panels = "
            f"{plan.get('total_panels', 0)} frames\n"
            f"💰 Est. cost: ${plan.get('total_cost', 0):.2f}\n\n"
            f"Commands:\n"
            f"  `!storyboard-preview` → Directives only (${plan.get('cost_claude', 0):.2f})\n"
            f"  `!storyboard-go` → Generate grids "
            f"(${plan.get('cost_claude', 0) + plan.get('cost_grids', 0):.2f})\n"
            f"  `!storyboard-approve` → Extract + upscale "
            f"(${plan.get('cost_upscale', 0):.2f})"
        )

    def notify_storyboard_start(self, title: str, beat_count: int) -> dict:
        """Notify storyboard generation started."""
        return self.send_message(
            f"🎬 Storyboard generation started — {beat_count} beats "
            f"for \"{title}\""
        )

    def notify_storyboard_beat_done(
        self, title: str, beat_num: int, total_beats: int, cost: float,
    ) -> dict:
        """Notify one beat's grid is complete."""
        return self.send_message(
            f"🎞️ Beat {beat_num}/{total_beats} complete — "
            f"9 panels generated (${cost:.2f})"
        )

    def notify_storyboard_done(
        self, title: str, total_panels: int, total_cost: float,
    ) -> dict:
        """Notify all storyboard grids are complete."""
        return self.send_message(
            f"✅ Storyboards complete — {total_panels} panels generated "
            f"(${total_cost:.2f})\n"
            f"Run `!storyboard-approve` to extract and upscale."
        )

    def notify_storyboard_preview_beat(
        self, title: str, beat_num: int, total_beats: int, summary: str,
    ) -> dict:
        """Send a beat's directive preview."""
        return self.send_message(summary)
