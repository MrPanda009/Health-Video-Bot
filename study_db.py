"""
Study & Topic Database
======================
SQLite-backed registry tracking:
  - studies: every PubMed study ever used in a job, with a rolling cooldown window
    so the same paper cannot be reused within `cooldown_days` days.
  - topics: the pool of PubMed search topics, with usage counters so Stage 1 can
    auto-select the least-recently-used topic each run.

On first initialisation the topics table is seeded from
`niche_profile.json["research"]["topic_rotation"]`.

Usage
-----
    from study_db import StudyDB

    db = StudyDB()

    # Topics
    topics = db.get_topics()               # LRU-first
    db.add_topic("insulin resistance diet")
    db.mark_topic_used("insulin resistance diet")

    # Studies
    db.add_or_update_study(pmid="12345678", topic="diabetes", title="...", ...)
    db.mark_study_used("12345678", job_id="abc-123", cooldown_days=30)
    if db.is_in_cooldown("12345678"):
        print("skip this one")
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

CACHE_DIR   = os.getenv("CACHE_DIR", "cache")
DEFAULT_DB  = os.path.join(CACHE_DIR, "study_db.sqlite")
NICHE_PROFILE_PATH = os.getenv("NICHE_PROFILE_PATH", "niche_profile.json")

# ─── Schema ───────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS studies (
    pmid            TEXT PRIMARY KEY,
    topic           TEXT NOT NULL,
    title           TEXT NOT NULL,
    authors         TEXT NOT NULL DEFAULT '[]',
    journal         TEXT,
    year            INTEGER,
    doi             TEXT,
    study_type      TEXT,
    last_used_at    TEXT,
    last_used_job   TEXT,
    cooldown_until  TEXT,
    created_at      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active'
                        CHECK(status IN ('active', 'cooldown'))
);

CREATE INDEX IF NOT EXISTS idx_studies_cooldown ON studies(cooldown_until);
CREATE INDEX IF NOT EXISTS idx_studies_topic    ON studies(topic);

CREATE TABLE IF NOT EXISTS topics (
    id              TEXT PRIMARY KEY,
    name            TEXT UNIQUE NOT NULL,
    times_used      INTEGER NOT NULL DEFAULT 0,
    last_used_at    TEXT,
    created_at      TEXT NOT NULL,
    active          INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_topics_active ON topics(active);
"""


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _study_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    if isinstance(d.get("authors"), str):
        try:
            d["authors"] = json.loads(d["authors"])
        except (json.JSONDecodeError, TypeError):
            d["authors"] = []
    # Recompute live status based on current time
    now = _now_iso()
    if d.get("cooldown_until") and d["cooldown_until"] > now:
        d["status"] = "cooldown"
    else:
        d["status"] = "active"
    return d


def _topic_row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["active"] = bool(d["active"])
    return d


# ─── StudyDB ──────────────────────────────────────────────────────────────────

