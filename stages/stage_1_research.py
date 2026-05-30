"""
Stage 1 — Research Ingestion
=============================
Responsibilities:
  1. Accept a topic query (from niche_profile topic_rotation or manual override)
  2. Search PubMed for relevant studies matching quality filters
  3. Return ranked candidates for selection (top 3)
  4. Once a study is selected, fetch its full abstract + metadata
  5. Attempt PDF download (PMC open access only)
  6. Screenshot abstract + key figures via Playwright
  7. Create the job JSON and write the fully populated study{} block

Reads from:  niche_profile.json
Writes to:   jobs/{job_id}.json  (creates it)
             assets/{job_id}/screenshots/
             assets/{job_id}/pdf/ (if available)

Exit status written to job: "stage_1_complete" or "error"
"""

import json
import os
import uuid
import time
import asyncio
import math
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from Bio import Entrez
from pydantic import BaseModel, Field
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# ─── Config ───────────────────────────────────────────────────────────────────

NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")
JOBS_DIR           = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR         = os.getenv("ASSETS_DIR", "assets")

# PubMed requires an email for Entrez (free, no key needed for basic use)
# Set ENTREZ_EMAIL in your .env — required by NCBI ToS
Entrez.email   = os.getenv("ENTREZ_EMAIL", "your@email.com")
Entrez.api_key = os.getenv("NCBI_API_KEY", None)  # Optional: 10 req/s vs 3 req/s


# ─── Pydantic models ──────────────────────────────────────────────────────────

class StudyCandidate(BaseModel):
    """A study returned from PubMed search, before full fetch."""
    pmid: str
    title: str
    authors: list[str]
    journal: str
    year: int
    publication_types: list[str]
    abstract_preview: str
    has_free_fulltext: bool
    citation_count: Optional[int] = None


