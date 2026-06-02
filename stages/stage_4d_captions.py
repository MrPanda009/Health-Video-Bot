"""
Stage 4d — Whisper Captions
============================
Transcribes the generated voiceover with WhisperX to produce:
  - Word-level timestamps JSON  →  job["assets"]["whisper_word_timestamps"]
  - SRT subtitle file           →  job["assets"]["srt_path"]

Does NOT change job status — the frontend API sets stage_4_complete after
all Stage 4 sub-stages (4a, 4b, 4c, 4d) have completed.

Stage 5 handles absence gracefully: if srt_path is None it falls back to
duration_hint_seconds for timing and skips ASS caption burn-in.

Prerequisites
-------------
  pip install whisperx torch
  Download models via the Models page in the dashboard, or:
    python stages/model_manager.py download large-v2
    python stages/model_manager.py download align-hi
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

JOBS_DIR   = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR = os.getenv("ASSETS_DIR", "assets")
NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")

# whisperx_transcriber lives at the project root (one level up from stages/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from whisperx_transcriber import transcribe, WHISPERX_MISSING_MSG
    _WHISPERX_AVAILABLE = True
except ImportError as _e:
    _WHISPERX_AVAILABLE = False
    _WHISPERX_IMPORT_ERROR = str(_e)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_job(job_id: str) -> dict:
    p = Path(JOBS_DIR) / f"{job_id}.json"
    if not p.exists():
        raise FileNotFoundError(f"Job file not found: {p}")
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def save_job(job: dict) -> None:
    Path(JOBS_DIR).mkdir(parents=True, exist_ok=True)
    p = Path(JOBS_DIR) / f"{job['job_id']}.json"
    with p.open("w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)


def mark_error(job: dict, message: str, retries: int = 0) -> dict:
    job["status"] = "error"
    job["error"] = {"stage": "stage_4d", "message": message, "retries": retries}
    save_job(job)
    print(f"[Stage 4d] ERROR: {message}", flush=True)
    return job


def _fmt_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    """Convert WhisperX segments to an SRT-formatted string."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        start = _fmt_srt_time(seg["start"])
        end = _fmt_srt_time(seg["end"])
        text = seg["text"].strip()
        lines.append(f"{i}\n{start} --> {end}\n{text}\n")
    return "\n".join(lines)


def load_niche_profile() -> dict:
    with open(NICHE_PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


_ASPECT_DIMS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),   # YouTube Shorts portrait
    "16:9": (1920, 1080),   # Standard landscape / YouTube long-form
}


def _video_dims(job: dict) -> tuple[int, int]:
    """Return (width, height) for this job based on its aspect_ratio field."""
    ar = job.get("aspect_ratio", "9:16")
    return _ASPECT_DIMS.get(ar, _ASPECT_DIMS["9:16"])


def parse_color_to_ass(color_str: str) -> str:
    """Convert a color name or hex code (e.g. #FFD700) to ASS format (&HAABBGGRR)."""
    color_str = color_str.strip().lower()
    if color_str.startswith("#"):
        hex_val = color_str.lstrip("#")
        if len(hex_val) == 6:
            r, g, b = hex_val[0:2], hex_val[2:4], hex_val[4:6]
            return f"&H00{b}{g}{r}"
        elif len(hex_val) == 8:
            r, g, b, a = hex_val[0:2], hex_val[2:4], hex_val[4:6], hex_val[6:8]
            # Convert web alpha (00 transparent, FF opaque) to ASS alpha (FF transparent, 00 opaque)
            try:
                web_a = int(a, 16)
                ass_a = 255 - web_a
                return f"&H{ass_a:02X}{b}{g}{r}"
            except ValueError:
                return f"&H00{b}{g}{r}"
    mapping = {
        "white": "&H00FFFFFF",
        "black": "&H00000000",
        "red": "&H000000FF",
        "green": "&H0000FF00",
        "blue": "&H00FF0000",
        "yellow": "&H0000FFFF",
    }
    return mapping.get(color_str, "&H00FFFFFF")


