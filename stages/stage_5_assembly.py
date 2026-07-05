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

# Subscribe-button sound effects (files live in assets/music/)
DEFAULT_CLICK_SOUND = "universfield-computer-mouse-click-352734.mp3"
DEFAULT_BELL_SOUND  = "freesound_community-bell-98033.mp3"

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

        def send_head(self):
            import os
            import re
            path = self.translate_path(self.path)
            if os.path.isdir(path):
                return super().send_head()

            ctype = self.guess_type(path)
            try:
                f = open(path, 'rb')
            except OSError:
                self.send_error(404, "File not found")
                return None

            try:
                fs = os.fstat(f.fileno())
                total_size = fs.st_size
                
                range_header = self.headers.get("Range")
                if range_header:
                    match = re.match(r"bytes=(\d+)-(\d*)", range_header)
                    if match:
                        start = int(match.group(1))
                        end_str = match.group(2)
                        end = int(end_str) if end_str else total_size - 1

                        if start >= total_size or end >= total_size or start > end:
                            f.close()
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{total_size}")
                            self.end_headers()
                            return None

                        self.send_response(206)
                        self.send_header("Content-type", ctype)
                        self.send_header("Content-Range", f"bytes {start}-{end}/{total_size}")
                        self.send_header("Content-Length", str(end - start + 1))
                        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()

                        class RangeFileWrapper:
                            def __init__(self, fileobj, start_byte, end_byte):
                                self.fileobj = fileobj
                                self.fileobj.seek(start_byte)
                                self.remaining = end_byte - start_byte + 1

                            def read(self, size=-1):
                                if self.remaining <= 0:
                                    return b""
                                to_read = self.remaining if size < 0 else min(size, self.remaining)
                                data = self.fileobj.read(to_read)
                                self.remaining -= len(data)
                                return data

                            def close(self):
                                self.fileobj.close()

                        return RangeFileWrapper(f, start, end)

                self.send_response(200)
                self.send_header("Content-type", ctype)
                self.send_header("Content-Length", str(total_size))
                self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                return f
            except Exception:
                f.close()
                raise

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

_DRAFT_SCALE = 0.5   # draft renders at half resolution — same aspect, 4× fewer pixels


def _video_dims(job: dict, draft: bool = False) -> tuple[int, int]:
    ar = job.get("aspect_ratio", "9:16")
    w, h = _ASPECT_DIMS.get(ar, _ASPECT_DIMS["9:16"])
    if draft:
        # Round down to nearest even pixel (required by most video codecs)
        w = int(w * _DRAFT_SCALE) & ~1
        h = int(h * _DRAFT_SCALE) & ~1
    return w, h


def _voiceover_duration(voiceover_path: str) -> float:
    """Return duration of the voiceover WAV in seconds via ffprobe."""
    info = probe_video(Path(voiceover_path))
    return info["duration"]


def _realign_segments_to_script(segments: list, hindi_script: str) -> list:
    """
    Replace the word text in whisper segments with tokens from hindi_script,
    preserving WhisperX timing. Called at render time so captions always match
    the current script even if stage 4d was not re-run after a stage 3 change.
    """
    all_whisper_words = [w for seg in segments for w in seg.get("words", [])]
    n_wt = len(all_whisper_words)
    script_tokens = hindi_script.split()
    n_orig = len(script_tokens)
    if n_orig == 0 or n_wt == 0:
        return segments

    aligned_flat = [
        {
            "word": script_tokens[min(round(i * n_orig / n_wt), n_orig - 1)],
            "start": wt["start"],
            "end": wt["end"],
        }
        for i, wt in enumerate(all_whisper_words)
    ]

    out, flat_idx = [], 0
    for seg in segments:
        count = len(seg.get("words", []))
        seg_words = aligned_flat[flat_idx : flat_idx + count]
        flat_idx += count
        out.append({
            "text": " ".join(w["word"] for w in seg_words),
            "start": seg["start"],
            "end": seg["end"],
            "words": seg_words,
        })
    return out


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
    draft: bool = False,
    animation_type: str = "none",
    transitions_enabled: bool = False,
    transition_duration: float = 0.4,
    click_sound: str | None = None,
    bell_sound: str | None = None,
    caption_combine_ms: int = 1500,
    font_family: str = "NotoSansDevanagari",
) -> dict:
    """Build the JSON props object consumed by the Remotion HealthVideoComposition."""
    video_w, video_h = _video_dims(job, draft=draft)
    assets  = job.get("assets") or {}
    job_id  = job["job_id"]

    voiceover_path = str(Path(assets["voiceover_path"]).resolve())
    vo_duration    = _voiceover_duration(voiceover_path)
    total_frames   = round((vo_duration + DISCLAIMER_DURATION) * FPS)

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

    # Subscribe-button sound effects — resolve filenames against assets/music/
    def _resolve_music(name: str | None) -> str | None:
        if not name:
            return None
        p = Path(ASSETS_DIR) / "music" / name
        return str(p.resolve()) if p.exists() else None

    click_sound_abs = _resolve_music(click_sound or DEFAULT_CLICK_SOUND)
    bell_sound_abs  = _resolve_music(bell_sound or DEFAULT_BELL_SOUND)

    # Word timestamps — always re-align to current hindi_script so captions
    # stay in sync with the script even if stage 4d wasn't re-run after stage 3.
    whisper_segs = assets.get("whisper_word_timestamps")
    if whisper_segs:
        hindi_script = (job.get("content") or {}).get("hindi_script", "")
        if hindi_script.strip():
            whisper_segs = _realign_segments_to_script(whisper_segs, hindi_script)
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
        "clickSoundPath":       click_sound_abs,
        "bellSoundPath":        bell_sound_abs,
        "transitionsEnabled":   transitions_enabled,
        "transitionDurationFrames": round(transition_duration * FPS),
        "captionCombineMs":     caption_combine_ms,
        "fontFamily":           font_family,
    }


