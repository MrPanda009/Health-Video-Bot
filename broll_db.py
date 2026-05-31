"""
B-roll Clip Database
====================
SQLite-backed registry for downloaded video clips. Tracks every clip that has
ever been downloaded so the pipeline never re-downloads the same file, and so
Stage 4a can reuse clips across jobs with LRU-style prioritisation.

Schema lives in a single `clips` table — see `_init_db()` for the full DDL.

Usage
-----
    from broll_db import ClipDB

    db = ClipDB()                        # default: cache/broll_cache.db
    db = ClipDB("path/to/custom.db")

    clip_id = db.add_clip(...)
    clips   = db.find_by_tags(["sunset", "nature"])
    if not db.is_duplicate(url):
        download(url)
    db.mark_used(clip_id, "job-abc123")
    missing = db.verify_integrity()
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR   = os.getenv("CACHE_DIR", "cache")
DEFAULT_DB  = os.path.join(CACHE_DIR, "broll_cache.db")

# ─── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS clips (
    id                 TEXT    PRIMARY KEY,
    filename           TEXT    NOT NULL,
    filepath           TEXT    NOT NULL,
    source_url         TEXT    NOT NULL,
    search_tags        TEXT    NOT NULL DEFAULT '[]',
    content_tags       TEXT    NOT NULL DEFAULT '[]',
    resolution         TEXT,
    duration_sec       REAL,
    license_type       TEXT,
    times_used         INTEGER NOT NULL DEFAULT 0,
    last_used_at       TEXT,
    last_used_project  TEXT,
    status             TEXT    NOT NULL DEFAULT 'active'
                               CHECK(status IN ('active', 'missing', 'deleted')),
    created_at         TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_source_url ON clips(source_url);
CREATE INDEX IF NOT EXISTS idx_clips_status     ON clips(status);
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict with JSON fields deserialized."""
    d = dict(row)
    for field in ("search_tags", "content_tags"):
        if isinstance(d.get(field), str):
            try:
                d[field] = json.loads(d[field])
            except (json.JSONDecodeError, TypeError):
                d[field] = []
    return d


# ─── ClipDB ───────────────────────────────────────────────────────────────────