class StudyDB:
    """
    Thread-safe SQLite wrapper managing both the study cooldown registry and
    the topic pool. Each method opens its own connection (WAL mode).
    """

    def __init__(self, db_path: str = DEFAULT_DB) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._seed_topics()

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

    def _seed_topics(self) -> None:
        """Insert any topics from niche_profile that aren't in the DB yet."""
        try:
            with open(NICHE_PROFILE_PATH, encoding="utf-8") as f:
                profile = json.load(f)
            rotation = profile.get("research", {}).get("topic_rotation", [])
        except (FileNotFoundError, json.JSONDecodeError):
            return

        now = _now_iso()
        with self._connect() as conn:
            for name in rotation:
                conn.execute(
                    "INSERT OR IGNORE INTO topics (id, name, created_at) VALUES (?, ?, ?)",
                    (str(uuid.uuid4()), name, now),
                )

    # ── Topics: public API ────────────────────────────────────────────────────

    def get_topics(self, active_only: bool = True) -> list[dict]:
        """
        Return topics ordered LRU-first (least used / least recently used first).

        Args:
            active_only: If True, exclude topics with active=0.

        Returns:
            List of topic dicts.
        """
        if active_only:
            sql = """
                SELECT * FROM topics
                WHERE active = 1
                ORDER BY times_used ASC,
                         last_used_at ASC NULLS FIRST,
                         created_at ASC
            """
            params: tuple = ()
        else:
            sql = """
                SELECT * FROM topics
                ORDER BY active DESC, times_used ASC,
                         last_used_at ASC NULLS FIRST
            """
            params = ()

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_topic_row_to_dict(r) for r in rows]

    def add_topic(self, name: str) -> str:
        """
        Add a new topic. Raises ValueError if a topic with that name already exists
        (even if inactive — reactivate instead).

        Args:
            name: The PubMed search query string.

        Returns:
            The new topic's UUID.
        """
        name = name.strip()
        if not name:
            raise ValueError("Topic name cannot be empty.")

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id, active FROM topics WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                if not existing["active"]:
                    conn.execute(
                        "UPDATE topics SET active = 1 WHERE id = ?", (existing["id"],)
                    )
                    return existing["id"]
                raise ValueError(f"Topic already exists: {name!r}")
            topic_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO topics (id, name, created_at) VALUES (?, ?, ?)",
                (topic_id, name, _now_iso()),
            )
        return topic_id

    def remove_topic(self, topic_id: str) -> None:
        """Soft-delete a topic by setting active=0."""
        with self._connect() as conn:
            conn.execute("UPDATE topics SET active = 0 WHERE id = ?", (topic_id,))

    def mark_topic_used(self, name: str) -> None:
        """Increment times_used and set last_used_at for the named topic."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE topics
                SET times_used   = times_used + 1,
                    last_used_at = ?
                WHERE name = ?
                """,
                (_now_iso(), name),
            )

    def get_topic_stats(self) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) AS total_active,
                    SUM(CASE WHEN active = 0 THEN 1 ELSE 0 END) AS total_inactive,
                    SUM(times_used)                              AS total_uses
                FROM topics
                """
            ).fetchone()
            most = conn.execute(
                "SELECT name FROM topics WHERE active=1 ORDER BY times_used DESC LIMIT 1"
            ).fetchone()
            least = conn.execute(
                "SELECT name FROM topics WHERE active=1 ORDER BY times_used ASC, "
                "last_used_at ASC NULLS FIRST LIMIT 1"
            ).fetchone()

        return {
            "total_active":   row["total_active"] or 0,
            "total_inactive": row["total_inactive"] or 0,
            "total_uses":     row["total_uses"] or 0,
            "most_used":      most["name"] if most else None,
            "least_used":     least["name"] if least else None,
        }

    # ── Studies: public API ───────────────────────────────────────────────────

    def add_or_update_study(
        self,
        pmid: str,
        topic: str,
        title: str,
        authors: list[str],
        journal: Optional[str],
        year: Optional[int],
        doi: Optional[str],
        study_type: Optional[str],
    ) -> None:
        """
        Upsert a study record. If the PMID already exists, updates metadata fields
        (topic, title, etc.) without touching cooldown/usage fields.
        """
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT pmid FROM studies WHERE pmid = ?", (pmid,)
            ).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE studies
                    SET topic=?, title=?, authors=?, journal=?, year=?, doi=?, study_type=?
                    WHERE pmid=?
                    """,
                    (topic, title, json.dumps(authors), journal, year, doi, study_type, pmid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO studies
                        (pmid, topic, title, authors, journal, year, doi, study_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pmid, topic, title, json.dumps(authors), journal, year, doi, study_type, _now_iso()),
                )

    def is_in_cooldown(self, pmid: str) -> bool:
        """Return True if this PMID's cooldown_until is in the future."""
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT cooldown_until FROM studies WHERE pmid = ?", (pmid,)
            ).fetchone()
        if row is None:
            return False
        return bool(row["cooldown_until"] and row["cooldown_until"] > now)

    def mark_study_used(self, pmid: str, job_id: str, cooldown_days: int = 30) -> None:
        """
        Record that a study was used in a job and set its cooldown window.

        Args:
            pmid:          PubMed ID.
            job_id:        Job UUID.
            cooldown_days: How many days before this study is eligible again.
        """
        now = datetime.now(timezone.utc)
        cooldown_until = (now + timedelta(days=cooldown_days)).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE studies
                SET last_used_at  = ?,
                    last_used_job = ?,
                    cooldown_until = ?,
                    status         = 'cooldown'
                WHERE pmid = ?
                """,
                (now.isoformat(), job_id, cooldown_until, pmid),
            )

    def get_all_studies(self, status: str = "all") -> list[dict]:
        """
        Return all study records.

        Args:
            status: "active", "cooldown", or "all".

        Returns:
            List of study dicts with live-computed status.
        """
        now = _now_iso()
        if status == "cooldown":
            sql = "SELECT * FROM studies WHERE cooldown_until > ? ORDER BY cooldown_until ASC"
            params: tuple = (now,)
        elif status == "active":
            sql = "SELECT * FROM studies WHERE (cooldown_until IS NULL OR cooldown_until <= ?) ORDER BY last_used_at DESC NULLS LAST"
            params = (now,)
        else:
            sql = "SELECT * FROM studies ORDER BY created_at DESC"
            params = ()

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_study_row_to_dict(r) for r in rows]

    def get_study_stats(self) -> dict:
        now = _now_iso()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN cooldown_until IS NULL OR cooldown_until <= ? THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN cooldown_until > ?                            THEN 1 ELSE 0 END) AS in_cooldown
                FROM studies
                """,
                (now, now),
            ).fetchone()
        return {
            "total":       row["total"] or 0,
            "active":      row["active"] or 0,
            "in_cooldown": row["in_cooldown"] or 0,
        }


