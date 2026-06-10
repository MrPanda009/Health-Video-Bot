# Health Video Bot

Automated Hindi health education video pipeline. Takes a PubMed health research topic, extracts claims from a real peer-reviewed study, generates a voiceover script, downloads B-roll, assembles a full-HD video, and uploads it to YouTube. Target: Hindi-speaking adults (35–65) managing chronic conditions.

---

## What's Built

| Stage | Script | Status | What it does |
|---|---|---|---|
| 0 | `stages/stage_0_clean.py` | ✅ | Interactive job & asset cleanup utility |
| 1 | `stages/stage_1_research.py` | ✅ | Auto-selects topic (LRU) or accepts query, searches PubMed, ranks citations, filters by study cooldown, downloads PDF & captures screenshots |
| 2 | `stages/stage_2_claim_extraction.py` | ✅ | LLM claim extraction + safety flags |
| 3 | `stages/stage_3_content_generation.py` | ✅ | Master LLM call — Hindi script (enforcing Devanagari script), metadata (with study citation + direct link), thumbnail prompts, B-roll tags |
| 4a | `stages/stage_4a_broll.py` | ✅ | B-roll video downloader with Pexels/Pixabay fallback and SQLite caching |
| 4b | `stages/stage_4b_thumbnail.py` | ✅ | AI thumbnail generation (DALL-E 3 or Vertex Imagen) |
| 4c | `stages/stage_4c_voiceover.py` | ✅ | Sarvam AI Hindi TTS, chunk-splitting, WAV concatenation |
| 4d | `stages/stage_4d_captions.py` | ✅ | WhisperX transcription → SRT/ASS captions + word-level timestamps (configurable model) |
| 5 | `stages/stage_5_assembly.py` | ✅ | Remotion assembly + visual transitions & pan/zoom animations + word-highlighted Devanagari captions + animated subscribe button + quality gate |
| 6 | `stages/stage_6_upload.py` | 🔲 TODO | YouTube Data API v3 upload |

**Supporting modules (project root):**
- `study_db.py` — SQLite-backed registry tracking studies and topics (cooldown & LRU selection)
- `seed_topics.py` — Utility script to seed the `study_db` with 120+ clinical research topics
- `broll_db.py` — SQLite B-roll clip cache and registry (integrity check, deduplication, LRU reuse)
- `whisperx_transcriber.py` — WhisperX-based audio transcription returning word-level timestamps
- `edit_decision.py` — Generates an EDL JSON from a transcript and the B-roll clip database
- `video_assembler.py` — Overlays B-roll from an EDL onto a base A-roll video using Remotion with custom transitions/animations
- `niche_profile.json` — all editorial config; never hardcode values from it in stage scripts
- `job_schema.json` — canonical shape of a job state object
- `settings.json` — global persistent configuration settings (assembly & pipeline parameters)

**Frontend dashboard (`frontend/`):**
- Next.js + React + Tailwind CSS
- **Jobs dashboard** — jobs list with live status polling, render mode/Whisper model configuration, stage runner execution, and live stdout log streaming
- **Clips Library (`/clips`)** — browse and filter cached B-roll clips, and visually run integrity checks on files
- **Models page (`/models`)** — check which WhisperX models are downloaded, and download missing ones with live progress streaming
- **Topics dashboard (`/topics`)** — view, add, or deactivate PubMed search queries, with stats on topic utilization
- **Studies registry (`/studies`)** — view all used papers, publication details, and monitor their active/cooldown status
- **Settings panel (`/settings`)** — view and edit the application's global configuration parameters (`settings.json`)

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
├── study_db.py                 # SQLite study and topic database registry
├── seed_topics.py              # Seeds 120+ default clinical research topics into DB
├── broll_db.py                 # SQLite B-roll clip registry
├── whisperx_transcriber.py     # WhisperX transcription with word-level timestamps
├── edit_decision.py            # EDL generator: transcript → clip placements
├── video_assembler.py          # Remotion assembler: base video + EDL → final video
├── niche_profile.json          # Editorial DNA — all stages read this
├── job_schema.json             # Canonical job state schema
├── settings.json               # Global persistent config (read by frontend and stages)
│
├── stages/
│   ├── model_manager.py        # CLI: check/download WhisperX models (called by frontend)
│   ├── stage_0_clean.py        # Interactive job & asset cleanup
│   ├── stage_1_research.py     # PubMed search & study extraction (LRU topic, cooldown checks)
│   ├── stage_2_claim_extraction.py
│   ├── stage_3_content_generation.py
│   ├── stage_4a_broll.py
│   ├── stage_4b_thumbnail.py
│   ├── stage_4c_voiceover.py
│   ├── stage_4d_captions.py    # WhisperX → SRT/ASS + word-level timestamps
│   └── stage_5_assembly.py     # Remotion assembly + animations/transitions + quality gate
│
├── remotion/                   # Remotion video composition project (React-based)
│   ├── package.json
│   ├── remotion.config.ts
│   └── src/
│       ├── index.ts            # Composition registry
│       ├── HealthVideoComposition.tsx   # Stage 5 full-pipeline video
│       ├── EDLComposition.tsx  # Standalone EDL assembler composition
│       └── components/         # DisclaimerCard, BRollSegment, CaptionOverlay, SubscribeButton
│
├── frontend/                   # Next.js dashboard
│   ├── app/
│   │   ├── jobs/               # Job list + per-job detail pages
│   │   ├── clips/              # Clip library page
│   │   ├── models/             # WhisperX model download page
│   │   ├── topics/             # Topics management page
│   │   ├── studies/            # Studies registry page
│   │   ├── settings/           # Global settings management panel
│   │   └── api/
│   │       ├── jobs/           # Job CRUD + stage runner + SSE log streaming
│   │       ├── clips/          # Clip library + integrity verify
│   │       ├── models/         # Model status check + download SSE stream
│   │       ├── topics/         # CRUD for topics database
│   │       ├── studies/        # Reads study records & stats
│   │       └── settings/       # Reads and writes settings.json
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
│   │   ├── captions/           # word_timestamps.json + captions.srt + captions.ass
│   │   └── output/
│   ├── intro.mp4               # Optional — prepended to every video
│   ├── outro.mp4               # Optional — appended to every video
│   └── music/                  # Shared background tracks (manual)
│
└── cache/
    ├── broll/                  # Cached clips by search-term slug (populated before copying)
    ├── broll_cache.db          # SQLite B-roll registry (managed by broll_db.py)
    └── study_db.sqlite         # SQLite studies & topics database (managed by study_db.py)
