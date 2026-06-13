"""
Stage 3 — Content Generation
==============================
The single most important stage. One LLM API call that generates everything
the rest of the pipeline needs:

  - Hindi voiceover script (segmented to match niche_profile structure)
  - YouTube title, description, tags
  - B-roll search terms per script segment
  - 3 thumbnail image generation prompts
  - Chapter timestamps

The prompt is constructed dynamically from the job's claims{} block and the
niche_profile's editorial rules, tone, compliance requirements, and format.
Safety flags from Stage 2 constrain what language can be used.

Reads from:  jobs/{job_id}.json  (claims{} must be present)
             niche_profile.json
Writes to:   jobs/{job_id}.json  (content{} block)

Exit status: "stage_3_complete" or "error"
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
LLM_MODEL          = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
LLM_PROVIDER       = os.getenv("LLM_PROVIDER", "auto").lower()


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
        provider = "anthropic" if LLM_MODEL.lower().startswith("claude") else "openai"
    if provider == "anthropic":
        import anthropic
        return "anthropic", anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    if provider in _OPENAI_COMPAT:
        base_url, key_env = _OPENAI_COMPAT[provider]
        from openai import OpenAI
        return provider, OpenAI(api_key=os.getenv(key_env), base_url=base_url)
    from openai import OpenAI
    return "openai", OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# ─── Pydantic models ──────────────────────────────────────────────────────────

class ScriptSegment(BaseModel):
    name: str                    # must match niche_profile segment_structure names
    hindi_text: str
    duration_hint_seconds: int
    broll_mood: str              # matches niche_profile visuals.broll_mood_map


class BrollTagSet(BaseModel):
    segment_name: str
    search_terms: list[str]      # English terms for Pexels/Pixabay


class ThumbnailPrompt(BaseModel):
    variant_id: str              # data_visual | human_lifestyle | concept_abstract
    prompt: str                  # English image generation prompt


class ChapterTimestamp(BaseModel):
    title: str
    estimated_start_seconds: int


class ContentBlock(BaseModel):
    """Full content output — written into job content{} block."""
    hindi_script: str
    script_segments: list[ScriptSegment]
    title: str
    description: str
    tags: list[str]
    broll_search_tags: list[BrollTagSet]
    thumbnail_prompts: list[ThumbnailPrompt]
    chapter_timestamps: list[ChapterTimestamp]
    validation_passed: bool = True
    validation_notes: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def title_length(cls, v):
        if len(v) > 70:
            raise ValueError(f"Title too long ({len(v)} chars) — must be under 70")
        return v

    @field_validator("tags")
    @classmethod
    def enough_tags(cls, v):
        if len(v) < 20:
            raise ValueError(f"Need at least 20 tags, got {len(v)}")
        return v

    @field_validator("script_segments")
    @classmethod
    def required_segments(cls, v):
        names = {s.name for s in v}
        required = {"hook", "finding", "caveat"}
        missing = required - names
        if missing:
            raise ValueError(f"Missing required segments: {missing}")
        return v

    @field_validator("hindi_script")
    @classmethod
    def script_not_empty(cls, v):
        if not v or len(v.strip()) < 50:
            raise ValueError("hindi_script is too short or empty")
        return v.strip()


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


def mark_error(job: dict, message: str, retries: int = 0) -> dict:
    job["status"] = "error"
    job["error"] = {"stage": "stage_3", "message": message, "retries": retries}
    save_job(job)
    print(f"[Stage 3] ERROR: {message}")
    return job


# ─── Prompt construction ──────────────────────────────────────────────────────

def build_content_prompt(study: dict, claims: dict, profile: dict) -> str:
    """
    Build the master content generation prompt.

    This prompt injects:
    - Study facts and extracted claims (from job state)
    - Niche profile rules (tone, terminology, segment structure, prohibitions)
    - Safety flags from Stage 2 (controls causal language, disclaimers)
    - Format requirements (word count, segment lengths)
    - Full JSON output schema

    The LLM must produce a single JSON object with everything needed for
    Stages 4-6 to run without additional LLM calls.
    """

    # Build segment instructions from profile
    segments = profile["script"]["segment_structure"]
    segment_instructions = "\n".join([
        f"  - {s['name']} ({s['duration_seconds']}s, ~{s.get('target_word_count', '?')} words): {s['purpose']}"
        for s in segments
    ])

    # Build broll mood map
    broll_moods = profile["visuals"]["broll_mood_map"]
    broll_mood_str = "\n".join([f"  - {seg}: {mood}" for seg, mood in broll_moods.items()])

    # Safety language rule
    if not claims.get("is_causal_language_safe"):
        causal_rule = (
            "⚠ CRITICAL: This is an OBSERVATIONAL study. You MUST use association language throughout. "
            "Use 'sambandh paaya gaya' (association found), never 'sabit hua ki' (proven that), "
            "'causes', 'prevents', or 'cures'. This is a hard rule."
        )
    else:
        causal_rule = (
            "This study type allows careful causal language where clearly supported by the data. "
            "Still qualify claims with 'shodh ke anusaar' or 'adhyayan mein paaya gaya'."
        )

    # Small study warning
    small_study_note = ""
    if claims.get("small_study_flag"):
        small_study_note = (
            f"\n⚠ SMALL STUDY FLAG: N={claims.get('sample_size')} is below threshold. "
            f"The script MUST mention this as a limitation in the caveat segment."
        )

    # Below-minimum sample size — spoken disclaimer required at end of script
    below_minimum_note = ""
    below_minimum_reminder = ""
    if claims.get("below_minimum_sample"):
        n = claims.get("sample_size")
        below_minimum_note = (
            f"\n⚠ VERY SMALL STUDY (N={n}): This study is below the "
            f"channel's minimum sample size of {profile['research']['minimum_sample_size']}. "
            f"The CTA segment MUST end with a spoken Hindi disclaimer acknowledging the "
            f"very small sample size and urging viewers to consult a doctor before acting."
        )
        below_minimum_reminder = (
            f"\n8. MANDATORY (very small study, N={n}): The last sentence of the cta segment "
            f"in hindi_script MUST be a spoken disclaimer in Hindi acknowledging that the "
            f"study had only {n} participants and that viewers should consult their doctor "
            f"before making any health decisions based on this video."
        )

    # Industry funding disclosure
    funding_note = ""
    if claims.get("industry_funded_flag"):
        funding_note = (
            f"\n⚠ INDUSTRY FUNDING: Study funded by {claims.get('funding_source')}. "
            f"The caveat segment MUST mention this."
        )

    # Build default tags from profile
    default_tags = profile["youtube_upload"]["default_tags_always_include"]
    tags_instruction = profile["youtube_upload"].get("tags_instruction", "")

    # Study citation + link for description
    authors = study.get("authors", [])
    authors_str = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")
    citation = profile["compliance"]["study_citation_format"].format(
        authors=authors_str,
        year=study.get("year", ""),
        title=study.get("title", ""),
        journal=study.get("journal", ""),
        doi_or_pmid=study.get("doi") or f"PMID: {study.get('pmid', '')}"
    )
    doi = study.get("doi")
    pmid = study.get("pmid", "")
    study_url = f"https://doi.org/{doi}" if doi else f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    # Disclaimer texts
    disclaimer_hindi   = profile["compliance"]["medical_disclaimer"]["text_hindi"]
    disclaimer_english = profile["compliance"]["medical_disclaimer"]["text_english"]
    ai_disclosure      = profile["compliance"]["ai_disclosure"]["description_text"]

    script_language_instruction = profile["script"].get(
        "script_language_instruction", ""
    )

    # Build the prompt
    return f"""You are an expert Hindi health science communicator. Generate a complete YouTube Shorts video package based on the research below.

