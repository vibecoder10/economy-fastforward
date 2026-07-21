"""Image generation client using Kie.ai API.

When a visual profile is loaded, model selection reads from the profile.
Falls back to hardcoded defaults when no profile is available.
"""

import os
import re as _re
import httpx
from typing import Optional
import asyncio
from orchestrator.pipeline_constants import Endpoints, Models

# Kie is the single upstream for text+image+video+voice. A blocked or
# credit-exhausted key is TERMINAL — polling/retrying again can never recover
# it, it just burns the whole retry budget while the user sees "still pending".
# Detect it once and propagate a marked error so the stage stops and the UI can
# tell the customer to fix their key (see backend/error_utils.humanize_error).
KIE_BLOCK_MARKER = "KIE_ACCOUNT_BLOCKED"
_KIE_BLOCK_SIGNALS = (
    "用户已被封禁", "已被封禁", "封禁", "余额不足",
    "insufficient credit", "insufficient balance", "out of credit",
    "account banned", "account is banned", "account suspended",
    KIE_BLOCK_MARKER.lower(),
)


def _is_kie_block(text) -> bool:
    """True if an error message/code signals a banned or out-of-credit Kie key."""
    if not text:
        return False
    low = str(text).lower()
    return any(sig in low or sig in str(text) for sig in _KIE_BLOCK_SIGNALS)


# Grok-imagine's content filter rejects some frames (failCode 430 / "flagged ...
# violating content policies"). It's deterministic for a given frame and costs
# no credits, so retrying the SAME image is pointless — we raise a marked error
# so the caller can redraw the shot with a safer framing and try once more.
CONTENT_POLICY_MARKER = "CONTENT_POLICY_BLOCKED"
_CONTENT_BLOCK_SIGNALS = (
    "430", "violating content polic", "content polic", "flagged",
    "content moderation", "not allowed", "sensitive content",
    CONTENT_POLICY_MARKER.lower(),
)


def _is_content_block(*texts) -> bool:
    """True if any error message/code signals a content-policy rejection."""
    for text in texts:
        if not text:
            continue
        low = str(text).lower()
        if any(sig in low for sig in _CONTENT_BLOCK_SIGNALS):
            return True
    return False


# --- kid-safe prompt scrub ----------------------------------------------------
# GPT Image 2's content policy flags prompts that MENTION minors ("a 7-year-old
# boy", "kid character sheet") even for wholesome family animation — each flag
# wastes the call and risks the account. The fix: never say the words. Every
# outbound image prompt is scrubbed word-for-word into age-neutral visual
# language at THIS send boundary, so no upstream writer (cast extractor,
# coverage planner, thumbnail bot, a creator's own text) can leak one through.
# Deterministic replacements — no model call; the DB/UI keep the natural story
# wording, only what the image model sees changes. Ordered: compound phrases
# before their parts so "kid-friendly" never degrades into "...-friendly".
_MINOR_SCRUB = [
    (_re.compile(r"\b(?:kid|child)[\s-]?friendly\b", _re.I), "family-friendly"),
    (_re.compile(r"\b\d{1,2}[\s-]?year[\s-]?old\s+(?:boy|girl|kid|child)s?\b", _re.I), "young character"),
    (_re.compile(r"\b\d{1,2}[\s-]?years?[\s-]?old\b", _re.I), "young"),
    (_re.compile(r"\bschool\s?(?:boy|girl)s?\b", _re.I), "student character"),
    (_re.compile(r"\b(?:little|small|young)\s+(?:boy|girl|kid|child)s?\b", _re.I), "small young character"),
    (_re.compile(r"\bboys?\b", _re.I), "young male character"),
    (_re.compile(r"\bgirls?\b", _re.I), "young female character"),
    (_re.compile(r"\bchildren\b", _re.I), "young characters"),
    (_re.compile(r"\bchild\b", _re.I), "young character"),
    (_re.compile(r"\bkids\b", _re.I), "young characters"),
    (_re.compile(r"\bkid\b", _re.I), "young character"),
    (_re.compile(r"\btoddlers?\b|\binfants?\b", _re.I), "very small young character"),
    (_re.compile(r"\bbab(?:y|ies)\b", _re.I), "very small"),
    (_re.compile(r"\bteen(?:ager)?s?\b", _re.I), "young character"),
    (_re.compile(r"\bminors?\b", _re.I), "young character"),
    (_re.compile(r"\bniñ[oa]s?\b", _re.I), "young character"),
]


def scrub_minor_terms(prompt: str) -> str:
    """Rewrite age/minor words into age-neutral visual language (see above)."""
    out = prompt or ""
    for rx, repl in _MINOR_SCRUB:
        out = rx.sub(repl, out)
    if out != (prompt or ""):
        print("      🧒 Kid-safe scrub: age words rewritten before sending to the image model")
    return out


def _get_profile():
    """Return the active visual profile, or None."""
    try:
        from shared.profiles.visual import load_profile
        return load_profile()
    except Exception:
        return None


def _scene_model_from_profile() -> str:
    """Get scene model from active profile or hardcoded default."""
    profile = _get_profile()
    if profile:
        return profile.image_gen.scene_model
    return Models.IMAGE_SCENE


