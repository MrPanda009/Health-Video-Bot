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

    # ── Update job ────────────────────────────────────────────────────────────
    if job.get("assets") is None:
        job["assets"] = {}
    job["assets"]["whisper_word_timestamps"] = segments
    job["assets"]["srt_path"] = srt_path
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