class ClipDB:
    """
    Thin SQLite wrapper for the B-roll clip registry.

    Thread safety: each method opens and closes its own connection, so it is
    safe to call from concurrent subprocesses as long as SQLite is compiled
    with SQLITE_THREADSAFE (it is, by default).
    """

    def __init__(self, db_path: str = DEFAULT_DB) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_DDL)

    # ── Public API ────────────────────────────────────────────────────────────

    def add_clip(
        self,
        filename: str,
        filepath: str,
        source_url: str,
        search_tags: list[str],
        content_tags: list[str],
        resolution: Optional[str],
        duration_sec: Optional[float],
        license_type: str,
    ) -> str:
        """
        Insert a new clip record and return its UUID.

        Does NOT check for duplicates — call is_duplicate() first if needed.

        Args:
            filename:     Basename of the file (e.g. "context_0.mp4").
            filepath:     Absolute path to the file on disk.
            source_url:   Original download URL (used for dedup).
            search_tags:  Terms used to find this clip (e.g. ["city traffic"]).
            content_tags: Descriptive tags of what the clip shows.
            resolution:   String like "1920x1080", or None if unknown.
            duration_sec: Clip duration in seconds, or None if unknown.
            license_type: Source identifier, e.g. "pexels_free", "pixabay".

        Returns:
            The newly assigned UUID string.
        """
        clip_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO clips
                    (id, filename, filepath, source_url, search_tags, content_tags,
                     resolution, duration_sec, license_type, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clip_id,
                    filename,
                    str(filepath),
                    source_url,
                    json.dumps(search_tags),
                    json.dumps(content_tags),
                    resolution,
                    duration_sec,
                    license_type,
                    _now_iso(),
                ),
            )
        return clip_id

    def find_by_tags(self, tags: list[str]) -> list[dict]:
        """
        Search for clips whose search_tags or content_tags contain any of `tags`.

        Matching is case-insensitive substring search against the raw JSON column
        (fast for typical tag lists; no need for a full-text index).

        Results are ordered by:
          1. times_used ASC  — least-used clips first (spread usage evenly)
          2. last_used_at ASC NULLS FIRST  — least recently used first

        Args:
            tags: List of tag strings to search for.

        Returns:
            List of clip dicts (tags fields are deserialized to Python lists).
        """
        if not tags:
            return []

        # Build one LIKE clause per tag, checking both tag columns
        conditions = []
        params: list[str] = []
        for tag in tags:
            pattern = f"%{tag.lower()}%"
            conditions.append(
                "(LOWER(search_tags) LIKE ? OR LOWER(content_tags) LIKE ?)"
            )
            params += [pattern, pattern]

        where = " OR ".join(conditions)
        sql = f"""
            SELECT * FROM clips
            WHERE status = 'active' AND ({where})
            ORDER BY times_used ASC,
                     last_used_at ASC NULLS FIRST
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def is_duplicate(self, source_url: str) -> bool:
        """
        Return True if an active clip with this source_url already exists.

        Deleted and missing clips are excluded — the URL can be re-downloaded
        to replace a clip that is no longer on disk.

        Args:
            source_url: The download URL to check.

        Returns:
            True if a live (active) copy already exists in the DB.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM clips WHERE source_url = ? AND status = 'active' LIMIT 1",
                (source_url,),
            ).fetchone()
        return row is not None

    def mark_used(self, clip_id: str, project_name: str) -> None:
        """
        Record that a clip was used in a project.

        Increments times_used, sets last_used_at to now, and records the project.

        Args:
            clip_id:      UUID of the clip.
            project_name: Job ID or human-readable project name.
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE clips
                SET times_used        = times_used + 1,
                    last_used_at      = ?,
                    last_used_project = ?
                WHERE id = ?
                """,
                (_now_iso(), project_name, clip_id),
            )

    def mark_missing(self, clip_id: str) -> None:
        """
        Set a clip's status to 'missing'.

        Called when the file at clip.filepath no longer exists on disk.
        Does not delete the DB record — use get_all_clips(status='missing')
        to review and decide whether to re-download.

        Args:
            clip_id: UUID of the clip to flag.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE clips SET status = 'missing' WHERE id = ?",
                (clip_id,),
            )

    def verify_integrity(self) -> list[str]:
        """
        Scan all active clips and flag any whose file no longer exists on disk.

        Calls mark_missing() for each affected clip. Safe to run at any time —
        it only reads the DB and the filesystem, then writes status updates.

        Returns:
            List of clip UUIDs that were newly marked as missing.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, filepath FROM clips WHERE status = 'active'"
            ).fetchall()

        newly_missing: list[str] = []
        for row in rows:
            if not Path(row["filepath"]).exists():
                self.mark_missing(row["id"])
                newly_missing.append(row["id"])

        return newly_missing

    def get_all_clips(self, status: str = "active") -> list[dict]:
        """
        Return all clips with the given status, ordered by created_at DESC.

        Args:
            status: One of "active", "missing", "deleted", or "all" to skip filtering.

        Returns:
            List of clip dicts.
        """
        if status == "all":
            sql = "SELECT * FROM clips ORDER BY created_at DESC"
            params: tuple = ()
        else:
            sql = "SELECT * FROM clips WHERE status = ? ORDER BY created_at DESC"
            params = (status,)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_stats(self) -> dict:
        """
        Return aggregate statistics about the clip library.

        Returns:
            Dict with keys: total, active, missing, deleted, total_uses,
            unique_projects, total_duration_sec.
        """
        with self._connect() as conn:
            counts = dict(
                conn.execute(
                    """
                    SELECT
                        COUNT(*)                                  AS total,
                        SUM(CASE WHEN status='active'  THEN 1 ELSE 0 END) AS active,
                        SUM(CASE WHEN status='missing' THEN 1 ELSE 0 END) AS missing,
                        SUM(CASE WHEN status='deleted' THEN 1 ELSE 0 END) AS deleted,
                        SUM(times_used)                           AS total_uses,
                        SUM(COALESCE(duration_sec, 0))            AS total_duration_sec
                    FROM clips
                    """
                ).fetchone()
            )
            unique_projects = conn.execute(
                "SELECT COUNT(DISTINCT last_used_project) FROM clips "
                "WHERE last_used_project IS NOT NULL"
            ).fetchone()[0]
        counts["unique_projects"] = unique_projects
        return counts


