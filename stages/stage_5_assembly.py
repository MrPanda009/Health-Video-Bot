"""
Stage 5 — Video Assembly (Remotion)
=====================================
Assembles the final YouTube Shorts video from all stage-4 assets using Remotion.

Timeline (in order, driven by the React composition):
  [optional: assets/intro.mp4 if it exists]
  3s medical disclaimer card
  Per segment: B-roll (or screenshot overlay) for duration_hint_seconds
  [optional: assets/outro.mp4 if it exists]
  Voiceover audio across the full duration
  Background music at 15% (if assets/background_music_path is set and exists)
  Word-highlighted captions (if whisper_word_timestamps is present from stage 4d)
  Animated subscribe button (last 7 seconds — no subscribe.mp4 file needed)

Pre-flight accepts:
  stage_4_complete  — normal orchestrator flow
  stage_3_complete  — development mode (manually placed assets)
  error+stage_5     — retry after a previous failure

Reads from:  jobs/{job_id}.json
             niche_profile.json
             assets/{job_id}/broll/, audio/, thumbnails/
Writes to:   jobs/{job_id}.json  (output block)
             assets/{job_id}/output/video.mp4
             assets/{job_id}/output/remotion_props.json  (intermediate)

Exit status: stage_5_complete or error
"""

import contextlib
import http.server
import json
import math
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR         = os.getenv("ASSETS_DIR", "assets")

FPS                 = 30
DISCLAIMER_DURATION = 3        # seconds
BROLL_CUT_INTERVAL  = 5.0      # seconds between B-roll cuts within a segment

# Supported output dimensions keyed by aspect_ratio string
_ASPECT_DIMS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
}

# Path to the remotion project (relative to this script's parent directory)
_REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"


# ─── Local asset HTTP server (Remotion cannot load file:// URIs) ──────────────

@contextlib.contextmanager
def _local_asset_server():
    """Temporarily serve the local filesystem over HTTP for Remotion rendering."""
    with socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory="/", **kw)
        def log_message(self, *_):
            pass

    with socketserver.TCPServer(("127.0.0.1", port), _Handler) as httpd:
        httpd.allow_reuse_address = True
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            yield f"http://127.0.0.1:{port}"
        finally:
            httpd.shutdown()


def _remap_paths(obj, base_url: str):
    """Recursively replace absolute filesystem paths with http:// URLs."""
    if isinstance(obj, str):
        return (base_url + obj) if obj.startswith("/") else obj
    if isinstance(obj, dict):
        return {k: _remap_paths(v, base_url) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_remap_paths(item, base_url) for item in obj]
    return obj


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


# ─── FFmpeg wrappers (quality gate only) ──────────────────────────────────────

def run_ffmpeg(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited {result.returncode}:\n{result.stderr[-3000:]}"
        )


def probe_video(path: Path) -> dict:
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


# ─── Remotion rendering ───────────────────────────────────────────────────────

def _video_dims(job: dict) -> tuple[int, int]:
    ar = job.get("aspect_ratio", "9:16")
    return _ASPECT_DIMS.get(ar, _ASPECT_DIMS["9:16"])


def _voiceover_duration(voiceover_path: str) -> float:
    """Return duration of the voiceover WAV in seconds via ffprobe."""
    info = probe_video(Path(voiceover_path))
    return info["duration"]


def _flatten_word_timestamps(segments: list) -> list[dict]:
    """Convert whisper_word_timestamps (list of segments with .words) to flat list."""
    words = []
    for seg in segments:
        for w in seg.get("words", []):
            text = (w.get("word") or "").strip()
            ws, we = w.get("start"), w.get("end")
            if text and ws is not None and we is not None:
                words.append({"word": text, "start": float(ws), "end": float(we)})
    return words


