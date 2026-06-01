# Stages — Claude Code Context

Detailed specifications for every stage. The root `CLAUDE.md` covers coding patterns
and conventions that apply to all stages. This file covers what each stage specifically does.

Stages 1–5 are complete. Stage 6 (YouTube upload) is TODO.

---

## Stage 4a — B-roll Download (`stage_4a_broll.py`) ✅

**Input:** `job["content"]["broll_search_tags"]` — list of `{segment_name, search_terms}`
**Output:** `job["assets"]["broll_video_paths"]` — list of `{segment_name, paths: [path1, path2]}`
**Status:** `stage_4_complete` (set by the frontend API after ALL stage 4 sub-stages complete)

### What it does
For each segment in `broll_search_tags`:
1. Try each `search_term` against Pexels API (better quality)
2. Filter results: min 1080p, min 5 seconds duration, landscape orientation
3. If Pexels returns < 2 results, fallback to Pixabay API for the same term
4. Download 2 best clips per segment (so Stage 5 has options)
5. Save to `assets/{job_id}/broll/{segment_name}_{n}.mp4`
6. Check local cache at `cache/broll/{search_term_slug}.mp4` before downloading

### Cache
- Cache key: slug of the search term (replace spaces with underscores, lowercase)
- If cached, copy from cache to `assets/{job_id}/broll/` instead of downloading
- After downloading, copy to cache for future use
- Cache path: `cache/broll/{search_term_slug}.mp4`

### Pexels API
```python
headers = {"Authorization": os.getenv("PEXELS_API_KEY")}
params = {"query": search_term, "per_page": 5, "orientation": "landscape",
          "min_width": 1920, "min_height": 1080, "min_duration": 5}
resp = requests.get("https://api.pexels.com/videos/search", headers=headers, params=params)
videos = resp.json().get("videos", [])
# Sort by duration desc, take first 2
# Download via: video["video_files"][0]["link"]
```

### Pixabay API (fallback)
```python
params = {"key": os.getenv("PIXABAY_API_KEY"), "q": search_term,
          "video_type": "film", "min_width": 1920, "order": "popular", "per_page": 5}
resp = requests.get("https://pixabay.com/api/videos/", params=params)
```

### Error handling
- If a segment gets 0 clips from both APIs: log warning, write empty list for that segment
- Do NOT abort the job — Stage 5 will handle missing B-roll by substituting study screenshots
- Write `"broll_missing_segments": [...]` into assets if any are missing

---

## Stage 4b — Thumbnail Generation (`stage_4b_thumbnail.py`) ✅

**Input:** `job["content"]["thumbnail_prompts"]` — 3 items: data_visual, human_lifestyle, concept_abstract
**Output:** `job["assets"]["thumbnail_paths"]` — list of `{variant_id, path}`
**Status:** contributes to `stage_4_complete`

### What it does
For each of the 3 thumbnail prompts:
1. Prepend style guidance from `niche_profile.thumbnail`
2. Call image generation API (DALL-E 3 or Vertex Imagen — controlled by `IMAGE_GEN_PROVIDER` env var)
3. Request 1280×720 resolution
4. Save to `assets/{job_id}/thumbnails/{variant_id}.png`

### DALL-E 3 call
```python
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
response = client.images.generate(
    model="dall-e-3",
    prompt=full_prompt,
    size="1792x1024",   # closest to 1280×720 landscape — resize after
    quality="hd",
    n=1
)
image_url = response.data[0].url
# Download and resize to 1280×720 using Pillow
```

### Vertex AI Imagen (alternative)
```python
# Only use if IMAGE_GEN_PROVIDER=vertex
# Requires google-cloud-aiplatform installed and GOOGLE_APPLICATION_CREDENTIALS set
from vertexai.preview.vision_models import ImageGenerationModel
model = ImageGenerationModel.from_pretrained("imagegeneration@006")
images = model.generate_images(prompt=full_prompt, number_of_images=1,
                                aspect_ratio="16:9")
```

### Prompt enhancement
Prepend this to every thumbnail prompt (from niche profile):
```
"{prompt}. Style: {niche_profile.thumbnail.art_direction}.
Text overlay rules: {niche_profile.thumbnail.text_overlay_rules}.
Do not include any text in the image — text will be added as overlay separately."
```

### Pillow resize
```python
from PIL import Image
img = Image.open(downloaded_path)
img = img.resize((1280, 720), Image.LANCZOS)
img.save(output_path, "PNG")
```

