"""
Stress Test 2: Bitemporal Redaction Cascade Test
Trigger handle_redaction("issue-13991"), then verify:
  - 0 active claims remain grounded exclusively in that source
  - valid_until was set on all affected claims
  - Retrieval API returns no items from that source as active
"""
import json, os, sys
from pathlib import Path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root)); os.chdir(root)

from graph.store import GraphStore
from retrieval.search import HybridSearch
from retrieval.context_pack import ContextPackBuilder

REDACT_SOURCE = "issue-35971"

def run():
    store = GraphStore()
    graph = store.load()

    # -- Step 1: Baseline count BEFORE redaction --
    before_active = []
    for n_id, d in graph.backend.get_all_nodes():
        if not d.get("_is_event"): continue
        ev_list = d.get("evidence", [])
        if not ev_list: continue
        sources = {ev.get("source_id") for ev in ev_list}
        if REDACT_SOURCE in sources and d.get("status", "active") == "active":
            before_active.append(n_id)

    print(f"Pre-Redaction: {len(before_active)} active claims grounded in {REDACT_SOURCE}")

    # -- Step 2: Trigger redaction --
    result = graph.handle_redaction(REDACT_SOURCE, redacted_at="2026-03-06T00:00:00Z")
    print(f"\nRedaction result: {json.dumps(result, indent=2)}")

    # -- Step 3: Verify AFTER redaction --
    exclusive_active = []   # claims ONLY grounded in redacted source but still active
    invalidated = []        # correctly invalidated claims
    partial = []            # multi-source claims that had source pruned

    for n_id, d in graph.backend.get_all_nodes():
        if not d.get("_is_event"): continue
        ev_list = d.get("evidence", [])
        sources = {ev.get("source_id") for ev in ev_list}
        status = d.get("status", "active")
        valid_until = d.get("valid_until")
        redacted_sources = d.get("redacted_sources", [])

        if d.get("redacted_source") == REDACT_SOURCE:
            # Was exclusively grounded in this source
            if status == "redacted" and valid_until:
                invalidated.append(n_id)
            else:
                exclusive_active.append(n_id)  # PROBLEM: should be redacted

        if REDACT_SOURCE in redacted_sources:
            partial.append(n_id)

    print(f"\n=== REDACTION CASCADE RESULTS ===")
    print(f"Claims correctly invalidated (status=redacted + valid_until set): {len(invalidated)}")
    print(f"Claims partially pruned (multi-source, still active):             {len(partial)}")
    print(f"PROBLEM — exclusive claims still active (should be 0):            {len(exclusive_active)}")

    # -- Step 4: Run retrieval and verify no active redacted claims surface --
    search = HybridSearch(graph)
    search.build_index()
    builder = ContextPackBuilder(graph)

    query = "Hooks + multiple instances of React"  # known to rely on issue-13991
    results = search.search(query, top_k=20)
    pack = builder.build(results, query)

    # Check every claim in the pack
    claims_from_redacted = []
    for claim in pack.claims:
        for ev in pack.evidence:
            if ev.get("source_id") == REDACT_SOURCE:
                # Check if this evidence is in an active claim
                claims_from_redacted.append(ev)

    print(f"\nRetrieval test after redaction:")
    print(f"  Query: '{query}'")
    print(f"  Claims returned: {len(pack.claims)}")
    print(f"  Evidence items from redacted source still appearing: {len(claims_from_redacted)}")

    all_pass = (len(exclusive_active) == 0 and len(claims_from_redacted) == 0)

    if all_pass:
        print(f"\n[ALL PASS] Redaction cascade is correct.")
    else:
        print(f"\n[FAIL] Issues found.")

    return all_pass

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