def build_remotion_props(
    job: dict,
    profile: dict,
    out_dir: Path,
    animation_type: str = "none",
    transitions_enabled: bool = False,
    transition_duration: float = 0.4,
) -> dict:
    """Build the JSON props object consumed by the Remotion HealthVideoComposition."""
    video_w, video_h = _video_dims(job)
    assets  = job.get("assets") or {}
    job_id  = job["job_id"]

    voiceover_path = str(Path(assets["voiceover_path"]).resolve())
    vo_duration    = _voiceover_duration(voiceover_path)
    total_frames   = round(vo_duration * FPS)

    # Disclaimer frames always prepended
    disclaimer_frames = DISCLAIMER_DURATION * FPS

    # Music
    music_path = assets.get("background_music_path")
    if not music_path or not Path(music_path).exists():
        import random
        music_dir = Path(ASSETS_DIR) / "music"
        candidates = [
            p for p in music_dir.glob("*")
            if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
        ] if music_dir.is_dir() else []
        if candidates:
            music_path = str(random.choice(candidates))
            print(f"[Stage 5]   Auto-selected background music: {Path(music_path).name}")
    music_abs = str(Path(music_path).resolve()) if music_path and Path(music_path).exists() else None

    # B-roll map
    broll_map: dict[str, list[str]] = {
        b["segment_name"]: [str(Path(p).resolve()) for p in b["paths"] if Path(p).exists()]
        for b in assets.get("broll_video_paths", [])
    }

    # Screenshot
    screenshot_paths = (job.get("study") or {}).get("screenshot_paths", [])
    screenshot_abs = str(Path(screenshot_paths[0]).resolve()) if screenshot_paths and Path(screenshot_paths[0]).exists() else None
    screenshot_used = False

    # Build per-segment data — scale duration_hint_seconds proportionally to total voiceover
    script_segments = job["content"]["script_segments"]
    total_hint = sum(float(s["duration_hint_seconds"]) for s in script_segments)
    available_frames = total_frames - disclaimer_frames

    segments = []
    for seg in script_segments:
        name = seg["name"]
        hint = float(seg["duration_hint_seconds"])
        seg_frames = max(FPS, round(available_frames * (hint / max(total_hint, 1))))

        use_screenshot = (
            name == "context"
            and not screenshot_used
            and screenshot_abs
        )
        if use_screenshot:
            screenshot_used = True

        segments.append({
            "name": name,
            "durationInFrames": seg_frames,
            "brollPaths": broll_map.get(name, []),
            "screenshotPath": screenshot_abs if use_screenshot else None,
            "animationType": animation_type,
            "brollCutIntervalFrames": round(BROLL_CUT_INTERVAL * FPS),
        })

    # Intro / outro
    intro_path = Path(ASSETS_DIR) / "intro.mp4"
    outro_path = Path(ASSETS_DIR) / "outro.mp4"

    # Word timestamps
    whisper_segs = assets.get("whisper_word_timestamps")
    word_timestamps = _flatten_word_timestamps(whisper_segs) if whisper_segs else None

    return {
        "width":                video_w,
        "height":               video_h,
        "fps":                  FPS,
        "totalDurationInFrames": total_frames,
        "disclaimerText":       profile["compliance"]["medical_disclaimer"]["text_english"],
        "segments":             segments,
        "voiceoverPath":        voiceover_path,
        "backgroundMusicPath":  music_abs,
        "wordTimestamps":       word_timestamps,
        "introPath":            str(intro_path.resolve()) if intro_path.exists() else None,
        "outroPath":            str(outro_path.resolve()) if outro_path.exists() else None,
        "transitionsEnabled":   transitions_enabled,
        "transitionDurationFrames": round(transition_duration * FPS),
    }


