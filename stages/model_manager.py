"""
Model manager CLI — checks download status and triggers model downloads.

Called by the frontend API routes to:
  - Report which WhisperX models are present in the HuggingFace cache.
  - Download missing models (streams progress to stdout for SSE relay).

Usage:
  python stages/model_manager.py status
  python stages/model_manager.py download <model_id>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ─── Model catalogue ──────────────────────────────────────────────────────────

TRANSCRIPTION_MODELS: list[dict] = [
    {
        "id": "large-v2",
        "hf_repo": "Systran/faster-whisper-large-v2",
        "label": "large-v2",
        "type": "transcription",
        "size_gb": 3.1,
        "description": "Best accuracy — recommended for production",
    },
    {
        "id": "large-v3",
        "hf_repo": "Systran/faster-whisper-large-v3",
        "label": "large-v3",
        "type": "transcription",
        "size_gb": 3.1,
        "description": "Latest large model with slight accuracy improvements",
    },
    {
        "id": "medium",
        "hf_repo": "Systran/faster-whisper-medium",
        "label": "medium",
        "type": "transcription",
        "size_gb": 1.5,
        "description": "Good balance of speed and accuracy",
    },
    {
        "id": "small",
        "hf_repo": "Systran/faster-whisper-small",
        "label": "small",
        "type": "transcription",
        "size_gb": 0.5,
        "description": "Fast and lightweight — suitable for testing",
    },
]

ALIGNMENT_MODELS: list[dict] = [
    {
        "id": "align-hi",
        "hf_repo": "theainerd/Wav2Vec2-large-xlsr-hindi",
        "label": "Hindi Alignment",
        "type": "alignment",
        "language": "hi",
        "size_gb": 1.2,
        "description": "Required for word-level timestamps in Hindi (Stage 4d)",
    },
]

ALL_MODELS: list[dict] = TRANSCRIPTION_MODELS + ALIGNMENT_MODELS


# ─── Cache helpers ────────────────────────────────────────────────────────────

def _hf_cache_dir() -> Path:
    return Path(os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface/hub")))


def _is_downloaded(hf_repo: str) -> bool:
    """Return True if the model's snapshots directory exists and is non-empty."""
    snapshots = _hf_cache_dir() / ("models--" + hf_repo.replace("/", "--")) / "snapshots"
    if not snapshots.exists():
        return False
    try:
        return any(snapshots.iterdir())
    except PermissionError:
        return False


def _whisperx_installed() -> bool:
    try:
        import whisperx  # noqa: F401
        return True
    except ImportError:
        return False


# ─── Commands ─────────────────────────────────────────────────────────────────

def cmd_status() -> None:
    """Print model status as a single JSON object to stdout."""
    whisperx_ok = _whisperx_installed()
    models = []
    for m in ALL_MODELS:
        entry = dict(m)
        entry["downloaded"] = _is_downloaded(m["hf_repo"])
        models.append(entry)
    print(json.dumps({"models": models, "whisperx_installed": whisperx_ok}))


def cmd_download(model_id: str) -> None:
    """
    Download a model and stream human-readable progress to stdout.

    Exits with code 1 on failure so the frontend SSE route can detect errors.
    """
    model = next((m for m in ALL_MODELS if m["id"] == model_id), None)
    if model is None:
        print(f"[model_manager] ERROR: unknown model ID '{model_id}'", flush=True)
        print(f"Known IDs: {[m['id'] for m in ALL_MODELS]}", flush=True)
        sys.exit(1)

    if not _whisperx_installed():
        print(
            "[model_manager] ERROR: whisperx is not installed.\n"
            "Install it first:\n"
            "  pip install whisperx\n"
            "See https://github.com/m-bain/whisperX for instructions.",
            flush=True,
        )
        sys.exit(1)

    print(f"[model_manager] Downloading: {model['label']}", flush=True)
    print(f"[model_manager] HuggingFace repo: {model['hf_repo']}", flush=True)
    print(f"[model_manager] Estimated size: ~{model['size_gb']} GB", flush=True)
    print(f"[model_manager] This may take several minutes…", flush=True)

    if model["type"] == "transcription":
        _download_transcription(model)
    else:
        _download_alignment(model)

    print(f"[model_manager] ✓ Download complete: {model['label']}", flush=True)


def _download_transcription(model: dict) -> None:
    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    size = model["id"]

    print(f"[model_manager] Loading '{size}' on {device} ({compute_type}) to trigger download…",
          flush=True)
    try:
        m = whisperx.load_model(size, device, compute_type=compute_type)
        del m
        print(f"[model_manager] '{size}' loaded and cached successfully.", flush=True)
    except Exception as e:
        print(f"[model_manager] ERROR: failed to download '{size}': {e}", flush=True)
        sys.exit(1)


def _download_alignment(model: dict) -> None:
    import torch
    import whisperx

    device = "cuda" if torch.cuda.is_available() else "cpu"
    lang = model.get("language", "hi")

    print(f"[model_manager] Loading alignment model for language '{lang}'…", flush=True)
    try:
        m, _ = whisperx.load_align_model(language_code=lang, device=device)
        del m
        print(f"[model_manager] Alignment model for '{lang}' loaded and cached.", flush=True)
    except Exception as e:
        print(f"[model_manager] ERROR: failed to download alignment model: {e}", flush=True)
        sys.exit(1)


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python stages/model_manager.py <status|download> [model_id]")
        sys.exit(1)

    _command = sys.argv[1]

    if _command == "status":
        cmd_status()
    elif _command == "download":
        if len(sys.argv) < 3:
            print("Usage: python stages/model_manager.py download <model_id>")
            sys.exit(1)
        cmd_download(sys.argv[2])
    else:
        print(f"Unknown command: {_command}.  Expected: status | download")
        sys.exit(1)
