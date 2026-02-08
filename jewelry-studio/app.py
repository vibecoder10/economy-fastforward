"""
Jewelry Studio - Product Image Generator

Locally-hosted tool for generating consistent jewelry product images.
Uses Google Gemini for jewelry analysis and Kie.ai (nano-banana-pro) for generation.

Usage:
    python app.py
    Then open http://localhost:8000 in your browser.
"""

import os
import json
import uuid
import base64
import asyncio
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv

# Load .env from parent directory (shared with main project) or local
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(title="Jewelry Studio")

# Directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# Serve uploaded and generated files
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

# API Keys
KIE_AI_API_KEY = os.getenv("KIE_AI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Kie.ai endpoints (same as existing video pipeline)
KIE_CREATE_TASK = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_MODEL = "nano-banana-pro"

# Gemini endpoint
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


# ──────────────────────────────────────────────
# Gemini Analysis
# ──────────────────────────────────────────────

async def analyze_jewelry(image_paths: list[Path], jewelry_type: str) -> dict:
    """Send jewelry images to Gemini for detailed structured analysis."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env")

    parts = [
        {
            "text": f"""Analyze these jewelry photos of a {jewelry_type}.
Return a detailed JSON description with these exact fields:

{{
  "jewelry_type": "{jewelry_type}",
  "material": "primary material (gold, silver, platinum, rose gold, white gold, etc.)",
  "material_finish": "polished, matte, brushed, hammered, satin, etc.",
  "gemstones": "describe any gemstones, diamonds, pearls - include cut, color, clarity, arrangement. Say 'none' if no gemstones",
  "design_style": "modern, vintage, art deco, minimalist, bohemian, statement, classic, contemporary, etc.",
  "band_chain_details": "describe the band, chain, clasp, or base structure in detail",
  "setting_type": "prong, bezel, pave, channel, tension, halo, etc. Say 'n/a' if not applicable",
  "decorative_elements": "filigree, engraving, milgrain, texture patterns, motifs, etc. Say 'none' if plain",
  "overall_shape": "round, oval, geometric, teardrop, heart, asymmetric, linear, etc.",
  "color_palette": "describe the dominant colors and tones",
  "size_proportion": "delicate, petite, medium, substantial, chunky, oversized, etc.",
  "detailed_description": "A comprehensive 3-4 sentence description capturing every important visual detail of this piece. Be extremely specific about materials, stones, design elements, and craftsmanship."
}}

IMPORTANT: Return ONLY valid JSON. Be extremely detailed and specific about what you see."""
        }
    ]

    for img_path in image_paths:
        img_bytes = img_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        suffix = img_path.suffix.lower()
        mime = "image/png" if suffix == ".png" else "image/jpeg"
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload)
        response.raise_for_status()

    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]

    # Robust JSON parsing (same pattern as existing gemini_client.py)
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        start = clean.find("{")
        end = clean.rfind("}")
        if start != -1 and end != -1:
            try:
                return json.loads(clean[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise HTTPException(
            status_code=500,
            detail=f"Failed to parse Gemini jewelry analysis. Raw: {text[:500]}",
        )


async def analyze_model(image_path: Path) -> str:
    """Analyze model hero image with Gemini to extract a description for prompting."""
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured in .env")

    img_bytes = image_path.read_bytes()
    b64 = base64.b64encode(img_bytes).decode("utf-8")
    suffix = image_path.suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"

    parts = [
        {
            "text": """Describe this model/person for use in an image generation prompt.
Include: skin tone, hair color/length/style, pose, angle, clothing (if visible),
expression, and lighting style.
Return a single paragraph under 80 words. Physical description and pose only.
Do NOT include any JSON formatting."""
        },
        {"inline_data": {"mime_type": mime, "data": b64}},
    ]

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 512},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload)
        response.raise_for_status()

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


# ──────────────────────────────────────────────
# Prompt Crafting
# ──────────────────────────────────────────────

def craft_prompts(jewelry_analysis: dict, model_description: str, jewelry_type: str) -> dict:
    """Create 4 optimized image generation prompts from the analysis."""

    material = jewelry_analysis.get("material", "")
    finish = jewelry_analysis.get("material_finish", "")
    gems = jewelry_analysis.get("gemstones", "")
    style = jewelry_analysis.get("design_style", "")
    setting = jewelry_analysis.get("setting_type", "")
    decorative = jewelry_analysis.get("decorative_elements", "")
    shape = jewelry_analysis.get("overall_shape", "")
    colors = jewelry_analysis.get("color_palette", "")
    size = jewelry_analysis.get("size_proportion", "")
    band = jewelry_analysis.get("band_chain_details", "")
    detailed = jewelry_analysis.get("detailed_description", "")

    # Build rich jewelry descriptor
    parts = [f"{finish} {material} {jewelry_type}"]

    if gems and gems.lower() not in ("none", "n/a", ""):
        parts.append(f"with {gems}")
    if setting and setting.lower() not in ("none", "n/a", ""):
        parts.append(f"{setting} setting")
    if decorative and decorative.lower() not in ("none", "n/a", ""):
        parts.append(f"featuring {decorative}")
    if band and band.lower() not in ("none", "n/a", ""):
        parts.append(f"{band}")

    core = ", ".join(parts)
    style_tag = f"{style} design" if style else ""
    size_tag = f"{size} proportions" if size else ""

    # White background product shot base
    product_base = (
        f"Professional jewelry product photography, {core}, "
        f"{style_tag}, {size_tag}, {colors} tones, "
        f"clean pure white seamless background, professional studio lighting with soft diffusion, "
        f"sharp focus on every detail, high-end commercial jewelry catalog photography, "
        f"no shadows on background, isolated product, 8K resolution, photorealistic"
    )

    prompts = {
        "front": (
            f"{product_base}, straight-on front view, "
            f"perfectly centered in frame, symmetrical composition, eye-level angle"
        ),
        "left": (
            f"{product_base}, three-quarter left angle view, "
            f"showing depth and dimension from the left side, slight 45-degree rotation, "
            f"revealing side profile and craftsmanship details"
        ),
        "right": (
            f"{product_base}, three-quarter right angle view, "
            f"showing depth and dimension from the right side, slight 45-degree rotation, "
            f"revealing side profile and construction details"
        ),
        "model": (
            f"Professional fashion editorial photography, {model_description}, "
            f"wearing a stunning {core}, {style_tag}, "
            f"the {jewelry_type} is the clear focal point of the image, "
            f"soft professional studio lighting, high-end jewelry advertising campaign, "
            f"elegant pose naturally highlighting the {jewelry_type}, "
            f"shallow depth of field on background, crisp focus on jewelry, "
            f"magazine editorial quality, photorealistic, 8K resolution"
        ),
    }

    return prompts


# ──────────────────────────────────────────────
# Kie.ai Image Generation
# ──────────────────────────────────────────────

async def generate_image_kie(prompt: str, aspect_ratio: str = "1:1") -> Optional[str]:
    """Generate a single image via Kie.ai nano-banana-pro and return the result URL."""
    if not KIE_AI_API_KEY:
        raise HTTPException(status_code=500, detail="KIE_AI_API_KEY not configured in .env")

    headers = {
        "Authorization": f"Bearer {KIE_AI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": KIE_MODEL,
        "input": {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "output_format": "png",
        },
    }

    # Create the generation task
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(KIE_CREATE_TASK, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"[Kie.ai] Error {response.status_code}: {response.text}")
            return None
        task_data = response.json()

    task_id = task_data.get("data", {}).get("taskId")
    if not task_id:
        print(f"[Kie.ai] No taskId in response: {task_data}")
        return None

    print(f"[Kie.ai] Task created: {task_id}")

    # Poll for completion
    await asyncio.sleep(5)

    for attempt in range(60):
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                KIE_RECORD_INFO,
                headers={"Authorization": f"Bearer {KIE_AI_API_KEY}"},
                params={"taskId": task_id},
            )
            response.raise_for_status()
            status_data = response.json()

        data = status_data.get("data", {})
        task_status = data.get("status")

        # Check for failure (status 3 = failed in Kie.ai)
        if task_status == 3 or str(task_status).lower() in ("failed", "failure", "error"):
            print(f"[Kie.ai] Task {task_id} failed (status={task_status})")
            return None

        # Check for result
        result_json = data.get("resultJson")
        if result_json:
            if isinstance(result_json, str):
                result_data = json.loads(result_json)
            else:
                result_data = result_json
            result_urls = result_data.get("resultUrls", [])
            if result_urls:
                print(f"[Kie.ai] Task {task_id} completed: {result_urls[0][:80]}...")
                return result_urls[0]

        await asyncio.sleep(3)

    print(f"[Kie.ai] Task {task_id} timed out after polling")
    return None


async def download_and_save(url: str, filename: str) -> str:
    """Download a generated image and save it locally."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    output_path = OUTPUT_DIR / filename
    output_path.write_bytes(response.content)
    return f"/outputs/{filename}"


# ──────────────────────────────────────────────
# API Endpoints
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the main page."""
    html_path = BASE_DIR / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload an image file and return its metadata."""
    file_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    save_path = UPLOAD_DIR / f"{file_id}{suffix}"

    content = await file.read()
    save_path.write_bytes(content)

    return {
        "id": file_id,
        "filename": file.filename,
        "path": f"/uploads/{file_id}{suffix}",
        "size": len(content),
    }


@app.post("/api/generate")
async def generate_product_images(
    jewelry_type: str = Form(...),
    jewelry_files: str = Form(...),
    model_file: str = Form(...),
):
    """
    Main generation endpoint.
    1. Analyzes jewelry photos with Gemini
    2. Analyzes model image with Gemini
    3. Crafts 4 targeted prompts
    4. Generates 4 images via Kie.ai nano-banana-pro
    """
    jewelry_ids = json.loads(jewelry_files)

    # Resolve uploaded file paths
    jewelry_paths = []
    for fid in jewelry_ids:
        matches = list(UPLOAD_DIR.glob(f"{fid}.*"))
        if matches:
            jewelry_paths.append(matches[0])

    model_matches = list(UPLOAD_DIR.glob(f"{model_file}.*"))
    if not model_matches:
        raise HTTPException(status_code=400, detail="Model image not found")
    model_path = model_matches[0]

    if not jewelry_paths:
        raise HTTPException(status_code=400, detail="No jewelry images found")

    # Step 1 & 2: Analyze in parallel
    jewelry_analysis, model_description = await asyncio.gather(
        analyze_jewelry(jewelry_paths, jewelry_type),
        analyze_model(model_path),
    )

    # Step 3: Craft prompts
    prompts = craft_prompts(jewelry_analysis, model_description, jewelry_type)

    # Step 4: Generate all 4 images concurrently
    batch_id = uuid.uuid4().hex[:8]

    async def gen_and_save(view: str, prompt: str):
        url = await generate_image_kie(prompt, aspect_ratio="1:1")
        if url:
            local_path = await download_and_save(url, f"{batch_id}_{view}.png")
            return {"view": view, "url": url, "local": local_path, "prompt": prompt}
        return {
            "view": view,
            "url": None,
            "local": None,
            "prompt": prompt,
            "error": "Generation failed",
        }

    results = await asyncio.gather(*[gen_and_save(k, v) for k, v in prompts.items()])

    return {
        "batch_id": batch_id,
        "jewelry_analysis": jewelry_analysis,
        "model_description": model_description,
        "results": list(results),
    }


@app.post("/api/regenerate")
async def regenerate_single(
    prompt: str = Form(...),
    view: str = Form(...),
    batch_id: str = Form("regen"),
):
    """Regenerate a single image with a modified prompt."""
    url = await generate_image_kie(prompt, aspect_ratio="1:1")
    if url:
        filename = f"{batch_id}_{view}_{uuid.uuid4().hex[:4]}.png"
        local_path = await download_and_save(url, filename)
        return {"view": view, "url": url, "local": local_path, "prompt": prompt}
    raise HTTPException(status_code=500, detail="Image generation failed")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    missing = []
    if not KIE_AI_API_KEY:
        missing.append("KIE_AI_API_KEY")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")

    print()
    print("  Jewelry Studio - Product Image Generator")
    print("  =========================================")
    if missing:
        print(f"  WARNING: Missing env vars: {', '.join(missing)}")
        print(f"  Add them to .env in this directory or the parent directory.")
    print()
    print("  Open http://localhost:8000 in your browser")
    print()

    uvicorn.run(app, host="0.0.0.0", port=8000)
