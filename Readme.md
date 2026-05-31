# Health Video Bot

Automated Hindi health education video pipeline. Takes a PubMed health research topic, extracts claims from a real peer-reviewed study, generates a voiceover script, downloads B-roll, assembles a full-HD video, and is ready for YouTube upload. Target: Hindi-speaking adults (35–65) managing chronic conditions.

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
| 4d | `stages/stage_4d_captions.py` | ⏭ Skipped | Whisper SRT/ASS (Stage 5 handles its absence gracefully) |
| 5 | `stages/stage_5_assembly.py` | ✅ | FFmpeg assembly + quality gate |
| 6 | `stages/stage_6_upload.py` | 🔲 TODO | YouTube Data API v3 upload |

**Supporting modules:**
- `broll_db.py` — SQLite clip registry (dedup, LRU reuse, integrity checking)
- `niche_profile.json` — all editorial config; never hardcode values from it in stage scripts
- `job_schema.json` — canonical shape of a job state object

**Frontend dashboard (`frontend/`):**
- Next.js 16 + React 19 + Tailwind CSS 4
- Jobs list with live status polling
- Per-job pipeline timeline — run any stage and stream its stdout in real time
- Job data explorer (study, claims, script, assets, output)
- Clip Library page — browse, filter by status, and verify the B-roll SQLite database
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
├── broll_db.py              # SQLite clip registry
├── niche_profile.json       # Editorial DNA — all stages read this
├── job_schema.json          # Canonical job state schema
│
├── stages/
│   ├── stage_0_clean.py     # Interactive job & asset cleanup
│   ├── stage_1_research.py
│   ├── stage_2_claim_extraction.py
│   ├── stage_3_content_generation.py
│   ├── stage_4a_broll.py
│   ├── stage_4b_thumbnail.py
│   ├── stage_4c_voiceover.py
│   └── stage_5_assembly.py
│
├── frontend/                # Next.js dashboard
│   ├── app/
│   │   ├── jobs/            # Job list + per-job detail pages
│   │   ├── clips/           # Clip library page
│   │   └── api/             # jobs, clips, assets, stage-runner routes
│   ├── components/
│   └── hooks/
│
├── jobs/                    # One JSON per job — never delete
│
├── assets/
│   ├── {job_id}/
│   │   ├── screenshots/
│   │   ├── broll/
│   │   ├── thumbnails/
│   │   ├── audio/
│   │   ├── captions/
│   │   └── output/
│   ├── intro.mp4            # Optional — prepended to every video
│   ├── outro.mp4            # Optional — appended to every video
│   └── music/               # Shared background tracks (manual)
│
└── cache/
    ├── broll/               # Cached clips by search-term slug
    └── broll_cache.db       # SQLite clip registry (managed by broll_db.py)
```

---

## Pipeline Flow

```
[Stage 1]  PubMed search → PDF/screenshots → study{}
[Stage 2]  LLM claim extraction + safety flags → claims{}
[Stage 3]  Master LLM call → hindi_script + metadata + prompts → content{}
               ↓                    ↓                   ↓
[Stage 4a] B-roll download   [Stage 4b] Thumbnails  [Stage 4c] TTS voiceover
               └──────────────────────┴───────────────────┘
                              → assets{}  (status → stage_4_complete)
[Stage 5]  FFmpeg assembly + quality gate → output/video.mp4
[Stage 6]  YouTube upload (TODO)
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
               pydub pillow python-dotenv
playwright install chromium
```

FFmpeg must be installed at the system level:
```bash
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Ubuntu/Debian
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

**Dev shortcut:** Groq is free and fast enough for stages 2 & 3. Get a key at [console.groq.com](https://console.groq.com).

### 4. One-time manual setup

- [ ] Set `channel.youtube_channel_id` in `niche_profile.json`
- [ ] Test Sarvam AI voices and set `audio.sarvam_voice_id` in `niche_profile.json`
- [ ] Download 5–8 royalty-free background tracks → `assets/music/`
- [ ] Optionally create `assets/intro.mp4` (≤3 s) and `assets/outro.mp4` (≤5 s)

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
.venv/bin/python3 stages/stage_5_assembly.py

# Pass a job_id explicitly
.venv/bin/python3 stages/stage_2_claim_extraction.py <job_id>

# Stage 1 — topic, PMID, and aspect ratio (all optional)
.venv/bin/python3 stages/stage_1_research.py "gut microbiome diabetes" "" 9:16
.venv/bin/python3 stages/stage_1_research.py "" 38452901 16:9

# Clean up old jobs
.venv/bin/python3 stages/stage_0_clean.py
```

### Dashboard

```bash
cd frontend && npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Click **New Job**, choose an output format, enter a topic or PMID, then use the Pipeline Timeline to run each stage with live log streaming.

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

The `/clips` page in the dashboard provides the same functionality with a visual interface: stat cards, per-status filter tabs, expandable clip rows showing source URL and full filepath, and a **Verify Integrity** button.

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
