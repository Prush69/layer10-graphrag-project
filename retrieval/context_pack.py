"""
Context pack builder.

Assembles grounded context packs from search results,
with ranked evidence, citations, conflict surfacing,
and Graph RBAC permission filtering (Check-Then-Return).
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from graph.memory_graph import MemoryGraph, TemporalResolver


# Permission filtering removed as per user request (Show everything to everyone)



class ContextPack:
    """A grounded context pack answering a question with evidence."""

    def __init__(self, question: str):
        self.question = question
        self.entities: list[dict] = []
        self.claims: list[dict] = []
        self.evidence: list[dict] = []
        self.conflicts: list[dict] = []
        self.created_at = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "entities": self.entities,
            "claims": self.claims,
            "evidence": self.evidence,
            "conflicts": self.conflicts,
            "created_at": self.created_at,
            "summary": self._build_summary(),
        }

    def _build_summary(self) -> str:
        """Build a human-readable summary of the context pack."""
        parts = [f"Found {len(self.entities)} relevant entities and {len(self.claims)} claims."]
        if self.conflicts:
            parts.append(f"[!] {len(self.conflicts)} conflicting sources detected.")
        parts.append(f"Backed by {len(self.evidence)} evidence items.")
        return " ".join(parts)


class ContextPackBuilder:
    """Builds context packs from search results."""

    def __init__(self, graph: MemoryGraph):
        self.graph = graph
        self.temporal = TemporalResolver()

    def build(self, search_results: list[dict], question: str,
              max_evidence: int = 20, include_conflicts: bool = True) -> ContextPack:
        """
        Build a context pack from search results.
        
        Assembles a focused context pack with ranked evidence and linked nodes.

        Args:
            search_results: Ranked results from HybridSearch.search()
            question: The original question
            max_evidence: Max evidence items to include
            include_conflicts: Whether to surface conflicting claims
        """
        pack = ContextPack(question)
        seen_entities = set()
        seen_claims = set()
        evidence_items = []
        evidence_by_claim = {}  # claim_id → [evidence_items]

        for result in search_results:
            if result.get("type") == "entity":
                entity_key = result["key"][1] if isinstance(result["key"], tuple) else result["key"]

                if entity_key not in seen_entities:
                    seen_entities.add(entity_key)
                    entity_data = result.get("data", {})

                    # Get claims for this entity
                    entity_claims = self.graph.get_claims_for(entity_key, include_historical=False)

                    pack.entities.append({
                        "key": entity_key,
                        "name": entity_data.get("name", entity_key),
                        "type": entity_data.get("type", "Unknown"),
                        "aliases": entity_data.get("aliases", []),
                        "score": result.get("score", 0),
                        "claim_count": len(entity_claims),
                    })

                    # Collect evidence from this entity's claims (skip redacted/retracted)
                    for claim in entity_claims[:5]:  # Limit per entity
                        claim_id = claim.get("id", "")
                        claim_status = claim.get("status", "active")
                        if claim_status in ("redacted", "retracted"):
                            continue
                        if claim_id not in seen_claims:
                            seen_claims.add(claim_id)
                            pack.claims.append(self._format_claim(claim))

                            claim_evidence = []
                            for ev in claim.get("evidence", []):
                                formatted = {
                                    "claim_id": claim_id,
                                    "claim_type": claim.get("type", ""),
                                    **self._format_evidence(ev),
                                }
                                evidence_items.append(formatted)
                                claim_evidence.append(formatted)
                            evidence_by_claim[claim_id] = claim_evidence

            elif result.get("type") == "claim":
                claim_data = result.get("data", {})
                claim_id = claim_data.get("id", "")
                claim_status = claim_data.get("status", "active")

                # Skip redacted or retracted claims — they must not surface in retrieval
                if claim_status in ("redacted", "retracted"):
                    continue

                if claim_id not in seen_claims:
                    seen_claims.add(claim_id)
                    pack.claims.append(self._format_claim(claim_data))

                    claim_evidence = []
                    for ev in claim_data.get("evidence", []):
                        formatted = {
                            "claim_id": claim_id,
                            "claim_type": claim_data.get("type", ""),
                            **self._format_evidence(ev),
                        }
                        evidence_items.append(formatted)
                        claim_evidence.append(formatted)
                    evidence_by_claim[claim_id] = claim_evidence

        # No permission filtering applied (Show everything)

        # Deduplicate and rank evidence
        pack.evidence = self._rank_evidence(evidence_items)[:max_evidence]

        # Detect conflicts
        if include_conflicts:
            pack.conflicts = self._find_conflicts(pack.claims)

        return pack

    def _format_claim(self, claim: dict) -> dict:
        """Format a claim for the context pack."""
        return {
            "id": claim.get("id", ""),
            "type": claim.get("type", ""),
            "subject": claim.get("_source", claim.get("subject_id", "")),
            "object": claim.get("_target", claim.get("object_id", "")),
            "properties": claim.get("properties", {}),
            "confidence": claim.get("confidence", 0),
            "status": claim.get("status", "active"),
            "valid_from": claim.get("valid_from"),
            "valid_until": claim.get("valid_until"),
            "is_current": TemporalResolver.is_current(claim),
            "evidence_count": len(claim.get("evidence", [])),
        }

    def _format_evidence(self, ev: dict) -> dict:
        """Format an evidence item with citation."""
        if not isinstance(ev, dict):
            return {"excerpt": str(ev), "citation": "unknown source"}

        source_id = ev.get("source_id", "")
        url = ev.get("url", "")
        timestamp = ev.get("timestamp", "")

        citation = f"[{source_id}]"
        if url:
            citation += f" ({url})"
        if timestamp:
            citation += f" @ {timestamp}"

        return {
            "source_id": source_id,
            "source_type": ev.get("source_type", ""),
            "excerpt": ev.get("excerpt", ""),
            "url": url,
            "timestamp": timestamp,
            "citation": citation,
        }

    def _rank_evidence(self, evidence_items: list[dict]) -> list[dict]:
        """Rank evidence items by relevance and freshness."""
        # Deduplicate by source_id + excerpt hash
        seen = set()
        unique = []
        for ev in evidence_items:
            key = f"{ev.get('source_id', '')}::{ev.get('excerpt', '')[:50]}"
            if key not in seen:
                seen.add(key)
                unique.append(ev)

        # Sort by timestamp (newest first)
        return sorted(unique, key=lambda e: e.get("timestamp") or "", reverse=True)

    def _find_conflicts(self, claims: list[dict]) -> list[dict]:
        """Find conflicting claims in the context pack."""
        conflicts = []

        # Group by type + subject + object
        groups: dict[str, list[dict]] = {}
        for claim in claims:
            sig = f"{claim['type']}::{claim['subject']}::{claim['object']}"
            if sig not in groups:
                groups[sig] = []
            groups[sig].append(claim)

        for sig, group in groups.items():
            if len(group) > 1:
                # Check for property differences
                active = [c for c in group if c.get("is_current", True)]
                historical = [c for c in group if not c.get("is_current", True)]

                if active and historical:
                    conflicts.append({
                        "type": "superseded",
                        "description": f"Claim was updated: {sig}",
                        "current": active[0],
                        "previous": historical,
                    })
                elif len(active) > 1:
                    conflicts.append({
                        "type": "conflicting",
                        "description": f"Multiple active claims: {sig}",
                        "claims": active,
                    })

        return conflicts

    def save_pack(self, pack: ContextPack, filename: str = None):
        """Save a context pack to the data directory."""
        if not filename:
            safe_q = "".join(c if c.isalnum() else "_" for c in pack.question[:50])
            filename = f"context_{safe_q}.json"

        output_path = config.CONTEXT_PACKS_DIR / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(pack.to_dict(), f, indent=2, ensure_ascii=False)

        print(f"Context pack saved: {output_path}")
        return output_path