```

---

## Pipeline Flow

```
                  [StudyDB (Topics)]
                         │ (LRU selection)
                         ▼
[Stage 1]  PubMed search → PDF/screenshots → check cooldown → update StudyDB → study{}
[Stage 2]  LLM claim extraction + safety flags → claims{}
[Stage 3]  Master LLM call → hindi_script + metadata + prompts → content{}
               ↓                    ↓                   ↓              ↓
[Stage 4a] B-roll download   [Stage 4b] Thumbnails  [Stage 4c] TTS   [Stage 4d] Captions (model select)
               └──────────────────────┴───────────────────┴──────────────┘
                               → assets{}  (status → stage_4_complete)
[Stage 5]  Remotion assembly + transitions/animations + word-highlighted captions + animated subscribe button → output/video.mp4
[Stage 6]  YouTube upload (TODO)
```

**Standalone editing pipeline** (independent of the job flow — used when you have A-roll footage):
```
audio file
    ↓  whisperx_transcriber.py
transcript JSON (word-level timestamps)
    ↓  edit_decision.py
EDL JSON (clip placements)
    ↓  video_assembler.py (with default transitions/animations)
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
               pydub pillow python-dotenv numpy
playwright install chromium
```

FFmpeg must be installed at the system level (required by the quality gate and ffprobe):
```bash
brew install ffmpeg        # macOS
sudo apt install ffmpeg    # Ubuntu/Debian
```

**For Stage 4d (WhisperX captions)** — install separately after PyTorch:
```bash
pip install torch
pip install whisperx
# Then download models from the dashboard at /models, or via CLI:
python stages/model_manager.py download large-v3
python stages/model_manager.py download align-hi
```

### 2. Remotion (video rendering)

```bash
cd remotion
npm install
```

The first render will also download Chrome Headless Shell (~94 MB, one-time, cached automatically).

To preview compositions in the browser:
```bash
cd remotion && npx remotion studio src/index.ts   # opens http://localhost:3000
```

### 3. Frontend

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

### 4. Environment variables (`.env` at project root)

```env
# LLM — pick one provider
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
GROQ_API_KEY=              # Free tier — recommended for dev (console.groq.com)

# Default LLM configuration
LLM_MODEL=llama-3.3-70b-versatile   # or claude-sonnet-4-6, gpt-4o
LLM_PROVIDER=groq                   # auto | groq | openai | anthropic

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

### 5. One-time manual setup

- [ ] Set `channel.youtube_channel_id` in `niche_profile.json`
- [ ] Test Sarvam AI voices and set `audio.sarvam_voice_id` in `niche_profile.json`
- [ ] Download 5–8 royalty-free background tracks → `assets/music/`
- [ ] Optionally create `assets/intro.mp4` (≤3 s) and `assets/outro.mp4` (≤5 s)
- [ ] Seed default research topics: `python seed_topics.py`
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