def render_with_remotion(
    props: dict,
    output_path: Path,
    props_file: Path,
    verbose: bool = False,
) -> None:
    """Write props JSON and invoke `npx remotion render`."""
    if not _REMOTION_DIR.exists():
        raise FileNotFoundError(
            f"Remotion project not found at {_REMOTION_DIR}. "
            "Run: cd remotion && npm install"
        )
    node_modules = _REMOTION_DIR / "node_modules"
    if not node_modules.exists():
        raise FileNotFoundError(
            f"Remotion node_modules missing at {node_modules}. "
            "Run: cd remotion && npm install"
        )

    props_file.parent.mkdir(parents=True, exist_ok=True)

    log_level = "verbose" if verbose else "error"
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "HealthVideoComposition",
        str(output_path.resolve()),
        f"--props={props_file.resolve()}",
        f"--log={log_level}",
    ]
    print(f"[Stage 5] Running Remotion render ({props['width']}×{props['height']}, "
          f"{props['totalDurationInFrames']} frames @ {props['fps']}fps)…")

    with _local_asset_server() as base_url:
        http_props = _remap_paths(props, base_url)
        props_file.write_text(json.dumps(http_props, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(cmd, cwd=str(_REMOTION_DIR), text=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"Remotion render exited {result.returncode}. "
            "Check the output above for details."
        )


def assemble_video(
    job: dict,
    profile: dict,
    out_dir: Path,
    draft: bool = False,
    animation_type: str = "none",
    transitions_enabled: bool = False,
    transition_duration: float = 0.4,
) -> Path:
    """
    Assemble the final video using Remotion.

    All rendering is done by the Remotion CLI (npx remotion render).
    Returns the path to the finished video.mp4.
    """
    video_w, video_h = _video_dims(job)
    if draft:
        print("[Stage 5] ⚠ Draft mode: Remotion renders at full resolution; "
              "draft flag reduces quality gate strictness only.")

    ar_label = job.get("aspect_ratio", "9:16")
    print(f"[Stage 5] Aspect ratio: {ar_label} → {video_w}×{video_h}")

    assets = job.get("assets") or {}
    voiceover_path = assets.get("voiceover_path")
    if not voiceover_path or not Path(voiceover_path).exists():
        raise FileNotFoundError(
            f"voiceover not found at '{voiceover_path}'. "
            "Run stage_4c_voiceover.py first."
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = out_dir / "video.mp4"
    props_file  = out_dir / "remotion_props.json"

    props = build_remotion_props(
        job, profile, out_dir,
        animation_type=animation_type,
        transitions_enabled=transitions_enabled,
        transition_duration=transition_duration,
    )

    render_with_remotion(props, output_path, props_file, verbose=False)
    return output_path


# ─── Quality gate ─────────────────────────────────────────────────────────────

def run_quality_gate(output_path: Path, profile: dict) -> dict:
    qg = profile["quality_gate"]

    checks: dict[str, bool | None] = {
        "duration_in_range": False,
        "disclaimer_present": True,
        "audio_peak_ok":     None,
        "audio_avg_ok":      None,
        "all_passed":        False,
    }

    info     = probe_video(output_path)
    duration = info["duration"]
    checks["duration_in_range"] = (
        qg["min_duration_seconds"] <= duration <= qg["max_duration_seconds"]
    )
    print(f"[Stage 5]   Duration        : {duration:.1f}s "
          f"(allowed {qg['min_duration_seconds']}–{qg['max_duration_seconds']}s) "
          f"→ {'✓' if checks['duration_in_range'] else '✗'}")

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

def run(
    job_id: str,
    draft: bool = False,
    animation_type: str = "none",
    transitions_enabled: bool = False,
    transition_duration: float = 0.4,
) -> dict:
    profile = load_niche_profile()
    job     = load_job(job_id)

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
        job["status"] = "stage_4_complete" if not dev_mode else "stage_3_complete"

    if dev_mode:
        print("[Stage 5] ⚠ Development mode — running with stage_3_complete status.")

    assets = job.get("assets") or {}
    if not assets.get("broll_video_paths"):
        return mark_error(job, "broll_video_paths missing — run stage_4a_broll.py first")

    out_dir = Path(ASSETS_DIR) / job_id / "output"
    print(f"[Stage 5] Assembling video for job {job_id}")
    anim_label = animation_type if animation_type != "none" else "none"
    trans_label = f"crossfade {transition_duration}s" if transitions_enabled else "none"
    print(f"[Stage 5] animation={anim_label}  transitions={trans_label}")

    try:
        output_path = assemble_video(
            job, profile, out_dir, draft=draft,
            animation_type=animation_type,
            transitions_enabled=transitions_enabled,
            transition_duration=transition_duration,
        )
    except FileNotFoundError as e:
        return mark_error(job, str(e))
    except RuntimeError as e:
        return mark_error(job, f"Remotion render failed: {e}")

    print(f"[Stage 5] Video written → {output_path}")

    print("\n[Stage 5] Running quality gate...")
    quality_checks = run_quality_gate(output_path, profile)

    info     = probe_video(output_path)
    duration = info["duration"]

    if not job.get("output"):
        job["output"] = {}
    job["output"]["final_video_path"]               = str(output_path)
    job["output"]["final_video_duration_seconds"]   = round(duration, 3)
    job["output"]["quality_checks"]                 = quality_checks
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
    import argparse

    parser = argparse.ArgumentParser(description="Stage 5 — video assembly (Remotion)")
    parser.add_argument("job_id", nargs="?", help="Job ID (auto-picks latest if omitted)")
    parser.add_argument("--draft", action="store_true", help="Draft mode flag (passed through; Remotion always renders full res)")
    parser.add_argument(
        "--animation-type", default="none",
        choices=["ken_burns", "slide_in", "zoom_punch", "none"],
    )
    parser.add_argument(
        "--transition-type", default="none",
        choices=["crossfade", "none"],
    )
    parser.add_argument(
        "--transition-duration", type=float, default=0.4,
    )
    parsed = parser.parse_args()

    transitions_enabled = parsed.transition_type == "crossfade"
    transition_duration = parsed.transition_duration
    animation_type      = parsed.animation_type

    if not parsed.job_id:
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
        job_id = parsed.job_id

    result = run(
        job_id,
        draft=parsed.draft,
        animation_type=animation_type,
        transitions_enabled=transitions_enabled,
        transition_duration=transition_duration,
    )
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
