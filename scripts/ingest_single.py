import json
import os
import sys
import requests
from pathlib import Path

# Add root to path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

import config
from corpus.downloader import fetch_comments, fetch_events, get_headers

def ingest_single(repo, number):
    headers = get_headers()
    url = f"https://api.github.com/repos/{repo}/issues/{number}"
    print(f"Fetching issue {number} from {repo}...")
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        print(f"Error: {resp.status_code} - {resp.text}")
        return
    
    issue = resp.json()
    comments = fetch_comments(repo, number)
    events = fetch_events(repo, number)
    
    record = {
        "issue": issue,
        "comments": comments,
        "events": events,
        "metadata": {
            "repo": repo,
            "downloaded_at": "2026-03-06T13:00:00Z",
            "is_pull_request": "pull_request" in issue,
        }
    }
    
    output_dir = config.RAW_DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / f"issue_{number}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)
    print(f"Saved to {filepath}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        num = int(sys.argv[1])
    else:
        num = 13991
    ingest_single("facebook/react", num)