# Stage 4d — requires whisperx. Can explicitly supply model size
.venv/bin/python3 stages/stage_4d_captions.py <job_id> --model large-v3

# Stage 5 Assembly — can pass draft flag, transition preferences, and image animations
.venv/bin/python3 stages/stage_5_assembly.py <job_id> --draft --animation-type ken_burns --transition-type crossfade --transition-duration 0.4

# Pass a job_id explicitly to any stage
.venv/bin/python3 stages/stage_2_claim_extraction.py <job_id>

# Stage 1 research parameters (topic, PMID override, aspect ratio - all optional)
.venv/bin/python3 stages/stage_1_research.py "gut microbiome diabetes" "" 9:16
.venv/bin/python3 stages/stage_1_research.py "" 38452901 16:9

# Clean up old jobs and unused assets
.venv/bin/python3 stages/stage_0_clean.py
```

### Standalone editing pipeline

```bash
# Transcribe audio → word-level timestamps JSON
.venv/bin/python3 whisperx_transcriber.py voiceover.wav hi large-v3

# Generate EDL from transcript + B-roll DB
.venv/bin/python3 edit_decision.py transcript.json edl.json

# Preview the edit plan before rendering
.venv/bin/python3 video_assembler.py --preview edl.json

# Render final video (B-roll overlaid on A-roll with custom transitions and animations)
.venv/bin/python3 video_assembler.py base_footage.mp4 edl.json final.mp4 --transition-type crossfade --animation-type ken_burns --transition-duration 0.4
```

### WhisperX model management

```bash
# Check which models are downloaded
.venv/bin/python3 stages/model_manager.py status

# Download a specific model
.venv/bin/python3 stages/model_manager.py download large-v3
.venv/bin/python3 stages/model_manager.py download align-hi
```

### Study & Topic Database Management

```bash
# List all topics in the DB
.venv/bin/python3 study_db.py topics list

# Add a new research topic query
.venv/bin/python3 study_db.py topics add "cardiovascular disease risk factors South Asian adults"

# Deactivate/Remove a topic (soft-delete)
.venv/bin/python3 study_db.py topics remove <topic_uuid>

# List study usage history
.venv/bin/python3 study_db.py studies list --status cooldown
```

### Dashboard

```bash
cd frontend && npm run dev
```

Open [http://localhost:3000](http://localhost:3000). Use the navigation to:
- **Jobs** — create/delete jobs, configure render mode & Whisper model, run pipeline stages, stream logs live
- **Clips** — browse the B-roll library, verify file integrity
- **Models** — check WhisperX model download status, download missing models
- **Topics** — manage search terms, add new queries, view topic stats
- **Studies** — view paper history, track cooldown statuses
- **Settings** — edit global transition options, default models, and visual animations

---

## Study & Topic Database (`study_db.py`)

To ensure content variety, the pipeline maintains a SQLite database (`cache/study_db.sqlite`) containing two tables:
1. **`topics`**: The pool of PubMed search terms. Each topic has an `active` status and a `times_used` counter. If no topic is passed to Stage 1, it queries this table and selects the active topic with the **least uses / oldest usage date (Least Recently Used - LRU)**.
2. **`studies`**: A registry of every paper processed by the pipeline. When a study is selected, it enters a cooldown phase of `study_cooldown_days` (default `30` days, configured in `niche_profile.json`).

### Cooldown and Auto-Fallback
During Stage 1:
- If a candidate paper from the current topic's search results is in active cooldown, it is skipped.
- If **all** candidate papers for the selected topic are in cooldown, Stage 1 will automatically fall back and search the subsequent active topics in the database (ordered by oldest usage) until it finds a topic with eligible, non-cooldown papers.
- Once a study is selected, the database records the paper's metadata, flags the study as in cooldown, and increments the usage counter for that topic.

The initial database can be populated with over 120 curated clinical topics using `python seed_topics.py`.

---

## Global Settings (`settings.json`)

Persistent global configuration is stored in `settings.json` and is editable through the `/settings` tab in the dashboard. The config structure contains:

```json
{
  "assembly": {
    "animations_enabled": true,
    "animation_type": "ken_burns",
    "transitions_enabled": true,
    "transition_type": "crossfade",
    "transition_duration": 0.2
  },
  "pipeline": {
    "default_render_mode": "final",
    "default_whisper_model": "large-v3"
  }
}
```

* **`assembly.animations_enabled`**: Toggle panning/zooming animations on static image clips (screenshots).
* **`assembly.animation_type`**: Visual style for image overlays (`ken_burns` | `slide_in` | `zoom_punch` | `none`).
* **`assembly.transitions_enabled`**: Enable overlap transition fades between video clips.
* **`assembly.transition_type`**: Transition style (`crossfade` | `none`).
* **`assembly.transition_duration`**: Duration of the overlap transition in seconds.
* **`pipeline.default_render_mode`**: Select standard `final` resolution or fast `draft` mode.
* **`pipeline.default_whisper_model`**: Default WhisperX model size for transcribing text.

---

## Aesthetics: Transitions, Animations & Subtitles

Stage 5 (`stage_5_assembly.py`) and `video_assembler.py` both use **Remotion** (React-based video composition) for all visual rendering. All animations and transitions are declarative React components — no MoviePy, no FFmpeg filter graphs.

### 1. Clip Transitions
Crossfade transitions between B-roll clips are handled natively in Remotion via CSS opacity interpolation across overlapping `<Sequence>` boundaries. Set `--transition-type crossfade` and `--transition-duration` to control the overlap.

### 2. Image Animations
Screenshot figures or still images in B-roll slots can be animated with one of three styles, all implemented as Remotion `interpolate()` transforms:

* **Ken Burns (`ken_burns`)**: Smooth 1.0× → 1.15× center zoom over the clip duration via CSS `scale` interpolation.
* **Slide In (`slide_in`)**: Translates the image onto the screen from the right over 0.3 s, holds, then exits left — driven by `translateX` interpolation.
* **Zoom Punch (`zoom_punch`)**: Grows from 95% to 105% over the clip — a subtle energy effect via CSS `scale`.

### 3. Hindi (Devanagari) Captions
Word-highlighted captions are rendered natively in the browser engine (Remotion uses headless Chrome), which handles Devanagari shaping and ligatures correctly without any system font configuration:

* **Word timestamps** from WhisperX (`whisper_word_timestamps`) are grouped into short phrase chunks (≤5 words per line).
* The **currently spoken word** is highlighted in gold (`#FFD700`); remaining words in the chunk are white.
* Text is positioned at the bottom 8% of the frame with a multi-directional text shadow for legibility on any background.
* No ASS burn-in, no PIL rendering, no ffmpeg libass dependency.

