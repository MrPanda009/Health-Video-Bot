# Health Video Bot — Codex Context

Automated Hindi health education video pipeline. Produces YouTube Shorts from peer-reviewed
research, fully end-to-end: PubMed → script → assets → YouTube upload.

## What this project is

A pipeline that takes a health research topic, finds a real peer-reviewed study on PubMed,
extracts its claims with an LLM, generates a Hindi voiceover script + all YouTube metadata,
downloads B-roll and generates thumbnails, assembles the video with Remotion, and uploads it.

Target audience: Hindi-speaking adults (35-65) managing chronic conditions. Channel language: Hindi.

---

## Directory layout

```
health_video_bot/
├── AGENTS.md                        ← you are here
├── niche_profile.json               ← editorial DNA — every stage reads this
├── job_schema.json                  ← canonical job state shape
├── .env                             ← API keys (never commit)
│
├── broll_db.py                      ← SQLite clip registry (dedup, LRU, integrity)
├── whisperx_transcriber.py          ← WhisperX transcription → word-level timestamps
├── edit_decision.py                 ← transcript + clip DB → EDL JSON
├── video_assembler.py               ← EDL + base video → final video (Remotion)
│
├── stages/
│   ├── AGENTS.md                    ← stage-specific context
│   ├── model_manager.py             ← CLI: check/download WhisperX models
│   ├── stage_1_research.py          ← DONE
│   ├── stage_2_claim_extraction.py  ← DONE
│   ├── stage_3_content_generation.py ← DONE
│   ├── stage_4a_broll.py            ← DONE
│   ├── stage_4b_thumbnail.py        ← DONE
│   ├── stage_4c_voiceover.py        ← DONE
│   ├── stage_4d_captions.py         ← DONE (WhisperX → SRT + word timestamps)
│   ├── stage_5_assembly.py          ← DONE (MoviePy assembly + quality gate)
│   └── stage_6_upload.py            ← TODO
│
├── jobs/                            ← one JSON per job, never delete
├── assets/                          ← generated/downloaded files per job
│   ├── {job_id}/screenshots/
│   ├── {job_id}/broll/
│   ├── {job_id}/thumbnails/
│   ├── {job_id}/audio/
│   ├── {job_id}/captions/           ← word_timestamps.json + captions.srt (from 4d)
│   ├── {job_id}/output/
│   └── music/                       ← shared background tracks (manual)
├── cache/
│   ├── broll/                       ← cached clips by search term
│   └── broll_cache.db               ← SQLite clip registry
├── remotion/                        ← Remotion video composition project
│   ├── package.json
│   ├── remotion.config.ts
│   └── src/
│       ├── index.ts                 ← composition registry
│       ├── HealthVideoComposition.tsx  ← main stage 5 video
│       ├── EDLComposition.tsx       ← standalone EDL assembler
│       └── components/              ← DisclaimerCard, BRollSegment, CaptionOverlay, SubscribeButton
└── frontend/                        ← Next.js dashboard
    └── app/
        ├── jobs/
        ├── clips/
        ├── models/                  ← WhisperX model download page
        └── api/
            ├── jobs/
            ├── clips/
            └── models/              ← model status + download SSE stream
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
[Stage 4d] WhisperX → word_timestamps.json + SRT → assets.srt_path, whisper_word_timestamps
[Stage 5]  Remotion assembly + quality gate → output.final_video_path
[Stage 6]  YouTube Data API v3 upload → output.youtube_upload_id  ← TODO
```

Stages 4a–4d can run in parallel. Stage 4d requires whisperx + downloaded models;
Stage 5 handles its absence gracefully (uses `duration_hint_seconds` for segment timing,
skips word-highlighted caption overlay).

### Standalone editing pipeline (independent of job flow)
```
audio file → whisperx_transcriber.py → transcript JSON (word-level)
           → edit_decision.py        → EDL JSON (clip placements)
           → video_assembler.py      → final video (B-roll over A-roll)
```

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
LLM_MODEL          = os.getenv("LLM_MODEL", "Codex-sonnet-4-6")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "auto").lower()
```

### LLM client — supports Anthropic, OpenAI, and OpenAI-compatible providers (Groq, NVIDIA, OpenRouter)
```python
# OpenAI-compatible providers: provider -> (base_url, api_key_env_var)
_OPENAI_COMPAT = {
    "groq":       ("https://api.groq.com/openai/v1",       "GROQ_API_KEY"),
    "nvidia":     ("https://integrate.api.nvidia.com/v1",  "NVIDIA_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1",         "OPENROUTER_API_KEY"),
}