---

## Stage 4c — Voiceover Generation (`stage_4c_voiceover.py`) ✅

**Input:** `job["content"]["hindi_script"]`
**Output:** `job["assets"]["voiceover_path"]`, `job["assets"]["voiceover_duration_seconds"]`
**Status:** contributes to `stage_4_complete`

### What it does
1. Read `hindi_script` from job
2. Read TTS config from niche_profile: `audio.sarvam_voice_id`, `audio.tts_pace`, `audio.tts_pitch`
3. Call Sarvam AI TTS API
4. Save WAV to `assets/{job_id}/audio/voiceover.wav`
5. Measure actual duration (use `pydub` or `librosa`)
6. Write duration to `assets.voiceover_duration_seconds`

### Sarvam AI TTS API
```python
import requests
headers = {
    "api-subscription-key": os.getenv("SARVAM_API_KEY"),
    "Content-Type": "application/json"
}
payload = {
    "inputs": [job["content"]["hindi_script"]],
    "target_language_code": "hi-IN",
    "speaker": niche_profile["audio"]["sarvam_voice_id"],
    "pace": niche_profile["audio"]["tts_pace"],
    "pitch": niche_profile["audio"]["tts_pitch"],
    "model": "bulbul:v1"
}
resp = requests.post("https://api.sarvam.ai/text-to-speech", headers=headers, json=payload)
# Response: {"audios": ["<base64-encoded-wav>"]}
audio_b64 = resp.json()["audios"][0]
import base64
audio_bytes = base64.b64decode(audio_b64)
with open(output_path, "wb") as f:
    f.write(audio_bytes)
```

### Duration measurement
```python
from pydub import AudioSegment
audio = AudioSegment.from_wav(voiceover_path)
duration_seconds = len(audio) / 1000.0
```

### Error handling
- If TTS call fails: retry once with a 5-second delay
- If script is too long for one API call (Sarvam limit is ~500 chars per call):
  split by sentence, call API per chunk, concatenate WAV files with pydub

---

## Stage 4d — Captions (`stage_4d_captions.py`) ✅

**Input:** `job["assets"]["voiceover_path"]` (WAV file from Stage 4c)
**Output:** `job["assets"]["srt_path"]`, `job["assets"]["whisper_word_timestamps"]`
**Status:** contributes to `stage_4_complete` (does NOT set status itself)

### What it does
1. Guards that `whisperx` is installed — marks job error with pip install instructions if not
2. Guards that the voiceover file exists
3. Calls `whisperx_transcriber.transcribe(voiceover_path, language="hi")` for word-level timestamps
4. Converts segments to SRT format
5. Saves `assets/{job_id}/captions/word_timestamps.json` and `captions.srt`
6. Writes `job["assets"]["whisper_word_timestamps"]` and `job["assets"]["srt_path"]`

### Implementation detail
Stage 4d imports from `whisperx_transcriber.py` (project root, one level up from `stages/`):
```python
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from whisperx_transcriber import transcribe
```

The transcriber auto-detects CUDA (`float16`) or CPU (`int8`). Alignment failures downgrade
gracefully to segment-level timestamps without aborting.

### Error cases — all handled explicitly
- `whisperx` not installed → `mark_error()` with pip install instructions
- Voiceover file missing → `mark_error()`
- Model not downloaded → `RuntimeError` from transcriber → `mark_error()` pointing to Models dashboard
- Empty transcription output → `mark_error()`

