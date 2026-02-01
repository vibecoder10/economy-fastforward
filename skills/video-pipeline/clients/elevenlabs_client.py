"""ElevenLabs/Wavespeed voice synthesis client."""

import os
import httpx
from typing import Optional
import asyncio


class ElevenLabsClient:
    """Client for voice synthesis via Wavespeed API (ElevenLabs turbo)."""
    
    # Default voice ID from n8n workflow
    DEFAULT_VOICE_ID = "G17SuINrv2H9FC6nvetn"
    
    # Wavespeed API endpoint (as used in n8n workflow)
    WAVESPEED_API_URL = "https://api.wavespeed.ai/api/v3/elevenlabs/turbo-v2.5"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        voice_id: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("WAVESPEED_API_KEY")
        if not self.api_key:
            raise ValueError("WAVESPEED_API_KEY not found in environment")
        
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", self.DEFAULT_VOICE_ID)
    
    async def generate_voice(
        self,
        text: str,
        voice_id: Optional[str] = None,
        similarity: float = 1.0,
        stability: float = 0.5,
    ) -> dict:
        """Generate voice audio from text.
        
        Args:
            text: Text to convert to speech
            voice_id: Voice ID to use (uses default if not specified)
            similarity: Voice similarity (0-1)
            stability: Voice stability (0-1)
            
        Returns:
            Dict with task ID and status URL for polling
        """
        target_voice = voice_id or self.voice_id
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "text": text,
            "voice_id": target_voice,
            "similarity": str(similarity),
            "stability": str(stability),
            "use_speaker_boost": True,
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.WAVESPEED_API_URL,
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()
    
    async def poll_for_completion(
        self,
        get_url: str,
        max_attempts: int = 30,
        poll_interval: float = 5.0,
    ) -> Optional[str]:
        """Poll for voice generation completion.
        
        Args:
            get_url: URL to poll for status
            max_attempts: Maximum polling attempts
            poll_interval: Seconds between polls
            
        Returns:
            Audio URL when complete, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        async with httpx.AsyncClient() as client:
            for _ in range(max_attempts):
                response = await client.get(get_url, headers=headers, timeout=30.0)
                response.raise_for_status()
                data = response.json()
                
                status = data.get("data", {}).get("status")
                
                if status == "completed":
                    outputs = data.get("data", {}).get("outputs", [])
                    return outputs[0] if outputs else None
                elif status == "failed":
                    return None
                
                await asyncio.sleep(poll_interval)
        
        return None
    
    async def generate_and_wait(
        self,
        text: str,
        voice_id: Optional[str] = None,
    ) -> Optional[str]:
        """Generate voice audio and wait for completion.
        
        Args:
            text: Text to convert to speech
            voice_id: Voice ID to use
            
        Returns:
            Audio URL when complete, or None if failed
        """
        result = await self.generate_voice(text, voice_id)
        
        get_url = result.get("data", {}).get("urls", {}).get("get")
        if not get_url:
            return None
        
        return await self.poll_for_completion(get_url)
    
    async def download_audio(self, audio_url: str) -> bytes:
        """Download audio file from URL.
        
        Args:
            audio_url: URL of the audio file
            
        Returns:
            Audio content as bytes
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(audio_url, timeout=60.0)
            response.raise_for_status()
            return response.content