⚠ CRITICAL LANGUAGE REQUIREMENT ⚠
{script_language_instruction}
This is non-negotiable. Hindi words must always be in Devanagari. English words that modern Hindi speakers say out loud (medical OR everyday: 'study', 'diet', 'lifestyle', 'ok', 'actually', 'basically') must stay in Roman — never substitute them with Sanskrit equivalents.

═══════════════════════════════════════════════
STUDY FACTS (from peer-reviewed research)
═══════════════════════════════════════════════
Title:      {study.get('title', '')}
Journal:    {study.get('journal', '')} ({study.get('year', '')})
PMID:       {study.get('pmid', '')}
Study type: {study.get('study_type', '')}

Core finding:           {claims.get('core_finding', '')}
Effect size:            {claims.get('effect_size') or 'not reported in abstract'}
Sample size:            {claims.get('sample_size') or 'not stated in abstract'}
Population:             {claims.get('population_description') or 'not specified'}
Follow-up:              {claims.get('follow_up_duration') or 'not stated'}
Study design:           {claims.get('methodology_summary') or 'see abstract'}
What it does NOT prove: {claims.get('what_study_does_not_prove', '')}
Key limitations:        {'; '.join(claims.get('primary_limitations', [])) or 'not stated in abstract'}
Additional stats:       {'; '.join(claims.get('key_stats', [])) or 'none'}
Specific interventions: {', '.join(claims.get('specific_interventions', [])) or 'NOT EXTRACTED — derive from abstract text'}

