import json
from pathlib import Path

def test_dedup_fixed():
    graph_path = Path("c:/Layer10/data/graph.json")
    
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
    
    # 1. Evidence Conservation Test
    total_evidence = 0
    event_nodes = 0
    for node in graph.get("nodes", []):
        ev = node.get("evidence", [])
        if ev:
            total_evidence += len(ev)
            event_nodes += 1
            
    print(f"Total event nodes: {event_nodes}")
    print(f"Total evidence items: {total_evidence}")
    
    if total_evidence >= 41:
        print(f"  [PASS] Evidence Conservation: {total_evidence} items found (>= 41 expected).")
    else:
        print(f"  [FAIL] Evidence Conservation: Expected >=41, found {total_evidence}")

    # 2. Bitemporal Audit
    sample_event = [n for n in graph.get("nodes", []) if n.get("_is_event")][0]
    print("\nBitemporal Audit (Sample Event):")
    print(f"  Type: {sample_event.get('type')}")
    print(f"  valid_from:   {sample_event.get('valid_from')}")
    print(f"  valid_until:  {sample_event.get('valid_until')}")
    print(f"  extracted_at: {sample_event.get('extracted_at')}")
    
    if sample_event.get("valid_from") and sample_event.get("extracted_at") and sample_event.get("valid_until") is None:
         print("  [PASS] Bitemporal fields present and consistent.")
    else:
         print("  [FAIL] Bitemporal fields missing or inconsistent.")

if __name__ == "__main__":
    test_dedup_fixed()
