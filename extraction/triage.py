"""
Heuristic comment triage filter (Tier 1 of the Agentic Triage system).

Classifies comments as 'noise' vs 'signal' using lightweight heuristics
BEFORE sending to the LLM, reducing token waste and preventing ephemeral
chatter from polluting durable memory.

Noise patterns: "+1", "LGTM", emoji-only, "me too", short non-technical,
bot-generated, and duplicate/near-duplicate comments.
"""
import re
from typing import Optional


# --- Noise patterns ---
NOISE_PHRASES = {
    "+1", "👍", "lgtm", "me too", "same here", "bump", "following",
    "any updates?", "any update?", "same issue", "same problem",
    "this", "yes", "no", "thanks", "thank you", "thx", "ty",
    "i have the same issue", "i have this issue too",
    "please fix", "please fix this", "when will this be fixed",
}

NOISE_REGEXES = [
    re.compile(r'^[\s\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\u2600-\u26FF\u2700-\u27BF]+$'),  # emoji-only
    re.compile(r'^\+\d+$'),                        # "+1", "+100"
    re.compile(r'^(lgtm|lg|sgtm)[\s!.]*$', re.I),  # LGTM variants
    re.compile(r'^me\s+too[\s!.]*$', re.I),         # me too
    re.compile(r'^same[\s!.]*$', re.I),             # "same"
    re.compile(r'^bump[\s!.]*$', re.I),             # "bump"
]

BOT_PATTERNS = [
    re.compile(r'\[bot\]$', re.I),
    re.compile(r'^(github-actions|dependabot|renovate|stale)', re.I),
]

# Minimum character threshold for a comment to be considered signal
MIN_SIGNAL_LENGTH = 30


class TriageResult:
    """Result of triaging a single comment."""
    def __init__(self, is_signal: bool, reason: str = ""):
        self.is_signal = is_signal
        self.reason = reason


class TriageFilter:
    """
    Heuristic Tier-1 triage filter for GitHub comments.
    
    Filters out noise (+1, LGTM, emoji-only, bots, very short comments)
    so the LLM only processes substantive developer discussion.
    """

    def __init__(self, min_length: int = MIN_SIGNAL_LENGTH):
        self.min_length = min_length
        self.stats = {
            "total_comments": 0,
            "noise_filtered": 0,
            "signal_kept": 0,
            "noise_reasons": {},
        }

    def classify_comment(self, comment: dict) -> TriageResult:
        """
        Classify a single comment as signal or noise.
        
        Returns TriageResult with is_signal=True for substantive content.
        """
        body = (comment.get("body") or "").strip()
        user = comment.get("user", {}).get("login", "")

        # Empty body
        if not body:
            return TriageResult(False, "empty_body")

        # Bot detection
        for pattern in BOT_PATTERNS:
            if pattern.search(user):
                return TriageResult(False, "bot_comment")

        # Exact noise phrase match
        normalized = body.lower().strip().rstrip("!.,?")
        if normalized in NOISE_PHRASES:
            return TriageResult(False, f"noise_phrase:{normalized}")

        # Regex noise patterns
        for regex in NOISE_REGEXES:
            if regex.match(body):
                return TriageResult(False, f"noise_regex:{regex.pattern[:30]}")

        # Too short (unless it contains code or URLs)
        has_code = '`' in body or '```' in body
        has_url = 'http' in body or 'github.com' in body
        has_reference = '#' in body and re.search(r'#\d+', body)
        
        if len(body) < self.min_length and not has_code and not has_url and not has_reference:
            return TriageResult(False, "too_short")

        # Passed all filters → signal
        return TriageResult(True, "signal")

    def filter_comments(self, comments: list[dict]) -> list[dict]:
        """
        Filter a list of comments, keeping only signal.
        Returns the filtered list and updates internal stats.
        """
        signal_comments = []

        for comment in comments:
            self.stats["total_comments"] += 1
            result = self.classify_comment(comment)

            if result.is_signal:
                self.stats["signal_kept"] += 1
                signal_comments.append(comment)
            else:
                self.stats["noise_filtered"] += 1
                reason = result.reason.split(":")[0]
                self.stats["noise_reasons"][reason] = \
                    self.stats["noise_reasons"].get(reason, 0) + 1

        return signal_comments

    def get_stats_summary(self) -> str:
        """Return a human-readable summary of triage stats."""
        total = self.stats["total_comments"]
        filtered = self.stats["noise_filtered"]
        kept = self.stats["signal_kept"]
        if total == 0:
            return "Triage: no comments processed"
        pct = (filtered / total * 100) if total > 0 else 0
        reasons = ", ".join(f"{k}={v}" for k, v in self.stats["noise_reasons"].items())
        return (f"Triage: {filtered}/{total} noise comments filtered ({pct:.0f}%), "
                f"{kept} signal kept. Reasons: {reasons}")