class StudyFull(BaseModel):
    """Fully populated study object — written into job state."""
    topic: str
    pubmed_query: str
    pmid: str
    doi: Optional[str] = None
    title: str
    authors: list[str]
    journal: str
    year: int
    study_type: str
    abstract: str
    full_text_available: bool
    pdf_path: Optional[str] = None
    screenshot_paths: list[str] = Field(default_factory=list)
    industry_funded: Optional[bool] = None
    funding_source: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_niche_profile() -> dict:
    with open(NICHE_PROFILE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_job(job: dict) -> None:
    path = Path(JOBS_DIR) / f"{job['job_id']}.json"
    job["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)


def create_job(topic: str) -> dict:
    """Create a fresh job object and save it to disk."""
    Path(JOBS_DIR).mkdir(exist_ok=True)
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "error": None,
        "study": None,
        "claims": None,
        "content": None,
        "assets": None,
        "output": None,
    }
    for subdir in ["screenshots", "pdf", "broll", "thumbnails", "audio", "captions", "output"]:
        (Path(ASSETS_DIR) / job_id / subdir).mkdir(parents=True, exist_ok=True)
    save_job(job)
    print(f"[Stage 1] Created job: {job_id}")
    return job


def mark_error(job: dict, message: str, retries: int = 0) -> dict:
    job["status"] = "error"
    job["error"] = {"stage": "stage_1", "message": message, "retries": retries}
    save_job(job)
    print(f"[Stage 1] ERROR: {message}")
    return job


# ─── Part 1: Build PubMed query ───────────────────────────────────────────────

def build_pubmed_query(topic: str, profile: dict) -> str:
    """
    Construct a PubMed query from topic + niche profile filters.
    Filters: publication type, date range, has abstract, humans only.
    """
    recency_months = profile["research"]["recency_months"]
    cutoff_date = (datetime.now() - timedelta(days=recency_months * 30)).strftime("%Y/%m/%d")
    today = datetime.now().strftime("%Y/%m/%d")

    pub_type_filter = (
        '("Meta-Analysis"[Publication Type]'
        ' OR "Systematic Review"[Publication Type]'
        ' OR "Randomized Controlled Trial"[Publication Type])'
    )

    query = (
        f"({topic})"
        f" AND {pub_type_filter}"
        f" AND hasabstract"
        f' AND ("{cutoff_date}"[Date - Publication] : "{today}"[Date - Publication])'
        f" AND (humans[MeSH Terms])"
    )
    return query


# ─── Part 2: Search PubMed and fetch summaries ────────────────────────────────

def search_pubmed(query: str, max_results: int = 10) -> list[str]:
    """Run PubMed esearch, return PMIDs."""
    print(f"[Stage 1] Searching PubMed...")
    handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
    record = Entrez.read(handle)
    handle.close()
    pmids = record["IdList"]
    print(f"[Stage 1] Found {len(pmids)} results")
    return pmids


def fetch_study_summaries(pmids: list[str]) -> list[dict]:
    """Fetch full metadata + abstracts for a list of PMIDs via efetch."""
    if not pmids:
        return []

    handle = Entrez.efetch(db="pubmed", id=",".join(pmids), rettype="xml", retmode="xml")
    records = Entrez.read(handle)
    handle.close()

    summaries = []
    for article in records["PubmedArticle"]:
        try:
            medline = article["MedlineCitation"]
            art     = medline["Article"]

            title   = str(art.get("ArticleTitle", ""))
            authors = [
                f"{a.get('LastName','')} {a.get('ForeName','')}".strip()
                for a in art.get("AuthorList", [])
                if a.get("LastName")
            ]
            journal = str(art.get("Journal", {}).get("Title", ""))
            pub_date = art.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
            year_raw = pub_date.get("Year") or pub_date.get("MedlineDate", "2000")[:4]
            year = int(str(year_raw)[:4])
            pub_types = [str(pt) for pt in art.get("PublicationTypeList", [])]

            abstract_obj   = art.get("Abstract", {})
            abstract_texts = abstract_obj.get("AbstractText", [])
            if isinstance(abstract_texts, list):
                abstract = " ".join(str(t) for t in abstract_texts)
            else:
                abstract = str(abstract_texts)

            pmid = str(medline["PMID"])

            id_list = article.get("PubmedData", {}).get("ArticleIdList", [])
            has_pmc = any(
                str(aid).startswith("PMC") or
                getattr(aid, "attributes", {}).get("IdType") == "pmc"
                for aid in id_list
            )

            summaries.append({
                "pmid": pmid,
                "title": title,
                "authors": authors[:3],
                "journal": journal,
                "year": year,
                "publication_types": pub_types,
                "abstract_preview": abstract[:300],
                "abstract_full": abstract,
                "has_free_fulltext": has_pmc,
            })
        except Exception as e:
            print(f"[Stage 1] Warning: Could not parse article — {e}")
            continue

    return summaries


# ─── Part 3: Enrich with citation counts ─────────────────────────────────────

def enrich_with_citation_counts(summaries: list[dict]) -> list[dict]:
    """
    Fetch citation counts from Semantic Scholar (free, no key needed).
    Rate limit: 1 req/sec. Fails gracefully.
    Also captures DOI if available.
    """
    print("[Stage 1] Fetching citation counts from Semantic Scholar...")
    for s in summaries:
        try:
            resp = requests.get(
                f"https://api.semanticscholar.org/graph/v1/paper/PMID:{s['pmid']}",
                params={"fields": "citationCount,externalIds"},
                timeout=5,
                headers={"User-Agent": "HealthVideoBot/1.0"}
            )
            if resp.status_code == 200:
                data = resp.json()
                s["citation_count"] = data.get("citationCount", 0)
                s["doi"] = data.get("externalIds", {}).get("DOI")
            else:
                s["citation_count"] = 0
                s["doi"] = None
            time.sleep(1.1)
        except Exception:
            s["citation_count"] = 0
            s["doi"] = None

    return summaries


# ─── Part 4: Rank and select candidates ──────────────────────────────────────

def rank_candidates(summaries: list[dict], profile: dict) -> list[StudyCandidate]:
    """
    Score studies and return top 3 as StudyCandidate objects.

    Scoring:
      - Study type (meta > SR > RCT > cohort > cross-sectional): up to 50 pts
      - Citation count (log-scaled): up to 30 pts
      - Free full text bonus: 10 pts
    """
    type_scores = {
        "meta-analysis": 50,
        "systematic review": 40,
        "randomized controlled trial": 30,
        "cohort": 15,
        "cross-sectional": 5,
    }

    def score(s: dict) -> float:
        pts = 0
        types_lower = " ".join(s["publication_types"]).lower()
        for term, weight in type_scores.items():
            if term in types_lower:
                pts += weight
                break
        pts += min(30, int(math.log(max(1, s.get("citation_count", 0) or 0) + 1) * 5))
        if s.get("has_free_fulltext"):
            pts += 10
        return pts

    ranked = sorted(summaries, key=score, reverse=True)

    return [
        StudyCandidate(
            pmid=s["pmid"],
            title=s["title"],
            authors=s["authors"],
            journal=s["journal"],
            year=s["year"],
            publication_types=s["publication_types"],
            abstract_preview=s["abstract_preview"],
            has_free_fulltext=s["has_free_fulltext"],
            citation_count=s.get("citation_count"),
        )
        for s in ranked[:3]
    ]


# ─── Part 5: Build full study object ─────────────────────────────────────────

def normalise_study_type(publication_types: list[str]) -> str:
    """Map PubMed publication type list to our internal enum."""
    t = " ".join(publication_types).lower()
    if "meta-analysis" in t:        return "meta_analysis"
    if "systematic review" in t:    return "systematic_review"
    if "randomized controlled" in t: return "rct"
    if "cohort" in t:               return "cohort"
    if "cross-sectional" in t:      return "cross_sectional"
    return "other"


def build_full_study(pmid: str, summaries: list[dict], topic: str, query: str) -> StudyFull:
    s = next((x for x in summaries if x["pmid"] == pmid), None)
    if not s:
        raise ValueError(f"PMID {pmid} not found in fetched summaries")

    return StudyFull(
        topic=topic,
        pubmed_query=query,
        pmid=s["pmid"],
        doi=s.get("doi"),
        title=s["title"],
        authors=s["authors"],
        journal=s["journal"],
        year=s["year"],
        study_type=normalise_study_type(s["publication_types"]),
        abstract=s["abstract_full"],
        full_text_available=s["has_free_fulltext"],
    )


# ─── Part 6: PDF download ─────────────────────────────────────────────────────

def try_download_pdf(study: StudyFull, job_id: str) -> Optional[str]:
    """
    Download PDF using the NCBI Open Access FTP service.
    This is the correct, API-sanctioned method — the direct PMC PDF URL
    blocks automated access with a 403. The OA service returns a proper
    FTP path for every open-access paper.

    API docs: https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/
    Returns local path on success, None on failure.
    Assets saved to: assets/{job_id}/pdf/
    """
    if not study.full_text_available:
        print(f"[Stage 1] No free full text for PMID {study.pmid} — skipping PDF")
        return None

    try:
        # Step 1: Get PMC ID from Entrez elink
        handle  = Entrez.elink(dbfrom="pubmed", db="pmc", id=study.pmid)
        record  = Entrez.read(handle)
        handle.close()

        pmc_ids = []
        for linkset in record:
            for link in linkset.get("LinkSetDb", []):
                if link.get("LinkName") == "pubmed_pmc":
                    pmc_ids = [l["Id"] for l in link.get("Link", [])]

        if not pmc_ids:
            print(f"[Stage 1] PMC ID not found for PMID {study.pmid} — skipping PDF")
            return None

        pmc_id = f"PMC{pmc_ids[0]}"
        print(f"[Stage 1] Found {pmc_id}, querying OA service...")

        # Step 2: Query NCBI OA service for the actual download URL
        # This returns an XML with an <link format="pdf"> element pointing to
        # the real FTP/HTTPS download path
        oa_resp = requests.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
            params={"id": pmc_id, "format": "pdf"},
            timeout=15,
            headers={"User-Agent": "HealthVideoBot/1.0 (mailto:" + os.getenv("ENTREZ_EMAIL", "bot@example.com") + ")"}
        )

        if oa_resp.status_code != 200:
            print(f"[Stage 1] OA service returned HTTP {oa_resp.status_code}")
            return None

        # Step 3: Parse the XML response to get the download href
        import xml.etree.ElementTree as ET
        root = ET.fromstring(oa_resp.text)

        # Check for error element
        error_el = root.find(".//error")
        if error_el is not None:
            print(f"[Stage 1] OA service error: {error_el.text} — PDF not available for {pmc_id}")
            return None

        # Find the PDF link — format attribute is "pdf"
        pdf_link = root.find(".//link[@format='pdf']")
        if pdf_link is None:
            # Fallback: try tgz (full package) — PDF is inside
            print(f"[Stage 1] No direct PDF link from OA service for {pmc_id} — trying tgz")
            tgz_link = root.find(".//link[@format='tgz']")
            if tgz_link is None:
                print(f"[Stage 1] No downloadable package found for {pmc_id}")
                return None
            download_url = tgz_link.get("href", "")
        else:
            download_url = pdf_link.get("href", "")

        if not download_url:
            print(f"[Stage 1] OA service returned empty href for {pmc_id}")
            return None

        # FTP URLs need to be converted to HTTPS for requests
        # NCBI FTP mirrors at ftp.ncbi.nlm.nih.gov also available via HTTPS
        if download_url.startswith("ftp://"):
            download_url = download_url.replace("ftp://", "https://", 1)

        print(f"[Stage 1] Downloading PDF from: {download_url[:70]}...")

        # Step 4: Download the file
        dl_resp = requests.get(
            download_url,
            timeout=60,
            headers={"User-Agent": "HealthVideoBot/1.0"},
            stream=True
        )

        if dl_resp.status_code != 200:
            print(f"[Stage 1] PDF download failed (HTTP {dl_resp.status_code})")
            return None

        content_type = dl_resp.headers.get("content-type", "")
        pdf_dir  = Path(ASSETS_DIR) / job_id / "pdf"

        if "pdf" in content_type or download_url.endswith(".pdf"):
            pdf_path = str(pdf_dir / f"{study.pmid}.pdf")
            with open(pdf_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"[Stage 1] PDF saved: {pdf_path}")
            return pdf_path

        elif "tgz" in content_type or download_url.endswith(".tar.gz"):
            # Extract PDF from the tgz package
            import tarfile, io
            tgz_path = str(pdf_dir / f"{study.pmid}.tar.gz")
            with open(tgz_path, "wb") as f:
                for chunk in dl_resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            with tarfile.open(tgz_path, "r:gz") as tar:
                pdf_members = [m for m in tar.getmembers() if m.name.endswith(".pdf")]
                if pdf_members:
                    pdf_member = pdf_members[0]
                    extracted = tar.extractfile(pdf_member)
                    if extracted:
                        pdf_path = str(pdf_dir / f"{study.pmid}.pdf")
                        with open(pdf_path, "wb") as f:
                            f.write(extracted.read())
                        print(f"[Stage 1] PDF extracted from tgz: {pdf_path}")
                        os.remove(tgz_path)
                        return pdf_path
            print(f"[Stage 1] No PDF found inside tgz for {pmc_id}")
            return None

        else:
            print(f"[Stage 1] Unexpected content type: {content_type}")
            return None

    except Exception as e:
        print(f"[Stage 1] PDF download error: {e}")
        return None


