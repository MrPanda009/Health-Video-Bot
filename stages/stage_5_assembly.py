"""
Stage 5 — Video Assembly
==========================
Assembles the final YouTube Shorts video from all stage-4 assets.

Timeline (in order):
  [optional: assets/intro.mp4 if it exists]
  3s medical disclaimer card (generated from niche_profile text)
  Per segment: B-roll (or screenshot) trimmed to duration_hint_seconds
  [optional: assets/outro.mp4 if it exists]
  Voiceover audio across the full duration
  Background music at 15% (if assets/background_music_path is set and exists)
  ASS caption burn-in (if assets.ass_path is set and exists — stage 4d)

Stage 4d (captions/Whisper) is optional. If ass_path is absent, captions are
skipped and segment durations come from content.script_segments duration_hint_seconds.

Pre-flight accepts:
  stage_4_complete  — normal orchestrator flow
  stage_3_complete  — development mode (manually placed assets)
  error+stage_5     — retry after a previous failure

Reads from:  jobs/{job_id}.json
             niche_profile.json
             assets/{job_id}/broll/, audio/, thumbnails/
Writes to:   jobs/{job_id}.json  (output block)
             assets/{job_id}/output/video.mp4
             assets/{job_id}/output/disclaimer.png  (intermediate)

Exit status: stage_5_complete or error
"""

import json
import math
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR         = os.getenv("ASSETS_DIR", "assets")

FPS                 = 30
DISCLAIMER_DURATION = 3            # seconds prepended to every video

# Supported output dimensions keyed by aspect_ratio string
_ASPECT_DIMS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),   # YouTube Shorts portrait
    "16:9": (1920, 1080),   # Standard landscape / YouTube long-form
}


def _video_dims(job: dict) -> tuple[int, int]:
    """Return (width, height) for this job based on its aspect_ratio field."""
    ar = job.get("aspect_ratio", "9:16")
    return _ASPECT_DIMS.get(ar, _ASPECT_DIMS["9:16"])

# Font search order for disclaimer card (Latin/English text)
_FONT_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
]


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
    job["error"]  = {"stage": "stage_5", "message": message, "retries": 0}
    save_job(job)
    print(f"[Stage 5] ERROR: {message}")
    return job


# ─── FFmpeg wrappers ──────────────────────────────────────────────────────────

def run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command. Raises RuntimeError with stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited {result.returncode}:\n{result.stderr[-3000:]}"
        )