def _fmt_ass_time(seconds: float) -> str:
    """Format seconds as ASS timestamp: H:MM:SS.cs."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"


def segments_to_ass(segments: list[dict], style_config: dict, video_w: int, video_h: int) -> str:
    """Convert WhisperX segments to styled ASS caption format."""
    font_name = style_config.get("font", "Noto Sans Devanagari")
    font_size = style_config.get("font_size", 48)
    margin_bottom_percent = style_config.get("margin_bottom_percent", 8)
    outline_color_raw = style_config.get("outline_color", "black")
    outline_width = style_config.get("outline_width", 2)
    highlight_current_word = style_config.get("highlight_current_word", True)
    highlight_color_raw = style_config.get("highlight_color", "#FFD700")

    outline_color = parse_color_to_ass(outline_color_raw)
    back_color = "&H00000000"
    
    if highlight_current_word:
        primary_color = parse_color_to_ass(highlight_color_raw)
        secondary_color = "&H00FFFFFF"
    else:
        primary_color = "&H00FFFFFF"
        secondary_color = "&H00FFFFFF"

    position = style_config.get("position", "bottom_center")
    alignment = 2
    if position == "bottom_center":
        alignment = 2
    elif position == "bottom_left":
        alignment = 1
    elif position == "bottom_right":
        alignment = 3
    elif position == "middle_center":
        alignment = 5
    elif position == "top_center":
        alignment = 8

    margin_v = round(video_h * margin_bottom_percent / 100)
    bold = 1 if style_config.get("bold", False) else 0
    italic = 1 if style_config.get("italic", False) else 0
    shadow_width = 1

    header = f"""[Script Info]
Title: Hindi Health Video Captions
ScriptType: v4.00+
WrapStyle: 0
PlayResX: {video_w}
PlayResY: {video_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},{primary_color},{secondary_color},{outline_color},{back_color},{bold},{italic},0,0,100,100,0,0,1,{outline_width},{shadow_width},{alignment},10,10,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in segments:
        start_time = _fmt_ass_time(seg["start"])
        end_time = _fmt_ass_time(seg["end"])
        
        words = seg.get("words", [])
        has_word_timestamps = len(words) > 0 and all("start" in w and "end" in w for w in words)
        
        dialogue_text = ""
        if highlight_current_word and has_word_timestamps:
            current_time = seg["start"]
            for idx, w in enumerate(words):
                w_start = w.get("start")
                w_end = w.get("end")
                w_text = w.get("word", "")
                
                if w_start is None or w_end is None:
                    suffix = " " if idx < len(words) - 1 else ""
                    dialogue_text += f"{w_text}{suffix}"
                    continue
                
                if w_start > current_time:
                    gap_cs = round((w_start - current_time) * 100)
                    if gap_cs > 0:
                        dialogue_text += f"{{\\k{gap_cs}}}"
                
                dur_cs = max(1, round((w_end - w_start) * 100))
                suffix = " " if idx < len(words) - 1 else ""
                dialogue_text += f"{{\\k{dur_cs}}}{w_text}{suffix}"
                current_time = w_end
        else:
            dialogue_text = seg["text"].strip()
            
        lines.append(f"Dialogue: 0,{start_time},{end_time},Default,,0,0,0,,{dialogue_text}")

    return "\n".join(lines)