### SRT generation
```python
def _fmt_srt_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

### Stage 5 without Stage 4d
Stage 5 checks `assets.ass_path` — if absent, it skips caption burn-in and uses
`duration_hint_seconds` from `content.script_segments` for clip timing. The video renders
normally; only the SRT upload to YouTube (Stage 6) and the caption burn-in are affected.

---

## Stage 5 — Video Assembly (`stage_5_assembly.py`) ✅

**Input:** All of `assets{}` — broll_video_paths, voiceover_path, srt_path,
          thumbnail_paths, background_music_path, whisper_word_timestamps
**Output:** `job["output"]["final_video_path"]`, `job["output"]["quality_checks"]`
**Status:** `stage_5_complete`

### Assembly engine: MoviePy 2.x
Stage 5 uses **MoviePy 2.x** (not FFmpeg filter_complex). `pip install moviepy` is required;
ffmpeg must be on PATH as MoviePy delegates encoding to it.

**Key MoviePy v2 API used — never use v1 equivalents:**
```python
from moviepy import (
    VideoFileClip, ImageClip, ColorClip,
    AudioFileClip, concatenate_videoclips,
    concatenate_audioclips, CompositeAudioClip,
)
clip.subclipped(t_start, t_end)  # not .subclip()
clip.resized((w, h))             # not .resize()
clip.cropped(x1=x1, y1=y1, x2=x2, y2=y2)  # not .crop()
clip.with_audio(audio)           # not .set_audio()
clip.with_fps(fps)               # not .set_fps()
audio.with_volume_scaled(0.15)   # not .volumex()
```

### What it does
Timeline built in order:
1. `[optional intro.mp4]` — scale-crop to target resolution
2. 3-second disclaimer card — `ImageClip` from Pillow-generated PNG
3. Per segment from `content.script_segments`:
   - `context` / `finding` segments → study screenshot (`ImageClip`) if available
   - All other segments → B-roll from `broll_video_paths` (looped if too short, scale-cropped)
   - Missing clips → black frame (`ColorClip`)
4. `[optional outro.mp4]` — scale-crop to target resolution

Audio chain:
- Voiceover at 100%
- Optional background music at 15% (`audio.with_volume_scaled(0.15)`)
- Mixed with `CompositeAudioClip([voiceover, music])`

ASS captions (if `assets.ass_path` exists from Stage 4d):
- MoviePy cannot render ASS filters, so Stage 5 does a single FFmpeg post-pass:
  ```python
  run_ffmpeg(["ffmpeg", "-y", "-i", raw_path, "-vf", f"ass='{escaped}'", ..., output_path])
  ```
  The intermediate `video_raw.mp4` is deleted after burn-in.

### Scale-crop helper
All clips are resized with scale-to-fill + center-crop — no letterboxing, no stretching:
```python
def _mp_scale_crop(clip, target_w, target_h):
    import math
    clip_w, clip_h = clip.size
    scale = max(target_w / clip_w, target_h / clip_h)
    new_w, new_h = math.ceil(clip_w * scale), math.ceil(clip_h * scale)
    clip = clip.resized((new_w, new_h))
    x1, y1 = (new_w - target_w) // 2, (new_h - target_h) // 2
    return clip.cropped(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)
```

### Quality gate (unchanged from original — uses ffprobe/volumedetect)
```python
quality_checks = {
    "duration_in_range": bool,      # from niche_profile.quality_gate
    "disclaimer_present": True,     # always true (included in assembly)
    "audio_peak_ok": bool,          # from volumedetect
    "audio_avg_ok": bool,           # from volumedetect
    "all_passed": bool,
}
```
If `all_passed` is False: marks job error with failing check names. Video is preserved on disk for inspection.

### Pre-flight: accepted job statuses
- `stage_4_complete` — normal flow
- `stage_3_complete` — dev mode (manually placed assets, no stage 4 needed)
- `error` with `error.stage == "stage_5"` — retry

---

## Standalone modules (project root, not stage scripts)

### `whisperx_transcriber.py`
Pure transcription utility. Used by Stage 4d and independently.

```python
from whisperx_transcriber import transcribe, transcribe_to_file

segments = transcribe("voiceover.wav", language="hi", model_size="large-v2")
# Returns: [{"text": str, "start": float, "end": float, "words": [{"word", "start", "end"}]}]

transcribe_to_file("voiceover.wav", "transcript.json", language="hi")
```

Requires: `pip install whisperx torch` + models downloaded via `model_manager.py`.
On import failure or missing model: raises `ImportError` / `RuntimeError` with actionable message.

### `edit_decision.py`
Generates an Edit Decision List from a transcript + B-roll clip database.

```python
from edit_decision import extract_keywords, generate_edl, edl_to_json

keywords = extract_keywords("रक्त शर्करा का स्तर बढ़ता है", max_terms=3)
# Returns: ['शर्करा', 'बढ़ता', 'रक्त']  (longest non-stopword tokens)

edl = generate_edl(segments, clip_db_path="cache/broll_cache.db")
# Returns: [{"clip_id", "clip_path", "timeline_start", "timeline_end",
#            "source_text", "search_terms"}]

edl_to_json(edl, "edl.json")
```

Hindi stopword list is built-in (100+ tokens). Keyword extraction is entirely offline.
Raises `FileNotFoundError` if the database does not exist yet (run Stage 4a first).

### `video_assembler.py`
Overlays B-roll from an EDL onto a base A-roll video using MoviePy.

```python
from video_assembler import assemble, preview_edl