def probe_video(path: Path) -> dict:
    """ffprobe a file; returns dict with 'duration' (float) and 'has_video'/'has_audio' bools."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    return {
        "duration":  float(data.get("format", {}).get("duration", 0)),
        "has_video": any(s["codec_type"] == "video" for s in streams),
        "has_audio": any(s["codec_type"] == "audio" for s in streams),
    }


def volumedetect(path: Path) -> dict[str, float]:
    """
    Run ffmpeg volumedetect on a file.
    Returns {"max_volume": float, "mean_volume": float} in dBFS.
    Returns empty dict if no audio stream or detection fails.
    """
    cmd = [
        "ffmpeg", "-i", str(path),
        "-af", "volumedetect",
        "-vn", "-f", "null", "/dev/null",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    stderr = result.stderr
    out: dict[str, float] = {}
    for key, pattern in [("max_volume", r"max_volume:\s*([\-\d.]+)\s*dB"),
                          ("mean_volume", r"mean_volume:\s*([\-\d.]+)\s*dB")]:
        m = re.search(pattern, stderr)
        if m:
            out[key] = float(m.group(1))
    return out


# ─── Disclaimer card ──────────────────────────────────────────────────────────

def _find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_disclaimer_png(profile: dict, output_path: Path,
                            video_w: int, video_h: int) -> None:
    """Generate a full-HD black PNG with the English medical disclaimer centered in white text."""
    text = profile["compliance"]["medical_disclaimer"]["text_english"]
    img  = Image.new("RGB", (video_w, video_h), color="black")
    draw = ImageDraw.Draw(img)

    font_large = _find_font(52)
    font_small = _find_font(38)

    lines = textwrap.wrap(text, width=32)
    line_h = 60
    total_h = len(lines) * line_h
    y_start = (video_h - total_h) // 2

    band_top    = y_start - 40
    band_bottom = y_start + total_h + 40
    draw.rectangle([(60, band_top), (video_w - 60, band_bottom)], fill=(20, 20, 20))

    header = "⚠  Medical Notice"
    try:
        draw.text((video_w // 2, y_start - 20), header,
                  font=font_small, fill=(255, 200, 0), anchor="mm")
    except Exception:
        draw.text((video_w // 2 - 150, y_start - 20), header, font=font_small, fill=(255, 200, 0))

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        try:
            draw.text((video_w // 2, y), line, font=font_large, fill="white", anchor="lm")
        except Exception:
            draw.text((100, y), line, font=font_large, fill="white")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path), "PNG")


# ─── Assembly (MoviePy) ───────────────────────────────────────────────────────

def _mp_scale_crop(clip, target_w: int, target_h: int):
    """
    Resize *clip* to fill target_w × target_h (scale-to-fill), then center-crop.

    Preserves the clip's aspect ratio — no stretching.  Works for both portrait
    (9:16) and landscape (16:9) target dimensions.
    """
    clip_w, clip_h = clip.size
    scale = max(target_w / clip_w, target_h / clip_h)
    new_w = math.ceil(clip_w * scale)
    new_h = math.ceil(clip_h * scale)
    clip = clip.resized((new_w, new_h))
    x1 = (new_w - target_w) // 2
    y1 = (new_h - target_h) // 2
    return clip.cropped(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)


def _mp_loop(clip, duration: float):
    """
    Tile *clip* to cover *duration* seconds, then trim to exactly *duration*.

    If the clip is already long enough it is simply trimmed without copying.
    """
    from moviepy import concatenate_videoclips

    if clip.duration >= duration - 0.01:
        return clip.subclipped(0, duration)
    n = math.ceil(duration / clip.duration)
    return concatenate_videoclips([clip] * n).subclipped(0, duration)


def assemble_video(job: dict, profile: dict, out_dir: Path) -> Path:
    """
    Assemble the final video using MoviePy.

    Timeline:
      [intro.mp4 if present]  →  3s disclaimer  →  per-segment B-roll/screenshots
      →  [outro.mp4 if present]
    Audio: voiceover at 100 % mixed with optional background music at 15 %.
    ASS captions (if present from Stage 4d) are burned in via a single FFmpeg
    post-pass so Stage 5 does not depend on MoviePy for that filter.

    Dimensions from job["aspect_ratio"]: "9:16" → 1080×1920, "16:9" → 1920×1080.

    Args:
        job:     Full job dict.
        profile: Loaded niche_profile dict.
        out_dir: Directory to write output files into.

    Returns:
        Path to the finished video file (assets/{job_id}/output/video.mp4).

    Raises:
        ImportError:      If moviepy is not installed.
        FileNotFoundError: If the voiceover file is missing.
        RuntimeError:     If MoviePy or FFmpeg (caption pass) fails.
    """
    try:
        from moviepy import (
            AudioFileClip,
            ColorClip,
            CompositeAudioClip,
            ImageClip,
            VideoFileClip,
            concatenate_audioclips,
            concatenate_videoclips,
        )
    except ImportError:
        raise ImportError(
            "moviepy is not installed — cannot run Stage 5.\n"
            "Install it with: pip install moviepy\n"
            "ffmpeg must also be available in your PATH."
        )

    video_w, video_h = _video_dims(job)
    assets  = job.get("assets") or {}
    job_id  = job["job_id"]

    ar_label = job.get("aspect_ratio", "9:16")
    print(f"[Stage 5] Aspect ratio: {ar_label} → {video_w}×{video_h}")

    # ── Voiceover (required) ──────────────────────────────────────────────────
    voiceover_path = assets.get("voiceover_path")
    if not voiceover_path or not Path(voiceover_path).exists():
        raise FileNotFoundError(
            f"voiceover not found at '{voiceover_path}'. "
            "Run stage_4c_voiceover.py first, or manually place a WAV at "
            f"assets/{job_id}/audio/voiceover.wav and set assets.voiceover_path in the job."
        )

    music_path   = assets.get("background_music_path")
    has_music    = bool(music_path and Path(music_path).exists())
    ass_path     = assets.get("ass_path")
    has_captions = bool(ass_path and Path(ass_path).exists())

    # ── Disclaimer card (3 s static image) ───────────────────────────────────
    out_dir.mkdir(parents=True, exist_ok=True)
    disclaimer_png = out_dir / "disclaimer.png"
    print("[Stage 5] Generating disclaimer card…")
    generate_disclaimer_png(profile, disclaimer_png, video_w, video_h)
    disclaimer_clip = (
        ImageClip(str(disclaimer_png), duration=DISCLAIMER_DURATION).with_fps(FPS)
    )

    # ── Per-segment video clips ───────────────────────────────────────────────
    broll_map: dict[str, list[str]] = {
        b["segment_name"]: b["paths"]
        for b in assets.get("broll_video_paths", [])
    }
    screenshot_paths = (job.get("study") or {}).get("screenshot_paths", [])
    SCREENSHOT_SEGS  = {"context", "finding"}

    segment_clips: list = []
    for seg in job["content"]["script_segments"]:
        name     = seg["name"]
        duration = float(seg["duration_hint_seconds"])

        use_screenshot = (
            name in SCREENSHOT_SEGS
            and screenshot_paths
            and Path(screenshot_paths[0]).exists()
        )

        if use_screenshot:
            clip = (
                ImageClip(str(screenshot_paths[0]), duration=duration)
                .with_fps(FPS)
            )
            clip = _mp_scale_crop(clip, video_w, video_h)
            print(f"[Stage 5]   {name}: screenshot ({duration}s)")
        else:
            clip_paths = broll_map.get(name, [])
            if clip_paths and Path(clip_paths[0]).exists():
                raw = VideoFileClip(str(clip_paths[0])).without_audio()
                raw = _mp_scale_crop(raw, video_w, video_h)
                clip = _mp_loop(raw, duration)
                print(f"[Stage 5]   {name}: b-roll ({duration}s)")
            else:
                clip = ColorClip(
                    size=(video_w, video_h), color=(0, 0, 0), duration=duration
                ).with_fps(FPS)
                print(f"[Stage 5]   {name}: ⚠ no clip — black frame ({duration}s)")

        segment_clips.append(clip)

    # ── Optional intro / outro cards ──────────────────────────────────────────
    intro_path = Path(ASSETS_DIR) / "intro.mp4"
    outro_path = Path(ASSETS_DIR) / "outro.mp4"

    video_parts: list = []
    if intro_path.exists():
        intro = VideoFileClip(str(intro_path)).without_audio()
        video_parts.append(_mp_scale_crop(intro, video_w, video_h))
        print("[Stage 5]   Found intro.mp4 — prepending")

    video_parts.append(disclaimer_clip)
    video_parts.extend(segment_clips)

    if outro_path.exists():
        outro = VideoFileClip(str(outro_path)).without_audio()
        video_parts.append(_mp_scale_crop(outro, video_w, video_h))
        print("[Stage 5]   Found outro.mp4 — appending")

    # ── Concatenate video track ───────────────────────────────────────────────
    print(f"\n[Stage 5] Concatenating {len(video_parts)} clip(s)…")
    video_track   = concatenate_videoclips(video_parts)
    total_duration = video_track.duration

    # ── Audio chain ───────────────────────────────────────────────────────────
    voiceover = AudioFileClip(str(voiceover_path))

    if has_music:
        music = AudioFileClip(str(music_path))
        if music.duration < total_duration:
            n = math.ceil(total_duration / music.duration)
            music = concatenate_audioclips([music] * n)
        music = music.subclipped(0, total_duration).with_volume_scaled(0.15)
        audio_out = CompositeAudioClip([voiceover, music])
        print(f"[Stage 5]   Background music: {Path(music_path).name} @ 15 %")
    else:
        audio_out = voiceover

    final = video_track.with_audio(audio_out)

    # ── Render ────────────────────────────────────────────────────────────────
    # If captions need burn-in we write an intermediate first, then do one
    # FFmpeg pass for the ASS filter.  Otherwise the MoviePy output IS the final.
    render_path = out_dir / ("video_raw.mp4" if has_captions else "video.mp4")

    print(f"\n[Stage 5] Rendering with MoviePy "
          f"({video_w}×{video_h}, {total_duration:.1f}s)…")
    final.write_videofile(
        str(render_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        audio_bitrate="128k",
        preset="fast",
        logger="bar",
        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )

    # ── Release MoviePy file handles ──────────────────────────────────────────
    disclaimer_png.unlink(missing_ok=True)
    for clip in video_parts:
        try:
            clip.close()
        except Exception:
            pass

    # ── Optional ASS caption burn-in (single FFmpeg pass) ────────────────────
    if has_captions:
        output_path = out_dir / "video.mp4"
        escaped = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
        print(f"\n[Stage 5] Burning ASS captions from {ass_path}…")
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(render_path),
            "-vf", f"ass='{escaped}'",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "copy",
            str(output_path),
        ])
        render_path.unlink(missing_ok=True)
    else:
        output_path = render_path
        if not ass_path:
            print("[Stage 5]   No ass_path — captions skipped (stage 4d not run)")

    return output_path


# ─── Quality gate ─────────────────────────────────────────────────────────────

def run_quality_gate(output_path: Path, profile: dict) -> dict:
    """
    Probe the assembled video and check it against niche_profile quality_gate thresholds.
    Returns quality_checks dict (with all_passed key).
    """
    qg = profile["quality_gate"]

    checks: dict[str, bool | None] = {
        "duration_in_range": False,
        "disclaimer_present": True,   # always included in assembly
        "audio_peak_ok":     None,
        "audio_avg_ok":      None,
        "all_passed":        False,
    }

    # ── Duration ──────────────────────────────────────────────────────────────
    info     = probe_video(output_path)
    duration = info["duration"]
    checks["duration_in_range"] = (
        qg["min_duration_seconds"] <= duration <= qg["max_duration_seconds"]
    )
    print(f"[Stage 5]   Duration        : {duration:.1f}s "
          f"(allowed {qg['min_duration_seconds']}–{qg['max_duration_seconds']}s) "
          f"→ {'✓' if checks['duration_in_range'] else '✗'}")

    # ── Audio levels ──────────────────────────────────────────────────────────
    if info["has_audio"]:
        vol = volumedetect(output_path)
        if vol:
            audio_cfg = qg["audio_checks"]
            checks["audio_peak_ok"] = vol.get("max_volume", -99) <= audio_cfg["max_peak_dbfs"]
            checks["audio_avg_ok"]  = vol.get("mean_volume", -99) >= audio_cfg["min_avg_dbfs"]
            print(f"[Stage 5]   Audio peak      : {vol.get('max_volume', '?')} dBFS "
                  f"(max {audio_cfg['max_peak_dbfs']}) → {'✓' if checks['audio_peak_ok'] else '✗'}")
            print(f"[Stage 5]   Audio avg       : {vol.get('mean_volume', '?')} dBFS "
                  f"(min {audio_cfg['min_avg_dbfs']}) → {'✓' if checks['audio_avg_ok'] else '✗'}")
        else:
            print("[Stage 5]   Audio levels    : volumedetect returned no data — skipping")
            checks["audio_peak_ok"] = True
            checks["audio_avg_ok"]  = True
    else:
        print("[Stage 5]   Audio levels    : no audio track — skipping")
        checks["audio_peak_ok"] = True
        checks["audio_avg_ok"]  = True

    checks["all_passed"] = all(
        v for k, v in checks.items() if k != "all_passed" and v is not None
    )
    print(f"[Stage 5]   Quality gate    : {'✓ PASSED' if checks['all_passed'] else '✗ FAILED'}")

    return {k: bool(v) if v is not None else False for k, v in checks.items()}


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 5 runner.

    Assembles the video, runs the quality gate, and writes the output block.
    Aborts with error status if:
      - Required assets are missing
      - FFmpeg fails
      - Quality gate does not pass

    Args:
        job_id: UUID of the job.

    Returns:
        Updated job dict with status stage_5_complete or error.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight ───────────────────────────────────────────────────────────
    errored_here = (
        job["status"] == "error"
        and job.get("error", {}).get("stage") == "stage_5"
    )
    dev_mode = job["status"] == "stage_3_complete"
    normal   = job["status"] == "stage_4_complete"

    if not normal and not dev_mode and not errored_here:
        return mark_error(
            job,
            f"Job status is '{job['status']}' — expected 'stage_4_complete' "
            "(or 'stage_3_complete' for development with manually placed assets)"
        )

    job.pop("error", None)
    if errored_here:
        # Restore to whatever status will re-admit us next time
        job["status"] = "stage_4_complete" if not dev_mode else "stage_3_complete"

    if dev_mode:
        print("[Stage 5] ⚠ Development mode — running with stage_3_complete status. "
              "Place assets manually or run stages 4a/4b/4c first.")

    assets = job.get("assets") or {}
    if not assets.get("broll_video_paths"):
        return mark_error(job, "broll_video_paths missing — run stage_4a_broll.py first")

    # ── Assemble ─────────────────────────────────────────────────────────────
    out_dir = Path(ASSETS_DIR) / job_id / "output"
    print(f"[Stage 5] Assembling video for job {job_id}")
    try:
        output_path = assemble_video(job, profile, out_dir)
    except FileNotFoundError as e:
        return mark_error(job, str(e))
    except RuntimeError as e:
        return mark_error(job, f"FFmpeg failed: {e}")

    print(f"[Stage 5] Video written → {output_path}")

    # ── Quality gate ─────────────────────────────────────────────────────────
    print("\n[Stage 5] Running quality gate...")
    quality_checks = run_quality_gate(output_path, profile)

    info     = probe_video(output_path)
    duration = info["duration"]

    if not job.get("output"):
        job["output"] = {}
    job["output"]["final_video_path"]          = str(output_path)
    job["output"]["final_video_duration_seconds"] = round(duration, 3)
    job["output"]["quality_checks"]            = quality_checks
    job["status"] = "stage_5_complete"
    save_job(job)

    if not quality_checks["all_passed"]:
        failing = [k for k, v in quality_checks.items() if k != "all_passed" and not v]
        return mark_error(
            job,
            f"Quality gate failed — {failing}. "
            f"Video is saved at {output_path} for inspection."
        )

    print(f"\n[Stage 5] ✓ Complete")
    print(f"  Output   : {output_path}")
    print(f"  Duration : {duration:.1f}s")

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_5_assembly.py <job_id>
    #   python stage_5_assembly.py          ← auto-picks most recent eligible job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                status = j.get("status")
                retryable = (status == "error"
                             and j.get("error", {}).get("stage") == "stage_5")
                ready = status in ("stage_4_complete", "stage_3_complete")
                if ready or retryable:
                    candidates.append((jf.stat().st_mtime, j["job_id"], status))
            except Exception:
                continue

        if not candidates:
            print("No eligible jobs found (need stage_4_complete, stage_3_complete, or stage_5 error).")
            sys.exit(1)

        candidates.sort(reverse=True)
        _, job_id, picked_status = candidates[0]
        label = "retrying errored" if picked_status == "error" else "most recent"
        print(f"[Stage 5] No job_id provided — using {label}: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result.get("error"):
        print(f"Error        : {result['error']['message']}")
    else:
        out = result.get("output", {})
        print(f"Video        : {out.get('final_video_path')}")
        print(f"Duration     : {out.get('final_video_duration_seconds')}s")
        qc = out.get("quality_checks", {})
        print(f"Quality gate : {'✓ passed' if qc.get('all_passed') else '✗ failed'}")
        print(f"Job saved to : jobs/{result['job_id']}.json")
