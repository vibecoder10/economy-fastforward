"""Image generation client using Kie.ai API."""

import os
import httpx
from typing import Optional
import asyncio


class ImageClient:
    """Client for image and video generation via Kie.ai API."""

    # Kie.ai API endpoints (from n8n workflow)
    CREATE_TASK_URL = "https://api.kie.ai/api/v1/jobs/createTask"
    RECORD_INFO_URL = "https://api.kie.ai/api/v1/jobs/recordInfo"

    # Veo 3.1 API endpoints (separate from generic jobs API)
    VEO_GENERATE_URL = "https://api.kie.ai/api/v1/veo/generate"
    VEO_RECORD_INFO_URL = "https://api.kie.ai/api/v1/veo/record-info"
    VEO_1080P_URL = "https://api.kie.ai/api/v1/veo/get-1080p-video"

    # Model routing (v2)
    SCENE_MODEL = "seedream/4.5-edit"  # Seed Dream 4.5 Edit — all scene images use reference
    THUMBNAIL_MODEL = "nano-banana-pro"  # Nano Banana Pro for thumbnails - text rendering

    # Veo 3.1 models
    VEO_MODEL_FAST = "veo3_fast"  # Faster, lower cost
    VEO_MODEL_QUALITY = "veo3"  # Higher quality, slower

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
                prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
                print(f"      ❌ Image API error: HTTP {response.status_code}")
                print(f"         Response: {response.text[:500]}")
                print(f"         Model: {use_model}")
                print(f"         Prompt: {prompt_preview}")
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
            try:
                status = await self.get_task_status(task_id)
            except Exception as e:
                print(f"      ⚠️ Poll error: {e}")
                await asyncio.sleep(poll_interval)
                continue

            if not status:
                print(f"      ⚠️ Empty status response")
                await asyncio.sleep(poll_interval)
                continue

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

                # Extract all available error details from the API response
                error_msg = data.get("errorMessage") or data.get("error") or data.get("msg") or "No error details provided"
                error_code = data.get("errorCode") or data.get("code")
                task_id_str = data.get("taskId", "unknown")
                print(f"      ❌ Task FAILED (taskId: {task_id_str})")
                print(f"         State: {task_state} | Status: {task_status}")
                print(f"         Error: {error_msg}")
                if error_code:
                    print(f"         Error code: {error_code}")
                # Log the full response data for debugging hard-to-diagnose failures
                print(f"         Full response data: {data}")
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
        use_model = model or self.DEFAULT_MODEL
        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt

        try:
            result = await self.create_image(prompt, aspect_ratio, model=model)
        except Exception as e:
            print(f"      ❌ create_image exception (model: {use_model}): {e}")
            print(f"         Prompt: {prompt_preview}")
            return None

        if not result:
            print(f"      ❌ create_image failed (model: {use_model}) — API returned no result")
            print(f"         Prompt: {prompt_preview}")
            return None

        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            api_msg = result.get("msg") or result.get("message") or "unknown"
            api_code = result.get("code", "unknown")
            print(f"      ❌ No task ID in response (model: {use_model})")
            print(f"         API code: {api_code}, message: {api_msg}")
            print(f"         Prompt: {prompt_preview}")
            return None

        print(f"      🎯 Task created: {task_id} (model: {use_model})")

        # Wait 5 seconds before first poll (Kie API typically returns in ~50-70s for pro model)
        await asyncio.sleep(5)

        # Use higher max_attempts for thumbnail generation (can take 60+ seconds)
        result_urls = await self.poll_for_completion(task_id, max_attempts=45, poll_interval=2.0)

        if not result_urls:
            print(f"      ❌ Generation failed for task {task_id} (model: {use_model})")
            print(f"         Prompt: {prompt_preview}")

        return result_urls

    async def generate_scene_image(
        self,
        prompt: str,
        reference_image_url: str,
        seed: int = None,
    ) -> Optional[dict]:
        """Generate a scene image using Seed Dream 4.5 Edit with Core Image reference.

        This is the primary method for all scene/content images in the pipeline.
        Every call requires a reference image (the Core Image from the project)
        to maintain visual consistency.

        Args:
            prompt: Image generation prompt (should use STYLE_ENGINE_PREFIX at start)
            reference_image_url: URL of the Core Image from the project
            seed: Optional seed for reproducibility

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Seed Dream 4.5 Edit API parameters
        payload = {
            "model": self.SCENE_MODEL,
            "input": {
                "prompt": prompt,
                "image_urls": [reference_image_url],
                "aspect_ratio": "16:9",
                "quality": "basic",
            },
        }

        if seed is not None:
            payload["input"]["seed"] = seed

        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        print(f"      🎨 Generating scene image with Seed Dream 4.5 Edit (Core Image ref)...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )
                if response.status_code != 200:
                    print(f"      ❌ Scene image API error: {response.status_code}")
                    print(f"         Response: {response.text[:500]}")
                    print(f"         Prompt: {prompt_preview}")
                    return None

                task_data = response.json()
                task_id = task_data.get("data", {}).get("taskId")

                if not task_id:
                    print(f"      ❌ No task ID returned")
                    print(f"         API response: {task_data}")
                    print(f"         Prompt: {prompt_preview}")
                    return None

                print(f"      🎯 Scene image task: {task_id}")

                # Wait and poll for completion
                await asyncio.sleep(5)
                result_urls = await self.poll_for_completion(task_id, max_attempts=60, poll_interval=2.0)

                if result_urls:
                    result_seed = task_data.get("data", {}).get("seed", seed)
                    return {
                        "url": result_urls[0],
                        "seed": result_seed,
                    }

                print(f"      ❌ Scene image generation failed (task: {task_id})")
                print(f"         Prompt: {prompt_preview}")
                return None

        except Exception as e:
            print(f"      ❌ Scene image error: {e}")
            print(f"         Prompt: {prompt_preview}")
            import traceback
            traceback.print_exc()
            return None

    async def generate_scene_image_with_reference(
        self,
        prompt: str,
        reference_image_url: str,
        seed: int = None,
    ) -> Optional[dict]:
        """Generate a scene image using Seed Dream 4.5 Edit with a reference image.

        Uses the Core Image as reference to maintain character/scene consistency
        when generating end frames for animation.

        Args:
            prompt: Image generation prompt describing the end frame
            reference_image_url: URL of the Core Image to use as reference
            seed: Optional seed for reproducibility

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        # Delegates to generate_scene_image which already uses Seed Dream 4.5 Edit
        return await self.generate_scene_image(prompt, reference_image_url, seed)

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

    async def generate_with_reference(
        self,
        prompt: str,
        reference_image_url: str,
        aspect_ratio: str = "16:9",
    ) -> Optional[dict]:
        """Generate an image using a reference for character consistency.

        Uses nano-banana-pro with image_input for maintaining visual consistency
        between start and end frames of a scene.

        Args:
            prompt: Image generation prompt
            reference_image_url: URL of reference image (e.g., start_image)
            aspect_ratio: Output aspect ratio

        Returns:
            Dict with 'url' key, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.THUMBNAIL_MODEL,  # nano-banana-pro
            "input": {
                "prompt": prompt,
                "image_input": [reference_image_url],
                "aspect_ratio": aspect_ratio,
            },
        }

        print(f"      🎨 Generating with reference (nano-banana-pro)...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )

                if response.status_code != 200:
                    print(f"      ❌ API error: {response.status_code} - {response.text}")
                    return None

                task_data = response.json()
                if task_data.get("code") != 200:
                    print(f"      ❌ API error: {task_data.get('msg')}")
                    return None

                task_id = task_data.get("data", {}).get("taskId")
                if not task_id:
                    print(f"      ❌ No task ID returned")
                    return None

                # Wait and poll
                await asyncio.sleep(5)
                result_urls = await self.poll_for_completion(task_id, max_attempts=60, poll_interval=2.0)

                if result_urls:
                    return {"url": result_urls[0]}

                print(f"      ❌ Generation failed (poll timeout)")
                return None

        except Exception as e:
            print(f"      ❌ Reference image error: {e}")
            return None

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

    # ==========================================================================
    # VEO 3.1 VIDEO GENERATION
    # ==========================================================================

    async def generate_video_veo(
        self,
        prompt: str,
        image_url: str = None,
        model: str = None,
        aspect_ratio: str = "16:9",
        seed: int = None,
    ) -> Optional[str]:
        """Generate a video using Veo 3.1.

        Supports both text-to-video and image-to-video generation.

        Args:
            prompt: Text description of desired video content
            image_url: Optional image URL for image-to-video mode
            model: 'veo3_fast' (default) or 'veo3' for higher quality
            aspect_ratio: '16:9' (default), '9:16', or 'Auto'
            seed: Optional seed (10000-99999) for reproducibility

        Returns:
            Video URL when complete, or None if failed
        """
        use_model = model or self.VEO_MODEL_FAST
        generation_type = "REFERENCE_2_VIDEO" if image_url else "TEXT_2_VIDEO"

        print(f"      🎬 Generating video with Veo 3.1 ({use_model})...")
        print(f"      Mode: {generation_type}")
        print(f"      Prompt: {prompt[:80]}...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "prompt": prompt,
            "model": use_model,
            "generationType": generation_type,
            "aspect_ratio": aspect_ratio,
            "enableTranslation": False,  # Prompts are already in English
        }

        if image_url:
            payload["imageUrls"] = [image_url]

        if seed is not None:
            payload["seeds"] = seed

        max_retries = 3
        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.VEO_GENERATE_URL,
                        headers=headers,
                        json=payload,
                        timeout=60.0,
                    )

                    # Handle specific error codes
                    if response.status_code == 400:
                        print(f"      ⚠️ 1080P processing in progress, retrying in 90s...")
                        await asyncio.sleep(90)
                        continue
                    elif response.status_code == 402:
                        print(f"      ❌ Insufficient credits")
                        return None
                    elif response.status_code == 429:
                        print(f"      ⚠️ Rate limited, waiting 30s...")
                        await asyncio.sleep(30)
                        continue

                    response.raise_for_status()
                    task_data = response.json()

                    task_id = task_data.get("data", {}).get("taskId")
                    if not task_id:
                        print(f"      ❌ No task ID returned: {task_data}")
                        continue

                    print(f"      🎬 Veo task started: {task_id}")

                    # Poll for completion (Veo has different polling endpoint)
                    await asyncio.sleep(15)  # Initial wait
                    result_url = await self._poll_veo_completion(task_id)

                    if result_url:
                        return result_url

                    print(f"      ⚠️ Attempt {attempt + 1} failed. Retrying...")

            except Exception as e:
                print(f"      ❌ Veo error (attempt {attempt + 1}): {e}")
                await asyncio.sleep(5)

        print("      ❌ All Veo retry attempts failed.")
        return None

    async def _poll_veo_completion(
        self,
        task_id: str,
        max_attempts: int = 120,
        poll_interval: float = 5.0,
    ) -> Optional[str]:
        """Poll Veo 3.1 task for completion.

        Args:
            task_id: Veo task ID
            max_attempts: Maximum polling attempts (default 120 = 10 min)
            poll_interval: Seconds between polls

        Returns:
            Video URL when complete, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        for attempt in range(max_attempts):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        self.VEO_RECORD_INFO_URL,
                        headers=headers,
                        params={"taskId": task_id},
                        timeout=30.0,
                    )
                    response.raise_for_status()
                    data = response.json().get("data", {})

                    success_flag = data.get("successFlag")

                    # successFlag: 0=generating, 1=success, 2=failed, 3=generation error
                    if success_flag == 1:
                        # Success - extract video URL
                        response_data = data.get("response", {})
                        result_urls = response_data.get("resultUrls", [])

                        if result_urls:
                            # resultUrls may be a JSON string or list
                            if isinstance(result_urls, str):
                                import json
                                result_urls = json.loads(result_urls)

                            print(f"      ✅ Veo generation complete!")
                            return result_urls[0] if result_urls else None

                    elif success_flag in [2, 3]:
                        error_msg = data.get("errorMessage", "Unknown error")
                        print(f"      ❌ Veo generation failed: {error_msg}")
                        return None

                    # Still generating (successFlag == 0)
                    if attempt % 6 == 0:  # Log every 30 seconds
                        print(f"      ⏳ Still generating... (attempt {attempt + 1}/{max_attempts})")

            except Exception as e:
                print(f"      ⚠️ Poll error: {e}")

            await asyncio.sleep(poll_interval)

        print(f"      ❌ Veo poll timeout after {max_attempts} attempts")
        return None

    async def upgrade_veo_to_1080p(self, task_id: str) -> Optional[str]:
        """Upgrade a completed Veo video to 1080p.

        Args:
            task_id: Original Veo task ID

        Returns:
            1080p video URL, or None if upgrade not available
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        print(f"      📺 Requesting 1080p upgrade...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self.VEO_1080P_URL,
                    headers=headers,
                    params={"taskId": task_id},
                    timeout=30.0,
                )

                if response.status_code == 400:
                    print(f"      ⏳ 1080p processing, will be available in 1-2 min")
                    return None

                response.raise_for_status()
                data = response.json().get("data", {})
                hd_url = data.get("hdUrl")

                if hd_url:
                    print(f"      ✅ 1080p upgrade available!")
                    return hd_url

        except Exception as e:
            print(f"      ⚠️ 1080p upgrade error: {e}")

        return None
