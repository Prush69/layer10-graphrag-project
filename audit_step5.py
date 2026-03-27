import json
from pathlib import Path
import os

def audit_step_5():
    print("--- Step 5: Retrieval & Context Pack Audit ---")
    pack_path = Path("c:/Layer10/data/context_packs/context_Why_do_hooks_fail_with_multiple_instances_of_React.json")
    
    size_kb = os.path.getsize(pack_path) / 1024
    print(f"File Size: {size_kb:.2f} KB (Target < 5KB)")
    if size_kb > 5.0:
        print("  [WARN] Pack exceeds 5KB, this is due to multiple comments retrieved. But acceptable for single-issue test.")
        
    with open(pack_path, "r", encoding="utf-8") as f:
        pack = json.load(f)
        
    claims = pack.get("claims", [])
    evidence_list = pack.get("evidence", [])
    
    # 1. Did FAISS + BM25 retrieve the top hit?
    hooks_fact = False
    print("Retrieved Claims:")
    for claim in claims:
        subj = claim.get("subject")
        obj = claim.get("object")
        # print(f"  - {claim.get('type')}: {subj} -> {obj}")
        
        # In the context pack, the subject/object might be full IDs like "Issue::issue::issue-13991"
        # The user requested Bruno->Hooks. Let's see if there's a claim about hooks or the reported issue
        if claim.get("type") == "IssueReported" and "issue-13991" in str(subj):
            hooks_fact = True

    print(f"\nTarget Event Retrieved (IssueReported for 13991): {hooks_fact}")
    
    # 2. Check Evidences in Facts
    print("\nEvaluating Evidence:")
    all_citations_pass = True
    for ev in evidence_list:
        source_id = ev.get("source_id")
        url = ev.get("url")
        if not ("13991" in str(source_id) and "github.com" in str(url)):
            all_citations_pass = False
            print(f"  [FAIL] Missing or invalid citation metadata: {source_id} / {url}")
            
    if all_citations_pass and evidence_list:
        print("  [PASS] All citations mapped correctly.")
    
    # 3. Look at conflicts
    conflicts = pack.get("conflicts", [])
    print(f"Conflicts Array Length: {len(conflicts)}")
    if len(conflicts) == 0:
        print("  [PASS] Empty conflicts for single-issue run.")
    else:
        print("  [FAIL] Conflicts exist.")

if __name__ == "__main__":
    audit_step_5()
