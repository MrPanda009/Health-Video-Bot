"""
Stage 4b — Thumbnail Generation
==================================
Responsibilities:
  1. Read thumbnail_prompts from job content{} block (3 variants from Stage 3)
  2. Enhance each prompt with style context from niche_profile
  3. Generate a 1280×720 image for each variant via DALL-E 3 (default) or Vertex Imagen
  4. Save to assets/{job_id}/thumbnails/{variant_id}.png

Does NOT change job status — the orchestrator sets stage_4_complete after all
stage-4 sub-stages finish. Sets status "error" only if all 3 thumbnails fail.

IMAGE_GEN_PROVIDER env var: "dalle" (default) | "vertex"

Reads from:  jobs/{job_id}.json  (content.thumbnail_prompts must be present)
             niche_profile.json
Writes to:   jobs/{job_id}.json  (assets.thumbnail_paths)
             assets/{job_id}/thumbnails/
"""

import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH  = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR            = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR          = os.getenv("ASSETS_DIR", "assets")
IMAGE_GEN_PROVIDER  = os.getenv("IMAGE_GEN_PROVIDER", "dalle").lower()

THUMBNAIL_W, THUMBNAIL_H = 1280, 720


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_niche_profile() -> dict:
    with open(NICHE_PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_job(job_id: str) -> dict:
    path = Path(JOBS_DIR) / f"{job_id}.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_job(job: dict) -> None:
    path = Path(JOBS_DIR) / f"{job['job_id']}.json"
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)


def mark_error(job: dict, message: str) -> dict:
    job["status"] = "error"
    job["error"]  = {"stage": "stage_4b", "message": message, "retries": 0}
    save_job(job)
    print(f"[Stage 4b] ERROR: {message}")
    return job


# ─── Prompt builder ───────────────────────────────────────────────────────────

def build_prompt(base_prompt: str, variant_id: str, profile: dict) -> str:
    """
    Enhance the Stage 3 base prompt with style context from niche_profile.
    Keeps it under 4000 chars for DALL-E compatibility.
    """
    variant_desc = ""
    for v in profile["thumbnail"]["style_variants"]:
        if v["id"] == variant_id:
            variant_desc = v["description"]
            break

    text_rules = "; ".join(profile["thumbnail"]["text_overlay_rules"])

    return (
        f"{base_prompt}. "
        f"Visual style: {variant_desc}. "
        f"Do NOT include any text, numbers, letters, or words anywhere in the image "
        f"— text will be added as overlay in post-production. "
        f"Constraints: {text_rules}. "
        f"YouTube thumbnail for a Hindi health education channel. "
        f"Audience: South Asian adults aged 35-65. Warm, trustworthy, non-alarming."
    )[:3900]  # hard cap for DALL-E


# ─── Image resize ─────────────────────────────────────────────────────────────

def resize_and_save(img_bytes: bytes, output_path: Path) -> None:
    """Resize raw image bytes to 1280×720 and save as PNG."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(BytesIO(img_bytes))
    img = img.resize((THUMBNAIL_W, THUMBNAIL_H), Image.LANCZOS)
    img.save(str(output_path), "PNG")


# ─── DALL-E 3 ─────────────────────────────────────────────────────────────────

def generate_dalle(prompt: str, output_path: Path) -> bool:
    """
    Generate one image with DALL-E 3, resize to 1280×720, save to output_path.
    Returns True on success.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("[Stage 4b] OPENAI_API_KEY not set — cannot use DALL-E")
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1792x1024",   # closest 16:9 DALL-E supports — resize after
            quality="hd",
            n=1,
        )
        url = response.data[0].url
        img_resp = requests.get(url, timeout=60)
        img_resp.raise_for_status()
        resize_and_save(img_resp.content, output_path)
        return True
    except Exception as e:
        print(f"[Stage 4b] DALL-E error: {e}")
        return False


# ─── Vertex Imagen ────────────────────────────────────────────────────────────

def generate_vertex(prompt: str, output_path: Path) -> bool:
    """
    Generate one image with Vertex AI Imagen, resize to 1280×720, save to output_path.
    Requires: google-cloud-aiplatform, GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_CLOUD_PROJECT.
    Returns True on success.
    """
    try:
        import vertexai
        from vertexai.preview.vision_models import ImageGenerationModel
    except ImportError:
        print("[Stage 4b] google-cloud-aiplatform not installed — cannot use Vertex Imagen")
        return False

    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("[Stage 4b] GOOGLE_CLOUD_PROJECT not set — cannot use Vertex Imagen")
        return False

    try:
        vertexai.init(project=project)
        model  = ImageGenerationModel.from_pretrained("imagegeneration@006")
        images = model.generate_images(
            prompt=prompt,
            number_of_images=1,
            aspect_ratio="16:9",
        )
        img_bytes = images[0]._image_bytes
        resize_and_save(img_bytes, output_path)
        return True
    except Exception as e:
        print(f"[Stage 4b] Vertex error: {e}")
        return False