# ─── Part 7: Screenshot via Playwright ───────────────────────────────────────

async def _screenshot_abstract(pmid: str, job_id: str) -> list[str]:
    """
    Screenshot the PubMed abstract page using Playwright.

    Key fixes vs naive implementation:
    - Use a real browser User-Agent (PubMed detects headless Chromium by default)
    - Disable the 'webdriver' navigator property that sites use to detect bots
    - Wait for DOM content rather than 'networkidle' (more reliable, less timeout-prone)
    - Try multiple selectors in priority order for resilience against PubMed UI changes
    - Scroll abstract into view before screenshotting
    """
    screenshot_dir = Path(ASSETS_DIR) / job_id / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    # Real Chrome User-Agent — PubMed rejects obvious headless UA strings
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",  # Hide webdriver flag
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/New_York",
        )

        # Mask navigator.webdriver — the primary bot detection signal
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = await context.new_page()

        try:
            print(f"[Stage 1] Opening PubMed for PMID {pmid}...")
            await page.goto(
                f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                wait_until="domcontentloaded",   # More reliable than networkidle
                timeout=30000
            )

            # Give JS a moment to render dynamic content
            await page.wait_for_timeout(2000)

            # ── Abstract screenshot ──────────────────────────────────────────
            # Try selectors in priority order — PubMed has changed these before
            abstract_selectors = [
                "#abstract",
                ".abstract-content",
                "[data-section-type='abstract']",
                ".abstract",
            ]

            abstract_captured = False
            for selector in abstract_selectors:
                try:
                    el = page.locator(selector).first
                    await el.wait_for(state="visible", timeout=4000)
                    await el.scroll_into_view_if_needed()
                    await page.wait_for_timeout(300)  # Brief settle after scroll
                    path = str(screenshot_dir / f"{pmid}_abstract.png")
                    await el.screenshot(path=path)
                    paths.append(path)
                    print(f"[Stage 1] Abstract screenshot saved (selector: {selector})")
                    abstract_captured = True
                    break
                except Exception:
                    continue

            if not abstract_captured:
                # Last resort: full viewport screenshot
                print(f"[Stage 1] All abstract selectors failed — taking viewport screenshot")
                path = str(screenshot_dir / f"{pmid}_viewport.png")
                await page.screenshot(path=path, full_page=False)
                paths.append(path)

            # ── Metadata screenshot (journal, authors, date) ─────────────────
            meta_selectors = [
                ".article-source",
                ".citation-authors",
                "#full-view-heading",
            ]
            for selector in meta_selectors:
                try:
                    el = page.locator(selector).first
                    await el.wait_for(state="visible", timeout=3000)
                    path = str(screenshot_dir / f"{pmid}_metadata.png")
                    await el.screenshot(path=path)
                    paths.append(path)
                    print(f"[Stage 1] Metadata screenshot saved")
                    break
                except Exception:
                    continue

        except Exception as e:
            print(f"[Stage 1] Screenshot error: {e}")
        finally:
            await context.close()
            await browser.close()

    return paths


