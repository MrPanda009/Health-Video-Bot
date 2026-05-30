#!/usr/bin/env python3
"""
Stage 0 — Job & Asset Cleanup Utility
=====================================
Responsibilities:
  1. Scan jobs/ directory for existing pipeline job state files.
  2. Parse metadata (topic, study title, created date, status) from job JSON files.
  3. Present a styled interactive terminal selection menu.
  4. Allow users to select specific jobs, ranges, all jobs, or orphaned asset directories for deletion.
  5. Safely delete jobs/{job_id}.json and its assets/{job_id}/ folder.
  6. Confirm all deletion actions before proceeding to prevent accidental data loss.

Usage:
  uv run python stages/stage_0_clean.py
"""

import os
import re
import json
import shutil
from pathlib import Path
from datetime import datetime

# ─── Config ───────────────────────────────────────────────────────────────────
JOBS_DIR = os.getenv("JOBS_DIR", "jobs")
ASSETS_DIR = os.getenv("ASSETS_DIR", "assets")
UUID_REGEX = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def parse_timestamp(ts_str: str) -> str:
    """Format an ISO timestamp string to a cleaner YYYY-MM-DD HH:MM format."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ts_str[:16].replace("T", " ")


def get_all_jobs() -> list[dict]:
    """Scan the jobs directory, parse JSONs, and return a sorted list of job dicts."""
    jobs_path = Path(JOBS_DIR)
    if not jobs_path.exists():
        return []

    jobs = []
    for file_path in jobs_path.glob("*.json"):
        if not file_path.is_file():
            continue
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                job_data = json.load(f)

            # Ensure minimal keys exist
            if "job_id" not in job_data:
                job_data["job_id"] = file_path.stem
            if "created_at" not in job_data:
                job_data["created_at"] = datetime.fromtimestamp(file_path.stat().st_ctime).isoformat()
            if "status" not in job_data:
                job_data["status"] = "unknown"

            # Add file path to job dict
            job_data["_file_path"] = file_path
            jobs.append(job_data)
        except Exception as e:
            print(f"\033[31m[Warning] Could not parse job file {file_path.name}: {e}\033[0m")
            continue

    # Sort jobs chronologically (oldest first)
    jobs.sort(key=lambda j: j.get("created_at", ""))
    return jobs


def display_jobs_table(jobs: list[dict]) -> None:
    """Print a beautifully formatted table representing all discovered jobs."""
    print("\n" + "=" * 85)
    print(f"  {'ACTIVE JOBS IN DATABASE':<81}")
    print("=" * 85)
    print(f"  {'Index':<6} | {'Job ID':<8} | {'Topic / Study Title':<38} | {'Created At':<16} | {'Status'}")
    print("-" * 85)

    for idx, job in enumerate(jobs, 1):
        job_id_short = job["job_id"][:8]
        created_at_clean = parse_timestamp(job.get("created_at", ""))
        status = job.get("status", "unknown")

        # Get topic and study title for display
        topic = job.get("study", {}).get("topic", "") if job.get("study") else "No topic registered"
        study_title = job.get("study", {}).get("title", "") if job.get("study") else ""

        # Color the status field
        status_color = "\033[36m"  # Cyan default
        if status == "complete":
            status_color = "\033[32m"  # Green
        elif status == "error":
            status_color = "\033[31m"  # Red
        elif "complete" in status:
            status_color = "\033[32;1m"  # Bright Green

        reset_color = "\033[0m"

        # Print main line: index, ID, topic, created date, status
        topic_preview = topic[:35] + "..." if len(topic) > 35 else topic
        print(f"  [{idx:<2}]  | {job_id_short:<8} | {topic_preview:<38} | {created_at_clean:<16} | {status_color}{status}{reset_color}")

        # Print secondary line: study title if available
        if study_title:
            study_preview = study_title[:45] + "..." if len(study_title) > 45 else study_title
            print(f"        |          | \033[90m> Study: {study_preview:<40}\033[0m |                  |")

    print("=" * 85)


def parse_selection(selection_str: str, max_val: int) -> list[int]:
    """Parse comma-separated values and dash-separated ranges into list of 0-based indices."""
    indices = set()
    parts = [p.strip() for p in selection_str.split(",") if p.strip()]

    for part in parts:
        if "-" in part:
            match = re.match(r"^(\d+)-(\d+)$", part)
            if match:
                start = int(match.group(1))
                end = int(match.group(2))
                if 1 <= start <= end <= max_val:
                    for i in range(start, end + 1):
                        indices.add(i - 1)
                else:
                    raise ValueError(f"Range '{part}' out of bounds or invalid")
            else:
                raise ValueError(f"Invalid range format: '{part}'")
        elif part.isdigit():
            val = int(part)
            if 1 <= val <= max_val:
                indices.add(val - 1)
            else:
                raise ValueError(f"Index '{val}' is out of bounds")
        else:
            raise ValueError(f"Invalid input token: '{part}'")

    return sorted(list(indices))


def delete_job_data(job_id: str, job_file_path: Path) -> bool:
    """Delete a single job's JSON state file and assets subdirectory recursively."""
    success = True

    # 1. Delete job file
    try:
        if job_file_path.exists():
            job_file_path.unlink()
            print(f"  \033[32m✓ Deleted job file: {job_file_path.name}\033[0m")
    except Exception as e:
        print(f"  \033[31m✗ Error deleting job file {job_file_path.name}: {e}\033[0m")
        success = False

    # 2. Delete assets directory
    assets_dir_path = Path(ASSETS_DIR) / job_id
    try:
        if assets_dir_path.exists() and assets_dir_path.is_dir():
            shutil.rmtree(assets_dir_path)
            print(f"  \033[32m✓ Deleted assets directory: assets/{job_id}/\033[0m")
    except Exception as e:
        print(f"  \033[31m✗ Error deleting assets folder assets/{job_id}/: {e}\033[0m")
        success = False

    return success


