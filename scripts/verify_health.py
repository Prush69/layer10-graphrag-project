"""Verify context pack evidence fields and graph health."""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
os.chdir(Path(__file__).parent)

import config
from graph.store import GraphStore

# Check context packs
pack_dir = config.DATA_DIR / "context_packs"
print("=== CONTEXT PACK EVIDENCE AUDIT ===")
all_ok = True
for fname in os.listdir(pack_dir):
    with open(pack_dir / fname, encoding="utf-8") as f:
        pack = json.load(f)
    ev_list = pack.get("evidence", [])
    nulls = [ev for ev in ev_list if not ev.get("source_id") or not ev.get("url")]
    status = "OK" if not nulls else f"FAIL ({len(nulls)} null)"
    print(f"  {status:25s} {fname}")
    if nulls:
        all_ok = False

print(f"\nAll evidence grounded: {all_ok}\n")

# Graph health
store = GraphStore()
graph = store.load()
health = store.health_check(graph)
print("=== GRAPH HEALTH ===")
print(f"  Nodes:              {health['stats']['total_nodes']}")
print(f"  Edges:              {health['stats']['total_edges']}")
print(f"  Claims w/o evidence:{health['claims_without_evidence']}")
print(f"  Avg confidence:     {health['avg_confidence']}")
print(f"  Orphan nodes:       {health['orphan_nodes']}")
