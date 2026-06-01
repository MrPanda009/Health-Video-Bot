"""WhisperX-based audio transcription with word-level timestamps."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

WHISPERX_MISSING_MSG = (
    "whisperx is not installed.\n"
    "Install it with:\n"
    "  pip install whisperx\n"
    "See https://github.com/m-bain/whisperX for full installation instructions.\n"
    "Note: whisperx requires PyTorch and ffmpeg to be installed first."
)

TORCH_MISSING_MSG = (
    "torch is not installed. Install PyTorch first:\n"
    "  pip install torch\n"
    "Then install whisperx:\n"
    "  pip install whisperx"
)


def _check_imports() -> None:
    """Raise a clear ImportError if whisperx or torch are not available."""
    try:
        import torch  # noqa: F401
    except ImportError:
        raise ImportError(TORCH_MISSING_MSG)
    try:
        import whisperx  # noqa: F401
    except ImportError:
        raise ImportError(WHISPERX_MISSING_MSG)


def transcribe(
    audio_path: str,
    language: str = "hi",
    model_size: str = "large-v2",
    device: Optional[str] = None,
) -> list[dict]:
    """
    Transcribe audio with WhisperX and return word-level timestamps.

    Args:
        audio_path:  Path to the audio file (WAV, MP3, M4A, etc.)
        language:    BCP-47 language code, e.g. "hi" for Hindi.
        model_size:  WhisperX model size — "tiny", "base", "small", "medium",
                     "large-v2", "large-v3".
        device:      "cuda" or "cpu".  Auto-detected from torch if None.

    Returns:
        List of segment dicts::

            [
              {
                "text": str,          # full sentence text
                "start": float,       # segment start in seconds
                "end": float,         # segment end in seconds
                "words": [
                  {"word": str, "start": float, "end": float}
                ]
              }
            ]

    Raises:
        ImportError:     If whisperx or torch are not installed.
        FileNotFoundError: If audio_path does not exist on disk.
        RuntimeError:    If the model cannot be loaded (not downloaded yet).
    """
    _check_imports()
    import torch
    import whisperx

    audio_path = str(audio_path)
    if not Path(audio_path).exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    print(f"[whisperx] Loading transcription model '{model_size}' on {device} ({compute_type})…",
          flush=True)
    try:
        model = whisperx.load_model(model_size, device, compute_type=compute_type)
    except Exception as e:
        raise RuntimeError(
            f"Failed to load WhisperX model '{model_size}'.\n"
            f"The model may not be downloaded yet. Use the Models page in the dashboard to download it.\n"
            f"Error: {e}"
        ) from e

    print(f"[whisperx] Transcribing {audio_path}…", flush=True)
    audio = whisperx.load_audio(audio_path)
    result = model.transcribe(audio, language=language)

    print(f"[whisperx] Aligning segments for language '{language}'…", flush=True)
    try:
        model_a, metadata = whisperx.load_align_model(language_code=language, device=device)
        result = whisperx.align(
            result["segments"],
            model_a,
            metadata,
            audio,
            device,
            return_char_alignments=False,
        )
    except Exception as e:
        # Alignment model not downloaded or language unsupported — return segments without word
        # timestamps rather than aborting, so the caller still gets usable output.
        print(
            f"[whisperx] WARNING: alignment failed ({e}).\n"
            "Returning segments without word-level timestamps.\n"
            "Download the Hindi alignment model from the Models page to enable word timestamps.",
            flush=True,
        )
        segments = []
        for seg in result.get("segments", []):
            segments.append({
                "text": seg.get("text", "").strip(),
                "start": float(seg.get("start", 0)),
                "end": float(seg.get("end", 0)),
                "words": [],
            })
        return segments

    segments = []
    for seg in result.get("segments", []):
        words = _extract_words(seg.get("words", []))
        segments.append({
            "text": seg.get("text", "").strip(),
            "start": float(seg.get("start", 0)),
            "end": float(seg.get("end", 0)),
            "words": words,
        })

    print(f"[whisperx] Done — {len(segments)} segments.", flush=True)
    return segments


def _extract_words(raw_words: list[dict]) -> list[dict]:
    """
    Clean word-timestamp list from WhisperX alignment output.

    Words that are missing start or end timestamps (WhisperX occasionally
    skips these for short filler words) are excluded from the output rather
    than causing downstream errors.
    """
    result = []
    for w in raw_words:
        if "start" not in w or "end" not in w:
            # No recoverable timestamp — skip the word entirely
            continue
        result.append({
            "word": w.get("word", "").strip(),
            "start": float(w["start"]),
            "end": float(w["end"]),
        })
    return result


def transcribe_to_file(
    audio_path: str,
    output_json_path: str,
    language: str = "hi",
) -> list[dict]:
    """
    Transcribe audio and save the result to a JSON file.

    Args:
        audio_path:        Path to the input audio file.
        output_json_path:  Destination path for the output JSON.
        language:          BCP-47 language code.

    Returns:
        The list of segment dicts (same as ``transcribe()``).
    """
    segments = transcribe(audio_path, language=language)
    out = Path(output_json_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"[whisperx] Transcript saved to {output_json_path}", flush=True)
    return segments


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python whisperx_transcriber.py <audio_path> [language] [model_size]\n"
            "\n"
            "  audio_path   Path to audio file (WAV, MP3, M4A, …)\n"
            "  language     BCP-47 code, default: hi\n"
            "  model_size   tiny|base|small|medium|large-v2|large-v3  default: large-v2\n"
        )
        sys.exit(1)

    _audio = sys.argv[1]
    _lang = sys.argv[2] if len(sys.argv) > 2 else "hi"
    _size = sys.argv[3] if len(sys.argv) > 3 else "large-v2"

    try:
        _segments = transcribe(_audio, language=_lang, model_size=_size)
    except (ImportError, FileNotFoundError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    for seg in _segments:
        print(f"\n[{seg['start']:.2f}s → {seg['end']:.2f}s]  {seg['text']}")
        for w in seg["words"]:
            print(f"  {w['word']:<20}  {w['start']:.2f}s → {w['end']:.2f}s")
