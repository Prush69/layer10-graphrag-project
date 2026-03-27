"""
Backfill Extraction Script

Queries the extraction_runs registry for artifacts processed with an older
schema version and re-routes them through the extraction pipeline.

Usage:
    python scripts/backfill_extraction.py --from-schema-version 1 --to-schema-version 2
    python scripts/backfill_extraction.py --all  # Re-extract all artifacts

This is used when:
- The ontology has structural changes (new entity types, claim types)
- The extraction prompt or model changes (prompt engineering updates)
- Evidence fields are added (new source_type, offset fields)

The script is idempotent: files already at the target schema version are skipped.
"""
import os
import sys
import json
import argparse
from pathlib import Path

# Project root
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
os.chdir(root)

import config


def load_runs_registry() -> list[dict]:
    """Load extraction runs log."""
    runs_path = config.DATA_DIR / "runs" / "extraction_runs.json"
    if not runs_path.exists():
        return []
    with open(runs_path, encoding="utf-8") as f:
        return json.load(f)


def get_current_schema_version() -> int:
    """Get the current schema version from config or ontology."""
    return getattr(config, "SCHEMA_VERSION", 2)


def backfill(from_version: int = None, to_version: int = None, force_all: bool = False):
    """
    Run backfill extraction for stale artifact versions.

    Args:
        from_version: Only re-extract artifacts at this schema version
        to_version: Target schema version (defaults to current)
        force_all: Re-extract all artifacts regardless of version
    """
    from extraction.pipeline import ExtractionPipeline

    target_version = to_version or get_current_schema_version()
    runs = load_runs_registry()

    if not runs and not force_all:
        print("[INFO] No extraction runs found. Run extraction first with: python run.py --step extract")
        return

    # Find raw corpus files that need backfill
    raw_files = sorted(config.RAW_DATA_DIR.glob("issue_*.json"))
    extraction_dir = config.EXTRACTION_DIR

    # Build set of already-at-target-version source_ids
    up_to_date = set()
    for run in runs:
        if run.get("schema_version", 1) >= target_version and not force_all:
            up_to_date.add(run.get("source_id", ""))

    stale = [f for f in raw_files
             if f.stem.replace("issue_", "") not in up_to_date or force_all]

    if not stale:
        print(f"[OK] All {len(raw_files)} artifacts are at schema version {target_version}. Nothing to backfill.")
        return

    print(f"[BACKFILL] {len(stale)} artifacts need re-extraction to schema v{target_version}")
    print(f"  Skipping {len(raw_files) - len(stale)} already up-to-date artifacts\n")

    pipeline = ExtractionPipeline()
    backfilled = 0
    errors = 0

    for raw_file in stale:
        source_id = f"issue-{raw_file.stem.replace('issue_', '')}"
        print(f"  Re-extracting {source_id}...")
        try:
            with open(raw_file, encoding="utf-8") as f:
                raw = json.load(f)

            result = pipeline.extract_single(raw, source_id=source_id, force=True)
            if result:
                backfilled += 1
                print(f"    [OK] {len(result.entities)} entities, {len(result.assertions)} assertions")
            else:
                errors += 1
                print(f"    [SKIP] No result returned")
        except Exception as e:
            errors += 1
            print(f"    [ERROR] {e}")

    print(f"\n[BACKFILL COMPLETE] {backfilled} re-extracted, {errors} errors")
    print(f"Run 'python run.py --step graph' to rebuild the memory graph with the new extractions.")


def main():
    parser = argparse.ArgumentParser(
        description="Layer10 Backfill Extraction — re-extract stale artifacts after schema changes"
    )
    parser.add_argument("--from-schema-version", type=int, default=None,
                        help="Only re-extract artifacts at this schema version")
    parser.add_argument("--to-schema-version", type=int, default=None,
                        help="Target schema version (default: current)")
    parser.add_argument("--all", action="store_true", dest="force_all",
                        help="Force re-extract ALL artifacts regardless of version")
    args = parser.parse_args()

    backfill(
        from_version=args.from_schema_version,
        to_version=args.to_schema_version,
        force_all=args.force_all,
    )


if __name__ == "__main__":
    main()