# ─── CLI (used by the Next.js API routes) ────────────────────────────────────

def _cli_studies_list(db: StudyDB, status: str) -> None:
    studies = db.get_all_studies(status=status)
    print(json.dumps({"studies": studies, "stats": db.get_study_stats()}, ensure_ascii=False))


def _cli_studies_stats(db: StudyDB) -> None:
    print(json.dumps(db.get_study_stats(), ensure_ascii=False))


def _cli_topics_list(db: StudyDB) -> None:
    topics = db.get_topics(active_only=False)
    print(json.dumps({"topics": topics, "stats": db.get_topic_stats()}, ensure_ascii=False))


def _cli_topics_stats(db: StudyDB) -> None:
    print(json.dumps(db.get_topic_stats(), ensure_ascii=False))


def _cli_topics_add(db: StudyDB, name: str) -> None:
    try:
        topic_id = db.add_topic(name)
        print(json.dumps({"ok": True, "id": topic_id}, ensure_ascii=False))
    except ValueError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(1)


def _cli_topics_remove(db: StudyDB, topic_id: str) -> None:
    db.remove_topic(topic_id)
    print(json.dumps({"ok": True}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Study & topic database CLI")
    parser.add_argument("--db", default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="entity")

    # ── studies subcommands ──────────────────────────────────────────────────
    p_studies = sub.add_parser("studies")
    s_studies  = p_studies.add_subparsers(dest="action")

    p_sl = s_studies.add_parser("list")
    p_sl.add_argument("--status", default="all", choices=["active", "cooldown", "all"])

    s_studies.add_parser("stats")

    # ── topics subcommands ───────────────────────────────────────────────────
    p_topics = sub.add_parser("topics")
    s_topics  = p_topics.add_subparsers(dest="action")

    s_topics.add_parser("list")
    s_topics.add_parser("stats")

    p_ta = s_topics.add_parser("add")
    p_ta.add_argument("name")

    p_tr = s_topics.add_parser("remove")
    p_tr.add_argument("id")

    args = parser.parse_args()
    db   = StudyDB(args.db)

    if args.entity == "studies":
        if args.action == "list":
            _cli_studies_list(db, args.status)
        elif args.action == "stats":
            _cli_studies_stats(db)
        else:
            p_studies.print_help(); sys.exit(1)

    elif args.entity == "topics":
        if args.action == "list":
            _cli_topics_list(db)
        elif args.action == "stats":
            _cli_topics_stats(db)
        elif args.action == "add":
            _cli_topics_add(db, args.name)
        elif args.action == "remove":
            _cli_topics_remove(db, args.id)
        else:
            p_topics.print_help(); sys.exit(1)

    else:
        parser.print_help(); sys.exit(1)