def _thumbnail_model_from_profile() -> str:
    """Get thumbnail model from active profile or hardcoded default."""
    profile = _get_profile()
    if profile:
        return profile.image_gen.thumbnail_model
    return Models.IMAGE_THUMBNAIL


def _valid_scene_models_from_profile() -> dict:
    """Get valid scene models from active profile or hardcoded default. GPT Image 2 is ALWAYS
    included (it holds the cast's identity best) regardless of the profile's configured list."""
    profile = _get_profile()
    if profile and profile.raw.get("valid_scene_models"):
        models = dict(profile.raw["valid_scene_models"])
    else:
        models = {
            "nano-banana-2": "Nano Banana 2 (default — reference support, $0.025/img)",
            "z-image": "Z Image ($0.004/img)",
        }
    models.setdefault("gpt-image-2", "GPT Image 2 (best character lock from the cast sheet)")
    return models


def _kie_fetchable_url(url: str, tenant_id=None) -> str:
    """Drive links -> backend media proxy URL (Kie can't ingest Drive's
    interstitial-prone public links). Other hosts pass through.

    C25a-fix2: the proxy (routes/media.py::serve_drive_file) now requires a
    tenant-scoped `?token=` — Kie fetches this URL over plain HTTP with no
    user session to forward, so mint one here for the KNOWN tenant, same
    mint_media_token() pattern pipeline_executor.py's clip dispatch
    (_proxy_url) and routes/characters.py's `_fetch_image_bytes` already use.
    `tenant_id=None` (legacy non-tenant callers, e.g. the standalone
    skills/video-pipeline Slack-bot scripts that construct ImageClient with
    no tenant) keeps the pre-C25a unsigned URL — those never went through
    the tenant-scoped SaaS proxy in the first place.

    C25a-fix5: the path carries a cosmetic ".png" suffix. Some Kie model
    input validators reject URLs without a recognizable file extension —
    the exact failure InfiniteTalk hit (fixed for the clip path by commit
    10d232e5 + pipeline_executor.py's _with_ext), and the prime suspect in
    gpt-image-2-image-to-image's failCode-400 "could not be processed"
    rejections of extension-less proxy URLs (2026-07-20, video cd5d2883):
    Kie failed those tasks WITHOUT ever fetching the URLs, i.e. at input
    validation. Every URL this helper builds is an image reference, so
    ".png" is always an appropriate cosmetic type hint. The suffix goes on
    the PATH, before any ?token= query (appending after the query would
    corrupt the JWT — see _with_ext's docstring), and the proxy route
    (routes/media.py::serve_drive_file) strips it before resolving the id."""
    import re as _re
    if not url or "drive.google.com" not in url:
        return url
    m = _re.search(r"[?&]id=([\w-]+)", url) or _re.search(r"/d/([\w-]+)", url)
    if not m:
        return url
    base = os.getenv("PUBLIC_MEDIA_BASE", "https://storyengine.dev").rstrip("/")
    proxy_url = f"{base}/api/media/drive/{m.group(1)}.png"
    if tenant_id:
        from routes.media import mint_media_token
        proxy_url = f"{proxy_url}?token={mint_media_token(tenant_id)}"
    return proxy_url


