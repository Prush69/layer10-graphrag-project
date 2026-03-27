import json
import os
from pathlib import Path

def verify_slicing():
    ext_dir = Path("c:/Layer10/data/extractions")
    raw_dir = Path("c:/Layer10/corpus/raw")
    failures = 0
    total = 0

    for ext_file in ext_dir.glob("*.json"):
        with open(ext_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        source_id = data["source_id"].replace("issue-", "issue_")
        raw_file = raw_dir / f"{source_id}.json"
        
        if not raw_file.exists():
            continue
            
        with open(raw_file, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        
        # Combine body and comments into one searchable text
        full_text = raw_data["issue"]["body"] or ""
        for comment in raw_data.get("comments", []):
            full_text += "\n" + (comment["body"] or "")
            
        for assertion in data.get("assertions", []):
            for evid in assertion.get("evidence", []):
                total += 1
                start = evid["offset_start"]
                end = evid["offset_end"]
                excerpt = evid["excerpt"]
                
                sliced = full_text[start:end]
                if sliced.strip() != excerpt.strip():
                    # Check if excerpt exists ELSEWHERE in text
                    idx = full_text.find(excerpt)
                    if idx != -1:
                        print(f"  [MISMATCH] {ext_file.name}: Offsets {start}:{end} invalid, but exists at {idx}")
                    else:
                        print(f"  [HALLUCINATION] {ext_file.name}: Excerpt not found in source!")
                    failures += 1
                    
    print(f"\nVerification Results: {total} items checked, {failures} failures.")
    return failures

if __name__ == "__main__":
    verify_slicing()