ORIGINAL ABSTRACT (for authentic phrasing and context):
{study.get('abstract', '')}

═══════════════════════════════════════════════
EDITORIAL RULES (from channel niche profile)
═══════════════════════════════════════════════
Target audience: {profile['editorial']['target_audience_description']}
Tone: {profile['editorial']['tone_description']}

Terminology rules:
{chr(10).join('- ' + r for r in profile['editorial']['terminology_rules'])}

ABSOLUTE PROHIBITIONS (never violate these):
{chr(10).join('- ' + p for p in profile['script']['absolute_prohibitions'])}

STATISTICS RULE:
The viewer is NOT a scientist. Present at most 2-3 numbers in the ENTIRE script and only as simple percentages or plain fractions — e.g. "22% कम risk" or "3 गुना ज़्यादा". NEVER use RR, OR, HR, SMD, confidence intervals, p-values, or any notation like "(RR = 0.78)" in the spoken script. Pick the single most striking percentage from the study to anchor the finding, and use at most 1-2 supporting numbers. The audience tunes out after the third number.

LANGUAGE RULE:
{causal_rule}{small_study_note}{below_minimum_note}{funding_note}

═══════════════════════════════════════════════
FORMAT REQUIREMENTS
═══════════════════════════════════════════════
Format: YouTube Shorts (vertical, under 60 seconds)
Target script duration: {profile['script']['target_duration_seconds']} seconds
Approximate word count (Hindi): {profile['script']['target_word_count_hindi']} words
Script language: Devanagari script only — no Roman transliteration of Hindi words

Required segments (produce ALL of them):
{segment_instructions}

B-roll mood per segment:
{broll_mood_str}

B-roll style: {profile['visuals']['broll_style_description']}

Thumbnail style variants to generate prompts for:
{chr(10).join('- ' + v['id'] + ': ' + v['description'] for v in profile['thumbnail']['style_variants'])}
Thumbnail rules: {'; '.join(profile['thumbnail']['text_overlay_rules'])}

TAG RULES
These default tags are always required — include all of them verbatim:
{json.dumps(default_tags)}

{tags_instruction}

═══════════════════════════════════════════════
OUTPUT REQUIREMENTS
═══════════════════════════════════════════════
Respond with ONLY a valid JSON object. No explanation, no markdown, no backticks.

The JSON must match this exact structure:

