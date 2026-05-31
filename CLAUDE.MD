# Health Video Bot — Claude Code Context

Automated Hindi health education video pipeline. Produces YouTube Shorts from peer-reviewed
research, fully end-to-end: PubMed → script → assets → YouTube upload.

## What this project is

A pipeline that takes a health research topic, finds a real peer-reviewed study on PubMed,
extracts its claims with an LLM, generates a Hindi voiceover script + all YouTube metadata,
downloads B-roll and generates thumbnails, assembles the video with FFmpeg, and uploads it.

Target audience: Hindi-speaking adults (35-65) managing chronic conditions. Channel language: Hindi.

---

## Directory layout

```
health_video_bot/
├── CLAUDE.md                        ← you are here
├── niche_profile.json               ← editorial DNA — every stage reads this
├── job_schema.json                  ← canonical job state shape
├── .env                             ← API keys (never commit)
├── requirements.txt
├── orchestrator.py                  ← runs all stages in sequence (build last)
│
├── stages/
│   ├── CLAUDE.md                    ← stage-specific context
│   ├── stage_1_research.py          ← DONE
│   ├── stage_2_claim_extraction.py  ← DONE
│   ├── stage_3_content_generation.py ← DONE
│   ├── stage_4a_broll.py            ← TODO
│   ├── stage_4b_thumbnail.py        ← TODO
│   ├── stage_4c_voiceover.py        ← TODO
│   ├── stage_4d_captions.py         ← TODO
│   ├── stage_5_assembly.py          ← TODO
│   └── stage_6_upload.py            ← TODO
│
├── jobs/                            ← one JSON per job, never delete
├── assets/                          ← generated/downloaded files per job
│   ├── {job_id}/screenshots/
│   ├── {job_id}/broll/
│   ├── {job_id}/thumbnails/
│   ├── {job_id}/audio/
│   ├── {job_id}/captions/
│   ├── {job_id}/output/
│   └── music/                       ← shared background tracks (manual)
├── cache/
│   └── broll/                       ← cached clips by search term
└── logs/
```

---

## Job state — the central object

Every stage reads and writes `jobs/{job_id}.json`. The schema is in `job_schema.json`.
**Never read from anywhere else, never write to anywhere else.** Each stage:

1. Reads `niche_profile.json`
2. Reads `jobs/{job_id}.json` — checks `status` field before proceeding
3. Does its work
4. Writes its output block into the job dict
5. Sets `job["status"]` and `job["updated_at"]`
6. Saves the job JSON back to disk

Status flow (linear, no branching except `error`):
```
created → stage_1_complete → stage_2_complete → stage_3_complete
        → stage_4_complete → stage_5_complete → complete
        → error  (can occur at any stage — always written to job["error"])
```

---

## Pipeline overview

```
[Stage 1] PubMed search → PDF/screenshots → study{}
[Stage 2] LLM claim extraction + safety flags → claims{}
[Stage 3] Master LLM call → script + metadata + prompts → content{}
[Stage 4a] Pexels/Pixabay B-roll download → assets.broll_video_paths
[Stage 4b] AI image generation → assets.thumbnail_paths
[Stage 4c] Sarvam AI TTS → assets.voiceover_path
[Stage 4d] Whisper → SRT + ASS captions → assets.srt_path, ass_path
[Stage 5]  FFmpeg assembly + quality gate → output.final_video_path
[Stage 6]  YouTube Data API v3 upload → output.youtube_upload_id
```

Stages 4a–4d can run in parallel (they all read from `content{}` and write to `assets{}`).

---

## niche_profile.json — the editorial config

**This file controls everything.** Do not hardcode values from it in stage scripts.
Read it at the top of every stage with `load_niche_profile()`.

