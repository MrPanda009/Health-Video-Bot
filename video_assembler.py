"""
Video assembler — overlays B-roll clips from an EDL onto a base A-roll video.

Reads an EDL JSON produced by edit_decision.generate_edl() and a base video
(talking-head / A-roll footage), replaces the video track at each EDL window
with the matched B-roll clip, and writes the result to disk.

The base video's audio is always kept intact — B-roll clips contribute video
only, never audio. Segments with no matching clip show the base video unchanged.

Requires MoviePy 2.x:
  pip install moviepy
ffmpeg must also be available in PATH (MoviePy delegates encoding to it).

EDL entry fields (all optional except timeline_start/timeline_end):
  clip_path         : str   — path to B-roll file (video or image)
  animation_type    : str   — "ken_burns" (default for images), "slide_in",
                              "zoom_punch", or None (video clips default to None)
  transition_to_next: str   — "crossfade" (default), or None
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # moviepy types imported lazily

MOVIEPY_MISSING_MSG = (
    "moviepy is not installed.\n"
    "Install it with:\n"
    "  pip install moviepy\n"
    "ffmpeg must also be available in your PATH."
)

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff"}
_TEMP_DIR = Path(tempfile.gettempdir()) / "assembler_temp"


def _check_moviepy() -> None:
    try:
        import moviepy  # noqa: F401
    except ImportError:
        raise ImportError(MOVIEPY_MISSING_MSG)


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_EXTS


def _temp_path(suffix: str = ".mp4") -> str:
    _TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return str(_TEMP_DIR / f"{uuid.uuid4().hex}{suffix}")


def _cleanup_temp() -> None:
    if _TEMP_DIR.exists():
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)


# ─── Private helpers ──────────────────────────────────────────────────────────

def _scale_and_crop(clip, target_w: int, target_h: int):
    """Resize clip to fill target_w × target_h, then center-crop to exact size."""
    clip_w, clip_h = clip.size
    scale = max(target_w / clip_w, target_h / clip_h)
    new_w = math.ceil(clip_w * scale)
    new_h = math.ceil(clip_h * scale)
    clip = clip.resized((new_w, new_h))
    x1 = (new_w - target_w) // 2
    y1 = (new_h - target_h) // 2
    return clip.cropped(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)


def _loop_to_duration(clip, duration: float):
    """Tile clip to fill duration, then trim to exactly duration."""
    from moviepy import concatenate_videoclips

    if clip.duration >= duration - 0.01:
        return clip.subclipped(0, duration)
    n = math.ceil(duration / clip.duration)
    tiled = concatenate_videoclips([clip] * n)
    return tiled.subclipped(0, duration)


# ─── Animation helpers ────────────────────────────────────────────────────────

def _ken_burns(image_path: str, duration: float, target_w: int, target_h: int):
    """
    Animate a still image with a slow zoom-in (1.0 → 1.15) via FFmpeg zoompan.
    Returns a MoviePy VideoFileClip from a temp file.
    """
    from moviepy import VideoFileClip

    out_path = _temp_path(".mp4")
    fps = 25
    total_frames = max(1, round(duration * fps))
    # zoompan: zoom from 1.0 to 1.15 linearly over all frames, centered
    zoom_expr = f"'1+(0.15*on/{total_frames})'"
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-vf", (
            f"zoompan=z={zoom_expr}:x={x_expr}:y={y_expr}"
            f":d={total_frames}:s={target_w}x{target_h}:fps={fps}"
        ),
        "-t", str(duration),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        out_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return VideoFileClip(out_path)


def _slide_in(clip, target_w: int, target_h: int, duration: float):
    """
    Slide clip in from right over 0.3 s, hold, then slide out to left over 0.3 s.
    Uses MoviePy with_position() + lambda.
    """
    slide_t = min(0.3, duration / 4)

    def _pos(t):
        if t < slide_t:
            # slide in from right
            frac = t / slide_t
            x = target_w * (1 - frac)
        elif t > duration - slide_t:
            # slide out to left
            frac = (t - (duration - slide_t)) / slide_t
            x = -target_w * frac
        else:
            x = 0
        return (x, 0)

    return clip.with_position(_pos)


def _zoom_punch(clip, duration: float):
    """
    Start at 95% size, grow to 105% over the clip duration (centered).
    Uses clip.fl() with a custom frame function.
    """
    import numpy as np

    target_w, target_h = clip.size

    def _transform_frame(get_frame, t):
        frame = get_frame(t)
        frac = t / max(duration, 0.001)
        scale = 0.95 + 0.10 * frac  # 0.95 → 1.05
        h, w = frame.shape[:2]
        new_w = int(w * scale)
        new_h = int(h * scale)
        # Use PIL for high-quality resize
        from PIL import Image
        img = Image.fromarray(frame)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        arr = np.array(img)
        # Center-crop back to original size
        y1 = max(0, (new_h - h) // 2)
        x1 = max(0, (new_w - w) // 2)
        arr = arr[y1:y1 + h, x1:x1 + w]
        # Pad if needed (scale < 1.0 edge case)
        if arr.shape[0] < h or arr.shape[1] < w:
            pad = np.zeros((h, w, arr.shape[2]), dtype=arr.dtype)
            pad[:arr.shape[0], :arr.shape[1]] = arr
            arr = pad
        return arr

    return clip.fl(_transform_frame)


def apply_animations(clip, edl_entry: dict, target_w: int, target_h: int,
                     default_animation: str | None = None):
    """
    Apply the animation specified in edl_entry["animation_type"] to clip.

    For image source clips: default is "ken_burns".
    For video source clips: default is None (no animation).

    The clip passed in should already be the correct duration.
    Returns the (possibly wrapped) clip. For "ken_burns" the returned clip
    is a freshly loaded VideoFileClip from a temp file — close it after use.
    """
    anim = edl_entry.get("animation_type", default_animation)
    if not anim:
        return clip

    duration = clip.duration

    if anim == "ken_burns":
        # ken_burns re-creates clip via FFmpeg; the original image-backed clip
        # is discarded by the caller after this returns.
        src = edl_entry.get("clip_path", "")
        if not src or not _is_image(src):
            # fall back to zoom_punch for non-images
            clip = _scale_and_crop(clip, target_w, target_h)
            return _zoom_punch(clip, duration)
        return _ken_burns(src, duration, target_w, target_h)

    elif anim == "slide_in":
        clip = _scale_and_crop(clip, target_w, target_h)
        return _slide_in(clip, target_w, target_h, duration)

    elif anim == "zoom_punch":
        clip = _scale_and_crop(clip, target_w, target_h)
        return _zoom_punch(clip, duration)

    return clip


# ─── Transition helpers ───────────────────────────────────────────────────────

def apply_transitions(
    clips: list,
    transition_types: list[str | None],
    duration: float = 0.4,
) -> list:
    """
    Apply transitions between consecutive clips.

    Args:
        clips:            List of video-only MoviePy clips (no audio).
        transition_types: List of transition type strings, one per clip.
                          transition_types[i] controls the transition from
                          clip[i] to clip[i+1]. Use None or "" to skip.
        duration:         Crossfade overlap duration in seconds.

    Returns:
        A new list of clips with start times adjusted for overlapping crossfades.
        Callers must assemble these with CompositeVideoClip, not concatenate.

    Supported types:
        "crossfade" — crossfadeout on the outgoing clip, crossfadein on the incoming.
    """
    if len(clips) <= 1:
        return clips

    result = []
    cursor = 0.0

    for i, clip in enumerate(clips):
        clip = clip.with_start(cursor)

        trans = transition_types[i] if i < len(transition_types) else None

        if trans == "crossfade" and i < len(clips) - 1:
            fade = min(duration, clip.duration / 2, clips[i + 1].duration / 2)
            clip = clip.crossfadeout(fade)
            result.append(clip)
            cursor += clip.duration - fade
        else:
            result.append(clip)
            cursor += clip.duration

    # Apply crossfadein to clips that had a preceding crossfadeout
    faded_result = []
    for i, clip in enumerate(result):
        if i > 0:
            trans = transition_types[i - 1] if i - 1 < len(transition_types) else None
            if trans == "crossfade":
                fade = min(duration, clip.duration / 2)
                clip = clip.crossfadein(fade)
        faded_result.append(clip)

    return faded_result


# ─── Public API ───────────────────────────────────────────────────────────────

def preview_edl(edl_path: str) -> None:
    """
    Print a human-readable summary of an EDL to the terminal.

    Each line shows the time window, the matched B-roll filename (or
    ``NO CLIP FOUND``), and the first 50 characters of the transcript text.
    """
    edl_path = str(edl_path)
    if not Path(edl_path).exists():
        print(f"EDL file not found: {edl_path}", file=sys.stderr)
        return

    with open(edl_path, encoding="utf-8") as f:
        edl = json.load(f)

    if not edl:
        print("(EDL is empty — nothing to preview)")
        return

    for entry in sorted(edl, key=lambda e: float(e.get("timeline_start", 0))):
        t_start = float(entry.get("timeline_start", 0))
        t_end = float(entry.get("timeline_end", 0))
        clip_path = entry.get("clip_path")
        text = entry.get("source_text", "")
        anim = entry.get("animation_type", "")
        trans = entry.get("transition_to_next", "")

        def _fmt(s: float) -> str:
            return f"{int(s // 60)}:{int(s % 60):02d}"

        clip_label = Path(clip_path).name if clip_path else "NO CLIP FOUND"
        text_preview = repr(text[:50].strip())
        tags = []
        if anim:
            tags.append(f"anim={anim}")
        if trans:
            tags.append(f"→{trans}")
        tag_str = f"  [{', '.join(tags)}]" if tags else ""
        print(f"{_fmt(t_start)} - {_fmt(t_end)} | {clip_label:<22} | {text_preview}{tag_str}")


def assemble(
    base_video_path: str,
    edl_path: str,
    output_path: str,
    default_transition: str = "crossfade",
    default_animation: str | None = None,
    transition_duration: float = 0.4,
) -> None:
    """
    Overlay B-roll clips from an EDL onto a base A-roll video and render.

    For each EDL entry with a valid ``clip_path`` the B-roll fully replaces
    the base video visually for that time window.  The base video's audio
    track is kept throughout — B-roll clips are silent in the output.

    Image files (.jpg, .png, etc.) in the EDL are animated:
      - Default animation: "ken_burns" (slow zoom via FFmpeg zoompan)
      - Override per entry: ``animation_type`` field in EDL entry
      - Override globally: ``default_animation`` argument / --animation-type flag

    Transitions between consecutive B-roll clips:
      - Default: "crossfade" with 0.4 s overlap
      - Override per entry: ``transition_to_next`` field on the outgoing entry
      - Override globally: ``default_transition`` / --transition-type flag

    Args:
        base_video_path:     Path to the A-roll / talking-head source video.
        edl_path:            Path to the EDL JSON.
        output_path:         Destination path for the rendered video (.mp4).
        default_transition:  Transition type when not set per-entry ("crossfade" or None).
        default_animation:   Animation type for image clips when not set per-entry.
        transition_duration: Crossfade overlap in seconds (default 0.4).

    Raises:
        ImportError:       If moviepy is not installed.
        FileNotFoundError: If base_video_path or edl_path do not exist.
        ValueError:        If the EDL JSON is malformed.
    """
    _check_moviepy()
    from moviepy import (
        CompositeVideoClip,
        ImageClip,
        VideoFileClip,
        concatenate_videoclips,
    )

    base_video_path = str(base_video_path)
    edl_path = str(edl_path)
    output_path = str(output_path)

    if not Path(base_video_path).exists():
        raise FileNotFoundError(f"Base video not found: {base_video_path}")
    if not Path(edl_path).exists():
        raise FileNotFoundError(f"EDL file not found: {edl_path}")

    # ── Load base ─────────────────────────────────────────────────────────────
    print(f"[assembler] Loading base video: {base_video_path}", flush=True)
    base = VideoFileClip(base_video_path)
    base_w, base_h = base.size
    base_duration = base.duration
    base_audio = base.audio

    print(f"[assembler] Base: {base_w}×{base_h}  {base_duration:.2f}s", flush=True)

    # ── Load EDL ──────────────────────────────────────────────────────────────
    with open(edl_path, encoding="utf-8") as f:
        try:
            edl = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed EDL JSON in {edl_path}: {exc}") from exc

    if not isinstance(edl, list):
        raise ValueError(f"EDL must be a JSON array, got {type(edl).__name__}")

    entries = sorted(edl, key=lambda e: float(e.get("timeline_start", 0)))

    # ── Build video-only segments ─────────────────────────────────────────────
    # Each segment is (clip, transition_to_next, is_broll)
    raw_segments: list[tuple] = []
    cursor = 0.0
    opened_clips: list = []  # track for cleanup

    for i, entry in enumerate(entries):
        t_start = max(0.0, float(entry.get("timeline_start", 0)))
        t_end = min(float(entry.get("timeline_end", 0)), base_duration)

        if t_end <= t_start + 0.01:
            continue

        # Gap: show base video unchanged, no animation, no transition
        if t_start > cursor + 0.01:
            gap = base.subclipped(cursor, t_start).without_audio()
            raw_segments.append((gap, None, False))

        clip_path = entry.get("clip_path")
        entry_transition = entry.get("transition_to_next", default_transition)
        needed = t_end - t_start

        if clip_path and Path(clip_path).exists():
            print(
                f"[assembler] [{i+1}/{len(entries)}] {Path(clip_path).name}"
                f"  [{t_start:.2f}s → {t_end:.2f}s]",
                flush=True,
            )

            is_img = _is_image(clip_path)

            if is_img:
                # Determine animation — default "ken_burns" for images
                anim = entry.get("animation_type", default_animation or "ken_burns")
                entry_with_anim = dict(entry, animation_type=anim)

                if anim == "ken_burns":
                    # ken_burns produces its own clip via FFmpeg subprocess
                    print(f"[assembler]   ken_burns animation", flush=True)
                    broll = apply_animations(
                        None, entry_with_anim, base_w, base_h, anim
                    )
                    broll = broll.subclipped(0, min(needed, broll.duration))
                    if broll.duration < needed - 0.01:
                        broll = _loop_to_duration(broll, needed)
                else:
                    img_clip = ImageClip(clip_path, duration=needed)
                    img_clip = _scale_and_crop(img_clip, base_w, base_h)
                    broll = apply_animations(
                        img_clip, entry_with_anim, base_w, base_h, anim
                    )
                    opened_clips.append(img_clip)

            else:
                raw = VideoFileClip(str(clip_path)).without_audio()
                opened_clips.append(raw)
                raw = _loop_to_duration(raw, needed)
                anim = entry.get("animation_type", default_animation)
                entry_with_anim = dict(entry, animation_type=anim)
                if anim:
                    raw = _scale_and_crop(raw, base_w, base_h)
                    broll = apply_animations(raw, entry_with_anim, base_w, base_h, anim)
                else:
                    broll = _scale_and_crop(raw, base_w, base_h)

            raw_segments.append((broll, entry_transition, True))
        else:
            reason = "null" if not clip_path else "file missing"
            print(
                f"[assembler] [{i+1}/{len(entries)}] no clip ({reason})"
                f"  [{t_start:.2f}s → {t_end:.2f}s] — base video",
                flush=True,
            )
            seg = base.subclipped(t_start, t_end).without_audio()
            raw_segments.append((seg, None, False))

        cursor = t_end

    # Tail
    if cursor < base_duration - 0.01:
        tail = base.subclipped(cursor, base_duration).without_audio()
        raw_segments.append((tail, None, False))

    # ── Apply transitions ─────────────────────────────────────────────────────
    if not raw_segments:
        print("[assembler] No segments — writing base video unchanged.", flush=True)
        final = base
    else:
        clips = [s[0] for s in raw_segments]
        trans_types = [s[1] for s in raw_segments]

        has_crossfade = any(t == "crossfade" for t in trans_types)

        if has_crossfade:
            print("[assembler] Applying crossfade transitions…", flush=True)
            clips_with_starts = apply_transitions(
                clips, trans_types, duration=transition_duration
            )
            total_dur = max(
                c.start + c.duration for c in clips_with_starts
            )
            video_track = CompositeVideoClip(clips_with_starts, size=(base_w, base_h))
            video_track = video_track.with_duration(min(total_dur, base_duration))
        else:
            print(f"[assembler] Concatenating {len(clips)} segment(s)…", flush=True)
            video_track = concatenate_videoclips(clips, size=(base_w, base_h))
            video_track = video_track.with_duration(base_duration)

        final = video_track.with_duration(base_duration)
        final = final.with_audio(base_audio) if base_audio else final

    # ── Render ────────────────────────────────────────────────────────────────
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    print(f"[assembler] Rendering → {output_path}", flush=True)
    final.write_videofile(
        output_path,
        codec="libx264",
        audio_codec="aac",
        logger="bar",
        ffmpeg_params=["-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart"],
    )

    # ── Cleanup ───────────────────────────────────────────────────────────────
    base.close()
    for clip in opened_clips:
        try:
            clip.close()
        except Exception:
            pass
    for seg, _, _ in raw_segments:
        try:
            seg.close()
        except Exception:
            pass

    _cleanup_temp()
    print("[assembler] Done.", flush=True)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Overlay B-roll from an EDL onto a base video."
    )
    parser.add_argument("base_or_preview", help="Base video path, or '--preview'")
    parser.add_argument("edl", nargs="?", help="EDL JSON path")
    parser.add_argument("output", nargs="?", default="output.mp4", help="Output path (default: output.mp4)")
    parser.add_argument(
        "--transition-type",
        default="crossfade",
        choices=["crossfade", "none"],
        help="Default transition between clips (default: crossfade)",
    )
    parser.add_argument(
        "--animation-type",
        default=None,
        choices=["ken_burns", "slide_in", "zoom_punch", "none"],
        help="Default animation for image clips (default: ken_burns for images)",
    )
    parser.add_argument(
        "--transition-duration",
        type=float,
        default=0.4,
        help="Crossfade overlap duration in seconds (default: 0.4)",
    )

    args = parser.parse_args()

    if args.base_or_preview == "--preview":
        if not args.edl:
            print("ERROR: --preview requires an EDL path.", file=sys.stderr)
            sys.exit(1)
        preview_edl(args.edl)
        sys.exit(0)

    if not args.edl:
        print("ERROR: EDL path required.", file=sys.stderr)
        sys.exit(1)

    default_anim = None if args.animation_type in (None, "none") else args.animation_type
    default_trans = None if args.transition_type == "none" else args.transition_type

    try:
        assemble(
            args.base_or_preview,
            args.edl,
            args.output,
            default_transition=default_trans,
            default_animation=default_anim,
            transition_duration=args.transition_duration,
        )
    except (ImportError, FileNotFoundError, ValueError) as _exc:
        print(f"ERROR: {_exc}", file=sys.stderr)
        sys.exit(1)
