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
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # moviepy types imported lazily to give a clean ImportError when missing

MOVIEPY_MISSING_MSG = (
    "moviepy is not installed.\n"
    "Install it with:\n"
    "  pip install moviepy\n"
    "ffmpeg must also be available in your PATH."
)


def _check_moviepy() -> None:
    try:
        import moviepy  # noqa: F401
    except ImportError:
        raise ImportError(MOVIEPY_MISSING_MSG)


# ─── Private helpers ──────────────────────────────────────────────────────────

def _scale_and_crop(clip, target_w: int, target_h: int):
    """
    Resize *clip* to fill target_w × target_h, then center-crop to exact size.

    Uses scale-to-fill (the smaller axis is scaled to fit, the larger is
    cropped) so the clip fills the frame without letterboxing or stretching.

    Args:
        clip:      Any MoviePy VideoClip.
        target_w:  Target width in pixels.
        target_h:  Target height in pixels.

    Returns:
        A new clip with size (target_w, target_h).
    """
    clip_w, clip_h = clip.size
    scale = max(target_w / clip_w, target_h / clip_h)
    new_w = math.ceil(clip_w * scale)
    new_h = math.ceil(clip_h * scale)
    clip = clip.resized((new_w, new_h))
    x1 = (new_w - target_w) // 2
    y1 = (new_h - target_h) // 2
    return clip.cropped(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)


def _loop_to_duration(clip, duration: float):
    """
    Tile *clip* enough times to fill *duration*, then trim to exactly *duration*.

    If the clip is already long enough it is simply trimmed; no copies are made.

    Args:
        clip:     A MoviePy VideoClip (audio stripped before calling).
        duration: Required output duration in seconds.

    Returns:
        A clip of exactly *duration* seconds.
    """
    from moviepy import concatenate_videoclips

    if clip.duration >= duration - 0.01:
        return clip.subclipped(0, duration)
    n = math.ceil(duration / clip.duration)
    tiled = concatenate_videoclips([clip] * n)
    return tiled.subclipped(0, duration)


# ─── Public API ───────────────────────────────────────────────────────────────

def preview_edl(edl_path: str) -> None:
    """
    Print a human-readable summary of an EDL to the terminal.

    Each line shows the time window, the matched B-roll filename (or
    ``NO CLIP FOUND``), and the first 50 characters of the transcript text.
    Useful for auditing the edit plan before committing to a full render.

    Args:
        edl_path: Path to the EDL JSON from ``edit_decision.generate_edl()``.

    Example output::

        0:04 - 0:07 | city_traffic.mp4       | 'aaj hum baat karenge'
        0:07 - 0:11 | NO CLIP FOUND          | 'productivity ke liye'
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

        def _fmt(s: float) -> str:
            return f"{int(s // 60)}:{int(s % 60):02d}"

        clip_label = Path(clip_path).name if clip_path else "NO CLIP FOUND"
        text_preview = repr(text[:50].strip())
        print(f"{_fmt(t_start)} - {_fmt(t_end)} | {clip_label:<22} | {text_preview}")


def assemble(
    base_video_path: str,
    edl_path: str,
    output_path: str,
) -> None:
    """
    Overlay B-roll clips from an EDL onto a base A-roll video and render.

    For each EDL entry with a valid ``clip_path`` the B-roll fully replaces
    the base video visually for that time window.  The base video's audio
    track is kept throughout — B-roll clips are silent in the output.

    Entries whose ``clip_path`` is ``null`` or points to a file that no longer
    exists show the base video footage unchanged.

    Clips shorter than their assigned window are looped to fill the gap.
    Clips longer than their window are trimmed.
    All clips are resized (scale-to-fill + center-crop) to match the base
    video's resolution.

    Args:
        base_video_path: Path to the A-roll / talking-head source video.
        edl_path:        Path to the EDL JSON from ``edit_decision.generate_edl()``.
        output_path:     Destination path for the rendered video (.mp4).

    Raises:
        ImportError:      If moviepy is not installed.
        FileNotFoundError: If *base_video_path* or *edl_path* do not exist.
        ValueError:        If the EDL JSON is malformed.
    """
    _check_moviepy()
    from moviepy import VideoFileClip, concatenate_videoclips

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
    base_audio = base.audio  # may be None if video has no audio track

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
    segments: list = []
    cursor = 0.0

    for i, entry in enumerate(entries):
        t_start = max(0.0, float(entry.get("timeline_start", 0)))
        t_end = min(float(entry.get("timeline_end", 0)), base_duration)

        if t_end <= t_start + 0.01:
            continue  # zero-length window, skip

        # Gap between cursor and this entry: show base video unchanged
        if t_start > cursor + 0.01:
            gap = base.subclipped(cursor, t_start).without_audio()
            segments.append(gap)

        clip_path = entry.get("clip_path")
        if clip_path and Path(clip_path).exists():
            needed = t_end - t_start
            print(
                f"[assembler] [{i+1}/{len(entries)}] B-roll {Path(clip_path).name}"
                f"  [{t_start:.2f}s → {t_end:.2f}s]",
                flush=True,
            )
            broll = VideoFileClip(str(clip_path)).without_audio()
            scale = min(base_w / broll.w, base_h / broll.h)
            broll = broll.resized(scale).with_position("center")
            broll = _loop_to_duration(broll, needed)
            segments.append(broll)
        else:
            # No matching clip — base video shows through
            reason = "null" if not clip_path else "file missing"
            print(
                f"[assembler] [{i+1}/{len(entries)}] no clip ({reason})"
                f"  [{t_start:.2f}s → {t_end:.2f}s] — base video",
                flush=True,
            )
            seg = base.subclipped(t_start, t_end).without_audio()
            segments.append(seg)

        cursor = t_end

    # Tail: remaining base video after the last EDL entry
    if cursor < base_duration - 0.01:
        tail = base.subclipped(cursor, base_duration).without_audio()
        segments.append(tail)

    # ── Assemble ──────────────────────────────────────────────────────────────
    if not segments:
        print("[assembler] No segments produced — writing base video unchanged.", flush=True)
        final = base
    else:
        print(f"[assembler] Concatenating {len(segments)} segment(s)…", flush=True)
        video_track = concatenate_videoclips(segments, size=(base_w, base_h))
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

    # ── Release file handles ───────────────────────────────────────────────────
    base.close()
    for seg in segments:
        try:
            seg.close()
        except Exception:
            pass

    print("[assembler] Done.", flush=True)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print(
            "Usage:\n"
            "  python video_assembler.py <base_video> <edl.json> [output.mp4]\n"
            "  python video_assembler.py --preview <edl.json>\n"
            "\n"
            "Examples:\n"
            "  python video_assembler.py footage.mp4 edl.json final.mp4\n"
            "  python video_assembler.py --preview edl.json\n"
        )
        sys.exit(1)

    if sys.argv[1] == "--preview":
        preview_edl(sys.argv[2])
        sys.exit(0)

    _base = sys.argv[1]
    _edl = sys.argv[2]
    _out = sys.argv[3] if len(sys.argv) > 3 else "output.mp4"

    try:
        assemble(_base, _edl, _out)
    except (ImportError, FileNotFoundError, ValueError) as _exc:
        print(f"ERROR: {_exc}", file=sys.stderr)
        sys.exit(1)