def run_orphaned_cleanup(active_job_ids: set[str]) -> None:
    """Find and delete folders in assets/ that are UUIDs but don't correspond to any active job."""
    assets_path = Path(ASSETS_DIR)
    if not assets_path.exists() or not assets_path.is_dir():
        print(f"[Stage 0] Assets directory '{ASSETS_DIR}' does not exist.")
        return

    # Scan for potential orphaned folders
    orphans = []
    for item in assets_path.iterdir():
        if item.is_dir() and UUID_REGEX.match(item.name):
            if item.name not in active_job_ids:
                orphans.append(item)

    if not orphans:
        print("\n\033[32mNo orphaned asset folders found in assets/ directory.\033[0m")
        return

    print("\n" + "=" * 60)
    print(f"  \033[33mFOUND {len(orphans)} ORPHANED ASSET FOLDERS\033[0m")
    print("=" * 60)
    for idx, o in enumerate(orphans, 1):
        print(f"  [{idx}] assets/{o.name}/")
    print("=" * 60)

    choice = input("\nAre you absolutely sure you want to delete these orphaned folders? (y/N): ").strip().lower()
    if choice in ("y", "yes"):
        print("\nStarting orphaned assets cleanup...")
        deleted_count = 0
        for o in orphans:
            try:
                shutil.rmtree(o)
                print(f"  \033[32m✓ Removed: assets/{o.name}/\033[0m")
                deleted_count += 1
            except Exception as e:
                print(f"  \033[31m✗ Error removing assets/{o.name}/: {e}\033[0m")
        print(f"\nCompleted! Deleted {deleted_count} orphaned folder(s).")
    else:
        print("\nOrphaned assets cleanup cancelled.")


def main():
    print("======================================================================")
    print("  HEALTH VIDEO BOT - STAGE 0: JOB & ASSET CLEANUP TOOL  ")
    print("======================================================================")

    while True:
        # Load latest list of jobs on each loop iteration
        jobs = get_all_jobs()
        active_ids = {j["job_id"] for j in jobs}

        if not jobs:
            print("\nNo active jobs or work records found in database.")
            print("\nOptions:")
            print("  [orphans] Find and delete orphaned asset folders")
            print("  [q]       Quit")
            choice = input("\nSelect option: ").strip().lower()

            if choice in ("q", "quit", "exit"):
                print("Exiting cleanup tool. Goodbye!")
                break
            elif choice == "orphans":
                run_orphaned_cleanup(active_ids)
            else:
                print("\033[31mInvalid option or no jobs to display.\033[0m")
            continue

        # Display jobs
        display_jobs_table(jobs)

        # Show options menu
        print("\nCleanup Menu:")
        print("  - Enter specific index(es) to delete (e.g. '1', '1,3', '1-3')")
        print("  - Type 'all' to delete ALL active jobs and their assets")
        print("  - Type 'orphans' to find and purge orphaned folders in assets/")
        print("  - Type 'q' to quit")

        choice = input("\nSelect option: ").strip()

        if choice.lower() in ("q", "quit", "exit"):
            print("Exiting cleanup tool. Goodbye!")
            break

        elif choice.lower() == "orphans":
            run_orphaned_cleanup(active_ids)

        elif choice.lower() == "all":
            confirm = input("\n\033[31;1m⚠️ WARNING: You are about to delete ALL active jobs and assets. Are you sure? (y/N): \033[0m").strip().lower()
            if confirm in ("y", "yes"):
                print("\nPurging all jobs and assets...")
                success_count = 0
                for job in jobs:
                    if delete_job_data(job["job_id"], job["_file_path"]):
                        success_count += 1
                print(f"\nDone! Purged {success_count} / {len(jobs)} active jobs.")
            else:
                print("\nPurge cancelled.")

        else:
            try:
                selected_indices = parse_selection(choice, len(jobs))
                selected_jobs = [jobs[i] for i in selected_indices]

                print("\n" + "=" * 50)
                print(f"  \033[33mSELECTED FOR DELETION:\033[0m")
                print("=" * 50)
                for idx, job in enumerate(selected_jobs, 1):
                    topic = job.get("study", {}).get("topic", "No topic registered") if job.get("study") else "No topic registered"
                    print(f"  [{idx}] Job ID: {job['job_id'][:8]}... | Topic: {topic}")
                print("=" * 50)

                confirm = input(f"\nAre you sure you want to delete these {len(selected_jobs)} job(s)? (y/N): ").strip().lower()
                if confirm in ("y", "yes"):
                    print("\nExecuting deletions...")
                    success_count = 0
                    for job in selected_jobs:
                        if delete_job_data(job["job_id"], job["_file_path"]):
                            success_count += 1
                    print(f"\nSuccessfully deleted {success_count} / {len(selected_jobs)} selected jobs.")
                else:
                    print("\nDeletion cancelled.")

            except ValueError as ve:
                print(f"\n\033[31mError parsing selection: {ve}\033[0m")
                print("Please enter valid indexes, lists (e.g. '1,2'), ranges (e.g. '1-3'), or keywords.")


if __name__ == "__main__":
    main()
