import json
from pathlib import Path

def audit_steps_3_4():
    print("--- Step 3: Canonicalization Audit ---")
    merges_path = Path("c:/Layer10/data/entity_merges.json")
    registry_path = Path("c:/Layer10/data/alias_registry.json")
    
    with open(merges_path, "r", encoding="utf-8") as f:
        merges = json.load(f)
    print(f"Total Merges Applied: {len(merges)}")
    for m in merges[:5]:
        print(f"  Merge: {m['merged_entity_id']} -> {m['canonical_id']}")

    print("\n--- Step 4: Graph Structure ---")
    graph_path = Path("c:/Layer10/data/graph.json")
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
        
    nodes = graph.get("nodes", [])
    edges = graph.get("links", [])
    print(f"Total Nodes: {len(nodes)}")
    print(f"Total Edges: {len(edges)}")
    
    event_nodes = [n for n in nodes if n.get("_is_event")]
    print(f"Event Nodes (Claims): {len(event_nodes)}")
    
    # Check for Orphan Nodes
    connected_nodes = set()
    for e in edges:
        connected_nodes.add(e.get("source"))
        connected_nodes.add(e.get("target"))
        
    orphans = [n['id'] for n in nodes if n['id'] not in connected_nodes]
    print(f"Orphan Nodes: {len(orphans)}")
    for o in orphans[:5]:
        print(f"  [WARN] Orphan: {o}")

    # Specific Ground Truth Checks
    print("\n--- Ground Truth Verification ---")
    bruno = [n for n in nodes if "brunolemos" in n['id'].lower()]
    gaearon = [n for n in nodes if "gaearon" in n['id'].lower()]
    hooks = [n for n in nodes if "hooks" in n['id'].lower()]
    
    print(f"Bruno Node Exists:   {len(bruno) > 0}")
    print(f"Gaearon Node Exists: {len(gaearon) > 0} (Auto-Upsert Check)")
    print(f"Hooks Node Exists:   {len(hooks) > 0}")
    
    if event_nodes:
        sample = event_nodes[0]
        print(f"\nSample Event: {sample.get('id')}")
        print(f"  valid_from:  {sample.get('valid_from')}")
        print(f"  valid_until: {sample.get('valid_until')}")
        print(f"  status:      {sample.get('status')}")

if __name__ == "__main__":
    audit_steps_3_4()
