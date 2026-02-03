"""Image generation client using Kie.ai API."""

import os
import httpx
from typing import Optional
import asyncio


class ImageClient:
    """Client for image generation via Kie.ai API."""

    # Kie.ai API endpoints (from n8n workflow)
    CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
    RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"
    QUERY_TASK_URL = "https://api.kie.ai/api/v1/jobs/queryTask"

    # Default model from n8n workflow
    DEFAULT_MODEL = "google/nano-banana"
    # High-quality thumbnail model
    THUMBNAIL_MODEL = "nano-banana-pro"
    
    def __init__(self, api_key: Optional[str] = None, google_client: Optional[object] = None):
        self.api_key = api_key or os.getenv("KIE_AI_API_KEY")
        if not self.api_key:
            raise ValueError("KIE_AI_API_KEY not found in environment")
        self.google_client = google_client
    
    async def proxy_image_to_drive(self, image_url: str) -> str:
        """Download image from URL and upload to Drive, returning public link."""
        if not self.google_client:
            print("⚠️ Cannot proxy image: GoogleClient not available.")
            return image_url
            
        print(f"      🛡️ Proxying image to Google Drive...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(image_url, timeout=30.0)
                response.raise_for_status()
                content = response.content
                
            # Upload to Drive
            # Using a temp filename based on timestamp or hash
            import time
            file_name = f"proxy_image_{int(time.time())}.png"
            
            # Use parent folder from google client
            folder_id = self.google_client.parent_folder_id
            
            # Upload
            file = self.google_client.upload_image(content, file_name, folder_id)
            print(f"      ✅ Uploaded to Drive: {file['name']}")
            
            # Make public
            public_link = self.google_client.make_file_public(file["id"])
            print(f"      🔗 Public Drive Link: {public_link}")
            return public_link
            
        except Exception as e:
            print(f"      ❌ Proxy failed: {e}")
            return image_url

    async def generate_video(
        self,
        image_url: str,
        prompt: str,
        duration: int = 5,
        model: str = "grok-imagine/image-to-video",
    ) -> Optional[str]:
        """Generate a video from an image."""
        
        # ... logic ...
        current_image_url = image_url
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # ... existing calls ...
                # Use current_image_url
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                
                payload = {
                    "model": model,
                    "input": {
                        "image_url": current_image_url, # Use dynamic URL
                        "prompt": prompt,
                        "duration": str(duration),
                        "mode": "normal", # default
                        "loop": False,
                    },
                }
                
                print(f"      DEBUG: Using Image URL: {current_image_url}")

                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.CREATE_TASK_URL,
                        headers=headers,
                        json=payload,
                        timeout=60.0,
                    )
                    
                if response.status_code == 500:
                    print(f"      ⚠️ Attempt {attempt + 1} failed (500). Retrying...")
                    # Proxy if Google Client exists
                    if self.google_client and attempt < max_retries - 1:
                       current_image_url = await self.proxy_image_to_drive(image_url)
                    continue
                    
                response.raise_for_status()
                task_data = response.json()
                task_id = task_data.get("data", {}).get("taskId")
                
                if task_id:
                    print(f"    🎬 Video task started: {task_id}")
                    
                    # 2. Wait and Poll
                    # Video generation takes longer, but we check sooner for fails
                    await asyncio.sleep(10) # Reduced from 60 to 10
                    
                    result_urls = await self.poll_for_completion(task_id, max_attempts=120, poll_interval=5.0) # More freq checks
                    if result_urls:
                        return result_urls[0] # Return the first video URL
                        
                    # If poll returns None/Empty -> Fail
                    print(f"      ❌ Video generation failed (Poll failed). Retrying...")
                    if self.google_client and attempt < max_retries - 1:
                        current_image_url = await self.proxy_image_to_drive(image_url)
                    continue
            
            except Exception as e:
                print(f"      ❌ Video generation error: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(5)
                    
        return None

    async def create_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        model: str = None,
        output_format: str = "png",
    ) -> dict:
        """Create an image generation task.
        
        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio (16:9 or 9:16)
            model: Model to use (defaults to google/nano-banana)
            output_format: Output format (png, jpg)
            
        Returns:
            Dict with task ID for polling
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        payload = {
            "model": model or self.DEFAULT_MODEL,
            "input": {
                "prompt": prompt,
                "output_format": output_format,
                "image_size": aspect_ratio,
            },
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.CREATE_TASK_URL,
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json()
    
    async def get_task_status(self, task_id: str) -> dict:
        """Get the status of an image generation task.
        
        Args:
            task_id: Task ID from create_image
            
        Returns:
            Task status dict
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.RECORD_INFO_URL,
                headers=headers,
                params={"taskId": task_id},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
    
    async def poll_for_completion(
        self,
        task_id: str,
        max_attempts: int = 30,
        poll_interval: float = 2.0,
    ) -> Optional[list[str]]:
        """Poll for image generation completion.
        
        Args:
            task_id: Task ID to poll
            max_attempts: Maximum polling attempts
            poll_interval: Seconds between polls
            
        Returns:
            List of image URLs when complete, or None if failed
        """
        for _ in range(max_attempts):
            status = await self.get_task_status(task_id)
            data = status.get("data", {})
            
            # Check explicit status or state
            # 0: Queue, 1: Running, 2: Success, 3: Failed (Common Kie.ai pattern)
            task_status = data.get("status")
            task_state = data.get("state")
            
            # Log status for debug
            print(f"      DEBUG: State: {task_state} | Status: {task_status}")

            if (task_status == 3 or 
                str(task_status).lower() in ["failed", "failure", "error"] or
                str(task_state).lower() in ["fail", "failed", "failure", "error"]):
                
                print(f"      ⚠️ Task reported failure (State: {task_state}, Status: {task_status})")
                return None

            result_json = data.get("resultJson")
            if result_json:
                # Parse the result
                import json
                if isinstance(result_json, str):
                    result_data = json.loads(result_json)
                else:
                    result_data = result_json
                
                result_urls = result_data.get("resultUrls", [])
                if result_urls:
                    return result_urls
            
            await asyncio.sleep(poll_interval)
        
        return None
    
    async def generate_and_wait(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
    ) -> Optional[list[str]]:
        """Generate an image and wait for completion.
        
        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio
            
        Returns:
            List of image URLs when complete, or None if failed
        """
        result = await self.create_image(prompt, aspect_ratio)
        
        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            return None
        
        # Wait 5 seconds before first poll (Kie API typically returns in ~10s)
        await asyncio.sleep(5)
        
        return await self.poll_for_completion(task_id)

    async def generate_video(
        self,
        image_url: str,
        prompt: str,
        duration: int = 6, # Grok supports 6 or 10. Default 6.
    ) -> Optional[str]:
        """Generate a video from an image using Grok Imagine via Kie.ai."""
        
        # Duration check (must be 6 or 10)
        # We will cast to string as per docs ("6" or "10")
        if duration not in [6, 10]:
            print(f"      ⚠️ Duration {duration} not supported by Grok. Defaulting to 6.")
            duration_str = "6"
        else:
            duration_str = str(duration)
            
        print(f"      🎬 Generating video with Grok Imagine (Duration: {duration_str}s)...")
        print(f"      Debugging Image URL: {image_url}") # Log URL
        print(f"      Prompt: {prompt[:50]}...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Grok Imagine Schema
        # Model: grok-imagine/image-to-video
        # Input: image_urls (array), prompt, duration (string), mode (default normal)
        payload = {
            "model": "grok-imagine/image-to-video",
            "input": {
                "image_urls": [image_url],
                "prompt": prompt,
                "duration": duration_str,
                "mode": "normal", # Spicy not supported for external images
            },
        }

        # Retry loop for robustness
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 1. Create Task
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.CREATE_TASK_URL,
                        headers=headers,
                        json=payload,
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    task_data = response.json()
                    print(f"      DEBUG: API Response (Attempt {attempt+1}): {task_data}")
                    
                    # Safe access
                    data_obj = task_data.get("data")
                    if not data_obj:
                        print(f"      ERROR: No 'data' in response: {task_data}")
                        continue # Retry
                        
                    task_id = data_obj.get("taskId")
                    
                    if not task_id:
                        print(f"❌ Failed to get video task ID: {task_data}")
                        continue # Retry
                        
                    print(f"    🎬 Video task started: {task_id}")
                    
                    # 2. Wait and Poll
                    # Video generation takes longer, but we check sooner for fails
                    await asyncio.sleep(10) # Reduced from 60 to 10
                    
                    result_urls = await self.poll_for_completion(task_id, max_attempts=120, poll_interval=5.0) # More freq checks
                    if result_urls:
                        return result_urls[0] # Return the first video URL
                    
                    print(f"      ⚠️ Attempt {attempt+1} failed (Poll returned failure). Retrying...")

            except Exception as e:
                print(f"❌ Video generation error (Attempt {attempt+1}): {str(e)}")
                # wait before retry
                await asyncio.sleep(5)
                
        print("❌ All retry attempts failed.")
        return None
    
    async def download_image(self, image_url: str) -> bytes:
        """Download image from URL.

        Args:
            image_url: URL of the image

        Returns:
            Image content as bytes
        """
        async with httpx.AsyncClient() as client:
            response = await client.get(image_url, timeout=60.0)
            response.raise_for_status()
            return response.content

    # ==================== THUMBNAIL GENERATION ====================

    async def create_thumbnail_task(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        output_format: str = "png",
    ) -> str:
        """Create a thumbnail generation task using nano-banana-pro model.

        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio (16:9 recommended for thumbnails)
            resolution: Output resolution (2K for high quality)
            output_format: Output format (png, jpg)

        Returns:
            Task ID for polling
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.THUMBNAIL_MODEL,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "output_format": output_format,
            },
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.CREATE_TASK_URL,
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            result = response.json()

        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            raise ValueError(f"Failed to get task ID: {result}")

        return task_id

    async def query_thumbnail_task(self, task_id: str) -> dict:
        """Query the status of a thumbnail generation task.

        Args:
            task_id: Task ID from create_thumbnail_task

        Returns:
            Task status dict with state and result
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(
                self.QUERY_TASK_URL,
                headers=headers,
                params={"taskId": task_id},
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()

    async def poll_thumbnail_completion(
        self,
        task_id: str,
        poll_interval: float = 5.0,
        timeout_seconds: float = 120.0,
    ) -> Optional[str]:
        """Poll for thumbnail generation completion.

        Args:
            task_id: Task ID to poll
            poll_interval: Seconds between polls (default 5s per PRD)
            timeout_seconds: Timeout in seconds (default 2 minutes per PRD)

        Returns:
            Image URL when complete, or None if failed/timeout
        """
        import time

        start_time = time.time()
        max_attempts = int(timeout_seconds / poll_interval)

        for attempt in range(max_attempts):
            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                print(f"      ⏱️ Thumbnail generation timed out after {timeout_seconds}s")
                return None

            status = await self.query_thumbnail_task(task_id)
            data = status.get("data", {})

            # Check state
            state = data.get("state", "").lower()
            print(f"      DEBUG: Thumbnail state: {state} (attempt {attempt + 1})")

            if state == "success":
                # Extract image URL from resultJson
                result_json = data.get("resultJson")
                if result_json:
                    import json
                    if isinstance(result_json, str):
                        result_data = json.loads(result_json)
                    else:
                        result_data = result_json

                    result_urls = result_data.get("resultUrls", [])
                    if result_urls:
                        return result_urls[0]

            if state in ["fail", "failed", "failure", "error"]:
                print(f"      ❌ Thumbnail generation failed: {data}")
                return None

            await asyncio.sleep(poll_interval)

        print(f"      ⏱️ Thumbnail polling exhausted after {max_attempts} attempts")
        return None

    async def generate_thumbnail(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
    ) -> Optional[str]:
        """Generate a thumbnail and wait for completion.

        Full pipeline: create task -> poll -> return URL.

        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio
            resolution: Output resolution

        Returns:
            Image URL when complete, or None if failed
        """
        print(f"    🎨 Generating thumbnail with {self.THUMBNAIL_MODEL}...")
        print(f"    Prompt: {prompt[:100]}...")

        try:
            # Create task
            task_id = await self.create_thumbnail_task(
                prompt=prompt,
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )
            print(f"    📋 Task created: {task_id}")

            # Poll for completion
            image_url = await self.poll_thumbnail_completion(task_id)

            if image_url:
                print(f"    ✅ Thumbnail generated: {image_url[:50]}...")
                return image_url
            else:
                print("    ❌ Thumbnail generation failed")
                return None

        except Exception as e:
            print(f"    ❌ Thumbnail generation error: {e}")
            return None
