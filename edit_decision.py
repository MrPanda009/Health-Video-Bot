"""Edit Decision List (EDL) generator from WhisperX transcripts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# broll_db lives at project root alongside this module
try:
    from broll_db import ClipDB
    _BROLL_DB_AVAILABLE = True
except ImportError:
    ClipDB = None  # type: ignore[misc,assignment]
    _BROLL_DB_AVAILABLE = False

# ─── Hindi keyword extraction ─────────────────────────────────────────────────

# Common Hindi function words that carry no content signal
_STOPWORDS: set[str] = {
    # copulas / auxiliaries
    "है", "हैं", "था", "थी", "थे", "हो", "हुआ", "हुई", "हुए", "होता", "होती", "होते",
    # conjunctions / particles
    "और", "या", "भी", "तो", "ही", "न", "नहीं", "मत", "कि", "जो",
    "लेकिन", "परंतु", "किंतु", "इसलिए", "क्योंकि", "अगर", "यदि",
    # postpositions / case markers
    "का", "की", "के", "में", "से", "को", "पर", "तक", "द्वारा", "साथ", "बाद", "पहले",
    "ने", "के लिए",
    # pronouns
    "यह", "वह", "ये", "वे", "इस", "उस", "इन", "उन", "इनके", "उनके",
    "मैं", "हम", "आप", "तुम", "वो", "मेरा", "हमारा", "आपका",
    # demonstratives / adverbs
    "यहाँ", "वहाँ", "अब", "फिर", "जब", "तब", "कभी", "हमेशा",
    # question words
    "क्या", "कैसे", "क्यों", "कहाँ", "कब", "कौन", "कितना",
    # common numbers / quantifiers
    "एक", "दो", "तीन", "बहुत", "कुछ", "सब", "सभी", "हर",
    # common English stopwords (scripts often mix Hindi + English)
    "the", "a", "an", "is", "are", "was", "were", "in", "of",
    "to", "and", "for", "on", "at", "it", "this", "that",
}

# Words shorter than this are almost always function words in Hindi/Devanagari
_MIN_CHARS = 4

# Punctuation / whitespace to split on
_SPLIT_RE = re.compile(r"[\s,।|!?॥\.\-–—\"'()\[\]]+")


def extract_keywords(text: str, max_terms: int = 3) -> list[str]:
    """
    Extract content keywords from Hindi (or mixed Hindi/English) text.

    Strategy: tokenise on whitespace/punctuation, filter common function words
    and short tokens, then return the longest survivors as noun proxies.
    No external NLP library required — this is intentionally simple and
    offline-safe.

    Args:
        text:       Raw Hindi text string.
        max_terms:  Maximum number of keyword terms to return.

    Returns:
        List of keyword strings (original casing preserved).
    """
    tokens = _SPLIT_RE.split(text)

    seen: set[str] = set()
    candidates: list[str] = []
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        lower = tok.lower()
        if lower in seen or lower in _STOPWORDS:
            continue
        if len(tok) < _MIN_CHARS:
            continue
        seen.add(lower)
        candidates.append(tok)

    # Longer tokens are better proxies for nouns in Hindi
    candidates.sort(key=len, reverse=True)
    return candidates[:max_terms]


# ─── EDL generation ───────────────────────────────────────────────────────────

def generate_edl(
    segments: list[dict],
    clip_db_path: str = "cache/broll_cache.db",
) -> list[dict]:
    """
    Generate an Edit Decision List from a WhisperX transcript.

    For each transcript segment the function:
    1. Extracts keyword search terms from the Hindi text (rule-based, no LLM).
    2. Queries the B-roll clip database for the best matching clip.
    3. Emits one EDL entry covering the segment's timeline window.

    Args:
        segments:     List of segment dicts from ``whisperx_transcriber.transcribe()``.
        clip_db_path: Path to the SQLite B-roll cache database.

    Returns:
        List of EDL entry dicts::

            [
              {
                "clip_id":        str | None,   # DB uuid, or None if no match
                "clip_path":      str | None,   # absolute filepath, or None
                "timeline_start": float,        # when to place it (seconds)
                "timeline_end":   float,        # end time (= segment end)
                "source_text":    str,          # transcript segment text
                "search_terms":   [str]         # keywords used to search DB
              }
            ]

    Raises:
        ImportError:      If broll_db.py is not importable.
        FileNotFoundError: If clip_db_path does not exist on disk.
    """
    if not _BROLL_DB_AVAILABLE:
        raise ImportError(
            "broll_db module not found. "
            "Make sure broll_db.py is present in the project root."
        )

    db_path = Path(clip_db_path)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Clip database not found at: {clip_db_path}\n"
            "Run Stage 4a on at least one job to populate the B-roll database,\n"
            "or provide a different --db path."
        )

    db = ClipDB(str(db_path))
    edl: list[dict] = []

    for seg in segments:
        text = seg.get("text", "")
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0))
        terms = extract_keywords(text)

        clip_id: str | None = None
        clip_path: str | None = None

        if terms:
            hits = db.find_by_tags(terms)
            if hits:
                # find_by_tags returns LRU-first — take the least-recently-used clip
                best = hits[0]
                clip_id = best["id"]
                clip_path = best["filepath"]

        edl.append({
            "clip_id": clip_id,
            "clip_path": clip_path,
            "timeline_start": start,
            "timeline_end": end,
            "source_text": text.strip(),
            "search_terms": terms,
        })

    return edl


def edl_to_json(edl: list[dict], output_path: str) -> None:
    """
    Persist an EDL to a JSON file.

    Args:
        edl:         List of EDL entry dicts from ``generate_edl()``.
        output_path: Destination file path (parent directories are created if needed).
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)
    print(f"[edit_decision] EDL saved to {output_path}", flush=True)


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python edit_decision.py <transcript.json> [output_edl.json] [db_path]\n"
            "\n"
            "  transcript.json   Output from whisperx_transcriber.py\n"
            "  output_edl.json   Where to write the EDL (default: edl_output.json)\n"
            "  db_path           Path to broll_cache.db (default: cache/broll_cache.db)\n"
        )
        sys.exit(1)

    _transcript_path = sys.argv[1]
    _output_path = sys.argv[2] if len(sys.argv) > 2 else "edl_output.json"
    _db_path = sys.argv[3] if len(sys.argv) > 3 else "cache/broll_cache.db"

    try:
        with open(_transcript_path, encoding="utf-8") as _f:
            _segments = json.load(_f)
    except FileNotFoundError:
        print(f"ERROR: transcript file not found: {_transcript_path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as _e:
        print(f"ERROR: invalid JSON in transcript file: {_e}", file=sys.stderr)
        sys.exit(1)

    try:
        _edl = generate_edl(_segments, clip_db_path=_db_path)
    except (ImportError, FileNotFoundError) as _e:
        print(f"ERROR: {_e}", file=sys.stderr)
        sys.exit(1)

    edl_to_json(_edl, _output_path)

    matched = sum(1 for e in _edl if e["clip_id"])
    print(f"\n[edit_decision] {len(_edl)} EDL entries — {matched} matched, "
          f"{len(_edl) - matched} unmatched:")
    for entry in _edl:
        status = entry["clip_path"] or "(no match)"
        print(
            f"  [{entry['timeline_start']:.2f}s → {entry['timeline_end']:.2f}s]"
            f"  terms={entry['search_terms']}"
            f"  →  {status}"
        )
