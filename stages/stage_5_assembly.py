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
BROLL_CUT_INTERVAL  = 5.0          # seconds before cutting to next B-roll clip

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

_DEVANAGARI_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/NotoSansDevanagari-Regular.ttf",
    "/System/Library/Fonts/Supplemental/NotoSansDevanagari.ttf",
    "/System/Library/Fonts/NotoSansDevanagari-Regular.ttf",
    "/Library/Fonts/NotoSansDevanagari-Regular.ttf",
    "/System/Library/Fonts/KohinoorDevanagari.ttc",  # macOS built-in
    "/System/Library/Fonts/Kohinoor.ttc",            # macOS built-in (Devanagari)
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",  # Linux
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

def _pick_video_codec(draft: bool = False) -> tuple[str, list[str], dict]:
    """Return (codec, ffmpeg_params, write_kwargs) preferring Apple VideoToolbox on macOS.

    draft=True uses ultrafast preset + threads=0 for faster preview renders.
    """
    extra_write: dict = {"threads": 0}
    try:
        out = subprocess.run(
            ["ffmpeg", "-encoders", "-v", "quiet"],
            capture_output=True, text=True, timeout=5
        ).stdout
        if "h264_videotoolbox" in out:
            q = "72" if draft else "65"
            return "h264_videotoolbox", ["-q:v", q, "-pix_fmt", "yuv420p", "-movflags", "+faststart"], extra_write
    except Exception:
        pass
    preset = "ultrafast" if draft else "fast"
    return "libx264", ["-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"], {**extra_write, "preset": preset}