### 4. Animated Subscribe Button
The subscribe call-to-action appears in the last 7 seconds of every video as a pure React component — no `assets/subscribe.mp4` file required. It enters with a spring animation (slide up from bottom) and features a pulsing bell icon.

---

## WhisperX Models

Stage 4d and the standalone `whisperx_transcriber.py` require two model downloads (stored in `~/.cache/huggingface/hub/`):

| Model ID | Type | Size | Use |
|---|---|---|---|
| `large-v3` | Transcription | ~3.1 GB | Recommended for production (latest model) |
| `large-v2` | Transcription | ~3.1 GB | Standard large model |
| `medium` | Transcription | ~1.5 GB | Faster, slightly less accurate |
| `small` | Transcription | ~0.5 GB | Dev/testing |
| `align-hi` | Alignment | ~1.2 GB | Word-level timestamps in Hindi |

If a model isn't downloaded, Stage 4d prints a clear error message pointing to the Models dashboard. Stage 5 (Remotion) handles the absence of Stage 4d output gracefully — caption overlay is skipped and segment timing falls back to `duration_hint_seconds`.

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
| `research.topic_rotation` | Queue of PubMed search queries used if DB is empty |
| `research.study_cooldown_days` | Number of days a selected study remains in cooldown (default: 30) |
| `research.minimum_sample_size` | Studies below this N are rejected in Stage 2 |
| `script.segment_structure` | The 6 segments every script must include |
| `script.absolute_prohibitions` | Hard rules injected into every LLM prompt |
| `script.target_duration_seconds` | Drives voiceover pacing (currently 90s) |
| `audio.sarvam_voice_id` | TTS voice used in Stage 4c (defaults to Bulbul Bulbul) |
| `visuals.broll_mood_map` | Mood per segment for B-roll selection |
| `thumbnail.style_variants` | The 3 thumbnail prompt styles Stage 3 must generate |
| `compliance.medical_disclaimer` | Auto-prepended by Stage 5 |
| `quality_gate` | Duration range + audio level thresholds checked in Stage 5 |

To add a new topic: Append a search query directly in the `/topics` UI dashboard, or run the CLI add command.

---

## Hard Rules

1. Never hardcode values from `niche_profile.json` in stage scripts — always read from the file.
2. Safety flags in Stage 2 are set by code, never by the LLM.
3. Observational studies must never use causal language — Stage 3 enforces this and will abort.
4. Never delete job files — failed jobs are useful for debugging.
5. The medical disclaimer must appear in every video.
6. All LLM calls have a maximum of 2 retry attempts, then abort via `mark_error()`.
7. Never use `datetime.utcnow()` — always use `datetime.now(timezone.utc)`.
