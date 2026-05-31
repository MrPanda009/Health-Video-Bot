"""
Stage 2 — Claim Extraction
============================
Responsibilities:
  1. Read the job's study{} block (abstract + metadata from Stage 1)
  2. Send to LLM with a strict structured extraction prompt
  3. Validate the extracted claims against niche_profile rules
  4. Set safety flags that Stage 3 will use to constrain script generation
  5. Write the populated claims{} block into the job state

This stage is intentionally conservative — it only extracts what is
EXPLICITLY stated in the abstract. No inference, no extrapolation.
If a field isn't in the text, it stays null. Stage 3 handles interpretation.

Reads from:  jobs/{job_id}.json  (study{} block must be present)
             niche_profile.json
Writes to:   jobs/{job_id}.json  (claims{} block)

Exit status: "stage_2_complete" or "error"
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


def _get_llm_client():
    """Return (provider_name, client) based on LLM_MODEL / LLM_PROVIDER env vars."""
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


# ─── Pydantic model for extracted claims ─────────────────────────────────────

class ClaimsBlock(BaseModel):
    """
    Structured claims extracted from the study abstract.
    Every field maps directly to job_schema.json claims{}.
    """
    core_finding: str = Field(
        description="The single most important finding, one sentence, exactly as the paper states it."
    )
    effect_size: Optional[str] = Field(
        default=None,
        description="Exact effect size with units as written. E.g. '23% reduction', 'HR 0.78 (95% CI 0.65-0.94)'. Null if not reported."
    )
    sample_size: Optional[int] = Field(
        default=None,
        description="Total number of participants. For meta-analyses, total across included studies. Null if not stated."
    )
    population_description: Optional[str] = Field(
        default=None,
        description="Who was studied — age range, condition, country if mentioned."
    )
    follow_up_duration: Optional[str] = Field(
        default=None,
        description="Study duration or follow-up period. E.g. '12 weeks', '5 years'. Null if not stated."
    )
    primary_limitations: list[str] = Field(
        default_factory=list,
        description="Limitations explicitly stated in the abstract. Empty list if none mentioned."
    )
    what_study_does_not_prove: str = Field(
        description="A clear one-sentence statement of what this study CANNOT conclude. Must be filled even if not in abstract — derive from study_type."
    )
    key_stats: list[str] = Field(
        default_factory=list,
        description="Up to 4 additional statistics or findings worth mentioning. Each as a short string."
    )
    industry_funded: Optional[bool] = Field(
        default=None,
        description="True if abstract mentions industry/commercial funding. False if explicitly states no COI. Null if not mentioned."
    )
    funding_source: Optional[str] = Field(
        default=None,
        description="Funding source if mentioned in abstract. Null otherwise."
    )

    # Safety flags — set by our validator logic, NOT by the LLM
    is_causal_language_safe: bool = Field(
        default=True,
        description="False if study_type is observational/cross-sectional. Set by validator."
    )
    small_study_flag: bool = Field(
        default=False,
        description="True if sample_size < threshold in niche_profile. Set by validator."
    )
    industry_funded_flag: bool = Field(
        default=False,
        description="True if industry_funded is True. Set by validator."
    )
    below_minimum_sample: bool = Field(
        default=False,
        description="True if sample_size < niche_profile.research.minimum_sample_size. Job aborted if True."
    )

    @field_validator("core_finding")
    @classmethod
    def core_finding_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("core_finding must not be empty — required field for Stage 3")
        return v.strip()

    @field_validator("what_study_does_not_prove")
    @classmethod
    def does_not_prove_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("what_study_does_not_prove must not be empty")
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
    job["error"] = {"stage": "stage_2", "message": message, "retries": retries}
    save_job(job)
    print(f"[Stage 2] ERROR: {message}")
    return job


# ─── Prompt construction ──────────────────────────────────────────────────────

def build_extraction_prompt(study: dict) -> str:
    """
    Build the structured extraction prompt.

    Key design decisions:
    - Instruct the LLM to ONLY extract what is explicitly in the text
    - Require JSON output with no preamble
    - Provide study_type so LLM can derive what_study_does_not_prove correctly
    - Give explicit per-field guidance to reduce hallucination
    """
    study_type_guidance = {
        "meta_analysis":     "This is a meta-analysis synthesising multiple studies. It cannot alone prove causation.",
        "systematic_review": "This is a systematic review summarising existing evidence. It is not a primary study.",
        "rct":               "This is an RCT. It CAN establish causation within its studied population.",
        "cohort":            "This is a cohort study. It can show association but NOT causation.",
        "cross_sectional":   "This is a cross-sectional study. It shows correlation at one point in time, NOT causation.",
        "other":             "Study type is unclear. Treat as observational — do not assume causation.",
    }

    study_type    = study.get("study_type", "other")
    type_guidance = study_type_guidance.get(study_type, study_type_guidance["other"])
    authors       = study.get("authors", [])
    authors_str   = ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else "")

    return f"""You are a medical research analyst. Extract structured claims from the following study abstract.

