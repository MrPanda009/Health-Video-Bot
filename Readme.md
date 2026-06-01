# Health Video Bot

Automated Hindi health education video pipeline. Takes a PubMed health research topic, extracts claims from a real peer-reviewed study, generates a voiceover script, downloads B-roll, assembles a full-HD video, and uploads it to YouTube. Target: Hindi-speaking adults (35–65) managing chronic conditions.

---

## What's Built

| Stage | Script | Status | What it does |
|---|---|---|---|
| 0 | `stages/stage_0_clean.py` | ✅ | Interactive job & asset cleanup utility |
| 1 | `stages/stage_1_research.py` | ✅ | PubMed search, citation ranking, PDF + screenshot acquisition |
| 2 | `stages/stage_2_claim_extraction.py` | ✅ | LLM claim extraction + safety flags |
| 3 | `stages/stage_3_content_generation.py` | ✅ | Master LLM call — Hindi script, metadata, thumbnail prompts, B-roll tags |
| 4a | `stages/stage_4a_broll.py` | ✅ | Pexels/Pixabay B-roll download with SQLite clip library |
| 4b | `stages/stage_4b_thumbnail.py` | ✅ | AI thumbnail generation (DALL-E 3 or Vertex Imagen) |
| 4c | `stages/stage_4c_voiceover.py` | ✅ | Sarvam AI Hindi TTS, chunk-splitting, WAV concatenation |
| 4d | `stages/stage_4d_captions.py` | ✅ | WhisperX transcription → SRT captions + word timestamps |
| 5 | `stages/stage_5_assembly.py` | ✅ | MoviePy assembly + quality gate |
| 6 | `stages/stage_6_upload.py` | 🔲 TODO | YouTube Data API v3 upload |

**Supporting modules (project root):**
- `broll_db.py` — SQLite clip registry (dedup, LRU reuse, integrity checking)
- `whisperx_transcriber.py` — WhisperX-based audio transcription returning word-level timestamps
- `edit_decision.py` — Generates an EDL JSON from a transcript and the B-roll clip database
- `video_assembler.py` — Overlays B-roll from an EDL onto a base A-roll video using MoviePy
- `niche_profile.json` — all editorial config; never hardcode values from it in stage scripts
- `job_schema.json` — canonical shape of a job state object

**Frontend dashboard (`frontend/`):**
- Next.js + React + Tailwind CSS
- Jobs list with live status polling
- Per-job pipeline timeline — run any stage and stream its stdout in real time
- Job data explorer (study, claims, script, assets, output)
- Clip Library page — browse, filter by status, and verify the B-roll SQLite database
- **Models page** — check which WhisperX models are downloaded, download missing ones with live progress streaming
- New Job dialog — choose topic, optional PMID, and output format (9:16 Shorts / 16:9 Landscape)

---

## Output Formats

Both formats are full HD. The format is chosen at job creation and stored in `job.aspect_ratio`.

| Format | Resolution | Use case |
|---|---|---|
| `9:16` (default) | 1080 × 1920 | YouTube Shorts |
| `16:9` | 1920 × 1080 | Standard YouTube / landscape |

---

## Directory Layout

```
health_video_bot/
│
├── broll_db.py                 # SQLite clip registry
├── whisperx_transcriber.py     # WhisperX transcription with word-level timestamps
├── edit_decision.py            # EDL generator: transcript → clip placements
├── video_assembler.py          # MoviePy assembler: base video + EDL → final video
├── niche_profile.json          # Editorial DNA — all stages read this
├── job_schema.json             # Canonical job state schema
│
├── stages/
│   ├── model_manager.py        # CLI: check/download WhisperX models (called by frontend)
│   ├── stage_0_clean.py        # Interactive job & asset cleanup
│   ├── stage_1_research.py
│   ├── stage_2_claim_extraction.py
│   ├── stage_3_content_generation.py
│   ├── stage_4a_broll.py
│   ├── stage_4b_thumbnail.py
│   ├── stage_4c_voiceover.py
│   ├── stage_4d_captions.py    # WhisperX → SRT + word timestamps
│   └── stage_5_assembly.py     # MoviePy assembly + quality gate
│
├── frontend/                   # Next.js dashboard
│   ├── app/
│   │   ├── jobs/               # Job list + per-job detail pages
│   │   ├── clips/              # Clip library page
│   │   ├── models/             # WhisperX model download page
│   │   └── api/
│   │       ├── jobs/           # Job CRUD + stage runner + SSE log streaming
│   │       ├── clips/          # Clip library + integrity verify
│   │       └── models/         # Model status check + download SSE stream
│   ├── components/
│   └── hooks/
│
├── jobs/                       # One JSON per job — never delete
│
├── assets/
│   ├── {job_id}/
│   │   ├── screenshots/
│   │   ├── broll/
│   │   ├── thumbnails/
│   │   ├── audio/
│   │   ├── captions/           # word_timestamps.json + captions.srt
│   │   └── output/
│   ├── intro.mp4               # Optional — prepended to every video
│   ├── outro.mp4               # Optional — appended to every video
│   └── music/                  # Shared background tracks (manual)
│
└── cache/
    ├── broll/                  # Cached clips by search-term slug
    └── broll_cache.db          # SQLite clip registry (managed by broll_db.py)
```