def _get_llm_client():
    """Return (provider_name, client) based on LLM_MODEL / LLM_PROVIDER env vars."""
    provider = LLM_PROVIDER
    if provider == "auto":
        provider = "anthropic" if LLM_MODEL.lower().startswith("Codex") else "openai"
    if provider == "anthropic":
        import anthropic
        return "anthropic", anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    if provider in _OPENAI_COMPAT:
        base_url, key_env = _OPENAI_COMPAT[provider]
        from openai import OpenAI
        return provider, OpenAI(api_key=os.getenv(key_env), base_url=base_url)
    from openai import OpenAI
    return "openai", OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
```

`LLM_PROVIDER` accepts `auto | anthropic | openai | groq | nvidia | openrouter`. Groq, NVIDIA, and
OpenRouter are OpenAI-compatible — same SDK, custom `base_url`. The provider/model and per-provider
API keys are also editable from the dashboard Settings page (writes to `.env`).
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

### Remotion patterns (Stage 5 and video_assembler.py)
Stage 5 and `video_assembler.py` both render via the Remotion CLI. Never use MoviePy.

```python
# Invoke Remotion render from Python (Stage 5 pattern)
_REMOTION_DIR = Path(__file__).resolve().parent.parent / "remotion"

def render_with_remotion(props: dict, output_path: Path, props_file: Path) -> None:
    props_file.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    cmd = [
        "npx", "remotion", "render",
        "src/index.ts",
        "HealthVideoComposition",   # or "EDLComposition"
        str(output_path.resolve()),
        f"--props={props_file.resolve()}",
        "--log=quiet",
    ]
    result = subprocess.run(cmd, cwd=str(_REMOTION_DIR), text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Remotion render failed (exit {result.returncode})")
```

Key Remotion rules:
- All asset paths in props must be **absolute** paths; components use `file://` prefix
- `HealthVideoComposition` props are defined in `remotion/src/types.ts`
- `EDLComposition` props are defined in `remotion/src/types.ts`
- Remotion must be installed: `cd remotion && npm install`
- Studio preview: `cd remotion && npx remotion studio src/index.ts`

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

### Stage 4a — `stages/stage_4a_broll.py` ✅
- Pexels API first, Pixabay fallback. 2 clips per segment. Cache by search term.
- Does NOT change job status (frontend API sets stage_4_complete after all 4x sub-stages complete)

### Stage 4b — `stages/stage_4b_thumbnail.py` ✅
- 3 thumbnail prompts from content{}, send to DALL-E 3 or Vertex Imagen, resize to 1280×720
- Does NOT change job status

### Stage 4c — `stages/stage_4c_voiceover.py` ✅
- Splits hindi_script into ≤500-char chunks at sentence boundaries
- Calls Sarvam AI TTS for each chunk (bulbul:v3, retry once on failure)
- Concatenates WAVs with pydub, measures duration
- Does NOT change job status

### Stage 4d — `stages/stage_4d_captions.py` ✅
- Requires: whisperx + PyTorch installed, plus models downloaded via `model_manager.py`
- Transcribes `assets.voiceover_path` with WhisperX (Hindi, large-v2 by default)
- Forced alignment produces word-level timestamps
- Saves `assets/{job_id}/captions/word_timestamps.json` and `captions.srt`
- Writes `job["assets"]["whisper_word_timestamps"]`, `job["assets"]["srt_path"]`, `job["assets"]["ass_path"]`
- If whisperx is not installed or model is not downloaded → marks job error with install instructions
- Does NOT change job status
- Stage 5 handles absence gracefully: skips word-highlighted captions, uses duration_hint_seconds for timing

### Stage 5 — `stages/stage_5_assembly.py` ✅
- Assembles video using **Remotion** (`npx remotion render HealthVideoComposition`)
- Timeline: [optional intro] → 3s disclaimer card → B-roll/screenshots per segment → [optional outro]
- Voiceover audio at 100%; optional background music at 15% via Remotion `<Audio volume={0.15} />`
- Scale-to-fill + center-crop on all clips via CSS `object-fit: cover`; B-roll loops automatically
- Word-highlighted captions from `whisper_word_timestamps` rendered natively in React (no FFmpeg)
- Animated subscribe button (last 7 s) built in React — no `assets/subscribe.mp4` needed
- Accepts `stage_4_complete` or `stage_3_complete` (dev mode with manually placed assets)
- Quality gate: duration, audio levels via ffprobe/volumedetect — unchanged
- Sets `status: stage_5_complete`

### Standalone modules

**`whisperx_transcriber.py`**
- `transcribe(audio_path, language, model_size, device)` → list of segment dicts with word timestamps
- `transcribe_to_file(audio_path, output_json_path, language)` → saves result to JSON
- Auto-detects CUDA; uses float16 on GPU, int8 on CPU
- Alignment failures degrade gracefully (returns segment-level timestamps without word detail)
- Clear ImportError / RuntimeError if whisperx not installed or model not downloaded

**`edit_decision.py`**
- `extract_keywords(text, max_terms)` → offline Hindi noun extraction (split, stopwords, length sort)
- `generate_edl(segments, clip_db_path)` → queries ClipDB.find_by_tags(), returns EDL list
- `edl_to_json(edl, output_path)` → saves EDL to JSON

**`video_assembler.py`**
- `preview_edl(edl_path)` → prints time/clip/text summary to terminal
- `assemble(base_video_path, edl_path, output_path)` → overlays B-roll on A-roll via Remotion
  - B-roll clips fully replace video track (not transparent overlay); base audio always kept
  - Images get Ken Burns animation by default; videos loop to fill their window
  - Renders via `npx remotion render EDLComposition` — requires `cd remotion && npm install`

**`stages/model_manager.py`**
- `python stages/model_manager.py status` → JSON: all 5 known models + HuggingFace cache check
- `python stages/model_manager.py download <id>` → streams download progress (SSE-friendly stdout)
- Called by the frontend `/api/models` and `/api/models/download` routes
- Known models: `large-v2`, `large-v3`, `medium`, `small` (transcription) + `align-hi` (Hindi alignment)

---

## What needs to be built next

1. **Stage 6** — YouTube upload

### Stage 6 — `stages/stage_6_upload.py` (TODO)
See `stages/AGENTS.md` for full spec.
Short version: YouTube Data API v3 — upload video, all 3 thumbnails, SRT, set metadata from content{}.

---

## Environment variables

All in `.env`, loaded by `python-dotenv` at the top of every stage:

```
ANTHROPIC_API_KEY=       # for Codex (Stages 2, 3)
OPENAI_API_KEY=          # for OpenAI LLM + DALL-E
GROQ_API_KEY=            # free tier — recommended for dev/testing (console.groq.com)

# LLM selection
LLM_MODEL=llama-3.3-70b-versatile   # change to Codex-sonnet-4-6 or gpt-4o as needed
LLM_PROVIDER=groq                   # auto | groq | openai  (auto resolves Codex* → anthropic, else openai)

ENTREZ_EMAIL=            # required by PubMed ToS (any email is fine)
NCBI_API_KEY=            # optional — raises rate limit from 3 to 10 req/s

PEXELS_API_KEY=          # free at pexels.com/api
PIXABAY_API_KEY=         # free at pixabay.com/api/docs
SARVAM_API_KEY=          # for Hindi TTS

IMAGE_GEN_PROVIDER=dalle # or: vertex
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
python stages/stage_4a_broll.py
python stages/stage_4b_thumbnail.py
python stages/stage_4c_voiceover.py
python stages/stage_4d_captions.py    # requires whisperx + downloaded models
python stages/stage_5_assembly.py

# Or specify job_id explicitly:
python stages/stage_2_claim_extraction.py abc123-job-id

# Standalone editing pipeline:
python whisperx_transcriber.py voiceover.wav hi large-v2
python edit_decision.py transcript.json edl.json
python video_assembler.py --preview edl.json
python video_assembler.py base.mp4 edl.json final.mp4

# WhisperX model management:
python stages/model_manager.py status
python stages/model_manager.py download large-v2
python stages/model_manager.py download align-hi
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
8. **Video assembly uses Remotion only** — never use MoviePy in stage 5 or video_assembler.py. All rendering goes through `npx remotion render` in the `remotion/` project.
