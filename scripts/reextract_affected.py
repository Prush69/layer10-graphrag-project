"""
Force re-extract only the 8 files that had hallucinated evidence excerpts.
Runs them through the extraction pipeline with force=True to overwrite existing files.
"""
import sys, os, json
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
os.chdir(root)

import config

# The 8 files confirmed to have hallucinated excerpts (text not in source at all)
AFFECTED_ISSUES = [
    "13991",  # 4 hallucinations
    "17275",  # 2 hallucinations
    "17355",  # 12 hallucinations
    "21057",  # 1 hallucination
    "24417",  # 1 hallucination
    "31357",  # 1 hallucination
    "31446",  # 1 hallucination
    "35860",  # 2 hallucinations
]

def run():
    from extraction.pipeline import ExtractionPipeline

    raw_files = [config.RAW_DATA_DIR / f"issue_{n}.json" for n in AFFECTED_ISSUES]
    missing = [f for f in raw_files if not f.exists()]
    if missing:
        print(f"[WARN] Missing raw files: {[str(f) for f in missing]}")
        raw_files = [f for f in raw_files if f.exists()]

    print(f"Re-extracting {len(raw_files)} affected files...\n")
    pipeline = ExtractionPipeline()

    results = []
    errors = []

    # Force-delete the old extraction files first so pipeline re-runs them
    for raw_f in raw_files:
        num = raw_f.stem.split("_")[1]
        ex_path = config.EXTRACTION_DIR / f"extraction_{num}.json"
        if ex_path.exists():
            ex_path.unlink()
            print(f"  Deleted old: {ex_path.name}")

    # Run extraction with force=True scoped to these files only
    # We'll do it by directly setting the files list
    batches = [raw_files[i:i+3] for i in range(0, len(raw_files), 3)]
    import time
    for i, batch in enumerate(batches):
        if i > 0:
            print(f"  Waiting 13s for rate limit...")
            time.sleep(13)
        try:
            batch_results, err_count = pipeline._extract_and_save_batch(i, batch, force=True)
            results.extend(batch_results)
            errors.append(err_count)
            print(f"  Batch {i+1}: {len(batch_results)} results, {err_count} errors")
        except Exception as e:
            print(f"  Batch {i+1} FAILED: {e}")
            errors.append(len(batch))

    print(f"\nRe-extraction done: {len(results)} succeeded, {sum(errors)} errors")

    # Run repair_offsets on the freshly extracted files
    print("\nRunning offset repair on new extraction files...")
    from scripts.repair_offsets import run as repair_run
    repair_run()

    print("\nDone. Now run: python run.py --step graph && python run.py --step query")

if __name__ == "__main__":
    run()
