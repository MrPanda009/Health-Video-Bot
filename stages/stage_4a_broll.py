"""
Stage 4a — B-roll Download
============================
Responsibilities:
  1. Read broll_search_tags from job content{} block (produced by Stage 3)
  2. For each segment, collect 2 video clips using Pexels (primary) + Pixabay (fallback)
  3. Check cache before downloading; populate cache after downloading
  4. Save clips to assets/{job_id}/broll/{segment_name}_{n}.mp4
  5. Write broll_video_paths (and broll_missing_segments if any) into job assets{}

Does NOT change job status — the orchestrator sets stage_4_complete after all
stage-4 sub-stages finish. Sets status "error" only on unrecoverable failures.

Reads from:  jobs/{job_id}.json  (content.broll_search_tags must be present)
             niche_profile.json  (minimum_clip_duration_seconds, minimum_resolution)
Writes to:   jobs/{job_id}.json  (assets.broll_video_paths, assets.broll_missing_segments)
             assets/{job_id}/broll/
             cache/broll/
"""

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

# Resolve project root (one level up from this file) so broll_db can be imported
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from broll_db import ClipDB  # noqa: E402

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR         = os.getenv("ASSETS_DIR", "assets")
CACHE_DIR          = os.getenv("CACHE_DIR", "cache")

PEXELS_API_KEY  = os.getenv("PEXELS_API_KEY", "")
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY", "")

CLIPS_PER_SEGMENT = 2   # target clips per segment — Stage 5 picks the better one


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    """Convert a search term to a filesystem-safe cache key (max 80 chars)."""
    return text.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")[:80]