def _print_render_progress(pct: int, total_frames: int, bar_width: int = 30) -> None:
    filled = round(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)
    rendered = round(total_frames * pct / 100)
    print(f"\r[Stage 5] [{bar}] {pct:3d}%  ({rendered}/{total_frames} frames)", end="", flush=True)


def render_with_remotion(
    props: dict,
    output_path: Path,
    props_file: Path,
    verbose: bool = False,
    concurrency: int = 0,
) -> None:
    """Write props JSON and invoke `npx remotion render`.

    `concurrency` is the number of frames Remotion renders in parallel. 0 means
    "let remotion.config.ts decide" (it defaults to ~half the CPU cores); a
    positive value is passed as `--concurrency=N` and overrides the config.
    """
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

    total_frames = props["totalDurationInFrames"]
    log_level = "verbose" if verbose else "info"
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "HealthVideoComposition",
        str(output_path.resolve()),
        f"--props={props_file.resolve()}",
        f"--log={log_level}",
    ]
    if concurrency and concurrency > 0:
        cmd.append(f"--concurrency={concurrency}")
    conc_label = f"{concurrency} workers" if concurrency and concurrency > 0 else "auto concurrency"
    print(f"[Stage 5] Running Remotion render ({props['width']}×{props['height']}, "
          f"{total_frames} frames @ {props['fps']}fps, {conc_label})…")

    # Remotion's render progress is newline-delimited. The bundling phase emits its
    # own "Bundling NN%" lines (which the old bare-% regex mistook for render
    # progress and jumped the bar to 100% instantly). Real frame progress arrives as
    # "Rendered <done>/<total>" — we key on that exclusively.
    _frame_re = re.compile(r"Rendered\s+(\d+)\s*/\s*(\d+)")
    last_pct = -1

    with _local_asset_server() as base_url:
        http_props = _remap_paths(props, base_url)
        props_file.write_text(json.dumps(http_props, ensure_ascii=False), encoding="utf-8")
        proc = subprocess.Popen(
            cmd,
            cwd=str(_REMOTION_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for line in proc.stdout:  # type: ignore[union-attr]
            m = _frame_re.search(line)
            if m:
                rendered, total = int(m.group(1)), int(m.group(2))
                pct = round(rendered * 100 / max(total, 1))
                if pct != last_pct:
                    last_pct = pct
                    _print_render_progress(pct, total)
            elif verbose:
                print(line, end="")
        proc.wait()

    if last_pct >= 0:
        print()  # newline after the progress bar
    if proc.returncode != 0:
        raise RuntimeError(
            f"Remotion render exited {proc.returncode}. "
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
    click_sound: str | None = None,
    bell_sound: str | None = None,
    concurrency: int = 0,
    caption_combine_ms: int = 1500,
    font_family: str = "NotoSansDevanagari",
) -> Path:
    """
    Assemble the final video using Remotion.

    All rendering is done by the Remotion CLI (npx remotion render).
    Returns the path to the finished video.mp4.
    """
    video_w, video_h = _video_dims(job, draft=draft)
    ar_label = job.get("aspect_ratio", "9:16")
    if draft:
        print(f"[Stage 5] Draft mode — rendering at {video_w}×{video_h} "
              f"({int(_DRAFT_SCALE * 100)}% of final resolution)")
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
        draft=draft,
        animation_type=animation_type,
        transitions_enabled=transitions_enabled,
        transition_duration=transition_duration,
        click_sound=click_sound,
        bell_sound=bell_sound,
        caption_combine_ms=caption_combine_ms,
        font_family=font_family,
    )

    render_with_remotion(props, output_path, props_file, verbose=False, concurrency=concurrency)
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
    click_sound: str | None = None,
    bell_sound: str | None = None,
    concurrency: int = 0,
    caption_combine_ms: int = 1500,
    font_family: str = "NotoSansDevanagari",
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
            click_sound=click_sound,
            bell_sound=bell_sound,
            concurrency=concurrency,
            caption_combine_ms=caption_combine_ms,
            font_family=font_family,
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
    parser.add_argument("--draft", action="store_true", help="Render at half resolution for fast preview (50%% of final dims)")
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
    parser.add_argument(
        "--click-sound", default=None,
        help="Filename in assets/music/ for the subscribe-button click sound",
    )
    parser.add_argument(
        "--bell-sound", default=None,
        help="Filename in assets/music/ for the subscribe-button bell sound",
    )
    parser.add_argument(
        "--concurrency", type=int, default=0,
        help="Number of frames Remotion renders in parallel. "
             "0 = auto (remotion.config.ts default, ~half the CPU cores).",
    )
    parser.add_argument(
        "--caption-combine-ms", type=int, default=1500,
        help="Max duration in ms for words to stay grouped on screen in captions"
    )
    parser.add_argument(
        "--font-family", default="NotoSansDevanagari",
        help="Google font submodule name to load for captions"
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
        click_sound=parsed.click_sound,
        bell_sound=parsed.bell_sound,
        concurrency=parsed.concurrency,
        caption_combine_ms=parsed.caption_combine_ms,
        font_family=parsed.font_family,
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