preview_edl("edl.json")   # prints time / clip / text table to terminal

assemble(
    base_video_path="footage.mp4",
    edl_path="edl.json",
    output_path="final.mp4",
)
```

- B-roll fully replaces the video track at each window (no transparent overlay)
- Base video audio is preserved throughout; B-roll audio is always stripped
- Clips shorter than their window are looped; all clips are scale-cropped to match base resolution
- Segments with `clip_path=null` or missing files show base video unchanged

### `stages/model_manager.py`
CLI called by the frontend `/api/models` routes. Not a stage script.

```bash
python stages/model_manager.py status          # → JSON of all models + download status
python stages/model_manager.py download large-v2
python stages/model_manager.py download align-hi
```

Known model IDs:
| ID | Type | HF repo | Size |
|---|---|---|---|
| `large-v2` | transcription | `Systran/faster-whisper-large-v2` | 3.1 GB |
| `large-v3` | transcription | `Systran/faster-whisper-large-v3` | 3.1 GB |
| `medium` | transcription | `Systran/faster-whisper-medium` | 1.5 GB |
| `small` | transcription | `Systran/faster-whisper-small` | 0.5 GB |
| `align-hi` | alignment | `theainerd/Wav2Vec2-large-xlsr-hindi` | 1.2 GB |

Download status is checked by looking for `~/.cache/huggingface/hub/models--{repo}/snapshots/`.

---

## Stage 6 — YouTube Upload (`stage_6_upload.py`) 🔲 TODO

**Input:** `job["output"]["final_video_path"]`, `job["content"]`, `job["assets"]["thumbnail_paths"]`,
          `job["assets"]["srt_path"]`
**Output:** `job["output"]["youtube_upload_id"]`, `job["output"]["youtube_url"]`,
           `job["output"]["scheduled_publish_time"]`
**Status:** `complete`

### Auth setup (one-time manual step)
```bash
python -c "
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file('credentials.json',
    scopes=['https://www.googleapis.com/auth/youtube.upload'])
creds = flow.run_local_server(port=0)
import pickle; pickle.dump(creds, open('token.pkl', 'wb'))
print('Done')
"
```

### Upload the video
```python
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import pickle

creds = pickle.load(open("token.pkl", "rb"))
youtube = build("youtube", "v3", credentials=creds)

body = {
    "snippet": {
        "title": job["content"]["title"],
        "description": job["content"]["description"],
        "tags": job["content"]["tags"],
        "categoryId": niche_profile["channel"]["youtube_category_id"],
        "defaultLanguage": niche_profile["channel"]["language"],
        "defaultAudioLanguage": niche_profile["channel"]["language"],
    },
    "status": {
        "privacyStatus": "private",
        "selfDeclaredMadeForKids": niche_profile["channel"]["made_for_kids"],
        "madeForKids": niche_profile["channel"]["made_for_kids"],
        "containsSyntheticMedia": True,  # AI-generated content disclosure
    }
}

media = MediaFileUpload(job["output"]["final_video_path"], chunksize=-1, resumable=True)
request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

response = None
while response is None:
    status, response = request.next_chunk()
    if status:
        print(f"Upload {int(status.progress() * 100)}%")

video_id = response["id"]
```

### Upload thumbnails
```python
for thumb in job["assets"]["thumbnail_paths"]:
    youtube.thumbnails().set(
        videoId=video_id,
        media_body=MediaFileUpload(thumb["path"])
    ).execute()
    # YouTube keeps the last thumbnail set — upload all 3 sequentially;
    # use concept_abstract last as it's the safest choice
```

### Upload SRT captions
```python
youtube.captions().insert(
    part="snippet",
    body={
        "snippet": {
            "videoId": video_id,
            "language": "hi",
            "name": "Hindi",
            "isDraft": False
        }
    },
    media_body=MediaFileUpload(job["assets"]["srt_path"], mimetype="text/plain")
).execute()
```

### Schedule publish
```python
# Schedule 20 hours out (gives YouTube time to process):
from datetime import timedelta
publish_time = (
    datetime.now(timezone.utc) + timedelta(hours=20)
).strftime("%Y-%m-%dT%H:%M:%S.000Z")
body["status"]["privacyStatus"] = "private"
body["status"]["publishAt"] = publish_time
```