---

## Pipeline Flow

```
[Stage 1]  PubMed search → PDF/screenshots → study{}
[Stage 2]  LLM claim extraction + safety flags → claims{}
[Stage 3]  Master LLM call → hindi_script + metadata + prompts → content{}
               ↓                    ↓                   ↓              ↓
[Stage 4a] B-roll download   [Stage 4b] Thumbnails  [Stage 4c] TTS   [Stage 4d] Captions
               └──────────────────────┴───────────────────┴──────────────┘
                              → assets{}  (status → stage_4_complete)
[Stage 5]  MoviePy assembly + quality gate → output/video.mp4
[Stage 6]  YouTube upload (TODO)
```

**Standalone editing pipeline** (independent of the job flow — used when you have A-roll footage):
```
audio file
    ↓  whisperx_transcriber.py
transcript JSON (word-level timestamps)
    ↓  edit_decision.py
EDL JSON (clip placements)
    ↓  video_assembler.py
final video (B-roll overlaid on A-roll, base audio preserved)
```

### Job status progression
```
created → stage_1_complete → stage_2_complete → stage_3_complete
        → stage_4_complete → stage_5_complete → complete
        → error  (any stage; job file is preserved for debugging)
```

Every stage reads `jobs/{job_id}.json`, does its work, writes its output block back, and updates `status` + `updated_at`. `niche_profile.json` is the only other config source.

---

## Setup

### 1. Python environment

```bash
uv venv
source .venv/bin/activate
uv pip install biopython playwright requests openai anthropic \
               pydub pillow python-dotenv moviepy
playwright install chromium
```

FFmpeg must be installed at the system level (required by MoviePy and the quality gate):
```bash
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Ubuntu/Debian
```

**For Stage 4d (WhisperX captions)** — install separately after PyTorch:
```bash
pip install torch
pip install whisperx
# Then download models from the dashboard at /models, or via CLI:
python stages/model_manager.py download large-v2
python stages/model_manager.py download align-hi
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev    # http://localhost:3000
```

Create `frontend/.env.local`:
```
PIPELINE_ROOT=..
PYTHON_BIN=../.venv/bin/python3
```

### 3. Environment variables (`.env` at project root)

```env
# LLM — pick one provider
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GROQ_API_KEY=              # Free tier — recommended for dev (console.groq.com)

LLM_MODEL=llama-3.3-70b-versatile   # or claude-sonnet-4-6, gpt-4o
LLM_PROVIDER=groq                   # auto | groq | openai

# PubMed
ENTREZ_EMAIL=              # Required by NCBI ToS (any email)
NCBI_API_KEY=              # Optional — raises rate limit to 10 req/s

# B-roll
PEXELS_API_KEY=            # Free at pexels.com/api
PIXABAY_API_KEY=           # Free at pixabay.com/api/docs

# Voiceover
SARVAM_API_KEY=            # Sarvam AI Hindi TTS

# Thumbnails
IMAGE_GEN_PROVIDER=dalle   # or: vertex
GOOGLE_APPLICATION_CREDENTIALS=   # for Vertex AI Imagen only

# Paths (defaults shown)
NICHE_PROFILE_PATH=niche_profile.json
JOBS_DIR=jobs
ASSETS_DIR=assets
CACHE_DIR=cache
```

