# Health Video Bot

Automated Hindi health education video pipeline. Produces YouTube Shorts backed by peer-reviewed research.

---

## Project Structure

```
health_video_bot/
│
├── niche_profile.json       # Editorial DNA — every stage reads this. Edit here, not in code.
├── job_schema.json          # Canonical definition of a job state object
├── orchestrator.py          # Runs the full pipeline stage by stage (Phase 7)
│
├── stages/
│   ├── stage_1_research.py         # PubMed search + PDF/screenshot acquisition
│   ├── stage_2_claim_extraction.py # LLM extracts structured claims from paper
│   ├── stage_3_content_generation.py # Master LLM call — script, metadata, prompts
│   ├── stage_4a_broll.py           # Pexels/Pixabay download
│   ├── stage_4b_thumbnail.py       # AI image generation
│   ├── stage_4c_voiceover.py       # Sarvam AI TTS
│   ├── stage_4d_captions.py        # Whisper transcription + SRT/ASS generation
│   └── stage_5_assembly.py         # FFmpeg video assembly + quality gate
│   └── stage_6_upload.py           # YouTube Data API v3 upload
│
├── jobs/                    # One JSON file per job. Never delete — failed jobs are useful.
│   └── {job_id}.json
│
├── assets/                  # All generated/downloaded files, organised by job_id
│   ├── {job_id}/
│   │   ├── screenshots/     # Study figure screenshots
│   │   ├── broll/           # Downloaded B-roll clips
│   │   ├── thumbnails/      # Generated thumbnail images
│   │   ├── audio/           # Voiceover WAV + background music
│   │   ├── captions/        # SRT and ASS files
│   │   └── output/          # Final rendered video
│   └── music/               # Manually curated background tracks (shared across jobs)
│
├── cache/
│   ├── broll/               # Cached B-roll clips by search term (avoid re-downloading)
│   └── thumbnails/          # Optional — cache generated thumbnails
│
└── logs/                    # One log file per pipeline run
```

---

## How a Job Flows

```
Topic from niche_profile.research.topic_rotation
    ↓
[Stage 1] PubMed search → PDF + screenshots → writes study{}
    ↓
[Stage 2] Claim extraction → validates → writes claims{}
    ↓
[Stage 3] Master LLM call → script + metadata + prompts → writes content{}
    ↓
[Stage 4a] B-roll download ─┐
[Stage 4b] Thumbnail gen    ├─ parallel → writes assets{}
[Stage 4c] TTS voiceover   ─┤
[Stage 4d] Whisper captions─┘
    ↓
[Stage 5] Video assembly + quality gate → writes output{}
    ↓
[Stage 6] YouTube upload → writes youtube_upload_id, url
```

Every stage:
1. Reads `niche_profile.json`
2. Reads the current job JSON from `jobs/{job_id}.json`
3. Does its work
4. Writes new fields into the job object
5. Updates `job.status` and `job.updated_at`
6. Saves the job JSON back to disk

---

## Job Status Flow

```
created
  → stage_1_complete
  → stage_2_complete
  → stage_3_complete
  → stage_4_complete
  → stage_5_complete
  → complete
  → error  (can occur at any stage)
```

---

## Setup Checklist

### API Keys needed (store in .env, never in code)
- [ ] `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` — for claim extraction + content generation
- [ ] `SARVAM_API_KEY` — for Hindi TTS
- [ ] `PEXELS_API_KEY` — for B-roll (free at pexels.com/api)
- [ ] `PIXABAY_API_KEY` — for B-roll fallback (free at pixabay.com/api/docs)
- [ ] Google Cloud project with YouTube Data API v3 enabled — OAuth 2.0 credentials JSON
- [ ] Image generation API key (OpenAI DALL-E 3 or Google Vertex AI Imagen)

### One-time manual tasks
- [ ] Fill in `channel.name` and `channel.youtube_channel_id` in niche_profile.json
- [ ] Fill in `audio.sarvam_voice_id` after testing voices on Sarvam AI playground
- [ ] Manually download 5-8 royalty-free background music tracks from Pixabay Music
  → Save to `assets/music/` with descriptive names (e.g. `calm_piano_01.mp3`)
- [ ] Design a static intro card (2 sec) and outro card (5 sec) as MP4 files
  → Save to `assets/intro.mp4` and `assets/outro.mp4`
- [ ] Set up Google Cloud OAuth consent screen and download credentials.json
- [ ] Run YouTube OAuth flow once manually to generate token.json

### Python dependencies (install order)
```
pip install langchain langgraph langchain-openai
pip install pydantic==2.*
pip install biopython          # PubMed API (Entrez)
pip install playwright         # Screenshot acquisition (run: playwright install chromium)
pip install requests           # Pexels/Pixabay API
pip install openai             # DALL-E + Whisper
pip install moviepy            # Video assembly
pip install pydub              # Audio processing + level checks
pip install google-api-python-client google-auth-oauthlib  # YouTube upload
pip install python-dotenv      # .env loading
pip install faster-whisper     # Local Whisper (faster than openai-whisper)
pip install ffmpeg-python      # FFmpeg wrapper
```
FFmpeg must also be installed at system level: `sudo apt install ffmpeg`

---

## Niche Profile — Key Fields to Know

| Field | What it controls |
|---|---|
| `editorial.topics` | Which health topics are in scope |
| `script.target_duration_seconds` | Drives word count calculation in Stage 3 |
| `script.segment_structure` | The exact segments the LLM must produce |
| `script.absolute_prohibitions` | Injected into every LLM prompt as hard rules |
| `research.topic_rotation` | The queue of search queries the orchestrator cycles through |
| `compliance.medical_disclaimer` | Auto-prepended in Stage 5 and Stage 6 |
| `quality_gate` | All checks Stage 5 runs before allowing upload |

---

## Adding a New Topic

1. Add the search query to `niche_profile.research.topic_rotation`
2. Optionally add a new broll mood hint to `visuals.broll_mood_map` if the topic needs different footage style
3. That's it — the pipeline picks it up on the next run

---

## Build Order (recommended)

Build stages in this order, not sequentially:

1. **Stage 3** — content generation. Get the LLM JSON output perfect first.
2. **Stage 5** — video assembly with placeholder assets. Get a real video file out.
3. **Stage 6** — YouTube upload. Confirm API is working end to end.
4. **Stages 4a–4d** — asset generation. Pipeline is now fully automated.
5. **Stages 1–2** — research + claim extraction. Connect the front end.
6. **Orchestrator** — wire everything together with LangGraph.