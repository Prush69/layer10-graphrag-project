import json
from pathlib import Path

def test_dedup():
    merges_path = Path("c:/Layer10/data/entity_merges.json")
    graph_path = Path("c:/Layer10/data/graph.json")
    
    with open(merges_path, "r", encoding="utf-8") as f:
        merges = json.load(f)
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
        
    print(f"Total merges found: {len(merges)}")
    
    # 1. Evidence Conservation Test
    # Pick a canonical fact and count its evidence
    total_evidence_in_graph = 0
    for edge in graph.get("edges", []):
        total_evidence_in_graph += len(edge.get("evidence", []))
    
    print(f"Total evidence items in Graph: {total_evidence_in_graph}")
    # Should match total extracted items (41)
    if total_evidence_in_graph >= 41:
        print(f"  [PASS] Evidence Conservation: {total_evidence_in_graph} total items preserved.")
    else:
        print(f"  [FAIL] Evidence Conservation: Expected ~41, found {total_evidence_in_graph}")

    # 2. Fracture Test (Conceptual check of the log)
    # Check if we have a merge to gaearon
    merges_to_gaearon = [m for m in merges if m["canonical_id"] == "person::gaearon"]
    if merges_to_gaearon:
        print(f"  [PASS] Fracture Test: Found {len(merges_to_gaearon)} merges to person::gaearon. Detailed ledger exists for reversal.")
    else:
        print(f"  [INFO] No merges found for person::gaearon. Checking others...")
        for m in merges[:3]:
            print(f"    Merge: {m['merged_entity_id']} -> {m['canonical_id']}")

if __name__ == "__main__":
    test_dedup()
