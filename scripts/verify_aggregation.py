"""
Verification: One Fact, Many Evidence pieces.
This script demonstrates assertion aggregation into a single claim.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from schema.ontology import Assertion, ClaimType, AssertionType
from graph.fact_factory import FactFactory

def main():
    factory = FactFactory()
    
    # Create two assertions for the same fact
    a1 = Assertion(
        id="a1",
        asserted_by="user1",
        type=AssertionType.OBSERVATION,
        claim_type=ClaimType.FIXES,
        subject_id="patch1",
        object_id="issue-A",
        confidence=0.9,
        artifact_version_id="v1",
        timestamp="2024-03-05T00:00:00Z",
        evidence=[{
            "excerpt": "User1 says patch1 fixes bug A",
            "source_id": "issue-A",
            "artifact_version_id": "v1",
            "offset_start": 10,
            "offset_end": 40
        }]
    )
    
    a2 = Assertion(
        id="a2",
        asserted_by="user2",
        type=AssertionType.AGREEMENT,
        claim_type=ClaimType.FIXES,
        subject_id="patch1",
        object_id="issue-A",
        confidence=0.8,
        artifact_version_id="v1",
        timestamp="2024-03-05T00:00:01Z",
        evidence=[{
            "excerpt": "User2 confirmed patch1 works for A",
            "source_id": "issue-A",
            "artifact_version_id": "v1",
            "offset_start": 100,
            "offset_end": 130
        }]
    )
    
    # Process them
    claims = factory.form_facts([a1, a2])
    
    print(f"\nCreated {len(claims)} claims from 2 assertions.")
    if claims:
        claim = claims[0]
        print(f"Claim ID: {claim.id}")
        print(f"Type: {claim.type}")
        print(f"Evidence Count: {len(claim.evidence)}")
        for idx, ev in enumerate(claim.evidence):
            print(f"  [{idx}] Source: {ev.source_id}, Excerpt: '{ev.excerpt}'")
        print(f"Memory Strength: {claim.memory_strength:.2f}")

if __name__ == "__main__":
    main()