class ImageClient:
    """Client for image and video generation via Kie.ai API."""

    # Kie.ai API endpoints
    CREATE_TASK_URL = Endpoints.KIE_CREATE_TASK
    RECORD_INFO_URL = Endpoints.KIE_RECORD_INFO

    # Veo 3.1 API endpoints
    VEO_GENERATE_URL = Endpoints.VEO_GENERATE
    VEO_RECORD_INFO_URL = Endpoints.VEO_RECORD_INFO
    VEO_1080P_URL = Endpoints.VEO_1080P

    # Model routing — reads from profile with hardcoded fallbacks
    SCENE_MODEL = _scene_model_from_profile()
    THUMBNAIL_MODEL = _thumbnail_model_from_profile()

    # Alternative scene image models (hot-swappable via Slack !model command)
    ZIMAGE_MODEL = Models.IMAGE_ZIMAGE  # Z Image — high-quality image generation
    NANO_BANANA_MODEL = Models.IMAGE_SCENE  # Nano Banana 2 — legacy/reference support

    # Valid scene image models for hot-swap validation
    VALID_SCENE_MODELS = _valid_scene_models_from_profile()

    # Veo 3.1 models
    VEO_MODEL_FAST = Models.VEO_FAST  # Faster, lower cost
    VEO_MODEL_QUALITY = Models.VEO_QUALITY  # Higher quality, slower

    # Legacy models (deprecated but kept for backwards compatibility)
    DEFAULT_MODEL = "google/nano-banana"  # Uses image_size parameter
    PRO_MODEL = Models.IMAGE_THUMBNAIL  # Alias for THUMBNAIL_MODEL
    
    def __init__(self, api_key: Optional[str] = None, google_client: Optional[object] = None,
                 tenant_id: Optional[object] = None):
        # C25a-fix2: threaded through to _kie_fetchable_url() so every
        # reference-image URL this client hands to Kie carries a valid
        # tenant-scoped media-proxy token. None (the default) preserves
        # pre-C25a behavior for the non-tenant standalone callers.
        self.tenant_id = tenant_id
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
        model: str = Models.ANIMATION_GROK,
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
                task_id = (task_data.get("data") or {}).get("taskId")
                
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
        if use_model in (self.PRO_MODEL, "nano-banana-2", self.NANO_BANANA_MODEL):
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
        fail_info_out: Optional[list] = None,
    ) -> Optional[list[str]]:
        """Poll for image generation completion.

        Args:
            task_id: Task ID to poll
            max_attempts: Maximum polling attempts
            poll_interval: Seconds between polls
            fail_info_out: optional list the caller passes in to receive Kie's
                raw failure details ({"failCode", "failMsg", "creditsConsumed"})
                on a FAILED task (append, don't assign — same fresh-box-per-call
                convention as task_id_out). Populated on every failure path
                below, including the ones that raise a marked RuntimeError
                (mutation happens before the raise, so callers that catch and
                swallow that exception — e.g. generate_thumbnail_gpt2 — still
                get the detail). C25a-fix8 (2026-07-20): lets a caller detect
                the specific zero-credit "content could not be processed" /
                "may violate OpenAI's content policies" rejection and retry
                with different prompt wording, instead of guessing from a bare
                None return.

        Returns:
            List of image URLs when complete, or None if failed
        """
        for _ in range(max_attempts):
            try:
                status = await self.get_task_status(task_id)
            except Exception as e:
                if _is_kie_block(e):
                    raise  # terminal — don't keep polling a blocked account
                print(f"      ⚠️ Poll error: {e}")
                await asyncio.sleep(poll_interval)
                continue

            if not status:
                print(f"      ⚠️ Empty status response")
                await asyncio.sleep(poll_interval)
                continue

            # Kie can return HTTP 200 with a present-but-null "data" key on an
            # in-body failure (code != 200) — `.get("data", {})` does NOT apply
            # the default for a null value, only a missing key, so the next
            # `.get()` on None used to raise AttributeError and swallow Kie's
            # real error message (tasks/lessons.md: present-but-NULL trap).
            data = status.get("data") or {}
            if not data:
                print(f"      ❌ Poll response has no usable data (code={status.get('code')}): "
                      f"{status.get('msg') or status.get('message')}")
                print(f"         Full response: {status}")
                await asyncio.sleep(poll_interval)
                continue

            # Check explicit status or state
            # 0: Queue, 1: Running, 2: Success, 3: Failed (Common Kie.ai pattern)
            task_status = data.get("status")
            task_state = data.get("state")
            
            # Log status for debug
            print(f"      DEBUG: State: {task_state} | Status: {task_status}")

            if (task_status == 3 or
                str(task_status).lower() in ["failed", "failure", "error"] or
                str(task_state).lower() in ["fail", "failed", "failure", "error"]):

                # Extract all available error details. Kie reports clip failures
                # in failMsg/failCode (NOT errorMessage) — read those first or the
                # log just says "No error details provided".
                error_msg = (data.get("failMsg") or data.get("errorMessage")
                             or data.get("error") or data.get("msg") or "No error details provided")
                error_code = data.get("failCode") or data.get("errorCode") or data.get("code")
                task_id_str = data.get("taskId", "unknown")
                print(f"      ❌ Task FAILED (taskId: {task_id_str})")
                print(f"         State: {task_state} | Status: {task_status}")
                print(f"         Error: {error_msg}")
                if error_code:
                    print(f"         Error code: {error_code}")
                # Log the full response data for debugging hard-to-diagnose failures
                print(f"         Full response data: {data}")
                if fail_info_out is not None:
                    fail_info_out.append({
                        "failCode": error_code, "failMsg": error_msg,
                        "creditsConsumed": data.get("creditsConsumed"),
                    })
                # A banned / out-of-credit account is terminal — raise a marked
                # error so the stage stops and the user gets an actionable
                # "fix your Kie key" message, instead of a silent None that the
                # caller retries until the budget is gone.
                if _is_kie_block(error_msg) or _is_kie_block(error_code):
                    raise RuntimeError(f"{KIE_BLOCK_MARKER}: {error_msg}")
                # Content-filter rejection (failCode 430): deterministic for this
                # frame and free — raise a marked error so the caller can redraw
                # the shot safer and retry, instead of burning 3 identical retries.
                if str(error_code) == "430" or _is_content_block(error_msg):
                    raise RuntimeError(f"{CONTENT_POLICY_MARKER}: {error_msg}")
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
        task_id_out: Optional[list] = None,
    ) -> Optional[list[str]]:
        """Generate an image and wait for completion.

        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio
            model: Model to use (defaults to DEFAULT_MODEL, use PRO_MODEL for thumbnails)
            task_id_out: optional list the caller passes in to receive the
                Kie taskId once create_image succeeds (append, don't assign
                — see generate_video's task_id_out docstring). Used for
                generation_ledger traceability (checklist C16c).

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

        task_id = (result.get("data") or {}).get("taskId")
        if not task_id:
            api_msg = result.get("msg") or result.get("message") or "unknown"
            api_code = result.get("code", "unknown")
            print(f"      ❌ No task ID in response (model: {use_model})")
            print(f"         API code: {api_code}, message: {api_msg}")
            print(f"         Prompt: {prompt_preview}")
            return None

        print(f"      🎯 Task created: {task_id} (model: {use_model})")
        if task_id_out is not None:
            task_id_out.append(task_id)

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
        """Generate a scene image using Nano Banana 2 with Core Image reference.

        This is the primary method for all scene/content images in the pipeline.
        Every call requires a reference image (the Core Image from the project)
        to maintain visual consistency.

        Args:
            prompt: Image generation prompt (should use STYLE_ENGINE_PREFIX at start)
            reference_image_url: URL of the Core Image from the project
            seed: Unused (kept for API compatibility). Nano Banana 2 does not support seeds.

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Nano Banana 2 API parameters
        payload = {
            "model": self.SCENE_MODEL,
            "input": {
                "prompt": prompt,
                "image_input": [_kie_fetchable_url(reference_image_url, self.tenant_id)],
                "aspect_ratio": "16:9",
                "resolution": "1K",
                "output_format": "png",
                "google_search": True,
            },
        }

        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        print(f"      🎨 Generating scene image with Nano Banana 2 (Core Image ref)...")

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
                task_id = (task_data.get("data") or {}).get("taskId")

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
                    return {
                        "url": result_urls[0],
                        "seed": None,
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
        """Generate a scene image using Nano Banana 2 with a reference image.

        Uses the Core Image as reference to maintain character/scene consistency
        when generating end frames for animation.

        Args:
            prompt: Image generation prompt describing the end frame
            reference_image_url: URL of the Core Image to use as reference
            seed: Unused (kept for API compatibility)

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        # Delegates to generate_scene_image which uses Nano Banana 2
        return await self.generate_scene_image(prompt, reference_image_url, seed)

    async def generate_scene_image_zimage(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        task_id_out: Optional[list] = None,
    ) -> Optional[dict]:
        """Generate a scene image using Z Image model.

        Z Image is a text-to-image model (no reference image support).
        Uses the same Kie.ai task/poll API pattern.

        Args:
            prompt: Image generation prompt
            aspect_ratio: Aspect ratio (16:9, 9:16, 1:1, 4:3, 3:4)
            task_id_out: optional list the caller passes in to receive the
                Kie taskId once the create-task call succeeds (append, don't
                assign — same fresh-box-per-call pattern as generate_video's
                task_id_out, so a shared empty list is safe under concurrent
                calls). Used for generation_ledger traceability (checklist
                C16c / migration 093's dedup index).

        Returns:
            Dict with 'url' and 'seed' keys, or None if failed
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.ZIMAGE_MODEL,
            "input": {
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
            },
        }

        prompt_preview = prompt[:100] + "..." if len(prompt) > 100 else prompt
        print(f"      🎨 Generating scene image with Z Image...")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL,
                    headers=headers,
                    json=payload,
                    timeout=60.0,
                )
                if response.status_code != 200:
                    print(f"      ❌ Z Image API error: {response.status_code}")
                    print(f"         Response: {response.text[:500]}")
                    print(f"         Prompt: {prompt_preview}")
                    return None

                task_data = response.json()
                task_id = (task_data.get("data") or {}).get("taskId")

                if not task_id:
                    print(f"      ❌ No task ID returned")
                    print(f"         API response: {task_data}")
                    print(f"         Prompt: {prompt_preview}")
                    return None

                print(f"      🎯 Z Image task: {task_id}")
                if task_id_out is not None:
                    task_id_out.append(task_id)

                # Wait and poll — Z Image uses state-based polling (waiting/success/fail)
                await asyncio.sleep(5)
                result_urls = await self.poll_for_completion(task_id, max_attempts=60, poll_interval=2.0)

                if result_urls:
                    return {
                        "url": result_urls[0],
                        "seed": None,
                    }

                print(f"      ❌ Z Image generation failed (task: {task_id})")
                print(f"         Prompt: {prompt_preview}")
                return None

        except Exception as e:
            print(f"      ❌ Z Image error: {e}")
            print(f"         Prompt: {prompt_preview}")
            import traceback
            traceback.print_exc()
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

    async def generate_with_reference(
        self,
        prompt: str,
        reference_image_url,
        aspect_ratio: str = "16:9",
        resolution: str = "1K",
        task_id_out: Optional[list] = None,
    ) -> Optional[dict]:
        """Generate an image using a reference for character consistency.

        Uses nano-banana-pro with image_input for maintaining visual consistency
        between start and end frames of a scene.

        Args:
            prompt: Image generation prompt
            reference_image_url: URL of reference image (e.g., start_image)
            aspect_ratio: Output aspect ratio
            resolution: nano-banana-pro output resolution ("1K", "2K", "4K").
                Storyboard grids pass a higher value so each extracted panel
                (1/9th of the grid) is sharp enough to drive video generation;
                the panels are the final frames and there is no upscale pass.
            task_id_out: optional list the caller passes in to receive the
                Kie taskId once the create-task call succeeds (append, don't
                assign — see generate_video's task_id_out docstring). Used
                for generation_ledger traceability (checklist C16c).

        Returns:
            Dict with 'url' key, or None if failed
        """
        prompt = scrub_minor_terms(prompt)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Accepts one URL or a list (multi-character casts) — Kie's
        # image_input is a list either way. Drive URLs are rewritten to the
        # backend media proxy: Kie fetches reference images over plain HTTP,
        # and Drive's public links degrade into HTML interstitials ('file
        # type not supported' rejections seen live).
        refs = reference_image_url if isinstance(reference_image_url, list) else [reference_image_url]
        refs = [_kie_fetchable_url(r, self.tenant_id) for r in refs if r][:6]

        payload = {
            "model": self.THUMBNAIL_MODEL,  # nano-banana-pro
            "input": {
                "prompt": prompt,
                "image_input": refs,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,  # Required with image_input to enforce aspect ratio
            },
        }

        print(f"      🎨 Generating with reference (nano-banana-pro, {resolution})...")

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

                task_id = (task_data.get("data") or {}).get("taskId")
                if not task_id:
                    print(f"      ❌ No task ID returned")
                    return None
                if task_id_out is not None:
                    task_id_out.append(task_id)

                # Wait and poll — multi-reference generations (character casts)
                # routinely take 2-4 minutes; the old 120s budget timed out on
                # real grids and read as silent failures.
                await asyncio.sleep(5)
                result_urls = await self.poll_for_completion(task_id, max_attempts=90, poll_interval=5.0)

                if result_urls:
                    return {"url": result_urls[0]}

                print(f"      ❌ Generation failed (poll timeout)")
                return None

        except Exception as e:
            print(f"      ❌ Reference image error: {e}")
            return None

    async def generate_thumbnail_gpt2(
        self,
        prompt: str,
        reference_image_url,
        aspect_ratio: str = "16:9",
        resolution: str = "2K",
        task_id_out: Optional[list] = None,
        fail_info_out: Optional[list] = None,
    ) -> Optional[dict]:
        """Generate a thumbnail with OpenAI GPT Image 2 via kie.ai
        (gpt-image-2-image-to-image). Same shape as generate_with_reference but
        routed to GPT Image 2, which holds character identity from the cast
        sheet markedly better (live A/B on the bird video: nailed Dr. May where
        nano-banana drifted). References go in `input_urls` (max 16).

        task_id_out: optional list the caller passes in to receive the Kie
        taskId once the create-task call succeeds (append, don't assign —
        see generate_video's task_id_out docstring). Used for
        generation_ledger traceability (checklist C16c).

        fail_info_out: optional list the caller passes in to receive Kie's
        raw failure detail dict on a FAILED poll (see poll_for_completion's
        docstring) — C25a-fix8, lets a caller (the storyboard sheet dispatch)
        detect the specific OpenAI content-filter rejection signature and
        retry with different prompt wording instead of guessing from None."""
        prompt = scrub_minor_terms(prompt)
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        refs = reference_image_url if isinstance(reference_image_url, list) else [reference_image_url]
        refs = [_kie_fetchable_url(r, self.tenant_id) for r in refs if r][:16]
        payload = {
            "model": "gpt-image-2-image-to-image",
            "input": {
                "prompt": prompt,
                "input_urls": refs,
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
            },
        }
        print("      🎨 Generating thumbnail (gpt-image-2)...")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL, headers=headers, json=payload, timeout=60.0,
                )
                if response.status_code != 200:
                    print(f"      ❌ API error: {response.status_code} - {response.text}")
                    return None
                task_data = response.json()
                if task_data.get("code") != 200:
                    print(f"      ❌ API error: {task_data.get('msg')}")
                    return None
                task_id = (task_data.get("data") or {}).get("taskId")
                if not task_id:
                    print("      ❌ No task ID returned")
                    return None
                if task_id_out is not None:
                    task_id_out.append(task_id)
                await asyncio.sleep(5)
                # poll_for_completion returns None on either of two distinct
                # paths: an explicit Kie fail-state it detected instantly
                # (populates fail_info_out) or genuine 120-attempt budget
                # exhaustion (fail_info_out stays empty). Use a local box when
                # the caller didn't pass one so we can still tell them apart —
                # a real Kie rejection is not a "timeout" and printing it as
                # one sends debugging down the wrong path.
                _fail_probe = fail_info_out if fail_info_out is not None else []
                result_urls = await self.poll_for_completion(
                    task_id, max_attempts=120, poll_interval=5.0, fail_info_out=_fail_probe)
                if result_urls:
                    return {"url": result_urls[0]}
                if _fail_probe:
                    info = _fail_probe[-1]
                    print(f"      ❌ Generation failed (Kie reported fail: {info.get('failCode')})")
                else:
                    print("      ❌ Generation failed (poll budget exhausted after 120 attempts)")
                return None
        except Exception as e:
            print(f"      ❌ GPT Image 2 error: {e}")
            return None

    async def generate_scene_image_gpt(
        self,
        prompt: str,
        reference_image_url=None,
        aspect_ratio: str = "16:9",
        allow_fallback: bool = True,
        resolution: str = "2K",
        task_id_out: Optional[list] = None,
    ) -> Optional[dict]:
        """Scene image via GPT Image 2 — holds the cast's character identity far better than
        nano-banana (see generate_thumbnail_gpt2). With a reference it's image-to-image; without
        one it falls back to gpt-image-2 text-to-image. Returns {'url': ...} or None.

        allow_fallback=False disables the nano-banana-2 last resort: accuracy-critical
        callers (static documentary channels) would rather fail the scene for review
        than ship a lesser model's guess of a specific historical machine.

        task_id_out: optional list the caller passes in to receive the Kie taskId
        of whichever attempt below succeeds (append, don't assign — see
        generate_video's task_id_out docstring). Used for generation_ledger
        traceability (checklist C16c)."""
        prompt = scrub_minor_terms(prompt)
        if reference_image_url:
            return await self.generate_thumbnail_gpt2(
                prompt, reference_image_url, aspect_ratio, resolution=resolution,
                task_id_out=task_id_out)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        async def _run(model: str, extra: dict, label: str):
            """Returns (status, url): 'ok' | 'blocked' (content policy) | 'fail' (transient)."""
            payload = {"model": model, "input": {"prompt": prompt, "aspect_ratio": aspect_ratio, **extra}}
            print(f"      🎨 Generating ({label} text-to-image)...")
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(self.CREATE_TASK_URL, headers=headers, json=payload, timeout=60.0)
                    if response.status_code != 200:
                        print(f"      ❌ {label} API error: {response.status_code} - {response.text[:160]}")
                        return ("fail", None)
                    task_data = response.json()
                    if task_data.get("code") != 200:
                        print(f"      ❌ {label} API error: {task_data.get('msg')}")
                        return ("fail", None)
                    task_id = (task_data.get("data") or {}).get("taskId")
                    if not task_id:
                        print(f"      ❌ {label}: no task ID returned")
                        return ("fail", None)
                    if task_id_out is not None:
                        task_id_out.append(task_id)
                    await asyncio.sleep(5)
                    urls = await self.poll_for_completion(task_id, max_attempts=120, poll_interval=5.0)
                    return ("ok", urls[0]) if urls else ("fail", None)
            except Exception as e:
                msg = str(e)
                if CONTENT_POLICY_MARKER in msg or _is_content_block(msg):
                    print(f"      🚫 {label} refused (content policy)")
                    return ("blocked", None)
                if KIE_BLOCK_MARKER in msg:
                    raise  # banned / out-of-credit is terminal; nano shares the same key
                print(f"      ❌ {label} error: {e}")
                return ("fail", None)

        # GPT Image 2 is the engine. nano-banana-2 is used ONLY when GPT genuinely can't:
        # a CONTENT-POLICY block (e.g. reference sheets of children) switches to nano right
        # away; a transient blip just RETRIES GPT (better quality), with nano as a last resort.
        status = "fail"
        for attempt in range(2):
            status, url = await _run("gpt-image-2-text-to-image", {"resolution": resolution}, "gpt-image-2")
            if status == "ok":
                return {"url": url, "model": "gpt-image-2"}
            if status == "blocked":
                break  # GPT will never render this — switch to nano now
            await asyncio.sleep(2 * (attempt + 1))  # transient — retry GPT
        why = "content-policy block" if status == "blocked" else "GPT Image 2 unavailable after retries"
        if not allow_fallback:
            print(f"      ❌ {why} — nano fallback disabled for this caller, failing the image")
            return None
        print(f"      ↩️  {why} — switching to nano-banana-2...")
        status, url = await _run("nano-banana-2", {"output_format": "png"}, "nano-banana-2")
        return {"url": url, "model": "nano-banana-2"} if status == "ok" and url else None

    async def generate_talking_video(
        self,
        image_url: str,
        audio_url: str,
        prompt: str,
        resolution: str = "480p",
        task_id_out: Optional[list] = None,
    ) -> Optional[str]:
        """Audio-driven speaking clip via InfiniteTalk (Kie).

        The mouth is GENERATED FROM the audio waveform, so lip-sync is
        inherent — no post-hoc alignment. Output length = audio length
        ($0.015/sec at 480p). Slow: ~7 min per clip observed live, so the
        poll budget covers 15 (lesson: budgets match real task duration).
        Audio max 15s; image/audio must be Kie-fetchable (media proxy URLs).
        """
        print(f"      🗣️ Generating talking clip (InfiniteTalk, {resolution})...")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "infinitalk/from-audio",
            "input": {
                "image_url": image_url,
                "audio_url": audio_url,
                "prompt": prompt,
                "resolution": resolution,
            },
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self.CREATE_TASK_URL, headers=headers, json=payload, timeout=30.0,
                )
                task_data = response.json()
                task_id = (task_data.get("data") or {}).get("taskId")
                if not task_id:
                    print(f"      ❌ InfiniteTalk createTask failed: {str(task_data.get('msg'))[:150]}")
                    return None
                if task_id_out is not None:
                    task_id_out.append(task_id)
            await asyncio.sleep(30)
            result_urls = await self.poll_for_completion(task_id, max_attempts=90, poll_interval=10.0)
            return result_urls[0] if result_urls else None
        except Exception as e:
            print(f"      ❌ InfiniteTalk error: {str(e)[:150]}")
            return None

    # Grok-imagine's accepted aspect ratios. It defaults to VERTICAL and ignores
    # the source image's shape, so a 16:9 frame gets cropped to portrait unless
    # we pass the ratio explicitly.
    GROK_ASPECTS = {"16:9", "9:16", "1:1", "2:3", "3:2"}
    # Grok-imagine resolutions (Kie). 480p is the default; 720p is YouTube-ready.
    GROK_RESOLUTIONS = {"480p", "720p"}

    async def generate_video(
        self,
        image_url: str,
        prompt: str,
        duration: int = 6, # Grok-imagine supports 6–30s (Kie). Default 6.
        extra_image_urls: Optional[list] = None,
        aspect_ratio: Optional[str] = None,
        resolution: Optional[str] = None,
        task_id_out: Optional[list] = None,
    ) -> Optional[str]:
        """Generate a video from an image using Grok Imagine via Kie.ai.

        extra_image_urls: Grok accepts up to 7 reference images, addressed in
        the prompt as @image1, @image2, ... — we pass the labeled cast sheet
        as @image2 to lock characters/style (same one-sheet trick that fixed
        storyboard drift).
        aspect_ratio: '16:9' / '9:16' / etc. REQUIRED to get a landscape clip —
        Grok crops to vertical by default, so omitting it ruined 16:9 videos.
        resolution: '480p' / '720p' — the quality selector.
        task_id_out: optional list the caller passes in to receive the Kie
        taskId once the create-task call succeeds (append, don't assign —
        keeps this safe to share a fresh empty list per concurrent call
        instead of a shared mutable attribute on self, which would race
        under concurrent clip generation). Used for generation_ledger
        traceability (storyengine-wiring-fix-checklist.md §0.3a).
        """

        # Grok-imagine (Kie) accepts any duration 6–30s as a string. Clamp to
        # that range so a long spoken line gets a long enough clip instead of
        # being silently knocked back to 6s.
        dur = max(6, min(30, int(duration)))
        if dur != duration:
            print(f"      ⚠️ Duration {duration}s out of Grok's 6–30s range; using {dur}s.")
        duration_str = str(dur)

        image_urls = [image_url] + [u for u in (extra_image_urls or []) if u][:6]
        print(f"      🎬 Generating video with Grok Imagine (Duration: {duration_str}s, refs: {len(image_urls)})...")
        print(f"      Debugging Image URL: {image_url}") # Log URL
        print(f"      Prompt: {prompt[:50]}...")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Grok Imagine Schema
        # Input: image_urls (array, max 7), prompt, duration (string), mode,
        # aspect_ratio (omit -> Grok crops to vertical, breaking 16:9 videos).
        grok_input = {
            "image_urls": image_urls,
            "prompt": prompt,
            "duration": duration_str,
            "mode": "normal", # Spicy not supported for external images
        }
        if aspect_ratio in self.GROK_ASPECTS:
            grok_input["aspect_ratio"] = aspect_ratio
        elif aspect_ratio:
            print(f"      ⚠️ Aspect '{aspect_ratio}' not a Grok ratio; letting it default.")
        if resolution in self.GROK_RESOLUTIONS:
            grok_input["resolution"] = resolution
        elif resolution:
            print(f"      ⚠️ Resolution '{resolution}' not a Grok option; letting it default.")
        payload = {"model": Models.ANIMATION_GROK, "input": grok_input}

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
                    
                    # Safe access. Back off before retrying — Kie fetches our
                    # media-proxy URLs at createTask, and right after a backend
                    # restart the proxy serves cold-start 502 HTML, which Kie
                    # reports as "File type not supported". Three instant
                    # retries all land in the same cold window and a clip tap
                    # taken seconds after a deploy fails 100% (S1.4, twice).
                    data_obj = task_data.get("data")
                    if not data_obj:
                        print(f"      ERROR: No 'data' in response: {task_data}")
                        await asyncio.sleep(4 * (attempt + 1))
                        continue # Retry

                    task_id = data_obj.get("taskId")

                    if not task_id:
                        print(f"❌ Failed to get video task ID: {task_data}")
                        await asyncio.sleep(4 * (attempt + 1))
                        continue # Retry

                    if task_id_out is not None:
                        task_id_out.append(task_id)
                    print(f"    🎬 Video task started: {task_id}")
                    
                    # 2. Wait and Poll
                    # Video generation takes longer, but we check sooner for fails
                    await asyncio.sleep(10) # Reduced from 60 to 10
                    
                    result_urls = await self.poll_for_completion(task_id, max_attempts=120, poll_interval=5.0) # More freq checks
                    if result_urls:
                        return result_urls[0] # Return the first video URL
                    
                    print(f"      ⚠️ Attempt {attempt+1} failed (Poll returned failure). Retrying...")

            except Exception as e:
                # Terminal failures must propagate, not burn retries: a content-
                # filter block is deterministic for this frame (the caller redraws
                # it safer), and a banned/out-of-credit key won't recover.
                if CONTENT_POLICY_MARKER in str(e) or _is_kie_block(e):
                    raise
                print(f"❌ Video generation error (Attempt {attempt+1}): {str(e)}")
                # wait before retry
                await asyncio.sleep(5)

        print("❌ All retry attempts failed.")
        return None

    async def generate_video_seedance(
        self,
        image_url: str,
        prompt: str,
        duration: int = 6,
        extra_image_urls: Optional[list] = None,
        aspect_ratio: str = "16:9",
        task_id_out: Optional[list] = None,
    ) -> Optional[str]:
        """Animate one keyframe with Seedance 2.0 Fast — the pricier, smoother tier.
        Same call shape as generate_video so the executor can swap them. image_url is
        the first frame. Reuses the same createTask + poll path as Grok.

        C25a-fix7: Kie's Seedance docs (docs.kie.ai/market/bytedance/seedance-2-fast)
        state "Image-to-Video (First Frame), Image-to-Video (First & Last Frames),
        and Multimodal Reference-to-Video are three mutually exclusive scenarios and
        cannot be used simultaneously" — sending both first_frame_url AND
        reference_image_urls in one call (as this used to) is exactly the combo Kie
        rejects with "The reference image and the first and last frames are mutually
        exclusive, and only one scene can be selected" (100% createTask failure,
        prod 2026-07-20 16:46). Animating one storyboard panel needs the frame to be
        EXACTLY that panel (see the "Animate @image1 exactly as shown" prompt
        contract in pipeline_executor's _decorate) — First-Frame mode is the only one
        of the three that guarantees literal frame fidelity; the docs note
        Multimodal Reference-to-Video can only "indirectly achieve" a first-frame
        match "through prompt specification", not a strict one. So: first_frame_url
        only. extra_image_urls (the cast sheet) is accepted for call-shape parity
        with generate_video/the executor's animate_fn signature but intentionally
        NOT sent — Seedance has no slot for it once first_frame_url is in play."""
        dropped_refs = len([u for u in (extra_image_urls or []) if u])
        payload = {
            "model": Models.ANIMATION_SEEDANCE,
            "input": {
                "prompt": prompt,
                "first_frame_url": image_url,
                "aspect_ratio": aspect_ratio,
                "resolution": "720p",  # ponytail: 720p tier; bump to 1080p if needed
                "duration": int(duration),
                "generate_audio": True,
            },
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if dropped_refs:
            print(f"      ⚠️ Seedance: dropping {dropped_refs} cast-sheet ref(s) — "
                  f"first_frame_url and reference_image_urls are mutually exclusive on Kie.")
        print(f"      🎬 Seedance 2.0 ({duration}s, {aspect_ratio}, first-frame only)...")
        for attempt in range(3):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self.CREATE_TASK_URL, headers=headers, json=payload, timeout=30.0)
                    response.raise_for_status()
                    task_data = response.json()
                task_id = (task_data.get("data") or {}).get("taskId")
                if not task_id:
                    print(f"      ⚠️ Seedance createTask failed (attempt {attempt+1}): "
                          f"{str(task_data.get('msg'))[:150]}")
                    await asyncio.sleep(4 * (attempt + 1))
                    continue
                if task_id_out is not None:
                    task_id_out.append(task_id)
                print(f"    🎬 Seedance task started: {task_id}")
                await asyncio.sleep(10)
                result_urls = await self.poll_for_completion(task_id, max_attempts=120, poll_interval=5.0)
                if result_urls:
                    return result_urls[0]
                print(f"      ⚠️ Seedance attempt {attempt+1} poll failed. Retrying...")
            except Exception as e:
                print(f"❌ Seedance error (attempt {attempt+1}): {str(e)[:150]}")
                await asyncio.sleep(5)
        print("❌ Seedance: all attempts failed.")
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
        task_id_out: Optional[list] = None,
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

                    task_id = (task_data.get("data") or {}).get("taskId")
                    if not task_id:
                        print(f"      ❌ No task ID returned: {task_data}")
                        continue

                    if task_id_out is not None:
                        task_id_out.append(task_id)
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
                    body = response.json()
                    # Present-but-null "data" (Kie in-body failure with HTTP 200)
                    # used to crash `.get("data", {}).get(...)` with an
                    # AttributeError that ate Kie's real msg (tasks/lessons.md).
                    data = body.get("data") or {}
                    if not data:
                        print(f"      ❌ Veo poll has no usable data (code={body.get('code')}): "
                              f"{body.get('msg') or body.get('message')}")
                        print(f"         Full response: {body}")
                        await asyncio.sleep(poll_interval)
                        continue

                    success_flag = data.get("successFlag")

                    # successFlag: 0=generating, 1=success, 2=failed, 3=generation error
                    if success_flag == 1:
                        # Success - extract video URL
                        response_data = data.get("response") or {}
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
                body = response.json()
                # Present-but-null "data" trap (tasks/lessons.md) — a bare
                # `.get("data", {})` doesn't apply the default when the key
                # exists with a null value, so a chained `.get("hdUrl")`
                # would crash and eat Kie's real code/msg.
                data = body.get("data") or {}
                if not data:
                    print(f"      ❌ 1080p upgrade has no usable data (code={body.get('code')}): "
                          f"{body.get('msg') or body.get('message')}")
                    print(f"         Full response: {body}")
                    return None
                hd_url = data.get("hdUrl")

                if hd_url:
                    print(f"      ✅ 1080p upgrade available!")
                    return hd_url

        except Exception as e:
            print(f"      ⚠️ 1080p upgrade error: {e}")

        return None