# ─── CLI (used by the Next.js API routes) ────────────────────────────────────

def _cli_list(db: ClipDB, status: str) -> None:
    clips = db.get_all_clips(status=status)
    print(json.dumps({"clips": clips, "stats": db.get_stats()}, ensure_ascii=False))


def _cli_verify(db: ClipDB) -> None:
    missing = db.verify_integrity()
    stats   = db.get_stats()
    print(json.dumps({"missing_ids": missing, "stats": stats}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="B-roll clip database CLI")
    sub    = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="List clips")
    p_list.add_argument("--status", default="active",
                        choices=["active", "missing", "deleted", "all"])
    p_list.add_argument("--db", default=DEFAULT_DB)

    p_verify = sub.add_parser("verify", help="Check file integrity")
    p_verify.add_argument("--db", default=DEFAULT_DB)

    p_demo = sub.add_parser("demo", help="Run usage examples")
    p_demo.add_argument("--db", default="/tmp/broll_demo.db")

    args = parser.parse_args()

    if args.command == "list":
        _cli_list(ClipDB(args.db), args.status)

    elif args.command == "verify":
        _cli_verify(ClipDB(args.db))

    elif args.command == "demo":
        print("── B-roll DB demo ──────────────────────────────────────────")
        db = ClipDB(args.db)

        # 1. add_clip
        cid1 = db.add_clip(
            filename="nature_0.mp4",
            filepath="/tmp/demo/nature_0.mp4",
            source_url="https://pexels.com/video/12345",
            search_tags=["nature", "forest walk"],
            content_tags=["trees", "sunlight", "path"],
            resolution="1920x1080",
            duration_sec=12.5,
            license_type="pexels_free",
        )
        print(f"1. add_clip       → {cid1}")

        cid2 = db.add_clip(
            filename="city_0.mp4",
            filepath="/tmp/demo/city_0.mp4",
            source_url="https://pixabay.com/video/67890",
            search_tags=["city traffic"],
            content_tags=["cars", "street", "urban"],
            resolution="1920x1080",
            duration_sec=8.0,
            license_type="pixabay",
        )
        print(f"   add_clip       → {cid2}")

        # 2. find_by_tags
        hits = db.find_by_tags(["urban", "forest"])
        print(f"2. find_by_tags   → {len(hits)} clip(s): {[h['filename'] for h in hits]}")

        # 3. is_duplicate
        dup = db.is_duplicate("https://pexels.com/video/12345")
        print(f"3. is_duplicate   → {dup}")

        # 4. mark_used
        db.mark_used(cid1, "job-demo-001")
        clips = db.get_all_clips()
        used  = next(c for c in clips if c["id"] == cid1)
        print(f"4. mark_used      → times_used={used['times_used']}, "
              f"project={used['last_used_project']}")

        # 5. mark_missing
        db.mark_missing(cid2)
        clips = db.get_all_clips(status="missing")
        print(f"5. mark_missing   → {len(clips)} clip(s) now missing")

        # 6. verify_integrity  (both filepaths are fake → both should be missing)
        db2 = ClipDB(args.db)
        # Re-add cid1 row in active state to show verify works
        cid3 = db.add_clip(
            filename="sunset_0.mp4",
            filepath="/nonexistent/sunset_0.mp4",
            source_url="https://pexels.com/video/99999",
            search_tags=["sunset"],
            content_tags=["sky", "orange", "clouds"],
            resolution="1920x1080",
            duration_sec=15.0,
            license_type="pexels_free",
        )
        missing = db.verify_integrity()
        print(f"6. verify_integrity → {len(missing)} newly marked missing: {missing}")

        # 7. get_all_clips
        all_clips = db.get_all_clips(status="all")
        print(f"7. get_all_clips  → {len(all_clips)} total clips in DB")

        # stats
        stats = db.get_stats()
        print(f"\n── Stats ────────────────────────────────────────────────────")
        for k, v in stats.items():
            print(f"   {k:<22} {v}")

    else:
        parser.print_help()
        sys.exit(1)