**Dev shortcut:** Groq is free and fast enough for Stages 2 & 3. Get a key at [console.groq.com](https://console.groq.com).

### 4. One-time manual setup

- [ ] Set `channel.youtube_channel_id` in `niche_profile.json`
- [ ] Test Sarvam AI voices and set `audio.sarvam_voice_id` in `niche_profile.json`
- [ ] Download 5–8 royalty-free background tracks → `assets/music/`
- [ ] Optionally create `assets/intro.mp4` (≤3 s) and `assets/outro.mp4` (≤5 s)
- [ ] Download WhisperX models (Stage 4d): open the dashboard `/models` page and click Download

---

## Running the Pipeline

### CLI

```bash
# Auto-picks the most recent eligible job at each stage
.venv/bin/python3 stages/stage_1_research.py
.venv/bin/python3 stages/stage_2_claim_extraction.py
.venv/bin/python3 stages/stage_3_content_generation.py
.venv/bin/python3 stages/stage_4a_broll.py
.venv/bin/python3 stages/stage_4b_thumbnail.py
.venv/bin/python3 stages/stage_4c_voiceover.py
.venv/bin/python3 stages/stage_4d_captions.py   # requires whisperx + downloaded models
.venv/bin/python3 stages/stage_5_assembly.py

# Pass a job_id explicitly
.venv/bin/python3 stages/stage_2_claim_extraction.py <job_id>

# Stage 1 — topic, PMID, and aspect ratio (all optional)
.venv/bin/python3 stages/stage_1_research.py "gut microbiome diabetes" "" 9:16
.venv/bin/python3 stages/stage_1_research.py "" 38452901 16:9

# Clean up old jobs
.venv/bin/python3 stages/stage_0_clean.py
```

### Standalone editing pipeline

```bash
# Transcribe audio → word-level timestamps JSON
.venv/bin/python3 whisperx_transcriber.py voiceover.wav hi large-v2

# Generate EDL from transcript + B-roll DB
.venv/bin/python3 edit_decision.py transcript.json edl.json

# Preview the edit plan before rendering
.venv/bin/python3 video_assembler.py --preview edl.json

# Render final video (B-roll overlaid on A-roll)
.venv/bin/python3 video_assembler.py base_footage.mp4 edl.json final.mp4
```

### WhisperX model management

```bash
# Check which models are downloaded
.venv/bin/python3 stages/model_manager.py status

# Download a specific model
.venv/bin/python3 stages/model_manager.py download large-v2
.venv/bin/python3 stages/model_manager.py download align-hi
```

### Dashboard

```bash
cd frontend && npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Use the navigation to:
- **Jobs** — create jobs, run pipeline stages, stream logs live
- **Clips** — browse the B-roll library, verify file integrity
- **Models** — check WhisperX model download status, download missing models

---

## WhisperX Models

Stage 4d and the standalone `whisperx_transcriber.py` require two model downloads (stored in `~/.cache/huggingface/hub/`):

| Model ID | Type | Size | Use |
|---|---|---|---|
| `large-v2` | Transcription | ~3.1 GB | Recommended for production |
| `large-v3` | Transcription | ~3.1 GB | Latest large model |
| `medium` | Transcription | ~1.5 GB | Faster, slightly less accurate |
| `small` | Transcription | ~0.5 GB | Dev/testing |
| `align-hi` | Alignment | ~1.2 GB | Word-level timestamps in Hindi |

If a model isn't downloaded, Stage 4d prints a clear error message pointing to the Models dashboard. Stage 5 handles the absence of Stage 4d output gracefully (no captions, timing from `duration_hint_seconds`).

---

## Clip Library (`broll_db.py`)

Stage 4a maintains a SQLite database of every downloaded clip. Before hitting the Pexels/Pixabay API, it first checks the DB for a tag match and reuses an existing file. New downloads are probed with `ffprobe` and registered automatically.

```bash
# List all clips (outputs JSON)
.venv/bin/python3 broll_db.py list

# List only clips whose file is missing from disk
.venv/bin/python3 broll_db.py list --status missing

# Scan active clips against the filesystem, mark missing
.venv/bin/python3 broll_db.py verify

# Run the usage demo
.venv/bin/python3 broll_db.py demo
```

The `/clips` page in the dashboard provides the same functionality visually: stat cards, filter tabs, expandable clip rows, and a **Verify Integrity** button.

---

## Niche Profile — Key Fields

| Field | What it controls |
|---|---|
| `research.topic_rotation` | Queue of PubMed search queries |
| `research.minimum_sample_size` | Studies below this N are rejected in Stage 2 |
| `script.segment_structure` | The 6 segments every script must include |
| `script.absolute_prohibitions` | Hard rules injected into every LLM prompt |
| `script.target_duration_seconds` | Drives voiceover pacing |
| `audio.sarvam_voice_id` | TTS voice used in Stage 4c |
| `visuals.broll_mood_map` | Mood per segment for B-roll selection |
| `thumbnail.style_variants` | The 3 thumbnail prompt styles Stage 3 must generate |
| `compliance.medical_disclaimer` | Auto-prepended by Stage 5 |
| `quality_gate` | Duration range + audio level thresholds checked in Stage 5 |

To add a new topic: append a search query to `research.topic_rotation`. Nothing else needs changing.

---

## Hard Rules

1. Never hardcode values from `niche_profile.json` in stage scripts — always read from the file.
2. Safety flags in Stage 2 are set by code, never by the LLM.
3. Observational studies must never use causal language — Stage 3 enforces this and will abort.
4. Never delete job files — failed jobs are useful for debugging.
5. The medical disclaimer must appear in every video.
6. All LLM calls have a maximum of 2 retry attempts, then abort via `mark_error()`.
7. Never use `datetime.utcnow()` — always use `datetime.now(timezone.utc)`.