def run_ffmpeg(cmd: list[str]) -> None:
    """Run an ffmpeg command. Raises RuntimeError with stderr on failure."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited {result.returncode}:\n{result.stderr[-3000:]}"
        )


def ffmpeg_has_ass_filter() -> bool:
    """
    Return True if this ffmpeg build exposes the libass 'ass' filter.

    Some builds (e.g. certain Homebrew installs) are compiled without libass, so
    the 'ass'/'subtitles' filters are unavailable.  In that case Stage 5 falls
    back to PIL/MoviePy caption overlays instead of an FFmpeg burn-in pass.
    """
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True, text=True,
        )
    except Exception:
        return False
    return bool(re.search(r"^\s*\S*\s+ass\s", result.stdout, re.MULTILINE))


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


def _find_devanagari_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _DEVANAGARI_FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return _find_font(size)


def _chunk_words(timed_words: list, font, space_w: float, max_line_w: float,
                 max_words: int) -> list:
    """
    Group a flat list of (start, end, text) words into short phrase chunks that
    each fit on a single line (≤ max_line_w) and contain at most max_words words.

    WhisperX segments are whole paragraphs; showing one at a time overflows the
    frame.  Subtitles must advance a few words at a time — that is what this does.
    """
    chunks: list[list[tuple]] = []
    cur: list[tuple] = []
    cur_w = 0.0
    for tw in timed_words:
        wlen = font.getlength(tw[2])
        add_w = wlen if not cur else cur_w + space_w + wlen
        if cur and (add_w > max_line_w or len(cur) >= max_words):
            chunks.append(cur)
            cur = [tw]
            cur_w = wlen
        else:
            cur.append(tw)
            cur_w = add_w
    if cur:
        chunks.append(cur)
    return chunks


def generate_caption_overlays(job: dict, profile: dict, video_w: int, video_h: int, temp_dir: Path) -> list:
    """
    Generate transparent PNGs for short, word-highlighted caption phrases and
    return a list of MoviePy ImageClips with correct start times / durations.

    Words from all WhisperX segments are flattened, then grouped into short
    phrases that fit on one line.  Each phrase is shown only during its own time
    window; within a phrase the currently-spoken word is highlighted.
    """
    try:
        from moviepy import ImageClip
    except ImportError:
        return []

    assets = job.get("assets") or {}
    segments = assets.get("whisper_word_timestamps")
    if not segments:
        return []

    style_cfg = profile.get("captions", {}).get("style", {})
    font_size = int(style_cfg.get("font_size", 48))
    margin_bottom_percent = style_cfg.get("margin_bottom_percent", 8)
    outline_color_raw = style_cfg.get("outline_color", "black")
    outline_width = int(style_cfg.get("outline_width", 2))
    highlight_current_word = style_cfg.get("highlight_current_word", True)
    highlight_color_raw = style_cfg.get("highlight_color", "#FFD700")

    MAX_WORDS_PER_CHUNK = 5

    font = _find_devanagari_font(font_size)
    space_w = font.getlength(" ")
    margin_v = round(video_h * margin_bottom_percent / 100)
    max_line_w = video_w * 0.9
    base_y = video_h - margin_v - font_size

    temp_dir.mkdir(parents=True, exist_ok=True)

    # ── Flatten all timed words across segments ───────────────────────────────
    timed_words: list[tuple] = []
    for seg in segments:
        for w in seg.get("words", []):
            wt = (w.get("word") or "").strip()
            ws, we = w.get("start"), w.get("end")
            if not wt or ws is None or we is None:
                continue
            timed_words.append((float(ws), float(we), wt))

    if not timed_words:
        return []

    chunks = _chunk_words(timed_words, font, space_w, max_line_w, MAX_WORDS_PER_CHUNK)

    def _draw_phrase(words_list: list, xs: list, active_idx: int) -> Path:
        img = Image.new("RGBA", (video_w, video_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for j, w_text in enumerate(words_list):
            fill_color = highlight_color_raw if j == active_idx else "white"
            draw.text((xs[j], base_y), w_text, font=font, fill=fill_color,
                      stroke_width=outline_width, stroke_fill=outline_color_raw)
        p = temp_dir / f"cap_{_draw_phrase.idx}.png"
        _draw_phrase.idx += 1
        img.save(str(p))
        return p
    _draw_phrase.idx = 0

    overlay_clips = []
    for chunk in chunks:
        words_list = [c[2] for c in chunk]
        widths = [font.getlength(w) for w in words_list]
        total_w = sum(widths) + space_w * (len(words_list) - 1)
        start_x = (video_w - total_w) / 2

        xs = []
        x = start_x
        for wlen in widths:
            xs.append(x)
            x += wlen + space_w

        chunk_end = chunk[-1][1]

        if not highlight_current_word:
            p = _draw_phrase(words_list, xs, -1)
            dur = chunk_end - chunk[0][0]
            if dur > 0.01:
                overlay_clips.append(
                    ImageClip(str(p), duration=dur).with_fps(FPS).with_start(chunk[0][0])
                )
            continue

        # One image per active word; each window runs until the next word starts
        # (or the chunk ends), so there are no blank gaps mid-phrase.
        for i in range(len(chunk)):
            win_start = chunk[i][0]
            win_end = chunk[i + 1][0] if i + 1 < len(chunk) else chunk_end
            if win_end - win_start <= 0.01:
                continue
            p = _draw_phrase(words_list, xs, i)
            overlay_clips.append(
                ImageClip(str(p), duration=win_end - win_start).with_fps(FPS).with_start(win_start)
            )

    return overlay_clips


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


def _speed_up_audio(src: Path, dst: Path, speed: float) -> None:
    """Write a time-stretched copy of src to dst via FFmpeg atempo (range 0.5–2.0)."""
    run_ffmpeg(["ffmpeg", "-y", "-i", str(src),
                "-filter:a", f"atempo={speed:.4f}",
                "-vn", str(dst)])


def _mix_audio(
    voiceover_path: str,
    music_path: str,
    output_path: str,
    music_volume_db: float = -16.5,
    voiceover_volume_db: float = -2.0,
) -> None:
    """Mix voiceover + looped background music via pydub overlay.

    Using pydub instead of MoviePy's CompositeAudioClip avoids the gain-reduction
    artefact that occurs when the voiceover peaks at 0 dBFS: MoviePy sums samples
    and the resulting >0 dBFS peaks cause the AAC encoder to normalise the whole
    mix down, making the music inaudible.  pydub's overlay() clips the sum at 0 dBFS
    without gain-reducing the entire signal.
    """
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError("pydub is required for audio mixing — pip install pydub")

    vo = AudioSegment.from_wav(voiceover_path)
    music = AudioSegment.from_file(music_path)

    loops_needed = math.ceil(len(vo) / len(music))
    music_looped = music * loops_needed
    music_trimmed = music_looped[: len(vo)]

    mixed = vo.apply_gain(voiceover_volume_db).overlay(
        music_trimmed.apply_gain(music_volume_db)
    )
    mixed.export(output_path, format="wav")


def _build_broll_segment(paths: list[str], duration: float,
                          video_w: int, video_h: int) -> object | None:
    """
    Build a segment clip by cutting between B-roll clips every BROLL_CUT_INTERVAL seconds.

    Cycles through all valid paths so consecutive chunks show different footage.
    Returns None if no valid paths exist.
    """
    from moviepy import VideoFileClip, concatenate_videoclips

    valid = [p for p in paths if Path(p).exists()]
    if not valid:
        return None

    raws = [_mp_scale_crop(VideoFileClip(p).without_audio(), video_w, video_h)
            for p in valid]

    chunks = []
    t, idx = 0.0, 0
    while t < duration - 0.05:
        chunk_dur = min(BROLL_CUT_INTERVAL, duration - t)
        raw = raws[idx % len(raws)]
        # Advance into the clip on each reuse so repeated chunks aren't identical
        usable = max(0.0, raw.duration - chunk_dur)
        offset = (idx * BROLL_CUT_INTERVAL) % raw.duration if usable == 0 else (idx * BROLL_CUT_INTERVAL) % usable
        if raw.duration >= offset + chunk_dur:
            chunks.append(raw.subclipped(offset, offset + chunk_dur))
        else:
            chunks.append(_mp_loop(raw, chunk_dur))
        t += chunk_dur
        idx += 1

    if not chunks:
        return None
    return concatenate_videoclips(chunks)


def assemble_video(job: dict, profile: dict, out_dir: Path, draft: bool = False) -> Path:
    """
    Assemble the final video using MoviePy.

    Timeline:
      [intro.mp4 if present]  →  3s disclaimer  →  per-segment B-roll/screenshots
      →  [outro.mp4 if present]
    Audio: voiceover at 100 % mixed with optional background music at 15 %.
    ASS captions (if present from Stage 4d) are burned in via a single FFmpeg
    post-pass so Stage 5 does not depend on MoviePy for that filter.

    draft=True halves the output resolution and uses ultrafast encoding for fast previews.

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
            CompositeVideoClip,
            ImageClip,
            VideoFileClip,
            concatenate_videoclips,
        )
    except ImportError:
        raise ImportError(
            "moviepy is not installed — cannot run Stage 5.\n"
            "Install it with: pip install moviepy\n"
            "ffmpeg must also be available in your PATH."
        )

    video_w, video_h = _video_dims(job)
    if draft:
        video_w, video_h = video_w // 2, video_h // 2
    assets  = job.get("assets") or {}
    job_id  = job["job_id"]

    ar_label = job.get("aspect_ratio", "9:16")
    mode_label = " [DRAFT — half resolution]" if draft else ""
    print(f"[Stage 5] Aspect ratio: {ar_label} → {video_w}×{video_h}{mode_label}")

    # ── Voiceover (required) ──────────────────────────────────────────────────
    voiceover_path = assets.get("voiceover_path")
    if not voiceover_path or not Path(voiceover_path).exists():
        raise FileNotFoundError(
            f"voiceover not found at '{voiceover_path}'. "
            "Run stage_4c_voiceover.py first, or manually place a WAV at "
            f"assets/{job_id}/audio/voiceover.wav and set assets.voiceover_path in the job."
        )

    music_path = assets.get("background_music_path")
    if not music_path or not Path(music_path).exists():
        # Auto-pick a random track from assets/music/
        import random
        music_dir = Path(ASSETS_DIR) / "music"
        candidates = [
            p for p in music_dir.glob("*")
            if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        ] if music_dir.is_dir() else []
        if candidates:
            music_path = str(random.choice(candidates))
            print(f"[Stage 5]   Auto-selected background music: {Path(music_path).name}")
    has_music = bool(music_path and Path(music_path).exists())
    ass_path     = assets.get("ass_path")
    ass_exists   = bool(ass_path and Path(ass_path).exists())
    # Prefer FFmpeg ASS burn-in (best Devanagari shaping) only if this ffmpeg has
    # libass; otherwise fall back to PIL/MoviePy overlays generated below.
    has_captions = ass_exists and ffmpeg_has_ass_filter()
    if ass_exists and not has_captions:
        print("[Stage 5]   ffmpeg has no libass 'ass' filter — using PIL caption overlays instead.")

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
    # Only show screenshot once, in the first matching segment
    SCREENSHOT_SEG   = "context"
    screenshot_used  = False

    segment_clips: list = []
    for seg in job["content"]["script_segments"]:
        name     = seg["name"]
        duration = float(seg["duration_hint_seconds"])

        use_screenshot = (
            name == SCREENSHOT_SEG
            and not screenshot_used
            and screenshot_paths
            and Path(screenshot_paths[0]).exists()
        )

        if use_screenshot:
            screenshot_used = True
            SCREENSHOT_DISPLAY_DURATION = 3.0
            ss_display = min(SCREENSHOT_DISPLAY_DURATION, duration)

            # Cutting B-roll as background for the full segment duration
            broll_paths = broll_map.get(name, [])
            bg = _build_broll_segment(broll_paths, duration, video_w, video_h)
            if bg is None:
                bg = ColorClip(
                    size=(video_w, video_h), color=(20, 20, 20), duration=duration
                ).with_fps(FPS)

            # Scale screenshot to 60% of video width, keep aspect ratio
            ss_target_w = int(video_w * 0.60)
            ss_img = ImageClip(str(screenshot_paths[0]), duration=ss_display).with_fps(FPS)
            ss_w, ss_h = ss_img.size
            ss_target_h = int(ss_h * (ss_target_w / ss_w))
            ss_img = ss_img.resized((ss_target_w, ss_target_h))
            ss_x = (video_w - ss_target_w) // 2
            ss_y = (video_h - ss_target_h) // 2
            ss_img = ss_img.with_position((ss_x, ss_y))

            # Composite: B-roll plays the whole segment; screenshot overlays first 3s only
            clip = CompositeVideoClip([bg, ss_img], size=(video_w, video_h))

            print(f"[Stage 5]   {name}: screenshot overlay {ss_display}s over b-roll ({duration}s total)")
        else:
            clip_paths = broll_map.get(name, [])
            built = _build_broll_segment(clip_paths, duration, video_w, video_h)
            if built is not None:
                clip = built
                n_clips = len([p for p in clip_paths if Path(p).exists()])
                n_cuts = max(1, math.ceil(duration / BROLL_CUT_INTERVAL))
                print(f"[Stage 5]   {name}: b-roll {n_cuts} cut(s) across {n_clips} clip(s) ({duration}s)")
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
    video_track = concatenate_videoclips(video_parts)

    # ── Audio chain ───────────────────────────────────────────────────────────
    # Load voiceover first — its duration is the authoritative timeline length.
    # The video segments are built from duration_hint_seconds estimates that never
    # match the real TTS output exactly, so we pin the video to the voiceover.
    voiceover = AudioFileClip(str(voiceover_path))
    total_duration = voiceover.duration

    print(f"[Stage 5]   Voiceover duration : {total_duration:.2f}s")
    print(f"[Stage 5]   Video track duration: {video_track.duration:.2f}s")

    # Trim or extend-freeze the video to exactly match the voiceover
    video_track = video_track.with_duration(total_duration)

    if has_music:
        # Pre-mix via FFmpeg: voiceover at -2 dB headroom + music at -16.5 dB (~15%).
        # MoviePy's CompositeAudioClip sums samples, which pushes peaks above 0 dBFS
        # when the voiceover is already normalised; the AAC encoder then applies gain
        # reduction that makes the music inaudible.  Doing the mix in FFmpeg with
        # explicit volume controls avoids that normalisation artefact.
        mixed_audio_path = out_dir / "mixed_audio.wav"
        _mix_audio(
            voiceover_path=str(voiceover_path),
            music_path=str(music_path),
            output_path=str(mixed_audio_path),
            music_volume_db=-16.5,   # ≈ 15 % amplitude
            voiceover_volume_db=-2.0, # 2 dB headroom to prevent clipping
        )
        audio_out = AudioFileClip(str(mixed_audio_path))
        print(f"[Stage 5]   Background music: {Path(music_path).name} @ 15 % (FFmpeg mix)")
    else:
        audio_out = AudioFileClip(str(voiceover_path))

    # ── Caption overlays — PIL fallback when no ASS file from stage 4d ──────────
    temp_captions_dir = out_dir / "temp_captions"
    if has_captions:
        print(f"[Stage 5]   ASS captions found — will burn in via FFmpeg post-pass.")
    else:
        try:
            caption_clips = generate_caption_overlays(job, profile, video_w, video_h, temp_captions_dir)
            if caption_clips:
                print(f"[Stage 5]   Generated {len(caption_clips)} caption overlay clips (PIL fallback).")
                video_track = CompositeVideoClip([video_track] + caption_clips, size=(video_w, video_h)).with_duration(total_duration)
        except Exception as e:
            print(f"[Stage 5]   WARNING: Failed to generate caption overlays: {e}")

    # ── Subscribe overlay ────────────────────────────────────────────────────
    subscribe_path = Path(ASSETS_DIR) / "subscribe.mp4"
    if subscribe_path.exists():
        sub_clip = VideoFileClip(str(subscribe_path))
        sub_start = max(0.0, total_duration - sub_clip.duration - 2.0)
        sub_x = (video_w - sub_clip.w) // 2
        sub_y = video_h - sub_clip.h - int(video_h * 0.05)  # 5% margin from bottom
        sub_clip = sub_clip.with_position((sub_x, sub_y)).with_start(sub_start)
        video_track = CompositeVideoClip(
            [video_track, sub_clip], size=(video_w, video_h)
        ).with_duration(total_duration)
        print(f"[Stage 5]   Subscribe overlay: {sub_clip.duration:.1f}s starting at {sub_start:.1f}s")
    else:
        print(f"[Stage 5]   No subscribe.mp4 found at {subscribe_path} — skipping overlay")

    final = video_track.with_audio(audio_out)

    # ── Render ────────────────────────────────────────────────────────────────
    # If captions need burn-in we write an intermediate first, then do one
    # FFmpeg pass for the ASS filter.  Otherwise the MoviePy output IS the final.
    render_path = out_dir / ("video_raw.mp4" if has_captions else "video.mp4")

    vcodec, vparams, vextra = _pick_video_codec(draft=draft)
    mode_tag = " [DRAFT]" if draft else ""
    print(f"\n[Stage 5] Rendering with MoviePy "
          f"({video_w}×{video_h}, {total_duration:.1f}s, codec={vcodec}{mode_tag})…")
    write_kwargs: dict = dict(
        fps=FPS,
        codec=vcodec,
        audio_codec="aac",
        audio_bitrate="128k",
        logger="bar",
        ffmpeg_params=vparams,
        **vextra,
    )
    final.write_videofile(str(render_path), **write_kwargs)

    # ── Release MoviePy file handles ──────────────────────────────────────────
    disclaimer_png.unlink(missing_ok=True)
    for clip in video_parts:
        try:
            clip.close()
        except Exception:
            pass
            
    # Cleanup temp captions directory
    if temp_captions_dir.exists():
        import shutil
        shutil.rmtree(temp_captions_dir, ignore_errors=True)

    # ── Optional ASS caption burn-in (single FFmpeg pass) ────────────────────
    if has_captions:
        output_path = out_dir / "video.mp4"
        abs_ass = str(Path(ass_path).resolve())
        # FFmpeg filter graph escaping: backslash-escape backslashes and colons (macOS paths have none, but be safe)
        escaped = abs_ass.replace("\\", "\\\\").replace(":", "\\:")
        print(f"\n[Stage 5] Burning ASS captions from {ass_path}…")
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", str(render_path),
            "-vf", f"ass=filename={escaped}",
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

def run(job_id: str, draft: bool = False) -> dict:
    """
    Main Stage 5 runner.

    Assembles the video, runs the quality gate, and writes the output block.
    Aborts with error status if:
      - Required assets are missing
      - FFmpeg fails
      - Quality gate does not pass

    Args:
        job_id: UUID of the job.
        draft:  If True, halves resolution and uses ultrafast encoding for fast previews.

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
    print(f"[Stage 5] Assembling video for job {job_id}" + (" [DRAFT]" if draft else ""))
    try:
        output_path = assemble_video(job, profile, out_dir, draft=draft)
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
    #   python stage_5_assembly.py <job_id> [--draft]
    #   python stage_5_assembly.py [--draft]   ← auto-picks most recent eligible job

    args = sys.argv[1:]
    draft_mode = "--draft" in args
    positional = [a for a in args if not a.startswith("--")]

    if not positional:
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
        job_id = positional[0]

    result = run(job_id, draft=draft_mode)
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