def _probe_clip(path: Path) -> tuple[Optional[str], Optional[float]]:
    """
    Use ffprobe to get (resolution, duration_sec) of a video file.
    Returns (None, None) if ffprobe is unavailable or the file can't be probed.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None, None
        data    = json.loads(result.stdout)
        streams = data.get("streams", [])
        v       = next((s for s in streams if s.get("codec_type") == "video"), None)
        if v:
            w, h = v.get("width"), v.get("height")
            resolution = f"{w}x{h}" if w and h else None
        else:
            resolution = None
        duration = float(data.get("format", {}).get("duration", 0)) or None
        return resolution, duration
    except Exception:
        return None, None


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
    job["error"]  = {"stage": "stage_4a", "message": message, "retries": 0}
    save_job(job)
    print(f"[Stage 4a] ERROR: {message}")
    return job


# ─── Pexels ───────────────────────────────────────────────────────────────────

def _best_pexels_file_url(video_files: list) -> Optional[str]:
    """
    Pick the highest-resolution MP4 download URL from a Pexels video's file list.
    Prefers ≥ 1080p; falls back to best available.
    """
    mp4 = [f for f in video_files if f.get("file_type") == "video/mp4"]
    if not mp4:
        mp4 = video_files
    hd = [f for f in mp4 if f.get("height", 0) >= 1080]
    pool = hd if hd else mp4
    pool.sort(key=lambda f: f.get("width", 0) * f.get("height", 0), reverse=True)
    return pool[0].get("link") if pool else None


def fetch_from_pexels(search_term: str, min_duration: int) -> list[tuple[str, int]]:
    """
    Search Pexels for landscape clips matching search_term.
    Returns list of (download_url, duration_seconds) sorted by duration desc.
    Empty list on API error or no key.
    """
    if not PEXELS_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={
                "query":        search_term,
                "per_page":     5,
                "orientation":  "landscape",
                "min_width":    1920,
                "min_height":   1080,
                "min_duration": min_duration,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[Stage 4a]   Pexels API error for '{search_term}': {e}")
        return []

    results = []
    for video in resp.json().get("videos", []):
        url = _best_pexels_file_url(video.get("video_files", []))
        if url:
            results.append((url, int(video.get("duration", 0))))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ─── Pixabay ──────────────────────────────────────────────────────────────────

def _best_pixabay_url(hit: dict) -> Optional[str]:
    """
    Pick the best download URL from a Pixabay video hit.
    Prefers large (1920p), falls through medium, small.
    """
    videos = hit.get("videos", {})
    for quality in ("large", "medium", "small"):
        v = videos.get(quality, {})
        if v.get("url"):
            return v["url"]
    return None


def fetch_from_pixabay(search_term: str, min_duration: int) -> list[tuple[str, int]]:
    """
    Search Pixabay for film clips matching search_term.
    Returns list of (download_url, duration_seconds) sorted by duration desc.
    Empty list on API error or no key.
    """
    if not PIXABAY_API_KEY:
        return []
    try:
        resp = requests.get(
            "https://pixabay.com/api/videos/",
            params={
                "key":        PIXABAY_API_KEY,
                "q":          search_term,
                "video_type": "film",
                "min_width":  1920,
                "order":      "popular",
                "per_page":   5,
            },
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        print(f"[Stage 4a]   Pixabay API error for '{search_term}': {e}")
        return []

    results = []
    for hit in resp.json().get("hits", []):
        duration = int(hit.get("duration", 0))
        if duration < min_duration:
            continue
        url = _best_pixabay_url(hit)
        if url:
            results.append((url, duration))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ─── Download ─────────────────────────────────────────────────────────────────

def download_clip(url: str, dest_path: Path, duration: int = 0) -> bool:
    """
    Stream-download a video clip to dest_path.
    Deletes the partial file on failure. Returns True on success.
    """
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total_size = int(r.headers.get("content-length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = int(downloaded * 100 / total_size)
                        bar_len = 20
                        filled = int(bar_len * downloaded / total_size)
                        bar = '█' * filled + '-' * (bar_len - filled)
                        sys.stdout.write(f"\r[Stage 4a]   ↓ {dest_path.name}  ({duration}s) [{bar}] {percent}%")
                    else:
                        mb = downloaded / (1024 * 1024)
                        sys.stdout.write(f"\r[Stage 4a]   ↓ {dest_path.name}  ({duration}s) [ Downloading... ] {mb:.1f}MB")
                    sys.stdout.flush()
            sys.stdout.write("\n")
        return True
    except Exception as e:
        print(f"\n[Stage 4a]   Download failed ({url[:60]}...): {e}")
        if dest_path.exists():
            dest_path.unlink()
        return False


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 4a runner.

    Iterates over broll_search_tags, collects CLIPS_PER_SEGMENT clips per segment
    using cache → Pexels → Pixabay, and writes the result into job assets{}.

    Never aborts on per-segment failures — missing segments are recorded so
    Stage 5 can substitute study screenshots.

    Args:
        job_id: UUID of the job (must be at stage_3_complete or previously errored here).

    Returns:
        Updated job dict. Status unchanged on success; "error" on unrecoverable failure.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight ───────────────────────────────────────────────────────────
    errored_here = job["status"] == "error" and job.get("error", {}).get("stage") == "stage_4a"
    if job["status"] != "stage_3_complete" and not errored_here:
        return mark_error(job, f"Job status is '{job['status']}' — expected 'stage_3_complete'")
    job.pop("error", None)
    job["status"] = "stage_3_complete"  # restore in case we're retrying a previous error

    broll_search_tags = job.get("content", {}).get("broll_search_tags")
    if not broll_search_tags:
        return mark_error(job, "broll_search_tags missing from content{} — re-run Stage 3")

    if not PEXELS_API_KEY and not PIXABAY_API_KEY:
        return mark_error(job, "Neither PEXELS_API_KEY nor PIXABAY_API_KEY is set")

    min_duration = profile["visuals"]["minimum_clip_duration_seconds"]
    broll_dir    = Path(ASSETS_DIR) / job_id / "broll"
    cache_dir    = Path(CACHE_DIR) / "broll"
    broll_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    db = ClipDB()

    broll_video_paths: list[dict] = []
    missing_segments:  list[str]  = []

    for segment in broll_search_tags:
        seg_name     = segment["segment_name"]
        search_terms = segment["search_terms"]
        collected:   list[str] = []

        print(f"\n[Stage 4a] Segment '{seg_name}' — terms: {search_terms}")

        for search_term in search_terms:
            if len(collected) >= CLIPS_PER_SEGMENT:
                break

            slug   = _slug(search_term)
            cached = cache_dir / f"{slug}.mp4"

            # ── DB tag search — reuse an already-downloaded clip ──────────
            db_hits = db.find_by_tags([search_term])
            if db_hits:
                hit      = db_hits[0]
                hit_path = Path(hit["filepath"])
                if hit_path.exists():
                    dest = broll_dir / f"{seg_name}_{len(collected)}.mp4"
                    shutil.copy2(hit_path, dest)
                    db.mark_used(hit["id"], job_id)
                    collected.append(str(dest))
                    print(f"[Stage 4a]   ✓ db     '{search_term}' → {dest.name} "
                          f"(used {hit['times_used'] + 1}×)")
                    continue
                else:
                    # File gone — mark it missing so the UI reflects reality
                    db.mark_missing(hit["id"])

            # ── Filesystem cache hit (clip not yet in DB) ─────────────────
            if cached.exists():
                dest = broll_dir / f"{seg_name}_{len(collected)}.mp4"
                shutil.copy2(cached, dest)
                collected.append(str(dest))
                print(f"[Stage 4a]   ✓ cache  '{search_term}' → {dest.name}")
                # Register it in the DB for future reuse
                resolution, duration_probed = _probe_clip(dest)
                db.add_clip(
                    filename=dest.name,
                    filepath=str(dest.resolve()),
                    source_url=f"cache:{slug}",
                    search_tags=[search_term],
                    content_tags=[],
                    resolution=resolution,
                    duration_sec=duration_probed,
                    license_type="cache",
                )
                continue

            # ── Pexels ───────────────────────────────────────────────────
            clips = fetch_from_pexels(search_term, min_duration)
            print(f"[Stage 4a]   Pexels  '{search_term}': {len(clips)} result(s)")

            # ── Pixabay fallback when Pexels didn't fill the quota ────────
            if len(clips) < CLIPS_PER_SEGMENT:
                time.sleep(0.4)  # polite gap between providers
                pb_clips = fetch_from_pixabay(search_term, min_duration)
                print(f"[Stage 4a]   Pixabay '{search_term}': {len(pb_clips)} result(s)")
                clips = clips + pb_clips  # Pexels quality first

            # ── Download up to what we still need ────────────────────────
            first_download_for_term = True
            for url, api_duration in clips:
                if len(collected) >= CLIPS_PER_SEGMENT:
                    break

                # Skip URLs already in the DB (another term may have found the same video)
                if db.is_duplicate(url):
                    print(f"[Stage 4a]   ⟳ skip  duplicate URL: {url[:60]}…")
                    continue

                dest = broll_dir / f"{seg_name}_{len(collected)}.mp4"
                if download_clip(url, dest, api_duration):
                    # Cache the first successful download for this term
                    if first_download_for_term and not cached.exists():
                        shutil.copy2(dest, cached)
                        first_download_for_term = False

                    resolution, duration_probed = _probe_clip(dest)
                    license_type = "pexels_free" if "pexels.com" in url else "pixabay"
                    db.add_clip(
                        filename=dest.name,
                        filepath=str(dest.resolve()),
                        source_url=url,
                        search_tags=[search_term],
                        content_tags=[],
                        resolution=resolution,
                        duration_sec=duration_probed or float(api_duration),
                        license_type=license_type,
                    )
                    collected.append(str(dest))
                time.sleep(0.2)

        # ── Segment result ────────────────────────────────────────────────
        n = len(collected)
        if n == 0:
            print(f"[Stage 4a]   ⚠ No clips found for '{seg_name}' — Stage 5 will use screenshots")
            missing_segments.append(seg_name)
        else:
            print(f"[Stage 4a]   ✓ '{seg_name}': {n} clip(s)")

        broll_video_paths.append({"segment_name": seg_name, "paths": collected})

    # ── Persist to job ────────────────────────────────────────────────────────
    if not job.get("assets"):
        job["assets"] = {}
    job["assets"]["broll_video_paths"] = broll_video_paths
    if missing_segments:
        job["assets"]["broll_missing_segments"] = missing_segments
    elif "broll_missing_segments" in job.get("assets", {}):
        # Clear stale field from a previous failed run
        del job["assets"]["broll_missing_segments"]

    save_job(job)

    total = sum(len(s["paths"]) for s in broll_video_paths)
    print(f"\n[Stage 4a] ✓ Complete — {total} clip(s) across {len(broll_video_paths)} segment(s)")
    if missing_segments:
        print(f"  ⚠ Missing segments (Stage 5 will use screenshots): {missing_segments}")

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_4a_broll.py <job_id>
    #   python stage_4a_broll.py          ← auto-picks most recent stage_3_complete job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                ready     = j.get("status") == "stage_3_complete"
                retryable = j.get("status") == "error" and j.get("error", {}).get("stage") == "stage_4a"
                if ready or retryable:
                    candidates.append((jf.stat().st_mtime, j["job_id"], j.get("status")))
            except Exception:
                continue

        if not candidates:
            print("No stage_3_complete or stage_4a error jobs found. Run stage_3_content_generation.py first.")
            sys.exit(1)

        candidates.sort(reverse=True)
        _, job_id, picked_status = candidates[0]
        label = "retrying errored" if picked_status == "error" else "most recent"
        print(f"[Stage 4a] No job_id provided — using {label}: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result.get("error"):
        print(f"Error        : {result['error']['message']}")
    else:
        paths_count = sum(len(s["paths"]) for s in result.get("assets", {}).get("broll_video_paths", []))
        print(f"Clips saved  : {paths_count}")
        print(f"Job saved to : jobs/{result['job_id']}.json")
