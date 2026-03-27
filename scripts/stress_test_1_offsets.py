"""
Stress Test 1: Offset Alignment
For every Evidence in data/extractions/*.json, load the raw source,
slice it at offset_start:offset_end, and assert it matches the excerpt exactly.
"""
import json
import os
import sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))
os.chdir(root)

import config

EXTRACTION_DIR = config.EXTRACTION_DIR
RAW_DIR = config.RAW_DATA_DIR

def build_source_text(raw: dict) -> str:
    """Reconstruct the source text the LLM saw during extraction."""
    issue = raw.get("issue", {})
    body = issue.get("body", "") or ""
    comments = raw.get("comments", [])
    # Build composite text same way the prompt does
    text = body
    for c in comments[:15]:
        c_body = (c.get("body", "") or "")[:1000]
        text += "\n" + c_body
    return text

def run():
    files = sorted(EXTRACTION_DIR.glob("extraction_*.json"))
    print(f"Checking {len(files)} extraction files...\n")

    total_evidence = 0
    total_pass = 0
    total_fail = 0
    not_found_skip = 0
    failures = []

    for ef in files:
        with open(ef, encoding="utf-8") as f:
            ex = json.load(f)

        # Use the source_text saved by repair_offsets.py
        # If not present, skip (run repair_offsets.py first)
        source_text = ex.get("source_text", "")
        if not source_text:
            print(f"  [SKIP] No source_text in {ef.name} — run repair_offsets.py first")
            continue

        for assertion in ex.get("assertions", []):
            for ev in assertion.get("evidence", []):
                total_evidence += 1
                excerpt = ev.get("excerpt", "")
                start = ev.get("offset_start")
                end = ev.get("offset_end")

                if start is None or end is None:
                    failures.append({
                        "source_id": ex.get("source_id"),
                        "excerpt": excerpt[:60],
                        "reason": "Missing offsets"
                    })
                    total_fail += 1
                    continue

                sliced = source_text[start:end]

                if sliced == excerpt:
                    total_pass += 1
                elif excerpt not in source_text:
                    # LLM hallucinated an excerpt that never existed in source
                    not_found_skip += 1
                    total_fail += 1
                else:
                    total_fail += 1
                    failures.append({
                        "source_id": ex.get("source_id"),
                        "offset_start": start,
                        "offset_end": end,
                        "expected_excerpt": excerpt[:80],
                        "actual_slice":     sliced[:80],
                        "reason": "Mismatch (offset incorrect despite repair)"
                    })

    print(f"=== OFFSET ALIGNMENT TEST RESULTS ===")
    print(f"Total evidence items:  {total_evidence}")
    print(f"PASS (exact match):    {total_pass}")
    print(f"FAIL (mismatch):       {total_fail}")
    print(f"Pass rate:             {total_pass/total_evidence*100:.1f}%" if total_evidence else "N/A")

    if failures:
        print(f"\n--- FAILURES (first 5) ---")
        for f in failures[:5]:
            print(json.dumps(f, indent=2))
    else:
        print("\n[ALL PASS] Every evidence excerpt exactly matches its source text offset.")

    return total_fail == 0

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
