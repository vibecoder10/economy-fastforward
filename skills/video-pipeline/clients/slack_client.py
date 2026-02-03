"""Slack API client for notifications."""

import os
from typing import Optional
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


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
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN not found in environment")
        
        self.channel_id = channel_id or os.getenv("SLACK_CHANNEL_ID", self.DEFAULT_CHANNEL_ID)
        self.client = WebClient(token=self.bot_token)
    
    def send_message(self, text: str, channel_id: Optional[str] = None) -> dict:
        """Send a message to a Slack channel.
        
        Args:
            text: Message text (supports Slack markdown)
            channel_id: Channel to send to (uses default if not specified)
            
        Returns:
            Slack API response dict
        """
        target_channel = channel_id or self.channel_id
        
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
            return {"ok": False, "error": str(e)}
    
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
    
    def notify_script_done(self, doc_url: str) -> dict:
        """Notify that the script is complete."""
        return self.send_message(
            f"✅ Script is Done!\n\n"
            f"📄 View your script: {doc_url}\n\n"
            f"Now generating voice overs... 🗣️"
        )
    
    def notify_voice_start(self) -> dict:
        """Notify that voice generation has started."""
        return self.send_message("🗣️ Starting to make the Voice Over!")
    
    def notify_voice_done(self) -> dict:
        """Notify that voice overs are complete."""
        return self.send_message(
            "✅ Voice Over Done!\n\n"
            "Now generating image prompts... 🌉"
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
    
    def notify_pipeline_complete(self, video_title: str, folder_url: str) -> dict:
        """Notify that the entire pipeline is complete."""
        return self.send_message(
            f"🎉 *Video Production Complete!*\n\n"
            f"📹 *{video_title}*\n\n"
            f"📁 All assets: {folder_url}\n\n"
            f"Ready for final video assembly in Remotion!"
        )
    
    def notify_error(self, step: str, error: str) -> dict:
        """Notify of an error in the pipeline."""
        return self.send_message(
            f"❌ *Error in {step}*\n\n"
            f"```{error}```\n\n"
            f"Please check and retry."
        )

    def notify_queue_complete(self, results: list[dict]) -> dict:
        """Send queue completion summary to Slack."""
        message = "✅ *Pipeline Queue Complete*\n\n"
        message += f"Processed {len(results)} videos:\n"
        for result in results:
            title = result.get("title", "Unknown")
            new_status = result.get("new_status", "Unknown")
            error = result.get("error")
            if error:
                message += f"• \"{title}\" → Failed ({error})\n"
            else:
                message += f"• \"{title}\" → {new_status}\n"
        message += "\nCheck Google Drive for completed assets."
        return self.send_message(message)