# ─── Main stage logic ─────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    print(f"[Stage 4d] Starting for job {job_id}", flush=True)

    # ── Guard: whisperx must be installed ────────────────────────────────────
    if not _WHISPERX_AVAILABLE:
        # Load job so we can mark it as errored
        try:
            job = load_job(job_id)
        except FileNotFoundError as e:
            print(f"[Stage 4d] ERROR: {e}", flush=True)
            sys.exit(1)
        return mark_error(
            job,
            f"whisperx is not installed — cannot run Stage 4d.\n"
            f"Install it with: pip install whisperx\n"
            f"Then download models via the Models page in the dashboard.\n"
            f"Original error: {_WHISPERX_IMPORT_ERROR}",
        )

    # ── Load job ──────────────────────────────────────────────────────────────
    try:
        job = load_job(job_id)
    except FileNotFoundError as e:
        print(f"[Stage 4d] ERROR: {e}", flush=True)
        sys.exit(1)

    status = job.get("status", "")
    if status not in ("stage_3_complete", "stage_4_complete"):
        print(
            f"[Stage 4d] Job status is '{status}' — expected stage_3_complete or "
            "stage_4_complete.  Skipping.",
            flush=True,
        )
        return job

    # ── Locate voiceover ──────────────────────────────────────────────────────
    voiceover_path = (job.get("assets") or {}).get("voiceover_path")
    if not voiceover_path:
        return mark_error(
            job,
            "No voiceover_path in job assets — run Stage 4c before Stage 4d.",
        )
    if not Path(voiceover_path).exists():
        return mark_error(
            job,
            f"Voiceover file not found on disk: {voiceover_path}",
        )

    # ── Transcribe ────────────────────────────────────────────────────────────
    print(f"[Stage 4d] Transcribing: {voiceover_path}", flush=True)
    try:
        segments = transcribe(voiceover_path, language="hi")
    except ImportError as e:
        return mark_error(job, str(e))
    except FileNotFoundError as e:
        return mark_error(job, str(e))
    except RuntimeError as e:
        # Model not downloaded — give a clear, actionable message
        return mark_error(
            job,
            f"WhisperX model error: {e}\n"
            "Use the Models page in the dashboard to download the required model.",
        )
    except Exception as e:
        return mark_error(job, f"Transcription failed: {e}")

    if not segments:
        return mark_error(job, "Transcription returned empty output — audio may be silent.")

    print(f"[Stage 4d] Got {len(segments)} segments with "
          f"{sum(len(s['words']) for s in segments)} words.", flush=True)

    # ── Save word timestamps JSON ──────────────────────────────────────────────
    job_id_str = job["job_id"]
    captions_dir = Path(ASSETS_DIR) / job_id_str / "captions"
    captions_dir.mkdir(parents=True, exist_ok=True)

    timestamps_path = str(captions_dir / "word_timestamps.json")
    with open(timestamps_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"[Stage 4d] Word timestamps saved to {timestamps_path}", flush=True)

    # ── Generate SRT ──────────────────────────────────────────────────────────
    srt_path = str(captions_dir / "captions.srt")
    srt_content = segments_to_srt(segments)
    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"[Stage 4d] SRT saved to {srt_path}", flush=True)

    # ── Generate ASS ──────────────────────────────────────────────────────────
    try:
        profile = load_niche_profile()
        style_config = profile.get("captions", {}).get("style", {})
        video_w, video_h = _video_dims(job)
        
        ass_path = str(captions_dir / "captions.ass")
        ass_content = segments_to_ass(segments, style_config, video_w, video_h)
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        print(f"[Stage 4d] ASS saved to {ass_path}", flush=True)
    except Exception as e:
        print(f"[Stage 4d] WARNING: Failed to generate ASS file: {e}", flush=True)
        ass_path = None

    # ── Update job ────────────────────────────────────────────────────────────
    if job.get("assets") is None:
        job["assets"] = {}
    job["assets"]["whisper_word_timestamps"] = segments
    job["assets"]["srt_path"] = srt_path
    if ass_path:
        job["assets"]["ass_path"] = ass_path
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_job(job)

    print(f"[Stage 4d] Complete.", flush=True)
    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Auto-pick the most recent job at a runnable status
        candidates = []
        for jf in Path(JOBS_DIR).glob("*.json"):
            try:
                j = json.loads(jf.read_text(encoding="utf-8"))
                if j.get("status") in ("stage_3_complete", "stage_4_complete"):
                    candidates.append((jf.stat().st_mtime, j["job_id"]))
            except Exception:
                continue
        if not candidates:
            print("[Stage 4d] No eligible jobs found (need stage_3_complete or stage_4_complete).")
            sys.exit(1)
        candidates.sort(reverse=True)
        _job_id = candidates[0][1]
        print(f"[Stage 4d] Auto-selected job: {_job_id}", flush=True)
    else:
        _job_id = sys.argv[1]

    run(_job_id)