Key sections:
- `editorial` — tone, terminology rules, target audience
- `script.segment_structure` — the 6 segments every script must have
- `script.absolute_prohibitions` — injected into every LLM prompt, never violate
- `research.topic_rotation` — the queue of PubMed search topics
- `research.minimum_sample_size` — studies below this N are rejected in Stage 2
- `research.small_study_flag_threshold` — studies below this get a warning flag
- `compliance.medical_disclaimer` — text injected by Stage 5 and Stage 6
- `quality_gate` — all checks Stage 5 must pass before upload is allowed
- `visuals.broll_mood_map` — mood per segment for B-roll selection
- `thumbnail.style_variants` — the 3 thumbnail prompts Stage 3 must generate
- `audio.sarvam_voice_id` — voice to use for TTS

---

## Coding patterns — follow these exactly

### Config loading
```python
NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
LLM_MODEL          = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "auto").lower()
```

### LLM client — supports Anthropic, OpenAI, and Groq
```python
def _get_llm_client():
    model = LLM_MODEL.lower()
    if model.startswith("claude"):
        import anthropic
        return "anthropic", anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    elif LLM_PROVIDER == "groq":
        from openai import OpenAI
        return "groq", OpenAI(
            api_key=os.getenv("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1",
        )
    else:
        from openai import OpenAI
        return "openai", OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

**Groq is free and recommended for development.** Get a key at console.groq.com.
Best free models: `llama-3.3-70b-versatile` (recommended), `mixtral-8x7b-32768`, `llama-3.1-8b-instant`.
Set `LLM_PROVIDER=groq` and `LLM_MODEL=llama-3.3-70b-versatile` in `.env` to switch.

### Error handling — always write error to job
```python
def mark_error(job: dict, message: str, retries: int = 0) -> dict:
    job["status"] = "error"
    job["error"] = {"stage": "stage_N", "message": message, "retries": retries}
    save_job(job)
    print(f"[Stage N] ERROR: {message}")
    return job
```

### LLM calls — always 2 attempts max, strip markdown fences
```python
for attempt in range(1, 3):
    try:
        raw = call_llm(prompt, attempt=attempt)
        parsed = parse_llm_response(raw)
        result = MyModel(**parsed)
        break
    except json.JSONDecodeError as e:
        if attempt == 2:
            return mark_error(job, f"Invalid JSON after 2 attempts: {e}", retries=2)
        prompt += f"\n\nInvalid JSON: {e}. Return only a JSON object."
    except Exception as e:
        if attempt == 2:
            return mark_error(job, f"Validation failed after 2 attempts: {e}", retries=2)
        prompt += f"\n\nValidation failed: {e}. Fix and retry."
```

### Datetime — always timezone-aware
```python
from datetime import datetime, timezone
job["updated_at"] = datetime.now(timezone.utc).isoformat()
# NEVER use: datetime.utcnow()  ← deprecated
```

### CLI auto-picker pattern (every stage has this)
```python
if __name__ == "__main__":
    if len(sys.argv) < 2:
        # auto-pick most recent job at the right status
        candidates = []
        for jf in Path(JOBS_DIR).glob("*.json"):
            j = json.load(open(jf))
            if j.get("status") == "stage_N_complete":
                candidates.append((jf.stat().st_mtime, j["job_id"]))
        candidates.sort(reverse=True)
        job_id = candidates[0][1]
    else:
        job_id = sys.argv[1]
```

---

## What's already built

### Stage 1 — `stages/stage_1_research.py` ✅
- PubMed search via Biopython Entrez
- Citation count lookup via Semantic Scholar API
- Top 3 candidate selection (interactive or auto)
- Full abstract + metadata fetch
- PMC open-access PDF download
- Playwright screenshots of abstract + figures
- Writes `study{}` block, sets `status: stage_1_complete`

### Stage 2 — `stages/stage_2_claim_extraction.py` ✅
- Reads `study.abstract` and sends to LLM
- Extracts: core_finding, effect_size, sample_size, population, limitations, what_study_does_not_prove
- `apply_safety_flags()` — sets is_causal_language_safe, small_study_flag, below_minimum_sample
  - These flags are set by our logic, NEVER by the LLM
- If `below_minimum_sample` → aborts job (study too small for channel)
- Writes `claims{}` block with validation_warnings list

### Stage 3 — `stages/stage_3_content_generation.py` ✅
- Reads `study{}` + `claims{}`, injects niche_profile rules into prompt
- Single LLM call producing everything: hindi_script, script_segments, title, description, tags,
  broll_search_tags, thumbnail_prompts, chapter_timestamps
- Post-generation: validates causal language for observational studies
- Aborts if causal language found in observational study script
- Writes `content{}` block, sets `status: stage_3_complete`

---

## What needs to be built next

Build in this order (not the stage number order):

### Recommended build order
1. **Stage 5** — video assembly with *placeholder* assets (manually place files)
   → Get a real video file rendered before worrying about automation
2. **Stage 6** — YouTube upload
   → Confirm the API works end-to-end
3. **Stages 4a–4d** — now automate the asset generation
4. **Orchestrator** — wire it all together

### Stage 4a — `stages/stage_4a_broll.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: Pexels API first, Pixabay fallback. 2 clips per segment. Cache by search term.

