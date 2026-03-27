"""Verify extraction output quality by spot-checking raw issues vs extraction results."""
import json
import sys
import os
from pathlib import Path

# Fix Windows console encoding
if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

def verify_issue(issue_num):
    raw_path = config.RAW_DATA_DIR / f"issue_{issue_num}.json"
    ext_path = config.EXTRACTION_DIR / f"extraction_{issue_num}.json"
    
    if not raw_path.exists():
        print(f"  Raw file not found: {raw_path}")
        return
    if not ext_path.exists():
        print(f"  Extraction file not found: {ext_path}")
        return
    
    with open(raw_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    with open(ext_path, "r", encoding="utf-8") as f:
        ext = json.load(f)
    
    issue = raw["issue"]
    print(f"\n{'='*60}")
    print(f"ISSUE #{issue['number']}: {issue['title']}")
    print(f"{'='*60}")
    print(f"  State: {issue['state']}")
    print(f"  Author: {issue['user']['login']}")
    print(f"  Labels: {[l['name'] for l in issue.get('labels', [])]}")
    print(f"  Comments: {len(raw.get('comments', []))}")
    print(f"  Body (first 200): {(issue['body'] or '')[:200]}")
    
    print(f"\n  --- EXTRACTION RESULTS ---")
    print(f"  Entities: {len(ext.get('entities', []))}")
    print(f"  Assertions: {len(ext.get('assertions', []))}")
    
    print(f"\n  Entities (first 5):")
    for e in ext.get("entities", [])[:5]:
        print(f"    [{e.get('type','?')}] {e.get('name','?')}")
    
    print(f"\n  Assertions (first 5):")
    for a in ext.get("assertions", [])[:5]:
        print(f"    {a.get('claim_type','?')}: {a.get('subject_id','?')} -> {a.get('object_id','N/A')} (conf={a.get('confidence','?')})")
        if a.get("evidence"):
            excerpt = a["evidence"][0].get("excerpt", "")[:80]
            print(f"      Evidence: \"{excerpt}...\"")
    
    # Basic quality checks
    print(f"\n  --- QUALITY CHECKS ---")
    checks_passed = 0
    total_checks = 0
    
    # Check 1: Author should appear as entity
    author = issue["user"]["login"]
    entity_names = [e.get("name", "").lower() for e in ext.get("entities", [])]
    total_checks += 1
    if author.lower() in entity_names:
        print(f"  [OK] Author '{author}' found in entities")
        checks_passed += 1
    else:
        print(f"  [WARN] Author '{author}' NOT found in entities")
    
    # Check 2: Issue itself should be an entity
    total_checks += 1
    issue_refs = [n for n in entity_names if str(issue["number"]) in n or "issue" in n]
    if issue_refs:
        print(f"  [OK] Issue #{issue['number']} found in entities")
        checks_passed += 1
    else:
        print(f"  [WARN] Issue #{issue['number']} NOT explicitly in entities")
    
    # Check 3: All assertions have evidence
    total_checks += 1
    assertions_with_evidence = sum(1 for a in ext.get("assertions", []) if a.get("evidence"))
    total_assertions = len(ext.get("assertions", []))
    if total_assertions > 0 and assertions_with_evidence == total_assertions:
        print(f"  [OK] All {total_assertions} assertions have evidence")
        checks_passed += 1
    elif total_assertions > 0:
        print(f"  [WARN] {assertions_with_evidence}/{total_assertions} assertions have evidence")
    
    # Check 4: Labels should appear as entities
    labels = [l["name"] for l in issue.get("labels", [])]
    if labels:
        total_checks += 1
        found_labels = [l for l in labels if l.lower() in entity_names]
        if found_labels:
            print(f"  [OK] Labels found: {found_labels}")
            checks_passed += 1
        else:
            print(f"  [WARN] Labels {labels} NOT found in entities")
    
    # Check 5: Confidence scores are reasonable
    total_checks += 1
    confidences = [a.get("confidence", 0) for a in ext.get("assertions", [])]
    if confidences:
        avg_conf = sum(confidences) / len(confidences)
        print(f"  [OK] Avg confidence: {avg_conf:.2f} (range: {min(confidences):.2f}-{max(confidences):.2f})")
        checks_passed += 1
    
    print(f"\n  Quality score: {checks_passed}/{total_checks} checks passed")
    return checks_passed, total_checks


def main():
    # Check a few different issues
    issues_to_check = ["13991", "17275", "24417", "31357", "32852"]
    
    total_passed = 0
    total_checks = 0
    
    for issue_num in issues_to_check:
        result = verify_issue(issue_num)
        if result:
            p, t = result
            total_passed += p
            total_checks += t
    
    print(f"\n{'='*60}")
    print(f"OVERALL QUALITY: {total_passed}/{total_checks} checks passed ({total_passed/total_checks*100:.0f}%)")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
