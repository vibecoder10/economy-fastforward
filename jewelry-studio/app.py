"""
Jewelry Studio - Product Image Generator

Workflow:
    Step 1: Upload YOUR jewelry (1-3 photos for 360° reference)
    Step 2: Upload a MODEL reference (person wearing jewelry - for the on-model shot)
    Step 3: Upload a STYLE reference (professional product shot to match)
    → Select jewelry type + optional extra instructions
    → Generate 3 images: Head-On, Angled, On-Model

Usage:
    python app.py
    Then open http://localhost:8000
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
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(title="Jewelry Studio")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")

KIE_AI_API_KEY = os.getenv("KIE_AI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

KIE_CREATE_TASK = "https://api.kie.ai/api/v1/jobs/createTask"
KIE_RECORD_INFO = "https://api.kie.ai/api/v1/jobs/recordInfo"
KIE_MODEL = "nano-banana-pro"

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _img_part(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode("utf-8")
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return {"inline_data": {"mime_type": mime, "data": b64}}


def _parse_json(text: str) -> dict:
    clean = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        s, e = clean.find("{"), clean.rfind("}")
        if s != -1 and e != -1:
            try:
                return json.loads(clean[s : e + 1])
            except json.JSONDecodeError:
                pass
        raise HTTPException(500, detail=f"Gemini JSON parse failed: {text[:500]}")


async def _gemini(parts: list, temp: float = 0.2, tokens: int = 2048, as_json: bool = True) -> str:
    if not GEMINI_API_KEY:
        raise HTTPException(500, detail="GEMINI_API_KEY not set in .env")
    cfg = {"temperature": temp, "maxOutputTokens": tokens}
    if as_json:
        cfg["responseMimeType"] = "application/json"
    payload = {"contents": [{"parts": parts}], "generationConfig": cfg}
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(GEMINI_URL, params={"key": GEMINI_API_KEY}, json=payload)
        r.raise_for_status()
    return r.json()["candidates"][0]["content"]["parts"][0]["text"]


def _resolve(file_id: str) -> Path:
    matches = list(UPLOAD_DIR.glob(f"{file_id}.*"))
    if not matches:
        raise HTTPException(400, detail=f"File {file_id} not found")
    return matches[0]


# ──────────────────────────────────────────────
# Gemini Analysis
# ──────────────────────────────────────────────

async def analyze_jewelry_piece(image_paths: list[Path], jewelry_type: str) -> dict:
    """Step 1 analysis: Extract detailed JSON description of the actual jewelry piece."""
    parts = [
        {"text": f"""You are analyzing {len(image_paths)} photo(s) of a {jewelry_type} that a jeweler wants professional product shots of.
These are raw/casual photos. Your job is to extract EVERY visual detail so an image generator can recreate this EXACT piece.

Return JSON with these fields:

{{
  "jewelry_type": "{jewelry_type}",
  "material": "exact metal type and color (yellow gold, white gold, rose gold, sterling silver, platinum, etc.)",
  "material_finish": "polished, matte, brushed, hammered, satin, oxidized, etc.",
  "gemstones": "DETAILED description of all stones: type, cut (round brilliant, princess, emerald, pear, marquise, cushion, oval, etc.), color, approximate size, clarity appearance, and arrangement. Say 'none' if no gemstones.",
  "gemstone_count": "number and arrangement of stones (e.g. '1 center stone with 12 pave side stones')",
  "design_style": "modern, vintage, art deco, minimalist, bohemian, statement, classic, filigree, etc.",
  "band_chain_details": "band width, chain type, clasp style, base structure details",
  "setting_type": "prong, bezel, pave, channel, tension, halo, cluster, cathedral, etc.",
  "decorative_elements": "filigree, engraving, milgrain, twisted rope, braided, texture patterns, openwork, etc.",
  "overall_shape": "describe the overall silhouette and form",
  "color_palette": "all visible colors and their relationships",
  "size_proportion": "delicate, petite, medium, substantial, chunky, oversized",
  "unique_features": "anything distinctive that makes this piece identifiable - unusual details, asymmetry, mixed metals, etc.",
  "detailed_description": "A comprehensive 4-5 sentence description that would let someone recreate this EXACT piece. Include every detail about materials, stones, metalwork, proportions, and design elements. This is the most important field."
}}