### Stage 4b — `stages/stage_4b_thumbnail.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: 3 thumbnail prompts from content{}, send to image generation API, save 1280×720.

### Stage 4c — `stages/stage_4c_voiceover.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: Sarvam AI TTS, hindi_script → WAV, save to assets/{job_id}/audio/.

### Stage 4d — `stages/stage_4d_captions.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: Whisper on voiceover WAV → word-level SRT + ASS burn-in file.

### Stage 5 — `stages/stage_5_assembly.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: FFmpeg timeline — B-roll + voiceover + music + burned captions + disclaimer card.
Quality gate before marking complete.

### Stage 6 — `stages/stage_6_upload.py` (TODO)
See `stages/CLAUDE.md` for full spec.
Short version: YouTube Data API v3 — upload video, all 3 thumbnails, SRT, set metadata from content{}.

---

## Environment variables

All in `.env`, loaded by `python-dotenv` at the top of every stage:

```
ANTHROPIC_API_KEY=       # for Claude (Stages 2, 3)
OPENAI_API_KEY=          # for OpenAI LLM + DALL-E + Whisper (Stage 4d)
GROQ_API_KEY=            # free tier — recommended for dev/testing (console.groq.com)

# LLM selection
LLM_MODEL=llama-3.3-70b-versatile   # change to claude-sonnet-4-6 or gpt-4o as needed
LLM_PROVIDER=groq                   # auto | groq | openai  (auto resolves claude* → anthropic, else openai)

ENTREZ_EMAIL=            # required by PubMed ToS (any email is fine)
NCBI_API_KEY=            # optional — raises rate limit from 3 to 10 req/s

PEXELS_API_KEY=          # free at pexels.com/api
PIXABAY_API_KEY=         # free at pixabay.com/api/docs
SARVAM_API_KEY=          # for Hindi TTS

IMAGE_GEN_PROVIDER=dalle # or: vertex
OPENAI_API_KEY=          # for DALL-E
GOOGLE_APPLICATION_CREDENTIALS=  # for Vertex AI Imagen

NICHE_PROFILE_PATH=niche_profile.json
JOBS_DIR=jobs
ASSETS_DIR=assets
CACHE_DIR=cache
```

---

## Running individual stages

```bash
# Auto-pick latest job at the right status:
python stages/stage_1_research.py
python stages/stage_2_claim_extraction.py
python stages/stage_3_content_generation.py

# Or specify job_id explicitly:
python stages/stage_2_claim_extraction.py abc123-job-id
```

---

## Hard rules — never violate these

1. **Never hardcode niche_profile values in stage scripts.** Always read from the JSON.
2. **Safety flags in Stage 2 are set by our code, never by the LLM.**
3. **Observational studies (cohort, cross_sectional) must never use causal language** —
   Stage 3 enforces this and will abort if found.
4. **Never delete job files.** Failed jobs are useful for debugging.
5. **The medical disclaimer must appear** in every video (Stage 5 adds it, Stage 6 includes it in description).
6. **All LLM calls must have a max of 2 retry attempts**, then abort via `mark_error()`.
7. **Never use `datetime.utcnow()`** — use `datetime.now(timezone.utc)` instead.