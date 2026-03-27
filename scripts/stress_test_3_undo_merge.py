"""
Stress Test 3: Undo Merge Fracture Test
Find a heavily-aliased entity in entity_merges.json, trigger undo_merge(merge_id),
verify the Union-Find splits cleanly and the ledger records the SplitEvent.
"""
import json, os, sys
from pathlib import Path
root = Path(__file__).parent.parent
sys.path.insert(0, str(root)); os.chdir(root)

import config
from dedup.entity_canon import EntityCanonicalizer

def run():
    ec = EntityCanonicalizer()

    # -- Step 1: Find a merge to undo --
    merges = ec.merge_ledger
    # Find one with a specific canonical_id we can trace
    # Pick the react-dom → reactdom merge for clarity
    target_merge = None
    for m in merges:
        if (m.canonical_id == "component::reactdom"
                and m.merged_entity_id == "component::react-dom"
                and m.event_type == "merge"):
            target_merge = m
            break

    if not target_merge:
        # Fallback: use any merge
        for m in merges:
            if m.event_type == "merge" and m.reversible:
                target_merge = m
                break

    if not target_merge:
        print("[SKIP] No merge records found in ledger.")
        return True

    print(f"=== UNDO MERGE FRACTURE TEST ===")
    print(f"Target merge: {target_merge.merge_id}")
    print(f"  Canonical:  {target_merge.canonical_id}")
    print(f"  Merged from:{target_merge.merged_entity_id}")
    print(f"  Reason:     {target_merge.reason}")

    # -- Step 2: Verify the merged entity IS connected via Union-Find before undo --
    merged_entity_id = target_merge.merged_entity_id
    canonical_id = target_merge.canonical_id

    before_root = ec.uf.find(merged_entity_id)
    print(f"\nBEFORE undo: UF.find('{merged_entity_id}') = '{before_root}'")
    is_connected_before = ec.uf.connected(merged_entity_id, canonical_id)
    print(f"  Connected to canonical: {is_connected_before}")

    # -- Step 3: Trigger undo_merge --
    ledger_len_before = len(ec.merge_ledger)
    success = ec.undo_merge(target_merge.merge_id)
    ledger_len_after = len(ec.merge_ledger)

    print(f"\nundo_merge() returned: {success}")
    print(f"Ledger entries before: {ledger_len_before}")
    print(f"Ledger entries after:  {ledger_len_after} (+{ledger_len_after - ledger_len_before} SplitEvent)")

    # -- Step 4: Verify the split in Union-Find --
    after_root = ec.uf.find(merged_entity_id)
    is_connected_after = ec.uf.connected(merged_entity_id, canonical_id)

    print(f"\nAFTER undo: UF.find('{merged_entity_id}') = '{after_root}'")
    print(f"  Connected to canonical: {is_connected_after}")
    print(f"  Now points to self: {after_root == merged_entity_id}")

    # -- Step 5: Verify SplitEvent recorded in ledger --
    split_events = [m for m in ec.merge_ledger if m.event_type == "split"
                    and target_merge.merge_id in m.reason]
    print(f"\nSplitEvent(s) recorded in ledger: {len(split_events)}")
    if split_events:
        print(f"  Split event: {json.dumps(split_events[0].model_dump(), indent=2)}")

    # -- Assertions --
    all_pass = (
        success is True
        and ledger_len_after == ledger_len_before + 1
        and not is_connected_after
        and after_root == merged_entity_id
        and len(split_events) >= 1
    )

    print(f"\n{'[ALL PASS] Undo merge fracture is clean.' if all_pass else '[FAIL] Issues found.'}")
    return all_pass

if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
