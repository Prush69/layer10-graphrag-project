"""
Retroactive Offset Repair Script

For each extraction file, rebuilds the exact source text the LLM was given
(_build_single_issue_text output), finds each evidence excerpt in that text
via text search (case-sensitive, then case-insensitive), and overwrites
offset_start/offset_end with the correct values.

Saves a corrected extraction file and writes the source_text into the
extraction JSON so that the alignment test and UI have the exact reference.

Run: python scripts/repair_offsets.py
"""
import json, os, sys
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root)); os.chdir(root)

import config
from extraction.prompts import _build_single_issue_text

EXTRACTION_DIR = config.EXTRACTION_DIR
RAW_DIR = config.RAW_DATA_DIR


def find_offset(text: str, excerpt: str) -> tuple[int, int] | None:
    """Find the first occurrence of excerpt in text. Returns (start, end) or None."""
    idx = text.find(excerpt)
    if idx >= 0:
        return idx, idx + len(excerpt)
    # Case-insensitive fallback
    idx = text.lower().find(excerpt.lower())
    if idx >= 0:
        return idx, idx + len(excerpt)
    # Partial match: try first 60 chars of excerpt
    short = excerpt[:60].strip()
    if short:
        idx = text.find(short)
        if idx >= 0:
            return idx, idx + len(excerpt)
    return None


def repair_file(ex_path: Path, raw_path: Path) -> dict:
    with open(ex_path, encoding="utf-8") as f:
        ex = json.load(f)
    with open(raw_path, encoding="utf-8") as f:
        raw = json.load(f)

    # Rebuild the exact source text the LLM was given for this issue
    source_text = _build_single_issue_text(raw)

    total = 0
    fixed = 0
    already_correct = 0
    not_found = 0
    not_found_excerpts = []

    for assertion in ex.get("assertions", []):
        for ev in assertion.get("evidence", []):
            total += 1
            excerpt = ev.get("excerpt", "")
            start = ev.get("offset_start", 0)
            end = ev.get("offset_end", 0)

            # Check if already correct
            if source_text[start:end] == excerpt:
                already_correct += 1
                continue

            # Find correct offset
            result = find_offset(source_text, excerpt)
            if result:
                ev["offset_start"] = result[0]
                ev["offset_end"] = result[1]
                fixed += 1
            else:
                not_found += 1
                not_found_excerpts.append(excerpt[:60])

    # Save source_text into the extraction file for future reference
    ex["source_text"] = source_text

    # Write back
    with open(ex_path, "w", encoding="utf-8") as f:
        json.dump(ex, f, indent=2, ensure_ascii=False)

    return {
        "source_id": ex.get("source_id"),
        "total": total,
        "already_correct": already_correct,
        "fixed": fixed,
        "not_found": not_found,
        "not_found_excerpts": not_found_excerpts[:3],
    }


def run():
    files = sorted(EXTRACTION_DIR.glob("extraction_*.json"))
    print(f"Repairing offsets in {len(files)} extraction files...\n")

    grand_total = 0
    grand_fixed = 0
    grand_correct = 0
    grand_not_found = 0

    for ef in files:
        source_id = ef.stem.replace("extraction_", "")
        raw_path = RAW_DIR / f"issue_{source_id}.json"
        if not raw_path.exists():
            print(f"  [SKIP] No raw file for {source_id}")
            continue

        result = repair_file(ef, raw_path)
        grand_total += result["total"]
        grand_fixed += result["fixed"]
        grand_correct += result["already_correct"]
        grand_not_found += result["not_found"]
        print(f"  {result['source_id']:15s} | {result['total']:3d} evidence | "
              f"already_ok={result['already_correct']} fixed={result['fixed']} not_found={result['not_found']}")
        if result["not_found_excerpts"]:
            for ex in result["not_found_excerpts"]:
                print(f"    [NOT FOUND] {repr(ex.encode('ascii', 'replace').decode())}")

    print(f"\n=== REPAIR SUMMARY ===")
    print(f"Total evidence items:  {grand_total}")
    print(f"Already correct:       {grand_correct}")
    print(f"Fixed (repaired):      {grand_fixed}")
    print(f"Not found (LLM hallucination): {grand_not_found}")
    pct = (grand_correct + grand_fixed) / grand_total * 100 if grand_total else 0
    print(f"Final coverage:        {pct:.1f}%")

    return grand_not_found == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
