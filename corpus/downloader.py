"""
Corpus downloader for GitHub Issues/PRs.

Fetches issues, comments, and events from a GitHub repository
via the REST API and saves them as raw JSON files.
"""
import json
import time
import requests
from pathlib import Path
from tqdm import tqdm

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


def get_headers() -> dict:
    """Build request headers with optional auth token."""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Layer10-Memory-System"
    }
    if config.GITHUB_TOKEN and config.GITHUB_TOKEN != "your_github_token_here":
        headers["Authorization"] = f"token {config.GITHUB_TOKEN}"
    return headers


def rate_limit_wait(response: requests.Response):
    """Check GitHub rate limit and wait if necessary."""
    remaining = int(response.headers.get("X-RateLimit-Remaining", 100))
    if remaining < 5:
        reset_time = int(response.headers.get("X-RateLimit-Reset", 0))
        wait_seconds = max(0, reset_time - int(time.time())) + 1
        print(f"Rate limit nearly exhausted. Waiting {wait_seconds}s...")
        time.sleep(wait_seconds)


def fetch_issues(repo: str, max_issues: int = 200, state: str = "all") -> list[dict]:
    """
    Fetch issues from a GitHub repository.
    Returns a list of issue dicts with full metadata.
    """
    issues = []
    page = 1
    per_page = min(config.ISSUES_PER_PAGE, 100)
    headers = get_headers()
    base_url = f"https://api.github.com/repos/{repo}/issues"

    pbar = tqdm(total=max_issues, desc="Fetching issues")

    while len(issues) < max_issues:
        params = {
            "state": state,
            "per_page": per_page,
            "page": page,
            "sort": "updated",
            "direction": "desc"
        }

        try:
            response = requests.get(base_url, headers=headers, params=params, timeout=30)
            rate_limit_wait(response)

            if response.status_code != 200:
                print(f"Error fetching issues: {response.status_code} - {response.text[:200]}")
                break

            batch = response.json()
            if not batch:
                break

            for issue in batch:
                if len(issues) >= max_issues:
                    break
                issues.append(issue)
                pbar.update(1)

            page += 1
            time.sleep(0.5)  # Be polite

        except requests.RequestException as e:
            print(f"Request error: {e}")
            time.sleep(5)
            continue

    pbar.close()
    return issues


def fetch_comments(repo: str, issue_number: int) -> list[dict]:
    """Fetch all comments for a specific issue."""
    headers = get_headers()
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    comments = []
    page = 1

    while True:
        params = {"per_page": 100, "page": page}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            rate_limit_wait(response)

            if response.status_code != 200:
                break

            batch = response.json()
            if not batch:
                break

            comments.extend(batch)
            page += 1
            time.sleep(0.3)

        except requests.RequestException:
            break

    return comments


def fetch_events(repo: str, issue_number: int) -> list[dict]:
    """Fetch timeline events for a specific issue (state changes, labels, etc.)."""
    headers = get_headers()
    headers["Accept"] = "application/vnd.github.mockingbird-preview+json"
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/events"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        rate_limit_wait(response)
        if response.status_code == 200:
            return response.json()
    except requests.RequestException:
        pass

    return []


def download_corpus(repo: str = None, max_issues: int = None, output_dir: Path = None):
    """
    Download a full corpus of issues with comments and events.
    Saves each issue as a separate JSON file for idempotent re-runs.
    """
    repo = repo or config.GITHUB_REPO
    max_issues = max_issues or config.MAX_ISSUES
    output_dir = output_dir or config.RAW_DATA_DIR

    output_dir.mkdir(parents=True, exist_ok=True)

    # Check which issues are already downloaded
    existing = set()
    for f in output_dir.glob("issue_*.json"):
        try:
            num = int(f.stem.split("_")[1])
            existing.add(num)
        except (ValueError, IndexError):
            pass

    print(f"Found {len(existing)} already-downloaded issues.")

    # Fetch issue list
    print(f"Fetching up to {max_issues} issues from {repo}...")
    issues = fetch_issues(repo, max_issues)
    print(f"Fetched {len(issues)} issue headers.")

    # Download details for each issue
    new_count = 0
    for issue in tqdm(issues, desc="Downloading details"):
        number = issue["number"]

        if number in existing:
            continue

        # Fetch comments and events
        comments = fetch_comments(repo, number)
        events = fetch_events(repo, number)

        # Build complete record
        record = {
            "issue": issue,
            "comments": comments,
            "events": events,
            "metadata": {
                "repo": repo,
                "downloaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "is_pull_request": "pull_request" in issue,
            }
        }

        # Save
        filepath = output_dir / f"issue_{number}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)

        new_count += 1
        time.sleep(0.5)  # Rate limit kindness

    print(f"Downloaded {new_count} new issues. Total: {len(existing) + new_count}")
    return len(existing) + new_count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Download GitHub issues corpus")
    parser.add_argument("--repo", default=config.GITHUB_REPO, help="GitHub repo (owner/name)")
    parser.add_argument("--max-issues", type=int, default=config.MAX_ISSUES)
    args = parser.parse_args()

    download_corpus(repo=args.repo, max_issues=args.max_issues)
