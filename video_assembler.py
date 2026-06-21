"""
Video assembler — overlays B-roll clips from an EDL onto a base A-roll video.

Reads an EDL JSON produced by edit_decision.generate_edl() and a base video
(talking-head / A-roll footage), replaces the video track at each EDL window
with the matched B-roll clip, and writes the result to disk using Remotion.

The base video's audio is always kept intact — B-roll clips contribute video
only, never audio. Segments with no matching clip show the base video unchanged.

Requires the Remotion project to be installed:
  cd remotion && npm install

EDL entry fields (all optional except timeline_start/timeline_end):
  clip_path         : str   — path to B-roll file (video or image)
  animation_type    : str   — "ken_burns" (default for images), "slide_in",
                              "zoom_punch", or None (video clips default to None)
  transition_to_next: str   — "crossfade" or None (informational; Remotion handles transitions)
"""

from __future__ import annotations

import contextlib
import http.server
import json
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


_REMOTION_DIR = Path(__file__).resolve().parent / "remotion"


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


def _ffprobe_duration(path: str) -> float:
    """Return video duration in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr}")
    data = json.loads(result.stdout)
    return float(data.get("format", {}).get("duration", 0))


def _ffprobe_dims(path: str) -> tuple[int, int]:
    """Return (width, height) of a video via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {result.stderr}")
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise RuntimeError(f"No video stream found in {path}")


def preview_edl(edl_path: str) -> None:
    """Print a human-readable summary of an EDL to the terminal."""
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
    Overlay B-roll clips from an EDL onto a base A-roll video and render via Remotion.

    For each EDL entry with a valid ``clip_path`` the B-roll fully replaces
    the base video visually for that time window.  The base video's audio
    track is kept throughout — B-roll clips are silent in the output.

    Image files (.jpg, .png, etc.) in the EDL are animated:
      - Default animation: "ken_burns" (slow zoom)
      - Override per entry: ``animation_type`` field in EDL entry
      - Override globally: ``default_animation`` argument / --animation-type flag

    Args:
        base_video_path:     Path to the A-roll / talking-head source video.
        edl_path:            Path to the EDL JSON.
        output_path:         Destination path for the rendered video (.mp4).
        default_transition:  Transition type when not set per-entry ("crossfade" or None).
        default_animation:   Animation type for image clips when not set per-entry.
        transition_duration: Crossfade overlap in seconds (default 0.4).

    Raises:
        FileNotFoundError: If base_video_path, edl_path, or remotion/node_modules absent.
        ValueError:        If the EDL JSON is malformed.
        RuntimeError:      If ffprobe or Remotion render fails.
    """
    base_video_path = str(base_video_path)
    edl_path = str(edl_path)
    output_path = str(output_path)

    if not Path(base_video_path).exists():
        raise FileNotFoundError(f"Base video not found: {base_video_path}")
    if not Path(edl_path).exists():
        raise FileNotFoundError(f"EDL file not found: {edl_path}")
    if not (_REMOTION_DIR / "node_modules").exists():
        raise FileNotFoundError(
            f"Remotion node_modules missing at {_REMOTION_DIR}. "
            "Run: cd remotion && npm install"
        )

    # Probe base video
    base_duration = _ffprobe_duration(base_video_path)
    base_w, base_h = _ffprobe_dims(base_video_path)
    fps = 30

    print(f"[assembler] Base: {base_w}×{base_h}  {base_duration:.2f}s", flush=True)

    # Load EDL
    with open(edl_path, encoding="utf-8") as f:
        try:
            raw_edl = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed EDL JSON in {edl_path}: {exc}") from exc

    if not isinstance(raw_edl, list):
        raise ValueError(f"EDL must be a JSON array, got {type(raw_edl).__name__}")

    # Build entries for Remotion EDLComposition
    entries = []
    for entry in raw_edl:
        t_start = float(entry.get("timeline_start", 0))
        t_end = float(entry.get("timeline_end", 0))
        clip_path = entry.get("clip_path")
        anim = entry.get("animation_type", default_animation)
        trans = entry.get("transition_to_next", default_transition)

        clip_abs = str(Path(clip_path).resolve()) if clip_path and Path(clip_path).exists() else None
        entries.append({
            "timelineStart":   t_start,
            "timelineEnd":     min(t_end, base_duration),
            "clipPath":        clip_abs,
            "animationType":   anim,
            "transitionToNext": trans,
        })

    props = {
        "baseVideoPath":       str(Path(base_video_path).resolve()),
        "baseDurationSeconds": base_duration,
        "fps":                 fps,
        "entries":             entries,
    }

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        props_path = tmp.name

    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "EDLComposition",
        str(Path(output_path).resolve()),
        f"--props={props_path}",
        "--log=error",
    ]
    print(f"[assembler] Rendering → {output_path}", flush=True)

    with _local_asset_server() as base_url:
        http_props = _remap_paths(props, base_url)
        with open(props_path, "w", encoding="utf-8") as f:
            json.dump(http_props, f, ensure_ascii=False)
        result = subprocess.run(cmd, cwd=str(_REMOTION_DIR), text=True)

    Path(props_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(
            f"Remotion render exited {result.returncode}. "
            "Check the output above for details."
        )
    print("[assembler] Done.", flush=True)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Overlay B-roll from an EDL onto a base video (via Remotion)."
    )
    parser.add_argument("base_or_preview", help="Base video path, or '--preview'")
    parser.add_argument("edl", nargs="?", help="EDL JSON path")
    parser.add_argument("output", nargs="?", default="output.mp4")
    parser.add_argument(
        "--transition-type",
        default="crossfade",
        choices=["crossfade", "none"],
    )
    parser.add_argument(
        "--animation-type",
        default=None,
        choices=["ken_burns", "slide_in", "zoom_punch", "none"],
    )
    parser.add_argument(
        "--transition-duration",
        type=float,
        default=0.4,
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
    except (FileNotFoundError, ValueError, RuntimeError) as _exc:
        print(f"ERROR: {_exc}", file=sys.stderr)
        sys.exit(1)