# ─── Dispatch ─────────────────────────────────────────────────────────────────

def generate_thumbnail(prompt: str, output_path: Path) -> bool:
    """Route to the configured image generation provider."""
    if IMAGE_GEN_PROVIDER == "vertex":
        return generate_vertex(prompt, output_path)
    return generate_dalle(prompt, output_path)


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 4b runner.

    Generates 3 thumbnail images (one per variant). Warns on individual failures
    but only aborts if all 3 fail — Stage 6 can still upload without a thumbnail.

    Args:
        job_id: UUID of the job (must be at stage_3_complete or previously errored here).

    Returns:
        Updated job dict. Status unchanged on success; "error" if all thumbnails fail.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight ───────────────────────────────────────────────────────────
    errored_here = job["status"] == "error" and job.get("error", {}).get("stage") == "stage_4b"
    if job["status"] != "stage_3_complete" and not errored_here:
        return mark_error(job, f"Job status is '{job['status']}' — expected 'stage_3_complete'")
    job.pop("error", None)
    job["status"] = "stage_3_complete"  # restore in case we're retrying a previous error

    thumbnail_prompts = job.get("content", {}).get("thumbnail_prompts")
    if not thumbnail_prompts:
        return mark_error(job, "thumbnail_prompts missing from content{} — re-run Stage 3")

    thumb_dir = Path(ASSETS_DIR) / job_id / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    print(f"[Stage 4b] Generating {len(thumbnail_prompts)} thumbnail(s) via {IMAGE_GEN_PROVIDER.upper()}")

    thumbnail_paths: list[dict] = []
    failed_variants: list[str]  = []

    for item in thumbnail_prompts:
        variant_id  = item["variant_id"]
        base_prompt = item["prompt"]
        output_path = thumb_dir / f"{variant_id}.png"

        full_prompt = build_prompt(base_prompt, variant_id, profile)
        print(f"\n[Stage 4b] Variant '{variant_id}'")
        print(f"[Stage 4b]   Prompt ({len(full_prompt)} chars): {full_prompt[:120]}...")

        ok = generate_thumbnail(full_prompt, output_path)

        if ok:
            thumbnail_paths.append({"variant_id": variant_id, "path": str(output_path)})
            print(f"[Stage 4b]   ✓ Saved → {output_path.name}  ({THUMBNAIL_W}×{THUMBNAIL_H})")
        else:
            failed_variants.append(variant_id)
            print(f"[Stage 4b]   ⚠ Failed to generate '{variant_id}'")

    # ── Abort if nothing was generated ───────────────────────────────────────
    if not thumbnail_paths:
        return mark_error(
            job,
            f"All thumbnail variants failed to generate ({IMAGE_GEN_PROVIDER}). "
            f"Check API key and provider config."
        )

    # ── Persist to job ────────────────────────────────────────────────────────
    if not job.get("assets"):
        job["assets"] = {}
    job["assets"]["thumbnail_paths"] = thumbnail_paths
    save_job(job)

    print(f"\n[Stage 4b] ✓ Complete — {len(thumbnail_paths)}/{len(thumbnail_prompts)} thumbnail(s) generated")
    if failed_variants:
        print(f"  ⚠ Failed variants: {failed_variants}")

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_4b_thumbnail.py <job_id>
    #   python stage_4b_thumbnail.py          ← auto-picks most recent stage_3_complete job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                ready     = j.get("status") == "stage_3_complete"
                retryable = j.get("status") == "error" and j.get("error", {}).get("stage") == "stage_4b"
                if ready or retryable:
                    candidates.append((jf.stat().st_mtime, j["job_id"], j.get("status")))
            except Exception:
                continue

        if not candidates:
            print("No stage_3_complete or stage_4b error jobs found. Run stage_3_content_generation.py first.")
            sys.exit(1)

        candidates.sort(reverse=True)
        _, job_id, picked_status = candidates[0]
        label = "retrying errored" if picked_status == "error" else "most recent"
        print(f"[Stage 4b] No job_id provided — using {label}: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result.get("error"):
        print(f"Error        : {result['error']['message']}")
    else:
        paths = result.get("assets", {}).get("thumbnail_paths", [])
        for t in paths:
            print(f"  {t['variant_id']:25s} → {t['path']}")
        print(f"Job saved to : jobs/{result['job_id']}.json")
