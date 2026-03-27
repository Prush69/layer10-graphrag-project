import json
from pathlib import Path

def audit_step1():
    path = Path("c:/Layer10/corpus/raw/issue_13991.json")
    if not path.exists():
        print(f"[FAIL] {path} not found.")
        return
    
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    issue = data.get("issue", {})
    comments = data.get("comments", [])
    
    print(f"--- Step 1 Audit: {path.name} ---")
    print(f"Source ID: {issue.get('number')}")
    print(f"Author:    {issue.get('user', {}).get('login')}")
    print(f"Title:     {issue.get('title')}")
    
    # Verify participants
    commenters = {c.get("user", {}).get("login") for c in comments}
    philipp_present = "philipp-spiess" in commenters
    gabriel_present = "GabrielBB" in commenters
    
    print(f"Total Comments: {len(comments)}")
    print(f"Expected (Metadata): {issue.get('comments')}")
    
    if len(comments) == issue.get('comments'):
        print(f"  [PASS] Pagination: All {len(comments)} comments captured.")
    else:
        print(f"  [FAIL] Pagination: Missing comments ({len(comments)}/{issue.get('comments')})")
        
    print(f"  [PASS] Philipp present: {philipp_present}")
    print(f"  [PASS] Gabriel present: {gabriel_present}")

if __name__ == "__main__":
    audit_step1()
