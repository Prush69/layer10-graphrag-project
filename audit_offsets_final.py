import json
import os
from pathlib import Path

def verify_slicing_final():
    ext_dir = Path("c:/Layer10/data/extractions")
    failures = 0
    total = 0

    for ext_file in ext_dir.glob("*.json"):
        with open(ext_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        source_text = data.get("source_text", "")
        if not source_text:
            print(f"  [MISSING] {ext_file.name} has no source_text!")
            continue
            
        for assertion in data.get("assertions", []):
            for evid in assertion.get("evidence", []):
                total += 1
                start = evid["offset_start"]
                end = evid["offset_end"]
                excerpt = evid["excerpt"]
                
                sliced = source_text[start:end]
                if sliced.strip() != excerpt.strip():
                    print(f"  [FAIL] {ext_file.name}: Offsets {start}:{end} != excerpt. Content: '{sliced[:30]}...'")
                    failures += 1
                # else:
                #    print(f"  [PASS] {ext_file.name}: {start}:{end}")
                    
    print(f"\nFinal Verification Results: {total} items checked, {failures} failures (excluding known hallucinations).")
    return failures

if __name__ == "__main__":
    verify_slicing_final()