{{
  "hindi_script": "Full voiceover script as one continuous string, exactly as it should be spoken",

  "script_segments": [
    {{
      "name": "hook",
      "hindi_text": "The hook portion of the script",
      "duration_hint_seconds": 5,
      "broll_mood": "striking, high-contrast, close-up detail shot"
    }},
    {{
      "name": "context",
      "hindi_text": "...",
      "duration_hint_seconds": 10,
      "broll_mood": "neutral, clinical but approachable — lab, doctor-patient, reading"
    }},
    {{
      "name": "finding",
      "hindi_text": "...",
      "duration_hint_seconds": 20,
      "broll_mood": "direct illustration of the topic — food, exercise, sleep, body"
    }},
    {{
      "name": "caveat",
      "hindi_text": "...",
      "duration_hint_seconds": 10,
      "broll_mood": "thoughtful, calm — person thinking, doctor consulting"
    }},
    {{
      "name": "actionable_takeaway",
      "hindi_text": "...",
      "duration_hint_seconds": 7,
      "broll_mood": "positive, active — person doing the recommended action"
    }},
    {{
      "name": "cta",
      "hindi_text": "...",
      "duration_hint_seconds": 3,
      "broll_mood": "warm, community — group of people, family"
    }}
  ],

  "title": "Hindi YouTube title, under 60 characters",

  "description": "Full YouTube description in Hindi and English. Must include:\\n1. 2-line video summary\\n2. Study citation: {citation}\\n3. Study link: {study_url}\\n4. Medical disclaimer: {disclaimer_hindi} | {disclaimer_english}\\n5. AI disclosure: {ai_disclosure}\\n6. Subscribe CTA",

  "tags": ["...25-35 tags total: see TAG RULES below..."],

  "broll_search_tags": [
    {{
      "segment_name": "hook",
      "search_terms": ["2-3 English Pexels/Pixabay search terms for this segment"]
    }},
    {{
      "segment_name": "context",
      "search_terms": ["..."]
    }},
    {{
      "segment_name": "finding",
      "search_terms": ["..."]
    }},
    {{
      "segment_name": "caveat",
      "search_terms": ["..."]
    }},
    {{
      "segment_name": "actionable_takeaway",
      "search_terms": ["..."]
    }},
    {{
      "segment_name": "cta",
      "search_terms": ["family health discussion", "happy people community"]
    }}
  ],

  "thumbnail_prompts": [
    {{
      "variant_id": "data_visual",
      "prompt": "English image generation prompt for bold-statistic thumbnail"
    }},
    {{
      "variant_id": "human_lifestyle",
      "prompt": "English prompt for South Asian middle-aged person in health context"
    }},
    {{
      "variant_id": "concept_abstract",
      "prompt": "English prompt for metaphorical/conceptual illustration"
    }}
  ],

  "chapter_timestamps": [
    {{"title": "Introduction", "estimated_start_seconds": 0}},
    {{"title": "About the Study", "estimated_start_seconds": 5}},
    {{"title": "Key Finding", "estimated_start_seconds": 15}},
    {{"title": "What This Doesn't Mean", "estimated_start_seconds": 35}},
    {{"title": "What You Can Do", "estimated_start_seconds": 45}},
    {{"title": "Summary", "estimated_start_seconds": 52}}
  ]
}}

