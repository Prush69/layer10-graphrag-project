"""
Fact Factory: Aggregates assertions into canonical facts.

Implements the Canonical Fact Formation pipeline:
Assertions -> Aggregation -> Canonical Fact

Scoring:
score = extraction_confidence + log(evidence_count) + authority_weight - decay_rate * age
"""
import math
import hashlib
from datetime import datetime
from typing import List, Dict, Any, Optional
from schema.ontology import Assertion, AssertionType, Claim, ClaimStatus, Evidence, ClaimType

# --- Source authority hierarchy ---
SOURCE_AUTHORITY = {
    "maintainer": 5.0,
    "collaborator": 3.0,
    "contributor": 2.0,
    "guest": 1.0,
    "system": 4.0,
    "unknown": 1.0,
}

# Known maintainers (for React corpus)
MAINTAINERS = {
    "gaearon", "acdlite", "sebmarkbage", "sophiebits", "bvaughn",
    "dan_abramov", "jordwalke", "rickyvetter"
}

class FactFactory:
    """Orchestrates the formation of canonical facts fromAssertions."""

    def __init__(self, decay_rate: float = 0.01):
        self.decay_rate = decay_rate

    def _get_authority_weight(self, author: str) -> float:
        """Calculate authority weight based on author reputation."""
        if author.lower() in MAINTAINERS:
            return SOURCE_AUTHORITY["maintainer"]
        # In a real system, we'd look this up in an entity registry
        return SOURCE_AUTHORITY["contributor"]

    def _calculate_age_days(self, created_at: str) -> float:
        """Calculate age in days from an ISO timestamp."""
        try:
            dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            delta = datetime.utcnow() - dt
            return max(0.0, delta.total_seconds() / 86400.0)
        except (ValueError, TypeError):
            return 0.0

    def calculate_fact_score(self, confidence: float, evidence_count: int, 
                             authority_weight: float, age_days: float) -> float:
        """
        Memory Strength Formula (Ideal Design Requirement):
        score = extraction_confidence + log(evidence_count) + authority_weight - decay_rate * age
        """
        # score = confidence + log(evidence_count) + authority_weight - (decay * age)
        # However, to keep it within a sane 0-1 or 0-10 range, we might need normalization.
        # The user provided a linear formula, so we'll implement it exactly as requested.
        
        evidence_boost = math.log1p(evidence_count)
        decay_penalty = self.decay_rate * age_days
        
        score = confidence + evidence_boost + authority_weight - decay_penalty
        return score

    def aggregate_assertions(self, assertions: List[Assertion], 
                             claim_type: ClaimType, 
                             subject_id: str, 
                             object_id: Optional[str] = None) -> Claim:
        """
        Aggregate multiple assertions into a single Canonical Fact (Claim).
        """
        if not assertions:
            raise ValueError("Cannot aggregate empty assertions list")

        # 1. Basic properties
        fact_id = f"fact::{claim_type.value.lower()}::{hashlib.md5(f'{subject_id}::{object_id}'.encode()).hexdigest()[:8]}"
        
        # 2. Evidence Aggregation (Deduplicated)
        all_evidence = []
        seen_evidence = set()
        for ass in assertions:
            for ev in ass.evidence:
                # Key on source_id + excerpt (not offsets — LLM offsets are unreliable)
                src = ev.source_id or ev.artifact_version_id or ""
                excerpt_key = (ev.excerpt or "")[:60]
                key = f"{src}::{excerpt_key}"
                if key not in seen_evidence:
                    all_evidence.append(ev)
                    seen_evidence.add(key)

        # 3. Confidence & Authority
        # Average confidence + Sum of authority? Or Max authority?
        # Let's take Weighted Average for confidence and Max for authority.
        avg_confidence = sum(a.confidence for a in assertions) / len(assertions)
        max_authority = max(self._get_authority_weight(a.asserted_by) for a in assertions)
        
        # 4. Temporal Bounds
        valid_from = None
        for a in assertions:
            if not valid_from or (a.timestamp < valid_from):
                valid_from = a.timestamp
        
        # 5. Formal Calculation
        age_days = self._calculate_age_days(valid_from)
        strength = self.calculate_fact_score(avg_confidence, len(all_evidence), max_authority, age_days)

        # 6. Status determination
        status = ClaimStatus.ACTIVE
        if any(a.type == AssertionType.CORRECTION for a in assertions):
            # Check if correction is more recent than a decision?
            pass # Simplified for now

        # Create the Claim (Canonical Fact)
        fact = Claim(
            id=fact_id,
            type=claim_type,
            subject_id=subject_id,
            object_id=object_id,
            properties={}, # In a real system, we'd merge properties
            confidence=avg_confidence,
            status=status,
            evidence=all_evidence,
            assertions=[a.id for a in assertions],
            valid_from=valid_from,
            extracted_at=datetime.utcnow().isoformat(),
            memory_strength=strength,
            decay_rate=self.decay_rate,
            reinforcement_count=len(assertions),
            authority_weight=max_authority
        )
        
        return fact

    def form_facts(self, assertions: List[Assertion]) -> List[Claim]:
        """Group assertions by semantic identity and form facts."""
        groups: Dict[str, List[Assertion]] = {}
        
        for ass in assertions:
            # Grouping key: claim_type, subject, object
            key = f"{ass.claim_type.value}::{ass.subject_id}::{ass.object_id or 'none'}"
            if key not in groups:
                groups[key] = []
            groups[key].append(ass)

        facts = []
        for key, group in groups.items():
            try:
                # Get common properties from the first assertion in the group
                first = group[0]
                fact = self.aggregate_assertions(
                    assertions=group,
                    claim_type=first.claim_type,
                    subject_id=first.subject_id,
                    object_id=first.object_id
                )
                facts.append(fact)
            except Exception as e:
                print(f"Error forming fact for {key}: {e}")
                continue
        
        return facts
