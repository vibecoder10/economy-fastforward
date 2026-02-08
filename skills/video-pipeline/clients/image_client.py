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

    # Model routing (v2)
    SCENE_MODEL = "seedream-v4"  # Seed Dream 4.0 for ALL scene images - best 3D editorial render
    THUMBNAIL_MODEL = "nano-banana-pro"  # Nano Banana Pro for thumbnails ONLY - proven text rendering

    # Legacy models (deprecated but kept for backwards compatibility)
    DEFAULT_MODEL = "google/nano-banana"  # Uses image_size parameter
    PRO_MODEL = "nano-banana-pro"  # Alias for THUMBNAIL_MODEL
    
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
        
        use_model = model or self.DEFAULT_MODEL

        # nano-banana-pro uses aspect_ratio parameter, google/nano-banana uses image_size
        if use_model == self.PRO_MODEL:
            size_param = {"aspect_ratio": aspect_ratio}
        else:
            size_param = {"image_size": aspect_ratio}

        payload = {
            "model": use_model,
            "input": {
                "prompt": prompt,
                **size_param,
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
            if response.status_code != 200:
                print(f"      ❌ Image API error: {response.status_code} - {response.text}")
                return None
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
        model: str = None,
    ) -> Optional[list[str]]:
        """Generate an image and wait for completion.

        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio
            model: Model to use (defaults to DEFAULT_MODEL, use PRO_MODEL for thumbnails)

        Returns:
            List of image URLs when complete, or None if failed
        """
        try:
            result = await self.create_image(prompt, aspect_ratio, model=model)
        except Exception as e:
            print(f"      ❌ create_image exception (model: {model or self.DEFAULT_MODEL}): {e}")
            return None

        if not result:
            print(f"      ❌ create_image failed (model: {model or self.DEFAULT_MODEL})")
            return None

        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            return None

        # Wait 5 seconds before first poll (Kie API typically returns in ~50-70s for pro model)
        await asyncio.sleep(5)

        # Use higher max_attempts for thumbnail generation (can take 60+ seconds)
        return await self.poll_for_completion(task_id, max_attempts=45, poll_interval=2.0)

    async def generate_scene_image(
        self,
        prompt: str,
        seed: int = None,
    ) -> Optional[dict]:
        """Generate a scene image using Seed Dream 4.0.

        This is the primary method for all scene/content images in the pipeline.
        Uses Seed Dream 4.0 which excels at 3D editorial clay render style.

        Args:
            prompt: Image generation prompt (should use STYLE_ENGINE_PREFIX at start)
            seed: Optional seed for reproducibility

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Seed Dream 4.0 API parameters
        payload = {
            "model": self.SCENE_MODEL,
            "input": {
                "prompt": prompt,
                "image_size": "landscape_16_9",  # Seed Dream uses image_size, not aspect_ratio
                "image_resolution": "2K",  # Balance of quality and speed
                "max_images": 1,  # Always 1 for automation pipeline
            },
        }

        if seed is not None:
            payload["input"]["seed"] = seed

        print(f"      🎨 Generating scene image with Seed Dream 4.0...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )
                if response.status_code != 200:
                    print(f"      ❌ Seed Dream API error: {response.status_code} - {response.text}")
                    return None

                task_data = response.json()
                task_id = task_data.get("data", {}).get("taskId")

                if not task_id:
                    print(f"      ❌ No task ID returned: {task_data}")
                    return None

                # Wait and poll for completion
                await asyncio.sleep(5)
                result_urls = await self.poll_for_completion(task_id, max_attempts=60, poll_interval=2.0)

                if result_urls:
                    # Extract seed from result if available
                    result_seed = task_data.get("data", {}).get("seed", seed)
                    return {
                        "url": result_urls[0],
                        "seed": result_seed,
                    }

                print(f"      ❌ Seed Dream generation failed (poll timeout)")
                return None

        except Exception as e:
            print(f"      ❌ Seed Dream error: {e}")
            return None

    async def generate_thumbnail(self, prompt: str) -> Optional[list[str]]:
        """Generate a thumbnail using Nano Banana Pro.

        This is the method for thumbnail images only. Uses Nano Banana Pro
        which excels at comic/editorial illustration with text rendering.

        Args:
            prompt: Thumbnail generation prompt

        Returns:
            List of image URLs, or None if failed
        """
        print(f"      🖼️ Generating thumbnail with Nano Banana Pro...")
        return await self.generate_and_wait(prompt, "16:9", model=self.THUMBNAIL_MODEL)

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
