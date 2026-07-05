"""
Stage 4c — Voiceover Generation
==================================
Responsibilities:
  1. Read hindi_script from job content{} block (produced by Stage 3)
  2. Split into ≤500-char chunks at sentence boundaries if needed
  3. Call Sarvam AI TTS for each chunk (retry once on failure)
  4. Concatenate multi-chunk WAVs with pydub
  5. Save final WAV to assets/{job_id}/audio/voiceover.wav
  6. Measure and record actual duration

Does NOT change job status — the orchestrator sets stage_4_complete after all
stage-4 sub-stages finish. Sets status "error" only on unrecoverable failures.

Reads from:  jobs/{job_id}.json  (content.hindi_script must be present)
             niche_profile.json  (audio config — voice, model, pace, pitch, loudness)
Writes to:   jobs/{job_id}.json  (assets.voiceover_path, assets.voiceover_duration_seconds)
             assets/{job_id}/audio/voiceover.wav
"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydub import AudioSegment

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR         = os.getenv("ASSETS_DIR", "assets")

SARVAM_TTS_URL  = "https://api.sarvam.ai/text-to-speech"
SARVAM_CHUNK_MAX = 250  # Prevent bulbul:v3 API truncation on mixed scripts / symbols


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
    job["error"]  = {"stage": "stage_4c", "message": message, "retries": 0}
    save_job(job)
    print(f"[Stage 4c] ERROR: {message}")
    return job


# ─── Text chunking ────────────────────────────────────────────────────────────

def split_into_chunks(text: str, max_chars: int = SARVAM_CHUNK_MAX) -> list[str]:
    """
    Split Hindi script into chunks ≤ max_chars at sentence boundaries.
    Sentence boundaries: । (Devanagari danda), . ! ? followed by whitespace.
    Falls back to word boundaries for oversized single sentences.
    """
    if len(text) <= max_chars:
        return [text]

    # Split on sentence-ending punctuation, keeping the delimiter attached
    sentences = re.split(r'(?<=[।.!?])\s+', text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = (current + " " + sentence).strip() if current else sentence
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            # Single sentence too long — split at word boundary
            if len(sentence) > max_chars:
                words = sentence.split()
                current = ""
                for word in words:
                    probe = (current + " " + word).strip() if current else word
                    if len(probe) <= max_chars:
                        current = probe
                    else:
                        if current:
                            chunks.append(current)
                        current = word
            else:
                current = sentence

    if current:
        chunks.append(current)

    return chunks if chunks else [text]


# ─── Sarvam TTS API ───────────────────────────────────────────────────────────

def call_sarvam_tts(text: str, profile: dict) -> bytes:
    """
    Call Sarvam AI TTS for a single text chunk.
    Retries once after 5s on failure.
    Returns raw WAV bytes.
    Raises on both attempts failing.
    """
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY not set")

    audio_cfg = profile["audio"]
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    model = audio_cfg.get("sarvam_model", "bulbul:v1")
    payload = {
        "inputs":               [text],
        "target_language_code": "hi-IN",
        "speaker":              audio_cfg["sarvam_voice_id"],
        "pace":                 audio_cfg.get("speaking_rate", 1.0),
        "model":                model,
    }
    # bulbul:v3 does not support pitch/loudness
    if not model.endswith(":v3"):
        payload["pitch"]    = audio_cfg.get("pitch", 0)
        payload["loudness"] = audio_cfg.get("loudness", 1.5)

    last_exc = None
    for attempt in range(1, 3):
        try:
            print(f"[Stage 4c]   TTS attempt {attempt} ({len(text)} chars)...")
            resp = requests.post(SARVAM_TTS_URL, headers=headers, json=payload, timeout=60)
            if not resp.ok:
                print(f"[Stage 4c]   TTS response body: {resp.text[:500]}")
            resp.raise_for_status()
            data = resp.json()
            if not data.get("audios"):
                raise ValueError(f"No 'audios' in response: {list(data.keys())}")
            return base64.b64decode(data["audios"][0])
        except Exception as e:
            last_exc = e
            print(f"[Stage 4c]   TTS attempt {attempt} failed: {e}")
            if attempt < 2:
                time.sleep(5)

    raise last_exc


# ─── WAV helpers ─────────────────────────────────────────────────────────────

def wav_duration(wav_path: Path) -> float:
    """Return duration in seconds of a WAV file."""
    audio = AudioSegment.from_wav(str(wav_path))
    return len(audio) / 1000.0


def concatenate_wavs(wav_paths: list[Path], output_path: Path) -> None:
    """Concatenate multiple WAV files into one, preserving sample rate of the first."""
    combined = AudioSegment.from_wav(str(wav_paths[0]))
    for p in wav_paths[1:]:
        combined += AudioSegment.from_wav(str(p))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="wav")


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 4c runner.

    Splits the hindi_script into Sarvam-sized chunks, synthesises each, concatenates,
    and writes the final WAV + its duration into job assets{}.

    Args:
        job_id: UUID of the job (must be at stage_3_complete or previously errored here).

    Returns:
        Updated job dict. Status unchanged on success; "error" on failure.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight ───────────────────────────────────────────────────────────
    errored_here = job["status"] == "error" and job.get("error", {}).get("stage") == "stage_4c"
    if job["status"] != "stage_3_complete" and not errored_here:
        return mark_error(job, f"Job status is '{job['status']}' — expected 'stage_3_complete'")
    job.pop("error", None)
    job["status"] = "stage_3_complete"  # restore in case we're retrying a previous error

    script = job.get("content", {}).get("hindi_script", "").strip()
    if not script:
        return mark_error(job, "hindi_script missing or empty in content{} — re-run Stage 3")

    if not os.getenv("SARVAM_API_KEY"):
        return mark_error(job, "SARVAM_API_KEY not set")

    audio_dir   = Path(ASSETS_DIR) / job_id / "audio"
    output_path = audio_dir / "voiceover.wav"
    audio_dir.mkdir(parents=True, exist_ok=True)

    # ── Split into chunks ────────────────────────────────────────────────────
    chunks = split_into_chunks(script, SARVAM_CHUNK_MAX)
    print(f"[Stage 4c] Script: {len(script)} chars → {len(chunks)} chunk(s)")
    for i, c in enumerate(chunks):
        print(f"[Stage 4c]   Chunk {i+1}: {len(c)} chars")

    # ── Synthesise each chunk ────────────────────────────────────────────────
    chunk_paths: list[Path] = []
    for i, chunk_text in enumerate(chunks):
        chunk_path = audio_dir / f"voiceover_chunk_{i}.wav"
        try:
            wav_bytes = call_sarvam_tts(chunk_text, profile)
            chunk_path.write_bytes(wav_bytes)
            chunk_paths.append(chunk_path)
            print(f"[Stage 4c]   ✓ Chunk {i+1} saved ({len(wav_bytes):,} bytes)")
        except Exception as e:
            return mark_error(job, f"TTS failed for chunk {i+1}/{len(chunks)}: {e}")

    # ── Concatenate (or just rename if single chunk) ──────────────────────────
    if len(chunk_paths) == 1:
        chunk_paths[0].rename(output_path)
    else:
        print(f"[Stage 4c] Concatenating {len(chunk_paths)} WAV chunks...")
        concatenate_wavs(chunk_paths, output_path)
        for p in chunk_paths:
            p.unlink(missing_ok=True)

    # ── Measure duration ──────────────────────────────────────────────────────
    duration = wav_duration(output_path)
    print(f"[Stage 4c] Voiceover duration: {duration:.1f}s")

    # ── Persist to job ────────────────────────────────────────────────────────
    if not job.get("assets"):
        job["assets"] = {}
    job["assets"]["voiceover_path"]              = str(output_path)
    job["assets"]["voiceover_duration_seconds"]  = round(duration, 3)
    save_job(job)

    print(f"\n[Stage 4c] ✓ Complete")
    print(f"  Output  : {output_path}")
    print(f"  Duration: {duration:.1f}s")

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_4c_voiceover.py <job_id>
    #   python stage_4c_voiceover.py          ← auto-picks most recent stage_3_complete job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                ready     = j.get("status") == "stage_3_complete"
                retryable = j.get("status") == "error" and j.get("error", {}).get("stage") == "stage_4c"
                if ready or retryable:
                    candidates.append((jf.stat().st_mtime, j["job_id"], j.get("status")))
            except Exception:
                continue

        if not candidates:
            print("No stage_3_complete or stage_4c error jobs found. Run stage_3_content_generation.py first.")
            sys.exit(1)

        candidates.sort(reverse=True)
        _, job_id, picked_status = candidates[0]
        label = "retrying errored" if picked_status == "error" else "most recent"
        print(f"[Stage 4c] No job_id provided — using {label}: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result.get("error"):
        print(f"Error        : {result['error']['message']}")
    else:
        print(f"Voiceover    : {result['assets']['voiceover_path']}")
        print(f"Duration     : {result['assets']['voiceover_duration_seconds']}s")
        print(f"Job saved to : jobs/{result['job_id']}.json")