CRITICAL RULES:
- Extract ONLY what is EXPLICITLY stated in the abstract. Do not infer, extrapolate, or add outside knowledge.
- If a field is not mentioned in the abstract, set it to null (or empty list for arrays).
- For effect_size: copy the exact number and units as written. Do not round or restate.
- For sample_size: extract the total N. For meta-analyses, look for total participants across studies.
- For what_study_does_not_prove: write one clear sentence. Guidance: {type_guidance}
- Do NOT mention the study's positive findings in what_study_does_not_prove — focus on its limits.
- For industry_funded: only set True if the abstract EXPLICITLY mentions commercial/industry funding.

STUDY DETAILS:
Title: {study.get('title', '')}
Authors: {authors_str}
Journal: {study.get('journal', '')} ({study.get('year', '')})
Study type: {study_type}
PMID: {study.get('pmid', '')}

ABSTRACT:
{study.get('abstract', '')}

Respond with ONLY a valid JSON object. No explanation, no markdown, no backticks. Match this exact structure:

{{
  "core_finding": "string — the single most important finding, one sentence",
  "effect_size": "string or null — exact effect size with units as written",
  "sample_size": integer or null,
  "population_description": "string or null — who was studied",
  "follow_up_duration": "string or null — study duration",
  "primary_limitations": ["string", ...],
  "what_study_does_not_prove": "string — what this study cannot conclude",
  "key_stats": ["string", ...],
  "industry_funded": true/false/null,
  "funding_source": "string or null"
}}"""


# ─── LLM call ─────────────────────────────────────────────────────────────────

def call_llm(prompt: str, attempt: int = 1) -> str:
    """Call the configured LLM and return raw response text."""
    provider, client = _get_llm_client()
    print(f"[Stage 2] Calling {provider} ({LLM_MODEL}), attempt {attempt}...")

    if provider == "anthropic":
        response = client.messages.create(
            model=LLM_MODEL,
            max_tokens=1024,
            temperature=0.1,  # Low temp — consistent extraction, not creativity
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    else:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=1024,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content


def parse_llm_response(raw: str) -> dict:
    """
    Parse the LLM's JSON response.
    Handles clean JSON, markdown-fenced JSON, and leading/trailing whitespace.
    """
    text = raw.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return json.loads(text)


# ─── Validation ───────────────────────────────────────────────────────────────

def apply_safety_flags(claims: ClaimsBlock, study: dict, profile: dict) -> ClaimsBlock:
    """
    Apply safety flags based on our own logic — NOT the LLM's output.

    Flags set here:
      is_causal_language_safe  — False for observational studies
      small_study_flag         — True if N < profile threshold (warning, not abort)
      below_minimum_sample     — True if N < profile minimum (causes abort)
      industry_funded_flag     — True if industry funding detected
    """
    study_type      = study.get("study_type", "other")
    min_sample      = profile["research"]["minimum_sample_size"]
    small_threshold = profile["research"]["small_study_flag_threshold"]

    observational_types = {"cohort", "cross_sectional", "other"}
    claims.is_causal_language_safe = study_type not in observational_types

    if claims.sample_size is not None:
        claims.small_study_flag     = claims.sample_size < small_threshold
        claims.below_minimum_sample = claims.sample_size < min_sample
    else:
        claims.small_study_flag     = True   # Unknown — be conservative
        claims.below_minimum_sample = False  # Don't abort on unknown N

    claims.industry_funded_flag = bool(claims.industry_funded)
    return claims


def validate_claims(claims: ClaimsBlock, study: dict, profile: dict) -> list[str]:
    """
    Produce validation warnings. These are logged and written to the job
    but do NOT abort — except below_minimum_sample which is handled in run().
    """
    warnings = []

    if not claims.effect_size:
        warnings.append("No effect size extracted — script must handle this gracefully")

    if claims.sample_size is None:
        warnings.append("Sample size not in abstract — script must note this uncertainty")

    if claims.small_study_flag:
        warnings.append(
            f"Small study: N={claims.sample_size} < {profile['research']['small_study_flag_threshold']} "
            f"— script must mention this limitation"
        )

    if not claims.is_causal_language_safe:
        warnings.append(
            f"Observational study ({study.get('study_type')}) — "
            f"script must use 'sambandh paaya gaya', never causal language"
        )

    if claims.industry_funded_flag:
        warnings.append(
            f"Industry funding: {claims.funding_source} — "
            f"script must disclose per niche_profile compliance rules"
        )

    if not claims.primary_limitations:
        warnings.append("No limitations in abstract — Stage 3 must derive from study type")

    return warnings


# ─── Main runner ──────────────────────────────────────────────────────────────

def run(job_id: str) -> dict:
    """
    Main Stage 2 runner.

    Args:
        job_id: UUID of the job created by Stage 1.

    Returns:
        Job dict with claims{} populated and status "stage_2_complete",
        or status "error" on failure.
    """
    profile = load_niche_profile()
    job     = load_job(job_id)

    # ── Pre-flight checks ────────────────────────────────────────────────────
    if job["status"] != "stage_1_complete":
        return mark_error(job, f"Job status is '{job['status']}' — expected 'stage_1_complete'")

    study = job.get("study")
    if not study:
        return mark_error(job, "study{} block missing — re-run Stage 1")

    if not study.get("abstract"):
        return mark_error(job, "Abstract is empty — cannot extract claims without text")

    print(f"[Stage 2] Processing: {study['title'][:65]}...")
    print(f"[Stage 2] Study type: {study['study_type']} | PMID: {study['pmid']}")

    # ── LLM extraction with one retry ────────────────────────────────────────
    prompt  = build_extraction_prompt(study)
    claims  = None
    retries = 0

    for attempt in range(1, 3):
        try:
            raw    = call_llm(prompt, attempt=attempt)
            parsed = parse_llm_response(raw)
            claims = ClaimsBlock(**parsed)
            break

        except json.JSONDecodeError as e:
            print(f"[Stage 2] JSON parse error (attempt {attempt}): {e}")
            if attempt == 2:
                return mark_error(job, f"LLM returned invalid JSON after 2 attempts: {e}", retries=2)
            prompt += f"\n\nYour previous response was not valid JSON. Error: {e}. Respond with ONLY a valid JSON object."
            retries += 1

        except Exception as e:
            print(f"[Stage 2] Validation error (attempt {attempt}): {e}")
            if attempt == 2:
                return mark_error(job, f"Claim validation failed after 2 attempts: {e}", retries=2)
            prompt += f"\n\nValidation failed: {e}. Ensure all required fields are present and correctly typed."
            retries += 1

    # ── Apply safety flags (our logic, never LLM) ────────────────────────────
    claims = apply_safety_flags(claims, study, profile)

    # ── Abort if sample size below minimum ───────────────────────────────────
    if claims.below_minimum_sample:
        return mark_error(
            job,
            f"Sample size N={claims.sample_size} is below minimum "
            f"{profile['research']['minimum_sample_size']} — "
            f"study too small for this channel. Select a different paper."
        )

    # ── Validation warnings ───────────────────────────────────────────────────
    warnings = validate_claims(claims, study, profile)
    if warnings:
        print(f"[Stage 2] {len(warnings)} validation warning(s):")
        for w in warnings:
            print(f"  ⚠  {w}")

    # ── Write to job state ────────────────────────────────────────────────────
    claims_dict = claims.model_dump()
    claims_dict["validation_warnings"] = warnings

    job["claims"] = claims_dict
    job["status"] = "stage_2_complete"
    save_job(job)

    print(f"\n[Stage 2] ✓ Complete.")
    print(f"  Core finding  : {claims.core_finding[:80]}...")
    print(f"  Effect size   : {claims.effect_size or 'not reported'}")
    print(f"  Sample size   : {claims.sample_size or 'not found in abstract'}")
    print(f"  Causal safe   : {claims.is_causal_language_safe}")
    print(f"  Small study   : {claims.small_study_flag}")
    print(f"  Industry fund : {claims.industry_funded_flag}")
    print(f"  Warnings      : {len(warnings)}")

    return job


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Usage:
    #   python stage_2_claim_extraction.py <job_id>
    #   python stage_2_claim_extraction.py          ← auto-picks most recent stage_1_complete job

    if len(sys.argv) < 2:
        jobs_dir   = Path(JOBS_DIR)
        candidates = []
        for jf in jobs_dir.glob("*.json"):
            try:
                with open(jf) as f:
                    j = json.load(f)
                if j.get("status") == "stage_1_complete":
                    candidates.append((jf.stat().st_mtime, j["job_id"]))
            except Exception:
                continue

        if not candidates:
            print("No stage_1_complete jobs found. Run stage_1_research.py first.")
            sys.exit(1)

        candidates.sort(reverse=True)
        job_id = candidates[0][1]
        print(f"[Stage 2] No job_id provided — using most recent: {job_id}")
    else:
        job_id = sys.argv[1]

    result = run(job_id)
    print(f"\nFinal status : {result['status']}")
    if result["status"] == "error":
        print(f"Error        : {result['error']['message']}")
    else:
        print(f"Job saved to : jobs/{result['job_id']}.json")