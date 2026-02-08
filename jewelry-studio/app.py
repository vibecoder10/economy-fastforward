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
    """Step 1 analysis: Molecular-level detail extraction of the jewelry piece."""
    parts = [
        {"text": f"""You are the world's foremost gemologist and jewelry forensic analyst examining {len(image_paths)} photo(s) of a {jewelry_type}.
Your analysis DIRECTLY drives an AI image generator. Every inaccuracy = a wrong product photo. Be forensically precise.

═══ COLOR ANALYSIS (MOST CRITICAL) ═══
- Metal color: Do NOT just say "gold". Specify the EXACT shade. Is it warm buttery yellow gold, pale lemon gold, deep rich honey gold, cool silvery white gold, soft blush rose gold, coppery rose gold, bright platinum silver, oxidized dark silver, etc.?
- If the piece has TWO-TONE or MULTI-COLOR metals, describe EACH color separately and WHERE each appears (e.g. "rose gold band with white gold prong heads" or "yellow gold base with rhodium-plated crown").
- Gemstone color: Use EXACT descriptors. Not "blue" but "deep royal sapphire blue" or "light icy baby blue" or "teal-green blue". Not "red" but "vivid pigeon blood red" or "pinkish-red raspberry". Not "clear" but "colorless icy white with rainbow fire" or "slightly warm near-colorless".
- Compare colors to known references when helpful (e.g. "the color of champagne", "matches Pantone rose quartz").

═══ SIZE & PROPORTION (CRITICAL - ALWAYS GETS WRONG) ═══
- Estimate the ACTUAL physical size of the piece. Use mm dimensions.
- For rings: estimate band width in mm, stone diameter in mm, total ring face height in mm.
- For earrings: estimate total drop length in mm, width in mm, and how large they appear relative to an earlobe (small/subtle, medium, large/statement).
- For necklaces: estimate pendant size in mm, chain thickness in mm.
- For bracelets: estimate width in mm, link size if applicable.
- Describe the size relationship: Is the center stone proportionally large or delicate compared to the band? Is this a dainty piece or a substantial piece?
- CRITICAL: If this piece would look SMALL and DELICATE on a hand/ear/neck, say so explicitly. If it would look LARGE and BOLD, say so. This controls the generated image scale.

═══ PRONGS & SETTINGS (ALWAYS GETS WRONG) ═══
- Count prongs PER STONE precisely. 4-prong? 6-prong? Shared prongs?
- Prong size relative to stone: Are prongs thin/delicate barely visible, or thick/substantial and clearly visible?
- Prong shape: pointed/tapered, rounded/bead, V-shaped, flat/square, claw, button?
- Prong color: same as band or different (e.g. white gold prongs on yellow gold band)?

═══ STONES & BRILLIANCE ═══
- Count EVERY stone. Not "several" - give exact numbers.
- Size of each stone or group: center stone mm, side stones mm, accent stones mm.
- Arrangement: halo? three-stone? solitaire? cluster? linear row? scattered? graduated?
- Brilliance: How do stones catch light? Fiery rainbow dispersion? Icy sharp sparkle? Soft muted glow? Mirror-like reflection?

Return JSON:

{{
  "jewelry_type": "{jewelry_type}",
  "metal_color_exact": "EXTREMELY specific color description of the metal(s). If two-tone, describe BOTH colors and where each appears. Use shade names like 'warm honey yellow gold', 'cool silvery white gold', 'soft pinkish rose gold', etc.",
  "metal_color_secondary": "If two-tone/multi-tone: the second metal color and where it appears. Say 'none' if single color.",
  "material": "metal type with karat if discernible (14k yellow gold, 18k rose gold, sterling silver, platinum, etc.)",
  "material_finish": "polished mirror-shine, matte, brushed, hammered, satin, oxidized, high-shine, etc.",
  "gemstones": "FOR EACH STONE: exact type, exact cut, EXACT color shade (not just 'blue' - specify the EXACT shade), approximate mm size, clarity, and light behavior. Be exhaustive.",
  "gemstone_count": "EXACT count per group: e.g. '1 center round 6mm + 2 side baguettes 3x1.5mm + 18 micro-pave rounds 1mm each'. Count precisely from the photos.",
  "prong_details": "prongs per stone, prong shape, prong thickness relative to stone (barely visible / clearly visible / substantial), prong color vs band color. Say 'n/a' if no prongs.",
  "stone_luminescence": "exactly how stones interact with light - fiery rainbow dispersion, icy white sparkle, soft warm glow, mirror-like flash, subtle shimmer, etc.",
  "physical_dimensions": "estimated real-world size in mm. Ring: band width x stone diameter x face height. Earring: total length x width. Necklace: pendant dimensions x chain thickness. Include how it would appear on the body - dainty/subtle, medium, or bold/statement.",
  "scale_on_body": "How this piece looks when worn: 'very small and delicate - barely noticeable', 'petite and understated', 'medium and noticeable', 'substantial and eye-catching', 'large and bold statement piece'. This is critical for generating correctly sized jewelry on a model.",
  "design_style": "modern, vintage, art deco, minimalist, bohemian, statement, classic, filigree, etc.",
  "band_chain_details": "band width in mm estimate, profile shape (flat, rounded, knife-edge, comfort-fit), chain type if applicable, clasp details",
  "setting_type": "prong, bezel, pave, channel, tension, halo, cluster, cathedral, flush, etc.",
  "decorative_elements": "filigree, engraving, milgrain, twisted rope, braided, texture patterns, openwork, gallery details, split shank, etc. Say 'none' if plain.",
  "overall_shape": "overall silhouette and form from front view",
  "color_palette": "COMPLETE color breakdown with exact shades: e.g. 'warm 18k yellow gold (honey tone) with icy colorless round brilliant diamond center, flanked by deep royal blue sapphire baguettes. The gold has a slight rose undertone where it meets the white gold prong heads.'",
  "size_proportion": "delicate/petite/medium/substantial/chunky with mm estimates",
  "unique_features": "anything distinctive: asymmetry, mixed metals, unusual stone shapes, special textures, signature details, color contrasts",
  "detailed_description": "6-8 sentences. START with exact colors (metal shade + stone shades). Then stone count, cut, arrangement. Then prong count/shape/size. Then band/chain details. Then overall proportions and scale on body. Then design style. This must be specific enough to CLONE this piece visually. If someone read only this field, they should be able to draw this piece accurately."
}}

THE #1 FAILURE MODE IS GETTING COLORS WRONG. Triple-check every color. If the metal has warm yellow tones, do NOT describe it as white/silver. If a stone is light blue, do NOT call it deep blue. Be EXACT."""}
    ]
    for p in image_paths:
        parts.append(_img_part(p))

    return _parse_json(await _gemini(parts, tokens=4096))


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
    """Step 3 analysis: Extract the photographic STYLE from the reference product shot.
    Note: Background will always be overridden to pure white in prompt crafting."""
    parts = [
        {"text": """Analyze this professional jewelry product photo purely for its PHOTOGRAPHIC STYLE.
I want to recreate this exact look with a DIFFERENT piece of jewelry.

NOTE: The background will be overridden to pure white regardless of what's in this image.
Focus on LIGHTING, MOOD, COMPOSITION, and CAMERA ANGLE - those are what matter most.

Return JSON:

{
  "lighting": "lighting setup in detail (direction, softness, highlights, shadows, rim light, fill, catch lights, specular highlights on metal, etc.)",
  "orientation": "how the jewelry sits (flat lay, angled, standing, elevated, hanging, draped, on bust/hand, etc.)",
  "camera_angle": "camera perspective (top-down, eye-level, 45-degree, macro close-up, slight overhead, etc.)",
  "composition": "framing style (centered, rule-of-thirds, tight crop, breathing room, negative space, etc.)",
  "mood": "overall aesthetic (luxurious, minimal, warm, cool, editorial, catalog, lifestyle, romantic, etc.)",
  "props_surface": "any props or surfaces visible (velvet, marble, wood, fabric, mirror, flowers, none, etc.) - note: these may or may not be used",
  "color_grading": "color temperature and tone (warm, cool, neutral, high contrast, low contrast, muted, vibrant)",
  "style_summary": "2-sentence summary of the entire photographic style EXCLUDING background. Focus on lighting quality, composition approach, and mood. Be specific enough to use as a generation directive."
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
    All product shots enforce PURE WHITE backgrounds regardless of style reference.
    Uses molecular-level color and proportion fields for exact replication.
    """

    # ── Jewelry description (from Step 1 analysis) ──
    detailed = jewelry.get("detailed_description", "")
    material = jewelry.get("material", "")
    finish = jewelry.get("material_finish", "")
    gems = jewelry.get("gemstones", "")
    gem_count = jewelry.get("gemstone_count", "")
    prongs = jewelry.get("prong_details", "")
    luminescence = jewelry.get("stone_luminescence", "")
    design = jewelry.get("design_style", "")
    setting = jewelry.get("setting_type", "")
    deco = jewelry.get("decorative_elements", "")
    band = jewelry.get("band_chain_details", "")
    shape = jewelry.get("overall_shape", "")
    colors = jewelry.get("color_palette", "")
    size = jewelry.get("size_proportion", "")
    unique = jewelry.get("unique_features", "")

    # New molecular-level fields
    metal_exact = jewelry.get("metal_color_exact", "")
    metal_secondary = jewelry.get("metal_color_secondary", "")
    dimensions = jewelry.get("physical_dimensions", "")
    scale = jewelry.get("scale_on_body", "")

    # ── COLOR BLOCK (highest priority - put first in prompt) ──
    color_block = f"EXACT COLORS (MATCH PRECISELY): "
    if metal_exact:
        color_block += f"Primary metal: {metal_exact}. "
    if metal_secondary and metal_secondary.lower() not in ("none", "n/a", ""):
        color_block += f"Secondary metal: {metal_secondary}. "
    if colors:
        color_block += f"Full palette: {colors}. "
    color_block += "DO NOT deviate from these exact color descriptions. "

    # ── SCALE BLOCK (second priority - prevents oversized jewelry) ──
    scale_block = ""
    if dimensions or scale:
        scale_block = "SIZE & PROPORTION (CRITICAL - DO NOT MAKE JEWELRY TOO LARGE): "
        if dimensions:
            scale_block += f"Physical dimensions: {dimensions}. "
        if scale:
            scale_block += f"Scale on body: {scale}. "
        scale_block += "Generate the jewelry at REALISTIC proportions - match the described scale exactly. "

    # Build rich piece descriptor - colors and prongs first (most important)
    pieces = [f"{finish} {material} {jewelry_type}"]
    if metal_exact:
        pieces.append(f"EXACT metal color: {metal_exact}")
    if metal_secondary and metal_secondary.lower() not in ("none", "n/a", ""):
        pieces.append(f"secondary metal: {metal_secondary}")
    if gems and gems.lower() not in ("none", "n/a", ""):
        pieces.append(f"set with {gems}")
    if gem_count and gem_count.lower() not in ("none", "n/a", ""):
        pieces.append(f"stone count: {gem_count}")
    if prongs and prongs.lower() not in ("none", "n/a", ""):
        pieces.append(f"prongs: {prongs}")
    if luminescence and luminescence.lower() not in ("none", "n/a", ""):
        pieces.append(f"stone brilliance: {luminescence}")
    if setting and setting.lower() not in ("none", "n/a", ""):
        pieces.append(f"in a {setting} setting")
    if deco and deco.lower() not in ("none", "n/a", ""):
        pieces.append(f"with {deco}")
    if band and band.lower() not in ("none", "n/a", ""):
        pieces.append(f"{band}")
    if dimensions:
        pieces.append(f"physical size: {dimensions}")
    if unique and unique.lower() not in ("none", "n/a", ""):
        pieces.append(f"distinctive features: {unique}")

    core = ", ".join(pieces)

    # Full description block - colors and scale FIRST, then stone details
    jewelry_block = (
        f"JEWELRY PIECE: {core}. "
        f"{color_block}"
        f"{scale_block}"
        f"Design: {design}. Shape: {shape}. Proportions: {size}. "
        f"STONE DETAIL (CRITICAL): {gems}. Count: {gem_count}. "
        f"PRONG DETAIL (CRITICAL): {prongs}. "
        f"Light behavior: {luminescence}. "
        f"Full description: {detailed}"
    )

    # ── Style directive (from Step 3 analysis) ──
    # NOTE: Background is ALWAYS pure white, regardless of style reference
    s = style
    style_block = (
        f"STYLE: {s.get('style_summary', 'Professional jewelry photography.')} "
        f"BACKGROUND: PURE WHITE (#FFFFFF). Seamless, clean, no shadows on background, no gradients, no texture - ONLY pure white. "
        f"Lighting: {s.get('lighting', 'soft studio')}. "
        f"Color grading: {s.get('color_grading', 'neutral')}. "
        f"Mood: {s.get('mood', 'luxurious')}. "
        f"Composition: {s.get('composition', 'centered')}. "
    )

    # ── Extra instructions ──
    extra_block = ""
    if extra and extra.strip():
        extra_block = f" ADDITIONAL INSTRUCTIONS: {extra.strip()}"

    # ── Product shot base ──
    product_base = (
        f"{style_block}"
        f"{jewelry_block} "
        f"Professional jewelry product photography on PURE WHITE background, "
        f"sharp focus on every detail, high-end commercial catalog quality, "
        f"photorealistic, 8K resolution, the jewelry must be REALISTICALLY SIZED - not oversized{extra_block}"
    )

    prompts = {
        "headon": (
            f"{product_base}, "
            f"straight-on front view, {s.get('camera_angle', 'eye-level')} camera angle, "
            f"orientation: {s.get('orientation', 'centered')}, "
            f"perfectly centered in frame, symmetrical composition, "
            f"pure white seamless background"
        ),
        "angled": (
            f"{product_base}, "
            f"three-quarter angle view showing depth and dimension, "
            f"slight 40-degree rotation revealing side profile and craftsmanship, "
            f"orientation: {s.get('orientation', 'angled')}, "
            f"pure white seamless background"
        ),
        "model": (
            f"Professional fashion editorial photography. "
            f"MODEL: {model_desc}. "
            f"The model is wearing the following {jewelry_type} - {jewelry_block} "
            f"CRITICAL: The {jewelry_type} must match the description above EXACTLY - "
            f"do not change or simplify the design, stones, materials, or COLORS. "
            f"{color_block}"
            f"The {jewelry_type} is the hero/focal point of the image. "
            f"{scale_block}"
            f"The jewelry must appear at REALISTIC scale on the model's body - NOT oversized. "
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
async def regenerate(
    prompt: str = Form(...),
    view: str = Form(...),
    batch_id: str = Form("re"),
    feedback: str = Form(""),
):
    """Regenerate a single image with optional feedback about what was wrong.

    If feedback is provided, it gets woven into the prompt as a correction
    directive so the generator knows what to fix.
    """
    final_prompt = prompt
    if feedback and feedback.strip():
        # Prepend a strong correction block so the model prioritizes the fix
        correction = (
            f"IMPORTANT CORRECTION - The previous generation had these issues: {feedback.strip()}. "
            f"You MUST address these problems in this new generation. "
            f"Specifically fix: {feedback.strip()}. "
            f"--- Original prompt follows --- "
        )
        final_prompt = correction + prompt

    url = await generate_image_kie(final_prompt)
    if url:
        fname = f"{batch_id}_{view}_{uuid.uuid4().hex[:4]}.png"
        local = await download_save(url, fname)
        return {"view": view, "url": url, "local": local, "prompt": final_prompt}
    raise HTTPException(500, detail="Generation failed")


if __name__ == "__main__":
    missing = [k for k in ("KIE_AI_API_KEY", "GEMINI_API_KEY") if not os.getenv(k)]
    print("\n  Jewelry Studio\n  ==============")
    if missing:
        print(f"  WARNING: Missing: {', '.join(missing)}")
    print("  http://localhost:8000\n")
    uvicorn.run(app, host="0.0.0.0", port=8000)
