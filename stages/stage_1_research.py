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


def create_job(topic: str, aspect_ratio: str = "9:16") -> dict:
    """Create a fresh job object and save it to disk."""
    if aspect_ratio not in ("9:16", "16:9"):
        aspect_ratio = "9:16"
    Path(JOBS_DIR).mkdir(exist_ok=True)
    job_id = str(uuid.uuid4())
    job = {
        "job_id": job_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
        "aspect_ratio": aspect_ratio,
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

            # ArticleIdList contains doi, pmc, pubmed ids — extract all in one pass
            id_list = article.get("PubmedData", {}).get("ArticleIdList", [])
            has_pmc = False
            doi_from_pubmed = None
            for aid in id_list:
                id_type = getattr(aid, "attributes", {}).get("IdType", "")
                id_val  = str(aid)
                if id_type == "pmc" or id_val.startswith("PMC"):
                    has_pmc = True
                if id_type == "doi":
                    doi_from_pubmed = id_val

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
                "doi": doi_from_pubmed,          # From PubMed XML ArticleIdList
                "doi_from_pubmed": doi_from_pubmed,  # Explicit key for build_full_study
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

    DOI priority: PubMed XML (already in summary as doi_from_pubmed) is the
    ground truth. Semantic Scholar DOI is only used if PubMed didn't have one.
    Never overwrite a known DOI with None.
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
                # Only use S2 DOI if PubMed XML didn't already provide one
                ss_doi = data.get("externalIds", {}).get("DOI")
                if not s.get("doi") and ss_doi:
                    s["doi"] = ss_doi
            else:
                s["citation_count"] = 0
                # DOI from PubMed XML (doi_from_pubmed) is already in s["doi"] — don't touch it
            time.sleep(1.1)
        except Exception:
            s["citation_count"] = 0
            # Same — leave s["doi"] untouched on failure

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

    # doi_from_pubmed (extracted from PubMed XML ArticleIdList) takes priority.
    # s["doi"] may have been set by Semantic Scholar — use as fallback only.
    doi = s.get("doi_from_pubmed") or s.get("doi")
    if doi:
        print(f"[Stage 1] DOI resolved: {doi}")
    else:
        print(f"[Stage 1] No DOI found for PMID {pmid} — Unpaywall fallback won't be available")

    return StudyFull(
        topic=topic,
        pubmed_query=query,
        pmid=s["pmid"],
        doi=doi,
        title=s["title"],
        authors=s["authors"],
        journal=s["journal"],
        year=s["year"],
        study_type=normalise_study_type(s["publication_types"]),
        abstract=s["abstract_full"],
        full_text_available=s["has_free_fulltext"],
    )


# ─── Part 6: PDF download ─────────────────────────────────────────────────────
#
# Three-strategy waterfall:
#
#  Strategy A — NCBI OA FTP service
#    Best for papers already ingested into PMC's open-access subset.
#    Works reliably for anything published > ~4 weeks ago.
#    Fails for brand-new papers (PMC ID exists but OA index not yet updated).
#
#  Strategy B — Unpaywall API
#    Free academic open-access resolver. No key required (just an email).
#    Finds legal open-access PDFs by DOI — covers publisher OA, preprints,
#    institutional repositories. Catches most cases Strategy A misses.
#    Docs: https://unpaywall.org/products/api
#
#  Strategy C — Graceful skip
#    PDF is genuinely unavailable right now (very new paper, paywalled,
#    publisher hasn't deposited). Log it clearly and move on — the pipeline
#    can run fine on abstract text + screenshots alone.

import xml.etree.ElementTree as ET
import tarfile


def _save_pdf_from_response(resp: requests.Response, pdf_path: str, pmid: str, source: str) -> Optional[str]:
    """
    Write a PDF response to disk, handling both direct PDF and tgz bundle.
    Returns the saved path on success, None on failure.
    """
    content_type  = resp.headers.get("content-type", "")
    download_url  = resp.url

    if "pdf" in content_type or download_url.endswith(".pdf"):
        with open(pdf_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[Stage 1] PDF saved via {source}: {pdf_path}")
        return pdf_path

    elif "tgz" in content_type or "tar" in content_type or download_url.endswith(".tar.gz"):
        tgz_path = pdf_path.replace(".pdf", ".tar.gz")
        with open(tgz_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        with tarfile.open(tgz_path, "r:gz") as tar:
            pdf_members = [m for m in tar.getmembers() if m.name.endswith(".pdf")]
            if pdf_members:
                extracted = tar.extractfile(pdf_members[0])
                if extracted:
                    with open(pdf_path, "wb") as f:
                        f.write(extracted.read())
                    os.remove(tgz_path)
                    print(f"[Stage 1] PDF extracted from tgz via {source}: {pdf_path}")
                    return pdf_path
        os.remove(tgz_path)
        print(f"[Stage 1] No PDF inside tgz ({source})")
        return None

    else:
        print(f"[Stage 1] Unexpected content-type from {source}: {content_type}")
        return None


def _strategy_a_ncbi_oa(study: StudyFull, pdf_path: str) -> Optional[str]:
    """
    Strategy A: NCBI Open Access FTP service.
    Reliable for papers ingested into PMC OA subset, but lags ~2-4 weeks
    behind publication for brand-new papers.
    """
    try:
        # Get PMC ID via Entrez elink
        handle  = Entrez.elink(dbfrom="pubmed", db="pmc", id=study.pmid)
        record  = Entrez.read(handle)
        handle.close()

        pmc_ids = []
        for linkset in record:
            for link in linkset.get("LinkSetDb", []):
                if link.get("LinkName") == "pubmed_pmc":
                    pmc_ids = [l["Id"] for l in link.get("Link", [])]

        if not pmc_ids:
            print(f"[Stage 1] Strategy A: no PMC ID found for PMID {study.pmid}")
            return None

        pmc_id = f"PMC{pmc_ids[0]}"
        print(f"[Stage 1] Strategy A: found {pmc_id}, querying OA service...")

        oa_resp = requests.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
            params={"id": pmc_id, "format": "pdf"},
            timeout=15,
            headers={"User-Agent": f"HealthVideoBot/1.0 (mailto:{os.getenv('ENTREZ_EMAIL', 'bot@example.com')})"}
        )

        if oa_resp.status_code != 200:
            print(f"[Stage 1] Strategy A: OA service HTTP {oa_resp.status_code}")
            return None

        root     = ET.fromstring(oa_resp.text)
        error_el = root.find(".//error")
        if error_el is not None:
            # This is the "does not exist" case — paper too new or not in OA subset
            print(f"[Stage 1] Strategy A: {error_el.text} (paper not yet in OA index)")
            return None

        # Try PDF link first, then tgz bundle
        link_el = root.find(".//link[@format='pdf']") or root.find(".//link[@format='tgz']")
        if link_el is None:
            print(f"[Stage 1] Strategy A: no download link in OA response")
            return None

        download_url = link_el.get("href", "")
        if not download_url:
            return None

        if download_url.startswith("ftp://"):
            download_url = download_url.replace("ftp://", "https://", 1)

        print(f"[Stage 1] Strategy A: downloading from {download_url[:70]}...")
        dl_resp = requests.get(download_url, timeout=60,
                               headers={"User-Agent": "HealthVideoBot/1.0"}, stream=True)

        if dl_resp.status_code != 200:
            print(f"[Stage 1] Strategy A: download HTTP {dl_resp.status_code}")
            return None

        return _save_pdf_from_response(dl_resp, pdf_path, study.pmid, "NCBI OA")

    except Exception as e:
        print(f"[Stage 1] Strategy A error: {e}")
        return None


def _strategy_b_unpaywall(study: StudyFull, pdf_path: str) -> Optional[str]:
    """
    Strategy B: Unpaywall API → iterate all OA locations → Playwright download.

    Key insight: Unpaywall returns multiple OA locations for most papers.
    best_oa_location is often the publisher's own PDF URL (e.g. MDPI, Springer)
    which is protected by Cloudflare and blocks automated downloads.
    Repository copies (PMC, EuropePMC, institutional repos) are NOT Cloudflared
    and download freely.

    So we:
    1. Get ALL oa_locations from Unpaywall
    2. Sort them: repository copies first, publisher copies last
    3. Try each in order via requests first, then Playwright headless, then visible
    """
    doi = study.doi
    if not doi:
        print(f"[Stage 1] Strategy B: no DOI for PMID {study.pmid} — skipping")
        return None

    try:
        email = os.getenv("ENTREZ_EMAIL", "bot@example.com")
        print(f"[Stage 1] Strategy B: querying Unpaywall for DOI {doi}...")

        resp = requests.get(
            f"https://api.unpaywall.org/v2/{doi}",
            params={"email": email},
            timeout=10,
            headers={"User-Agent": "HealthVideoBot/1.0"}
        )

        if resp.status_code == 404:
            print(f"[Stage 1] Strategy B: DOI not in Unpaywall index")
            return None
        if resp.status_code != 200:
            print(f"[Stage 1] Strategy B: Unpaywall HTTP {resp.status_code}")
            return None

        data = resp.json()
        if not data.get("is_oa"):
            print(f"[Stage 1] Strategy B: paper is not open access per Unpaywall")
            return None

        # Collect all OA locations that have a direct PDF URL
        all_locations = data.get("oa_locations", [])
        pdf_locations = [
            loc for loc in all_locations
            if loc.get("url_for_pdf")
        ]

        if not pdf_locations:
            print(f"[Stage 1] Strategy B: no direct PDF URLs in any Unpaywall location")
            return None

        # Sort: repository copies first (not Cloudflared), publisher copies last
        # host_type values: 'repository' (PMC, arXiv, institutional) vs 'publisher'
        pdf_locations.sort(key=lambda loc: 0 if loc.get("host_type") == "repository" else 1)

        print(f"[Stage 1] Strategy B: {len(pdf_locations)} PDF locations found")
        for i, loc in enumerate(pdf_locations):
            print(f"  [{i+1}] {loc.get('host_type','?'):12} {loc.get('url_for_pdf','')[:65]}")

        # Try each location
        for loc in pdf_locations:
            pdf_url    = loc["url_for_pdf"]
            host_type  = loc.get("host_type", "unknown")
            result     = _try_download_url(pdf_url, pdf_path, host_type)
            if result:
                return result

        print(f"[Stage 1] Strategy B: all {len(pdf_locations)} locations failed")
        return None

    except Exception as e:
        print(f"[Stage 1] Strategy B error: {e}")
        return None


def _try_download_url(pdf_url: str, pdf_path: str, host_type: str) -> Optional[str]:
    """
    Try to download a PDF URL using three escalating methods:
      1. Plain requests — fastest, works for repository URLs (PMC, EuropePMC, arXiv)
      2. Playwright headless — handles JS/cookie requirements without Cloudflare
      3. Playwright visible — handles Cloudflare (real browser fingerprint)

    Repository URLs (PMC, EuropePMC) almost always work with plain requests.
    Publisher URLs (MDPI, Springer) need visible browser for Cloudflare bypass.
    """
    print(f"[Stage 1] Trying: {pdf_url[:70]}...")

    # ── Method 1: plain requests (fast, works for repos) ──────────────────
    try:
        r = requests.get(
            pdf_url,
            timeout=30,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,*/*",
            },
            stream=True,
            allow_redirects=True,
        )
        if r.status_code == 200:
            ct = r.headers.get("content-type", "")
            if "pdf" in ct or pdf_url.endswith(".pdf"):
                with open(pdf_path, "wb") as f:
                    for chunk in r.iter_content(8192):
                        f.write(chunk)
                # Verify it's actually a PDF (first 4 bytes = %PDF)
                with open(pdf_path, "rb") as f:
                    magic = f.read(4)
                if magic == b"%PDF":
                    print(f"[Stage 1] PDF saved via requests ({host_type}): {pdf_path}")
                    return pdf_path
                else:
                    os.remove(pdf_path)
                    print(f"[Stage 1] Got non-PDF response from requests (got HTML/redirect)")
    except Exception as e:
        print(f"[Stage 1] requests method failed: {e}")

    # ── Method 2: Playwright headless (JS/cookie requirements, no Cloudflare) ──
    result = asyncio.run(_playwright_download_pdf(pdf_url, pdf_path, headless=True))
    if result:
        return result

    # ── Method 3: Playwright visible (Cloudflare bypass for publisher URLs) ──
    # Only worth trying for publisher-hosted URLs — repo URLs don't use Cloudflare
    if host_type == "publisher":
        print(f"[Stage 1] Trying visible browser for Cloudflare-protected publisher URL...")
        result = asyncio.run(_playwright_download_pdf(pdf_url, pdf_path, headless=False))
        if result:
            return result

    return None


async def _playwright_download_pdf(pdf_url: str, pdf_path: str, headless: bool = True) -> Optional[str]:
    """
    Download a PDF using Playwright. Supports both headless (fast, no Cloudflare)
    and visible (Cloudflare bypass) modes.
    """
    USER_AGENT = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=USER_AGENT,
            accept_downloads=True,
        )
        if not headless:
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

        try:
            page = await context.new_page()
            
            # 1. Track inline PDF response bytes via response interceptor
            pdf_bytes = None
            async def handle_response(response):
                nonlocal pdf_bytes
                try:
                    ct = response.headers.get("content-type", "")
                    if "pdf" in ct and response.status == 200:
                        pdf_bytes = await response.body()
                except Exception:
                    pass

            page.on("response", handle_response)

            # 2. Track download events
            download_event = None
            async def handle_download(dl):
                nonlocal download_event
                download_event = dl

            page.on("download", handle_download)

            # 3. Trigger navigation
            try:
                # Wait until commit (headers received), so we don't block forever if it's a download
                await page.goto(pdf_url, wait_until="commit", timeout=25000)
            except Exception:
                # e.g., net::ERR_ABORTED if navigation is aborted due to a download starting
                pass

            # 4. CAPTCHA/Cloudflare handoff (if visible browser)
            if not headless:
                await page.wait_for_timeout(2000)
                try:
                    page_text = (await page.content()).lower()
                    CAPTCHA_SIGNALS = ["captcha", "robot", "unusual traffic", "verify you are human", "cloudflare", "access denied", "blocked"]
                    if any(sig in page_text for sig in CAPTCHA_SIGNALS):
                        print(f"\n{'='*60}")
                        print(f"  Cloudflare/CAPTCHA detected on publisher page.")
                        print(f"  Please solve it in the browser window that just opened.")
                        print(f"  Press ENTER here once you've solved it/download has started.")
                        print(f"{'='*60}")
                        input("> ")
                except Exception:
                    pass

            # 5. Bounded wait for download event or response interception to complete
            for _ in range(10):
                if download_event or pdf_bytes:
                    break
                await asyncio.sleep(0.5)

            # 6. Save from download event if captured
            if download_event:
                await download_event.save_as(pdf_path)
                if os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as f:
                        magic = f.read(4)
                    if magic == b"%PDF":
                        mode = "headless" if headless else "visible"
                        print(f"[Stage 1] PDF saved via download event ({mode}): {pdf_path}")
                        return pdf_path
                    else:
                        os.remove(pdf_path)

            # 7. Save from response intercept if captured
            if pdf_bytes and pdf_bytes[:4] == b"%PDF":
                with open(pdf_path, "wb") as f:
                    f.write(pdf_bytes)
                mode = "headless" if headless else "visible"
                print(f"[Stage 1] PDF saved via response intercept ({mode}): {pdf_path}")
                return pdf_path

            return None

        except Exception as e:
            print(f"[Stage 1] Playwright ({'headless' if headless else 'visible'}) error: {e}")
            return None
        finally:
            await context.close()
            await browser.close()


def try_download_pdf(study: StudyFull, job_id: str) -> Optional[str]:
    """
    Waterfall PDF download: Strategy A (NCBI OA) → Strategy B (Unpaywall) → skip.
    Returns local path on success, None if all strategies fail.
    A None result is not an error — the pipeline continues on abstract alone.
    """
    if not study.full_text_available:
        print(f"[Stage 1] No free full text flag for PMID {study.pmid} — skipping PDF")
        return None

    pdf_dir  = Path(ASSETS_DIR) / job_id / "pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = str(pdf_dir / f"{study.pmid}.pdf")

    # Strategy A — NCBI OA FTP service (best for established OA papers)
    result = _strategy_a_ncbi_oa(study, pdf_path)
    if result:
        return result

    # Strategy B — Unpaywall (best for new papers and publisher OA)
    result = _strategy_b_unpaywall(study, pdf_path)
    if result:
        return result

    # Strategy C — graceful skip
    print(
        f"[Stage 1] PDF unavailable for PMID {study.pmid} — "
        f"paper may be too new for OA index, or publisher hasn't deposited yet. "
        f"Pipeline will continue using abstract text + screenshots."
    )
    return None


# ─── Part 7: Screenshot via Playwright ───────────────────────────────────────
#
# Strategy: visible browser with CAPTCHA handoff
#
# PubMed's bot detection is robust enough that no headless trick reliably
# bypasses it long-term. The cleanest solution for a human-in-the-loop
# pipeline is to launch a VISIBLE browser, navigate to the page, and if a
# CAPTCHA appears, print a prompt and wait for the user to solve it manually.
# Once the abstract is visible, the script takes over and screenshots it.
#
# This is also more honest — we're not trying to impersonate a browser,
# we ARE using a real browser. The user just needs to click "I'm not a robot"
# when PubMed asks.

ABSTRACT_SELECTORS = [
    "#abstract",
    ".abstract-content",
    "[data-section-type='abstract']",
    ".abstract",
]

METADATA_SELECTORS = [
    ".article-source",
    ".citation-authors",
    "#full-view-heading",
]

CAPTCHA_SIGNALS = [
    "captcha",
    "robot",
    "unusual traffic",
    "verify you are human",
    "cloudflare",
    "access denied",
    "blocked",
]


async def _screenshot_abstract(pmid: str, job_id: str) -> list[str]:
    """
    Open a VISIBLE browser, navigate to the PubMed abstract page, handle any
    CAPTCHA by asking the user to solve it, then screenshot the abstract and
    metadata sections.

    Visible browser is intentional — headless detection is an arms race we
    don't want to play for a tool with a human already at the keyboard.
    """
    screenshot_dir = Path(ASSETS_DIR) / job_id / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    async with async_playwright() as p:
        # headless=False — opens a real visible browser window
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="en-US",
        )
        page = await context.new_page()

        try:
            print(f"[Stage 1] Opening browser for PMID {pmid}...")
            print(f"[Stage 1] URL: {url}")

            # Use 'load' instead of 'domcontentloaded' — ensures the full page
            # including any redirect targets has finished loading before we
            # attempt to read page.content(). domcontentloaded fires too early
            # on pages with JS-based redirects, causing the "page is navigating"
            # error when content() is called immediately after.
            await page.goto(url, wait_until="load", timeout=30000)
            await page.wait_for_timeout(1500)

            # ── CAPTCHA detection and handoff loop ───────────────────────────
            max_captcha_waits = 3
            captcha_waits = 0

            while captcha_waits < max_captcha_waits:

                # Check if abstract is already visible first — fastest path
                abstract_visible = False
                for sel in ABSTRACT_SELECTORS:
                    try:
                        el = page.locator(sel).first
                        await el.wait_for(state="visible", timeout=1500)
                        abstract_visible = True
                        break
                    except Exception:
                        continue

                if abstract_visible:
                    break  # Good — skip CAPTCHA check entirely

                # Abstract not visible — check if it's a CAPTCHA page.
                # Wrap page.content() in try/except: if the page is still
                # navigating (e.g. a JS redirect is in progress), this call
                # throws "Unable to retrieve content because the page is
                # navigating". We catch it, wait, and retry.
                captcha_detected = False
                try:
                    page_text = (await page.content()).lower()
                    captcha_detected = any(sig in page_text for sig in CAPTCHA_SIGNALS)
                except Exception:
                    # Page still navigating — wait and let it settle
                    await page.wait_for_timeout(2000)
                    continue

                if captcha_detected:
                    captcha_waits += 1
                    print(f"\n{'='*60}")
                    print(f"  CAPTCHA detected on PubMed page.")
                    print(f"  Please solve it in the browser window that just opened.")
                    print(f"  Press ENTER here once you've solved it and the abstract is visible.")
                    print(f"{'='*60}")
                    input("> ")
                    await page.wait_for_timeout(1500)
                else:
                    # No CAPTCHA, no abstract — page may still be loading
                    await page.wait_for_timeout(2000)
                    break

            # ── Abstract screenshot ──────────────────────────────────────────
            abstract_captured = False
            for selector in ABSTRACT_SELECTORS:
                try:
                    el = page.locator(selector).first
                    await el.wait_for(state="visible", timeout=5000)
                    await el.scroll_into_view_if_needed()
                    await page.wait_for_timeout(400)
                    path = str(screenshot_dir / f"{pmid}_abstract.png")
                    await el.screenshot(path=path)
                    paths.append(path)
                    print(f"[Stage 1] Abstract screenshot saved")
                    abstract_captured = True
                    break
                except Exception:
                    continue

            if not abstract_captured:
                # Fallback: screenshot whatever is visible
                print(f"[Stage 1] Abstract element not found — screenshotting full viewport")
                path = str(screenshot_dir / f"{pmid}_viewport.png")
                await page.screenshot(path=path, full_page=False)
                paths.append(path)

            # ── Metadata screenshot ──────────────────────────────────────────
            for selector in METADATA_SELECTORS:
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

def run(topic: str = None, pmid_override: str = None, aspect_ratio: str = "9:16") -> dict:
    """
    Main Stage 1 runner.

    Args:
        topic:         Search topic. If None, uses first item in
                       niche_profile.research.topic_rotation.
        pmid_override: Skip search entirely and use this PMID directly.
                       Useful for manual curation or re-runs.
        aspect_ratio:  Output video format — "9:16" (1080×1920 Shorts) or
                       "16:9" (1920×1080 landscape). Default: "9:16".

    Returns:
        Job dict with study{} populated and status "stage_1_complete",
        or status "error" on failure.
    """
    profile = load_niche_profile()

    if topic is None:
        topic = profile["research"]["topic_rotation"][0]
        print(f"[Stage 1] No topic provided — using rotation: '{topic}'")

    job    = create_job(topic, aspect_ratio=aspect_ratio)
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
    #
    #   python stage_1_research.py "diabetes" "" 16:9
    #       Searches topic, auto-selects, outputs 1920×1080 landscape video

    topic_arg        = sys.argv[1] if len(sys.argv) > 1 else None
    pmid_arg         = sys.argv[2] if len(sys.argv) > 2 else None
    aspect_ratio_arg = sys.argv[3] if len(sys.argv) > 3 else "9:16"

    result = run(
        topic=topic_arg if topic_arg else None,
        pmid_override=pmid_arg if pmid_arg else None,
        aspect_ratio=aspect_ratio_arg,
    )

    print(f"\nFinal status : {result['status']}")
    if result["status"] == "error":
        print(f"Error        : {result['error']['message']}")
    else:
        print(f"Job saved to : jobs/{result['job_id']}.json")