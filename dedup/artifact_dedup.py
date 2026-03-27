"""
Artifact-level deduplication.

Detects duplicate or near-duplicate issues (cross-posts, forwarded content,
duplicate filings) using Semantic Embeddings and cross-references.
"""
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


class MergeRecord(BaseModel):
    """Audit record for an artifact merge."""
    merge_id: str
    merged_at: str
    canonical_id: str
    merged_ids: list[str]
    reason: str
    similarity_score: Optional[float] = None
    reversible: bool = True


class ArtifactDeduplicator:
    """Detects and merges duplicate artifacts (issues)."""

    def __init__(self):
        self.merge_log_path = config.DATA_DIR / "artifact_merges.json"
        self.merges: list[MergeRecord] = []
        self._load_merges()
        self._embedding_model = None

    def _get_model(self):
        if self._embedding_model is None:
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
        return self._embedding_model

    def _load_merges(self):
        if self.merge_log_path.exists():
            with open(self.merge_log_path, "r") as f:
                data = json.load(f)
                self.merges = [MergeRecord(**m) for m in data]

    def _save_merges(self):
        with open(self.merge_log_path, "w") as f:
            json.dump([m.model_dump() for m in self.merges], f, indent=2)

    def _text_hash(self, text: str) -> str:
        """Create a normalized hash of text content."""
        normalized = " ".join(text.lower().split())
        return hashlib.md5(normalized.encode()).hexdigest()

    def _simhash(self, text: str) -> str:
        """
        Implementation of a simple Char-based SimHash for near-duplicate detection.
        Returns a 64-bit hash as a hex string.
        """
        import hashlib
        # Normalize and tokenize into character n-grams (3-grams)
        text = " ".join(text.lower().split())
        features = [text[i:i+3] for i in range(len(text)-2)]
        if not features:
            features = [text]

        # 64-bit vector
        v = [0] * 64
        for feature in features:
            h = int(hashlib.md5(feature.encode()).hexdigest(), 16)
            for i in range(64):
                bit = (h >> i) & 1
                if bit:
                    v[i] += 1
                else:
                    v[i] -= 1
        
        # Build the final fingerprint
        fingerprint = 0
        for i in range(64):
            if v[i] > 0:
                fingerprint |= (1 << i)
        
        return hex(fingerprint)

    def _hamming_distance(self, h1: str, h2: str) -> int:
        """Calculate hamming distance between two hex fingerprints."""
        i1 = int(str(h1), 16)
        i2 = int(str(h2), 16)
        x = i1 ^ i2
        return bin(x).count('1')

    def find_duplicates(self, issues: list[dict], threshold: float = 0.85) -> list[tuple[str, str, float]]:
        """
        Find duplicate issue pairs based on semantic embedding similarity.
        Returns list of (id1, id2, similarity_score) tuples.
        """
        duplicates = []
        if not issues:
            return duplicates

        from sentence_transformers import util

        issue_ids = []
        texts = []

        for issue in issues:
            issue_num = str(issue.get("issue", {}).get("number", ""))
            title = issue.get("issue", {}).get("title", "")
            body = (issue.get("issue", {}).get("body", "") or "")[:500]
            issue_ids.append(issue_num)
            texts.append(f"{title} {body}")

        # Compute embeddings
        model = self._get_model()
        embeddings = model.encode(texts, convert_to_tensor=True)

        # Compute cosine similarities
        cosine_scores = util.cos_sim(embeddings, embeddings)

        for i in range(len(issue_ids)):
            for j in range(i + 1, len(issue_ids)):
                sim = cosine_scores[i][j].item()
                if sim >= threshold:
                    # Optional: Confirm with LLM fallback before declaring duplicate
                    if self._llm_confirm_duplicate(texts[i], texts[j]):
                        duplicates.append((issue_ids[i], issue_ids[j], sim))

        # Also check for exact hash matches (identical content)
        hashes = {}
        for i, text in enumerate(texts):
            h = self._text_hash(text)
            if h in hashes:
                existing = hashes[h]
                if not any((d[0] == existing and d[1] == issue_ids[i]) or (d[1] == existing and d[0] == issue_ids[i]) for d in duplicates):
                    duplicates.append((existing, issue_ids[i], 1.0))
            else:
                hashes[h] = issue_ids[i]

        return duplicates

    def find_cross_references(self, issues: list[dict]) -> dict[str, list[str]]:
        """
        Find issues that reference each other (potential duplicates or related).
        Returns a mapping of issue_id → [referenced_issue_ids].
        """
        import re
        references = {}

        for issue in issues:
            issue_num = str(issue.get("issue", {}).get("number", ""))
            body = issue.get("issue", {}).get("body", "") or ""

            # Find #NNN references
            refs = re.findall(r'#(\d+)', body)

            # Also check comments
            for comment in issue.get("comments", []):
                c_body = comment.get("body", "") or ""
                refs.extend(re.findall(r'#(\d+)', c_body))

            # Unique references (excluding self)
            refs = list(set(r for r in refs if r != issue_num))
            if refs:
                references[issue_num] = refs

        return references

    def merge_artifacts(self, canonical_id: str, duplicate_ids: list[str],
                        reason: str, similarity: float = None) -> MergeRecord:
        """Record a merge of duplicate artifacts."""
        merge = MergeRecord(
            merge_id=f"merge_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{hashlib.md5(canonical_id.encode()).hexdigest()[:6]}",
            merged_at=datetime.utcnow().isoformat(),
            canonical_id=canonical_id,
            merged_ids=duplicate_ids,
            reason=reason,
            similarity_score=similarity,
        )
        self.merges.append(merge)
        self._save_merges()
        return merge

    def undo_merge(self, merge_id: str) -> bool:
        """Undo a specific merge by ID."""
        for i, merge in enumerate(self.merges):
            if merge.merge_id == merge_id and merge.reversible:
                self.merges.pop(i)
                self._save_merges()
                return True
        return False

    def get_canonical_id(self, artifact_id: str) -> str:
        """Get the canonical ID for an artifact (follows merge chain)."""
        for merge in self.merges:
            if artifact_id in merge.merged_ids:
                return merge.canonical_id
        return artifact_id