def screenshot_pubmed_abstract(pmid: str, job_id: str) -> list[str]:
    """Sync wrapper around async Playwright screenshot function."""
    return asyncio.run(_screenshot_abstract(pmid, job_id))


# ─── Display helpers ──────────────────────────────────────────────────────────

def display_candidates(candidates: list[StudyCandidate]) -> None:
    """Print ranked candidates to terminal for manual selection."""
    print("\n" + "=" * 70)
    print("  TOP STUDY CANDIDATES")
    print("=" * 70)
    for i, c in enumerate(candidates, 1):
        print(f"\n  [{i}] {c.title[:75]}")
        print(f"      Authors  : {', '.join(c.authors[:2])}{' et al.' if len(c.authors) > 2 else ''}")
        print(f"      Journal  : {c.journal} ({c.year})")
        print(f"      PMID     : {c.pmid}  |  Citations: {c.citation_count or 'unknown'}  |  Free PDF: {'✓' if c.has_free_fulltext else '✗'}")
        print(f"      Type     : {', '.join(c.publication_types[:2])}")
        print(f"      Preview  : {c.abstract_preview[:180]}...")
    print("\n" + "=" * 70)


# ─── Main entry point ─────────────────────────────────────────────────────────

def run(topic: str = None, pmid_override: str = None) -> dict:
    """
    Main Stage 1 runner.

    Args:
        topic:         Search topic. If None, uses first item in
                       niche_profile.research.topic_rotation.
        pmid_override: Skip search entirely and use this PMID directly.
                       Useful for manual curation or re-runs.

    Returns:
        Job dict with study{} populated and status "stage_1_complete",
        or status "error" on failure.
    """
    profile = load_niche_profile()

    if topic is None:
        topic = profile["research"]["topic_rotation"][0]
        print(f"[Stage 1] No topic provided — using rotation: '{topic}'")

    job    = create_job(topic)
    job_id = job["job_id"]

    try:
        # ── Search PubMed ────────────────────────────────────────────────────
        if pmid_override:
            query  = f"manual_override:{pmid_override}"
            pmids  = [pmid_override]
        else:
            query  = build_pubmed_query(topic, profile)
            pmids  = search_pubmed(query, max_results=10)
            if not pmids:
                return mark_error(job, f"No PubMed results for: {query}")

        # ── Fetch + enrich ───────────────────────────────────────────────────
        summaries = fetch_study_summaries(pmids)
        if not summaries:
            return mark_error(job, "Could not parse any PubMed results")

        summaries  = enrich_with_citation_counts(summaries)
        candidates = rank_candidates(summaries, profile)
        if not candidates:
            return mark_error(job, "No candidates passed ranking")

        # ── Manual selection ─────────────────────────────────────────────────
        display_candidates(candidates)

        if pmid_override:
            selected_pmid = pmid_override
        else:
            print("Select a study — enter 1, 2, or 3 (or paste a PMID directly):")
            choice = input("> ").strip()
            if choice in ("1", "2", "3"):
                selected_pmid = candidates[int(choice) - 1].pmid
            elif choice.isdigit() and len(choice) > 3:
                selected_pmid = choice
            else:
                return mark_error(job, f"Invalid selection: '{choice}'")

        print(f"[Stage 1] Selected PMID: {selected_pmid}")

        # ── Build study object ───────────────────────────────────────────────
        study = build_full_study(selected_pmid, summaries, topic, query)

        # ── PDF download ─────────────────────────────────────────────────────
        study.pdf_path = try_download_pdf(study, job_id)

        # ── Screenshots ──────────────────────────────────────────────────────
        study.screenshot_paths = screenshot_pubmed_abstract(selected_pmid, job_id)

        # ── Write to job state ───────────────────────────────────────────────
        job["study"]  = study.model_dump()
        job["status"] = "stage_1_complete"
        save_job(job)

        print(f"\n[Stage 1] ✓ Complete.")
        print(f"  Job ID     : {job_id}")
        print(f"  Study      : {study.title[:65]}...")
        print(f"  Type       : {study.study_type}")
        print(f"  PDF        : {'saved' if study.pdf_path else 'unavailable'}")
        print(f"  Screenshots: {len(study.screenshot_paths)} saved")

        return job

    except Exception as e:
        import traceback
        traceback.print_exc()
        return mark_error(job, str(e))


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Usage examples:
    #   python stage_1_research.py
    #       Uses first topic from rotation, prompts for selection
    #
    #   python stage_1_research.py "gut microbiome diabetes RCT"
    #       Searches given topic, prompts for selection
    #
    #   python stage_1_research.py "" 38234567
    #       Skips search, uses PMID 38234567 directly

    topic_arg = sys.argv[1] if len(sys.argv) > 1 else None
    pmid_arg  = sys.argv[2] if len(sys.argv) > 2 else None

    result = run(
        topic=topic_arg if topic_arg else None,
        pmid_override=pmid_arg
    )

    print(f"\nFinal status : {result['status']}")
    if result["status"] == "error":
        print(f"Error        : {result['error']['message']}")
    else:
        print(f"Job saved to : jobs/{result['job_id']}.json")