IMPORTANT REMINDERS before you write:
1. The hindi_script must be the concatenation of all segment hindi_text fields
2. Never open with "Namaste doston" or "Aaj ki video mein"
3. The caveat segment is non-negotiable — every video must have it
4. The sample size ({claims.get('sample_size') or 'unknown'}) must be mentioned somewhere in the script
5. Thumbnail prompts must be in English (for image generation APIs)
6. B-roll search terms must be in English (for Pexels/Pixabay)
7. Title and description must be in Hindi (or bilingual for description)
8. SPECIFICITY RULE: The finding segment MUST name each specific intervention individually by name (e.g. 'Mediterranean diet', 'aerobic exercise', '7-8 ghante ki neend'). Never say 'lifestyle changes', 'healthy habits', or 'behtar jeevan shaili' without naming EXACTLY what those changes are. The specific interventions from this study are: {', '.join(claims.get('specific_interventions', [])) or 'derive these from the abstract above'}.
9. WORD COUNT RULE: The total hindi_script must be at least {profile['script']['minimum_word_count']} words. Target {profile['script']['target_word_count_hindi']} words. Each segment has a target: {'; '.join(f"{s['name']} ~{s.get('target_word_count', '?')} words" for s in profile['script']['segment_structure'])}. The finding segment is the most important — write it fully, do not truncate.{below_minimum_reminder}"""


# ─── LLM call ─────────────────────────────────────────────────────────────────

def call_llm(prompt: str, attempt: int = 1) -> str:
    provider, client = _get_llm_client()
    print(f"[Stage 3] Calling {provider} ({LLM_MODEL}), attempt {attempt}...")

    if provider == "anthropic":
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=4096,  # More tokens — this produces a lot of content
            temperature=0.4,  # Slightly more creative than Stage 2
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    else:
        kwargs = dict(
            model=LLM_MODEL,
            max_tokens=8192,  # headroom for reasoning models + a lot of content
            temperature=0.4,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        # Reasoning models (e.g. NVIDIA's gpt-oss) emit chain-of-thought tokens that
        # share the max_tokens budget — keep effort low so the JSON body isn't truncated.
        if "gpt-oss" in LLM_MODEL.lower():
            kwargs["reasoning_effort"] = "low"
        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        if choice.finish_reason == "length":
            raise RuntimeError(
                "Response truncated (hit max_tokens) before the JSON was complete — "
                "raise max_tokens or pick a model that reasons less."
            )
        return choice.message.content


def parse_llm_response(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return json.loads(text)


# ─── Post-generation validation ───────────────────────────────────────────────

def validate_content(content: ContentBlock, claims: dict, profile: dict) -> list[str]:
    """
    Run safety checks on generated content.
    Returns list of warnings. Critical violations cause abort (handled in run()).
    """
    notes = []
    script = content.hindi_script.lower()

    # Check sample size is mentioned
    sample_size = claims.get("sample_size")
    if sample_size:
        # Look for the number or approximate Hindi number words
        n_str = str(sample_size)
        if n_str not in content.hindi_script and n_str not in content.description:
            notes.append(f"Sample size ({sample_size}) not found in script — add manually")

    # Check causal language for observational studies
    if not claims.get("is_causal_language_safe"):
        causal_words = ["causes", "prevents", "cures", "sabit", "prove"]
        found = [w for w in causal_words if w in script]
        if found:
            notes.append(
                f"Causal language found in script for observational study: {found}. "
                f"Replace with association language before proceeding."
            )

    # Check caveat segment exists and has content
    caveat_segs = [s for s in content.script_segments if s.name == "caveat"]
    if not caveat_segs or len(caveat_segs[0].hindi_text.strip()) < 20:
        notes.append("Caveat segment is missing or too short — required for health content")

    # Check that script is in Devanagari, not Hinglish
    devanagari_chars = sum(1 for c in content.hindi_script if 'ऀ' <= c <= 'ॿ')
    total_letters = sum(1 for c in content.hindi_script if c.isalpha())
    if total_letters > 0 and devanagari_chars / total_letters < 0.5:
        notes.append(
            "Script appears to be in Hinglish (Roman script) — regenerate with Devanagari only. "
            f"Devanagari ratio: {devanagari_chars}/{total_letters} characters."
        )

    # Check title length
    if len(content.title) > 60:
        notes.append(f"Title is {len(content.title)} chars — YouTube truncates at 60 for mobile")

    # Check thumbnail prompts are in English
    for tp in content.thumbnail_prompts:
        # Rough check: if it contains Devanagari script, it's probably Hindi
        has_devanagari = any('\u0900' <= c <= '\u097f' for c in tp.prompt)
        if has_devanagari:
            notes.append(f"Thumbnail prompt '{tp.variant_id}' appears to be in Hindi — must be English for image APIs")

    # ── Specificity check (soft warning) ────────────────────────────────────
    # If Stage 2 extracted named interventions, at least half should appear in
    # the finding segment. English terms stay Roman in Devanagari text so we
    # can match them directly.
    specific_interventions = claims.get("specific_interventions", [])
    if specific_interventions:
        finding_segs = [s for s in content.script_segments if s.name == "finding"]
        finding_text = finding_segs[0].hindi_text.lower() if finding_segs else ""
        combined_text = (finding_text + " " + script).lower()
        found_count = sum(
            1 for iv in specific_interventions
            # Match any keyword from the intervention phrase (e.g. "Mediterranean" from "Mediterranean diet")
            if any(kw.lower() in combined_text for kw in iv.split() if len(kw) > 3)
        )
        threshold = max(1, len(specific_interventions) // 2)
        if found_count < threshold:
            missing = [
                iv for iv in specific_interventions
                if not any(kw.lower() in combined_text for kw in iv.split() if len(kw) > 3)
            ]
            notes.append(
                f"[QUALITY:SPECIFICITY] Only {found_count}/{len(specific_interventions)} specific interventions "
                f"found in script (threshold: {threshold}). Missing: {missing}. "
                f"The finding segment must name each intervention individually."
            )

    # ── Stat jargon check (soft warning) ────────────────────────────────────
    import re
    jargon_re = re.compile(r'\b(RR|OR|HR|SMD)\s*[=≈<>]', re.IGNORECASE)
    jargon_hits = jargon_re.findall(content.hindi_script)
    if jargon_hits:
        notes.append(
            f"[QUALITY:STAT_JARGON] Script contains raw statistical notation: "
            f"{jargon_hits}. Replace with plain-language percentages."
        )

    # ── Word count check (soft warning) ─────────────────────────────────────
    word_count = len(content.hindi_script.split())
    min_words = profile["script"].get("minimum_word_count", 200)
    if word_count < min_words:
        notes.append(
            f"[QUALITY:WORDCOUNT] Script has {word_count} words, below minimum of {min_words}. "
            f"Target is {profile['script']['target_word_count_hindi']} words. "
            f"Expand the finding segment — it should be ~{next((s.get('target_word_count', 120) for s in profile['script']['segment_structure'] if s['name'] == 'finding'), 120)} words."
        )

    return notes


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 3 runner.

    Args:
        job_id: UUID of the job (must be at stage_2_complete).

    Returns:
        Job dict with content{} populated and status "stage_3_complete",
        or status "error" on failure.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight checks ────────────────────────────────────────────────────
    errored_here = job["status"] == "error" and job.get("error", {}).get("stage") == "stage_3"
    if job["status"] != "stage_2_complete" and not errored_here:
        return mark_error(job, f"Job status is '{job['status']}' — expected 'stage_2_complete'")
    job.pop("error", None)
    job["status"] = "stage_2_complete"  # restore in case we're retrying a previous error

    study  = job.get("study")
    claims = job.get("claims")

    if not study or not claims:
        return mark_error(job, "study{} or claims{} block missing — re-run earlier stages")

    if not claims.get("core_finding"):
        return mark_error(job, "core_finding is missing from claims — cannot generate script")

    print(f"[Stage 3] Generating content for: {study['title'][:55]}...")
    print(f"[Stage 3] Study type: {study['study_type']} | Causal safe: {claims.get('is_causal_language_safe')}")
    print(f"[Stage 3] Specific interventions: {claims.get('specific_interventions', [])}")

    # ── LLM content generation: up to 2 parse/schema attempts + 1 quality retry
    #
    # Strategy:
    #   - Inner loop (2 attempts): handles JSON / Pydantic validation failures
    #   - Outer quality pass (max 2): if content passes schema but has QUALITY
    #     issues (specificity or word count), we retry once with targeted feedback.
    # ─────────────────────────────────────────────────────────────────────────
    base_prompt   = build_content_prompt(study, claims, profile)
    prompt        = base_prompt
    content       = None
    retries       = 0
    quality_notes = []

    for quality_pass in range(1, 3):  # at most 2 quality passes (initial + 1 retry)

        # ── Inner loop: JSON/schema validation ───────────────────────────────
        for attempt in range(1, 3):
            try:
                raw     = call_llm(prompt, attempt=attempt)
                parsed  = parse_llm_response(raw)
                content = ContentBlock(**parsed)
                break

            except json.JSONDecodeError as e:
                print(f"[Stage 3] JSON parse error (pass {quality_pass}, attempt {attempt}): {e}")
                if attempt == 2:
                    return mark_error(job, f"LLM returned invalid JSON after 2 attempts: {e}", retries=retries)
                prompt += f"\n\nYour previous response was not valid JSON. Error: {e}. Respond with ONLY a valid JSON object."
                retries += 1

            except Exception as e:
                print(f"[Stage 3] Validation error (pass {quality_pass}, attempt {attempt}): {e}")
                if attempt == 2:
                    return mark_error(job, f"Content validation failed after 2 attempts: {e}", retries=retries)
                prompt += f"\n\nValidation failed: {e}. Fix the issue and respond with a corrected JSON object."
                retries += 1

        if content is None:
            return mark_error(job, "Content generation failed — content is None after retry loop", retries=retries)

        # ── Post-generation safety + quality validation ───────────────────────
        quality_notes = validate_content(content, claims, profile)

        # Critical: abort immediately if causal language in observational study
        if not claims.get("is_causal_language_safe"):
            critical = [n for n in quality_notes if "Causal language found" in n]
            if critical:
                return mark_error(
                    job,
                    f"Critical: causal language found in script for observational study. "
                    f"Re-run Stage 3 or edit the script manually. Notes: {critical}"
                )

        # Check for quality issues eligible for retry
        quality_issues = [n for n in quality_notes if n.startswith("[QUALITY:")]
        if not quality_issues or quality_pass == 2:
            # No quality issues, or we've already retried — accept result
            break

        # ── Quality retry: append targeted feedback and go again ─────────────
        print(f"[Stage 3] Quality issues found (pass {quality_pass}) — retrying with feedback:")
        for issue in quality_issues:
            print(f"  ⚠  {issue}")

        feedback_lines = [
            "\n\nYour previous response had quality issues. Please rewrite the full JSON with these fixes:"
        ]
        for issue in quality_issues:
            if "QUALITY:SPECIFICITY" in issue:
                feedback_lines.append(
                    f"- SPECIFICITY: {issue.split(chr(93) + chr(32), 1)[-1]} "
                    f"Name every intervention explicitly in the finding segment. Do not use umbrella phrases."
                )
            elif "QUALITY:WORDCOUNT" in issue:
                target_wc = next(
                    (s.get("target_word_count", 120)
                     for s in profile["script"]["segment_structure"]
                     if s["name"] == "finding"),
                    120
                )
                feedback_lines.append(
                    f"- WORD COUNT: {issue.split(chr(93) + chr(32), 1)[-1]} "
                    f"Write more for the finding segment — it needs ~{target_wc} words alone."
                )
            elif "QUALITY:STAT_JARGON" in issue:
                feedback_lines.append(
                    f"- STAT JARGON: {issue.split(chr(93) + chr(32), 1)[-1]} "
                    f"Remove ALL RR/OR/HR/SMD notation from the script. "
                    f"Use plain percentages only — '22% कम risk' not '(RR = 0.78)'."
                )

        prompt  = base_prompt + "\n".join(feedback_lines)
        content = None   # Reset so we don't use stale content on next pass
        retries += 1

    # ── Log all notes ─────────────────────────────────────────────────────────
    if quality_notes:
        print(f"[Stage 3] {len(quality_notes)} content note(s):")
        for n in quality_notes:
            prefix = "  ⚠ " if n.startswith("[QUALITY:") else "  ℹ "
            print(f"{prefix}{n}")

    content.validation_notes = quality_notes

    # ── Write to job state ────────────────────────────────────────────────────
    job["content"] = content.model_dump()
    job["status"]  = "stage_3_complete"
    save_job(job)

    print(f"\n[Stage 3] ✓ Complete.")
    print(f"  Title        : {content.title}")
    print(f"  Script words : ~{len(content.hindi_script.split())} words")
    print(f"  Segments     : {len(content.script_segments)}")
    print(f"  Tags         : {len(content.tags)}")
    print(f"  Thumbnails   : {len(content.thumbnail_prompts)}")
    print(f"  Notes        : {len(quality_notes)}")

    # Print the script for review
    print(f"\n{'─'*60}")
    print("GENERATED HINDI SCRIPT (review before proceeding):")
    print('─'*60)
    for seg in content.script_segments:
        print(f"\n[{seg.name.upper()} — {seg.duration_hint_seconds}s]")
        print(seg.hindi_text)
    print('─'*60)

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_3_content_generation.py <job_id>
    #   python stage_3_content_generation.py          ← auto-picks most recent stage_2_complete job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                ready = j.get("status") == "stage_2_complete"
                retryable = j.get("status") == "error" and j.get("error", {}).get("stage") == "stage_3"
                if ready or retryable:
                    candidates.append((jf.stat().st_mtime, j["job_id"], j.get("status")))
            except Exception:
                continue

        if not candidates:
            print("No stage_2_complete or stage_3 error jobs found. Run stage_2_claim_extraction.py first.")
            sys.exit(1)

        candidates.sort(reverse=True)
        _, job_id, picked_status = candidates[0]
        label = "retrying errored" if picked_status == "error" else "most recent"
        print(f"[Stage 3] No job_id provided — using {label}: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result["status"] == "error":
        print(f"Error        : {result['error']['message']}")
    else:
        print(f"Job saved to : jobs/{result['job_id']}.json")