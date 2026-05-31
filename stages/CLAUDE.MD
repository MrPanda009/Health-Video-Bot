# Stages — Claude Code Context

Detailed specifications for every stage. The root `CLAUDE.md` covers coding patterns
and conventions that apply to all stages. This file covers what each stage specifically does.

Stages 1–3 are complete. This file focuses on Stages 4a–4d, 5, and 6.

---

## Stage 4a — B-roll Download (`stage_4a_broll.py`)

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

## Stage 4b — Thumbnail Generation (`stage_4b_thumbnail.py`)

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

## Stage 4c — Voiceover Generation (`stage_4c_voiceover.py`)

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

## Stage 4d — Caption Generation (`stage_4d_captions.py`)

**Input:** `job["assets"]["voiceover_path"]` (WAV file from Stage 4c)
**Output:** `job["assets"]["srt_path"]`, `job["assets"]["ass_path"]`,
           `job["assets"]["whisper_word_timestamps"]`
**Status:** contributes to `stage_4_complete`

### What it does
1. Run Whisper on the voiceover WAV to get word-level timestamps
2. Generate SRT file (for YouTube upload — accessibility + SEO)
3. Generate ASS file (for burning into the video in Stage 5)
4. Map timestamps back to `script_segments` so Stage 5 knows B-roll timing

### Whisper call (faster-whisper, local)
```python
from faster_whisper import WhisperModel
model = WhisperModel("base", device="cpu", compute_type="int8")
segments, info = model.transcribe(
    voiceover_path,
    language="hi",
    word_timestamps=True
)
```

### SRT generation
```python
def to_srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

srt_lines = []
for i, segment in enumerate(segments, 1):
    srt_lines.append(str(i))
    srt_lines.append(f"{to_srt_timestamp(segment.start)} --> {to_srt_timestamp(segment.end)}")
    srt_lines.append(segment.text.strip())
    srt_lines.append("")

with open(srt_path, "w", encoding="utf-8") as f:
    f.write("\n".join(srt_lines))
```

### ASS generation (burn-in captions)
ASS format allows styling. Use this template for Shorts:
```
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, Bold, Alignment, MarginV
Style: Default,Noto Sans Devanagari,72,&H00FFFFFF,1,2,120

[Events]
Format: Layer, Start, End, Style, Text
```
ASS timestamp format: `H:MM:SS.cc` (centiseconds, not milliseconds)

### Segment-timestamp mapping
After generating timestamps, match each Whisper segment back to the script segment it belongs to.
Store as `whisper_word_timestamps` in the job — Stage 5 uses this to cut B-roll clips.

---

## Stage 5 — Video Assembly (`stage_5_assembly.py`)

**Input:** All of `assets{}` — broll_video_paths, voiceover_path, srt_path, ass_path,
          thumbnail_paths, background_music_path, whisper_word_timestamps
**Output:** `job["output"]["final_video_path"]`, `job["output"]["quality_checks"]`
**Status:** `stage_5_complete`

### What it does
Assembles the final video using FFmpeg. Timeline per segment:
- Use Whisper timestamps to know exactly how long each segment is
- Layer the matching B-roll clip under the voiceover
- Loop B-roll if the segment is longer than the clip
- For the `finding` and `context` segments: use study screenshots instead of B-roll
  if `study.screenshot_paths` is non-empty
- Prepend 3-second medical disclaimer card (white text on black, from compliance config)
- Add 2-second intro card from `assets/intro.mp4` (manually created once)
- Add 5-second outro card from `assets/outro.mp4`
- Burn in ASS captions
- Mix voiceover at 100% with background music at 15% volume

### FFmpeg assembly approach
Use `ffmpeg-python` wrapper. Prefer filter_complex over multiple passes.

