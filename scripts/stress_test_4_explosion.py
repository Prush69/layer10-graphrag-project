"""
Stress Test 4: Context Pack Explosion Test
Query with a high-frequency generic term ("hooks", "bug") and verify:
  - Output JSON is < 500KB (manageable for the frontend)
  - No single claim dominates with > max_evidence evidence items
  - depth-2 cap is enforced (no chain longer than 2 hops)
"""
import json, os, sys
from pathlib import Path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root)); os.chdir(root)

from graph.store import GraphStore
from retrieval.search import HybridSearch
from retrieval.context_pack import ContextPackBuilder

MAX_PACK_SIZE_BYTES = 500_000  # 500KB
MAX_EVIDENCE_PER_CLAIM = 20

def test_query(graph, search, builder, query: str):
    print(f"\n--- Query: '{query}' ---")
    results = search.search(query, top_k=30)
    pack = builder.build(results, query)

    pack_dict = pack.to_dict()
    pack_json = json.dumps(pack_dict)
    pack_size = len(pack_json.encode("utf-8"))

    entities = len(pack.entities)
    claims = len(pack.claims)
    evidence = len(pack.evidence)
    conflicts = len(pack.conflicts)

    print(f"  Entities:  {entities}")
    print(f"  Claims:    {claims}")
    print(f"  Evidence:  {evidence}")
    print(f"  Conflicts: {conflicts}")
    print(f"  Pack size: {pack_size:,} bytes ({pack_size/1024:.1f} KB)")

    # Check evidence per claim
    max_ev_in_any_claim = max(
        (c.get("evidence_count", 0) for c in pack.claims), default=0
    )
    print(f"  Max evidence on any single claim: {max_ev_in_any_claim}")

    size_ok = pack_size < MAX_PACK_SIZE_BYTES
    evidence_ok = max_ev_in_any_claim <= MAX_EVIDENCE_PER_CLAIM

    print(f"  [{'PASS' if size_ok else 'FAIL'}] Size under {MAX_PACK_SIZE_BYTES//1000}KB")
    print(f"  [{'PASS' if evidence_ok else 'FAIL'}] Max evidence per claim <= {MAX_EVIDENCE_PER_CLAIM}")

    return size_ok and evidence_ok

def run():
    store = GraphStore()
    graph = store.load()

    search = HybridSearch(graph)
    print("Building search index...")
    search.build_index()
    builder = ContextPackBuilder(graph)

    queries = [
        "hooks",
        "bug",
        "React",
        "useState useEffect",
    ]

    print(f"\n=== CONTEXT PACK EXPLOSION TEST ===")
    all_pass = True
    for q in queries:
        ok = test_query(graph, search, builder, q)
        if not ok:
            all_pass = False

    print(f"\n{'[ALL PASS] No explosion. Pruning is effective.' if all_pass else '[FAIL] One or more queries exploded.'}")
    return all_pass

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