Be EXTREMELY specific. The goal is to describe this piece so accurately that the generated image looks like the same piece, not just a similar one."""}
    ]
    for p in image_paths:
        parts.append(_img_part(p))

    return _parse_json(await _gemini(parts))


async def analyze_model_reference(image_path: Path) -> str:
    """Step 2 analysis: Describe the model/person ONLY (ignore any jewelry they're wearing)."""
    parts = [
        {"text": """Describe this model/person for an image generation prompt.

IMPORTANT: IGNORE any jewelry the model is wearing. Only describe the PERSON.

Include: skin tone, hair (color, length, style), facial features, pose, body angle,
expression, clothing (if visible), and the lighting/environment.

Return a single paragraph, under 100 words. Focus on physical description and pose.
Do NOT mention or describe any jewelry in the image.
Do NOT use JSON formatting."""},
        _img_part(image_path),
    ]
    return await _gemini(parts, temp=0.3, tokens=512, as_json=False)


async def analyze_style_reference(image_path: Path) -> dict:
    """Step 3 analysis: Extract the photographic STYLE from the reference product shot."""
    parts = [
        {"text": """Analyze this professional jewelry product photo purely for its PHOTOGRAPHIC STYLE.
I want to recreate this exact look with a DIFFERENT piece of jewelry.

Return JSON:

{
  "background": "describe background (color, gradient, texture, surface material, any visible elements)",
  "lighting": "lighting setup (direction, softness, highlights, shadows, rim light, fill, etc.)",
  "orientation": "how the jewelry sits (flat lay, angled, standing, elevated, hanging, draped, on bust/hand, etc.)",
  "camera_angle": "camera perspective (top-down, eye-level, 45-degree, macro close-up, slight overhead, etc.)",
  "composition": "framing style (centered, rule-of-thirds, tight crop, breathing room, negative space, etc.)",
  "mood": "overall aesthetic (luxurious, minimal, warm, cool, editorial, catalog, lifestyle, romantic, etc.)",
  "props_surface": "any props or surfaces (velvet, marble, wood, fabric, mirror, flowers, none, etc.)",
  "color_grading": "color temperature and tone (warm, cool, neutral, high contrast, low contrast, muted, vibrant)",
  "style_summary": "2-sentence summary of the entire photographic style. Be specific enough to use as a generation directive."
}

IMPORTANT: Describe the STYLE, not the jewelry. Return ONLY valid JSON."""},
        _img_part(image_path),
    ]
    return _parse_json(await _gemini(parts))


# ──────────────────────────────────────────────
# Prompt Crafting
# ──────────────────────────────────────────────

def craft_prompts(
    jewelry: dict,
    style: dict,
    model_desc: str,
    jewelry_type: str,
    extra: str = "",
) -> dict:
    """Build 3 prompts: head-on, angled, on-model.

    The on-model prompt uses the jewelry JSON description (from the uploaded piece),
    NOT the shape of whatever jewelry the model reference is wearing.
    """

    # ── Jewelry description (from Step 1 analysis) ──
    detailed = jewelry.get("detailed_description", "")
    material = jewelry.get("material", "")
    finish = jewelry.get("material_finish", "")
    gems = jewelry.get("gemstones", "")
    gem_count = jewelry.get("gemstone_count", "")
    design = jewelry.get("design_style", "")
    setting = jewelry.get("setting_type", "")
    deco = jewelry.get("decorative_elements", "")
    band = jewelry.get("band_chain_details", "")
    shape = jewelry.get("overall_shape", "")
    colors = jewelry.get("color_palette", "")
    size = jewelry.get("size_proportion", "")
    unique = jewelry.get("unique_features", "")

    # Build rich piece descriptor
    pieces = [f"{finish} {material} {jewelry_type}"]
    if gems and gems.lower() not in ("none", "n/a", ""):
        pieces.append(f"set with {gems}")
    if gem_count and gem_count.lower() not in ("none", "n/a", ""):
        pieces.append(f"({gem_count})")
    if setting and setting.lower() not in ("none", "n/a", ""):
        pieces.append(f"in a {setting} setting")
    if deco and deco.lower() not in ("none", "n/a", ""):
        pieces.append(f"with {deco}")
    if band and band.lower() not in ("none", "n/a", ""):
        pieces.append(f"{band}")
    if unique and unique.lower() not in ("none", "n/a", ""):
        pieces.append(f"distinctive features: {unique}")

    core = ", ".join(pieces)

    # Full description block for the piece
    jewelry_block = (
        f"JEWELRY PIECE: {core}. "
        f"Design: {design}. Shape: {shape}. Proportions: {size}. Colors: {colors}. "
        f"Full description: {detailed}"
    )

    # ── Style directive (from Step 3 analysis) ──
    s = style
    style_block = (
        f"STYLE: {s.get('style_summary', 'Professional jewelry photography.')} "
        f"Background: {s.get('background', 'clean white')}. "
        f"Lighting: {s.get('lighting', 'soft studio')}. "
        f"Color grading: {s.get('color_grading', 'neutral')}. "
        f"Mood: {s.get('mood', 'luxurious')}. "
        f"Composition: {s.get('composition', 'centered')}. "
    )
    props = s.get("props_surface", "")
    if props and props.lower() not in ("none", "n/a", ""):
        style_block += f"Surface/props: {props}. "

    # ── Extra instructions ──
    extra_block = ""
    if extra and extra.strip():
        extra_block = f" ADDITIONAL INSTRUCTIONS: {extra.strip()}"

    # ── Product shot base ──
    product_base = (
        f"{style_block}"
        f"{jewelry_block} "
        f"Professional jewelry product photography, "
        f"sharp focus on every detail, high-end commercial catalog quality, "
        f"photorealistic, 8K resolution{extra_block}"
    )

    prompts = {
        "headon": (
            f"{product_base}, "
            f"straight-on front view, {s.get('camera_angle', 'eye-level')} camera angle, "
            f"orientation: {s.get('orientation', 'centered')}, "
            f"perfectly centered in frame, symmetrical composition"
        ),
        "angled": (
            f"{product_base}, "
            f"three-quarter angle view showing depth and dimension, "
            f"slight 40-degree rotation revealing side profile and craftsmanship, "
            f"orientation: {s.get('orientation', 'angled')}"
        ),
        "model": (
            f"Professional fashion editorial photography. "
            f"MODEL: {model_desc}. "
            f"The model is wearing the following {jewelry_type} - {jewelry_block} "
            f"CRITICAL: The {jewelry_type} must match the description above EXACTLY - "
            f"do not change or simplify the design, stones, or materials. "
            f"The {jewelry_type} is the hero/focal point of the image. "
            f"Lighting: {s.get('lighting', 'soft studio')}. "
            f"Color grading: {s.get('color_grading', 'neutral')}. "
            f"Mood: {s.get('mood', 'luxurious')}. "
            f"Crisp focus on the jewelry, shallow depth of field on background, "
            f"magazine editorial quality, photorealistic, 8K resolution{extra_block}"
        ),
    }

    return prompts


# ──────────────────────────────────────────────
# Kie.ai Generation
# ──────────────────────────────────────────────

async def generate_image_kie(prompt: str, aspect_ratio: str = "1:1") -> Optional[str]:
    if not KIE_AI_API_KEY:
        raise HTTPException(500, detail="KIE_AI_API_KEY not set in .env")

    headers = {"Authorization": f"Bearer {KIE_AI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": KIE_MODEL,
        "input": {"prompt": prompt, "aspect_ratio": aspect_ratio, "output_format": "png"},
    }

    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(KIE_CREATE_TASK, headers=headers, json=payload)
        if r.status_code != 200:
            print(f"[Kie.ai] Error {r.status_code}: {r.text}")
            return None
        task_id = r.json().get("data", {}).get("taskId")

    if not task_id:
        return None
    print(f"[Kie.ai] Task: {task_id}")

    await asyncio.sleep(5)
    for _ in range(60):
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(KIE_RECORD_INFO, headers={"Authorization": f"Bearer {KIE_AI_API_KEY}"},
                            params={"taskId": task_id})
            r.raise_for_status()
            data = r.json().get("data", {})

        if data.get("status") == 3:
            print(f"[Kie.ai] Task {task_id} failed")
            return None

        rj = data.get("resultJson")
        if rj:
            rd = json.loads(rj) if isinstance(rj, str) else rj
            urls = rd.get("resultUrls", [])
            if urls:
                print(f"[Kie.ai] Done: {urls[0][:80]}...")
                return urls[0]

        await asyncio.sleep(3)
    return None


async def download_save(url: str, filename: str) -> str:
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
    (OUTPUT_DIR / filename).write_bytes(r.content)
    return f"/outputs/{filename}"


# ──────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse((BASE_DIR / "templates" / "index.html").read_text())


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    fid = str(uuid.uuid4())
    ext = Path(file.filename).suffix.lower() or ".jpg"
    path = UPLOAD_DIR / f"{fid}{ext}"
    content = await file.read()
    path.write_bytes(content)
    return {"id": fid, "filename": file.filename, "path": f"/uploads/{fid}{ext}", "size": len(content)}


@app.post("/api/generate")
async def generate(
    jewelry_type: str = Form(...),
    jewelry_files: str = Form(...),       # Step 1: JSON array of file IDs
    model_file: str = Form(...),          # Step 2: model reference file ID
    style_file: str = Form(...),          # Step 3: style reference file ID
    extra_instructions: str = Form(""),
):
    """Generate 3 product images: head-on, angled, on-model."""
    jewelry_ids = json.loads(jewelry_files)
    jewelry_paths = [_resolve(fid) for fid in jewelry_ids]
    model_path = _resolve(model_file)
    style_path = _resolve(style_file)

    # All 3 Gemini analyses in parallel
    jewelry_analysis, model_description, style_analysis = await asyncio.gather(
        analyze_jewelry_piece(jewelry_paths, jewelry_type),
        analyze_model_reference(model_path),
        analyze_style_reference(style_path),
    )

    prompts = craft_prompts(jewelry_analysis, style_analysis, model_description,
                            jewelry_type, extra_instructions)

    batch = uuid.uuid4().hex[:8]

    async def gen(view, prompt):
        url = await generate_image_kie(prompt)
        if url:
            local = await download_save(url, f"{batch}_{view}.png")
            return {"view": view, "url": url, "local": local, "prompt": prompt}
        return {"view": view, "url": None, "local": None, "prompt": prompt, "error": "Generation failed"}

    results = await asyncio.gather(*[gen(v, p) for v, p in prompts.items()])

    return {
        "batch_id": batch,
        "jewelry_analysis": jewelry_analysis,
        "style_analysis": style_analysis,
        "model_description": model_description,
        "results": list(results),
    }


@app.post("/api/regenerate")
async def regenerate(prompt: str = Form(...), view: str = Form(...), batch_id: str = Form("re")):
    url = await generate_image_kie(prompt)
    if url:
        fname = f"{batch_id}_{view}_{uuid.uuid4().hex[:4]}.png"
        local = await download_save(url, fname)
        return {"view": view, "url": url, "local": local, "prompt": prompt}
    raise HTTPException(500, detail="Generation failed")


if __name__ == "__main__":
    missing = [k for k in ("KIE_AI_API_KEY", "GEMINI_API_KEY") if not os.getenv(k)]
    print("\n  Jewelry Studio\n  ==============")
    if missing:
        print(f"  WARNING: Missing: {', '.join(missing)}")
    print("  http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