```python
import ffmpeg

def assemble_video(segments_with_broll, voiceover_path, music_path, ass_path, output_path):
    # Build video stream from B-roll clips trimmed to segment durations
    # This is complex — use subprocess with ffmpeg directly for filter_complex
    import subprocess
    
    # Example concat filter:
    filter_parts = []
    inputs = []
    for i, seg in enumerate(segments_with_broll):
        inputs += ["-i", seg["broll_path"]]
        filter_parts.append(f"[{i}:v]trim=duration={seg['duration']},setpts=PTS-STARTPTS[v{i}]")
    
    concat_inputs = "".join(f"[v{i}]" for i in range(len(segments_with_broll)))
    filter_parts.append(f"{concat_inputs}concat=n={len(segments_with_broll)}:v=1:a=0[vout]")
    
    cmd = ["ffmpeg", "-y"]
    cmd += inputs
    cmd += ["-i", voiceover_path]
    cmd += ["-i", music_path]
    cmd += ["-filter_complex", ";".join(filter_parts)]
    cmd += ["-vf", f"ass={ass_path}"]
    # ... audio mix, output settings
    subprocess.run(cmd, check=True)
```

### Disclaimer card
Generate programmatically using FFmpeg drawtext or a pre-rendered PNG:
```python
disclaimer_text = niche_profile["compliance"]["medical_disclaimer"]["text_hindi"]
# Use FFmpeg drawtext filter or create a black frame with white text using Pillow
```

### Quality gate
Read thresholds from `niche_profile["quality_gate"]`:

```python
quality_checks = {
    "duration_in_range": False,
    "disclaimer_present": False,
    "audio_peak_ok": False,
    "audio_avg_ok": False,
    "all_passed": False
}

# Duration check
import subprocess, json
probe = subprocess.run(
    ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", output_path],
    capture_output=True, text=True
)
duration = float(json.loads(probe.stdout)["format"]["duration"])
target = niche_profile["script"]["target_duration_seconds"]
tolerance = niche_profile["quality_gate"]["video_duration_tolerance_pct"] / 100
quality_checks["duration_in_range"] = abs(duration - target) / target <= tolerance

# Audio level check (use ffmpeg volumedetect)
# Thresholds from niche_profile["quality_gate"]["audio_peak_dbfs_max"] etc.

quality_checks["all_passed"] = all(v for k, v in quality_checks.items() if k != "all_passed")
```

If `all_passed` is False: set `job["output"]["quality_checks"]`, mark error with specific failing check.

---

## Stage 6 — YouTube Upload (`stage_6_upload.py`)

**Input:** `job["output"]["final_video_path"]`, `job["content"]`, `job["assets"]["thumbnail_paths"]`,
          `job["assets"]["srt_path"]`
**Output:** `job["output"]["youtube_upload_id"]`, `job["output"]["youtube_url"]`,
           `job["output"]["scheduled_publish_time"]`
**Status:** `complete`

### Auth setup (one-time manual step)
```bash
# User must do this once:
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

publish_time = (datetime.now(timezone.utc) + timedelta(hours=20)).isoformat()

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
        "privacyStatus": "private",   # change to "public" or use scheduledPublishAt
        "selfDeclaredMadeForKids": niche_profile["channel"]["made_for_kids"],
        "madeForKids": niche_profile["channel"]["made_for_kids"],
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
    # YouTube only keeps the last thumbnail set — upload all 3 sequentially,
    # final one will be the active thumbnail (use concept_abstract last as safest choice)
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

### AI-generated content disclosure
Required by YouTube policy. Set in video snippet:
```python
body["snippet"]["madeForKids"] = False
# For AI disclosure — use YouTube's self-declaration flag:
body["status"]["containsSyntheticMedia"] = True  # if thumbnail or video is AI-generated
```

### Schedule publish
```python
# Schedule 20 hours out (gives YouTube time to process):
publish_time = (datetime.now(timezone.utc) + timedelta(hours=20)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
body["status"]["privacyStatus"] = "private"
body["status"]["publishAt"] = publish_time
```

