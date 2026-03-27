"""
Deep verification of dedup/canonicalization step.

1. Reads all extraction files and builds a raw entity inventory
2. Runs the canonicalizer on them
3. Reports merges, aliases, and statistics for manual comparison
"""
import json
import sys
import os
from pathlib import Path
from collections import defaultdict

if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from schema.ontology import ExtractionResult, Entity
from dedup.entity_canon import EntityCanonicalizer
from graph.fact_factory import FactFactory


def main():
    ext_dir = config.EXTRACTION_DIR
    ext_files = sorted(ext_dir.glob("extraction_*.json"))
    
    print("=" * 70)
    print("PHASE 1: RAW ENTITY INVENTORY (Before Canonicalization)")
    print("=" * 70)
    
    # Collect ALL entities and assertions across all files
    all_entities = []
    all_assertions = []
    entities_by_name = defaultdict(list)  # name -> [(type, source_id, aliases)]
    entities_by_type = defaultdict(list)
    
    for ext_file in ext_files:
        with open(ext_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        result = ExtractionResult(**data)
        source_id = data.get("source_id", ext_file.stem)
        
        for entity in result.entities:
            all_entities.append(entity)
            key = entity.name.lower().strip()
            entities_by_name[key].append({
                "type": entity.type.value if hasattr(entity.type, 'value') else str(entity.type),
                "name": entity.name,
                "source": source_id,
                "aliases": entity.aliases or [],
            })
            etype = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
            entities_by_type[etype].append(entity.name)
        
        all_assertions.extend(result.assertions)
    
    print(f"\nTotal raw entities: {len(all_entities)}")
    print(f"Unique entity names (case-insensitive): {len(entities_by_name)}")
    print(f"\nEntities by type:")
    for etype, names in sorted(entities_by_type.items()):
        print(f"  {etype}: {len(names)}")
    
    # Find duplicates (same name appearing in multiple issues)
    print(f"\n--- ENTITIES APPEARING IN MULTIPLE ISSUES (candidates for merge) ---")
    duplicated = {name: entries for name, entries in entities_by_name.items() if len(entries) > 1}
    for name, entries in sorted(duplicated.items(), key=lambda x: -len(x[1])):
        sources = [e["source"] for e in entries]
        types = set(e["type"] for e in entries)
        print(f"  '{name}' ({', '.join(types)}): appears in {len(entries)} issues: {sources}")
    
    # Find entities with same aliases
    print(f"\n--- ENTITIES WITH ALIASES ---")
    for name, entries in entities_by_name.items():
        for e in entries:
            if e["aliases"]:
                print(f"  '{e['name']}' ({e['type']}) aliases: {e['aliases']} (from {e['source']})")

    # Find potential Person duplicates (@ prefix, case variations)
    print(f"\n--- POTENTIAL PERSON MERGES (@ stripping, case normalization) ---")
    person_names = defaultdict(list)
    for entity in all_entities:
        etype = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
        if etype == "Person":
            normalized = entity.name.lower().strip().lstrip("@")
            person_names[normalized].append(entity.name)
    
    for normalized, variants in person_names.items():
        if len(set(variants)) > 1:
            print(f"  {normalized}: {list(set(variants))}")

    # Find potential Component merges
    print(f"\n--- POTENTIAL COMPONENT MERGES (alias table) ---")
    comp_names = defaultdict(list)
    for entity in all_entities:
        etype = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
        if etype == "Component":
            comp_names[entity.name.lower().strip()].append(entity.name)
    
    for name, variants in comp_names.items():
        if len(variants) > 1:
            print(f"  {name}: {variants}")

    print(f"\n\n{'=' * 70}")
    print("PHASE 2: RUNNING CANONICALIZER")
    print("=" * 70)
    
    # Run the actual canonicalizer
    canonicalizer = EntityCanonicalizer()
    # Reset state for clean test
    canonicalizer.uf = type(canonicalizer.uf)()
    canonicalizer.entities = {}
    canonicalizer.merge_log = []
    
    canonical_entities = []
    merge_events = []
    
    for entity in all_entities:
        before_count = len(canonicalizer.merge_log)
        canonical = canonicalizer.register_entity(entity)
        after_count = len(canonicalizer.merge_log)
        
        if after_count > before_count:
            # A merge happened
            new_merges = canonicalizer.merge_log[before_count:]
            for m in new_merges:
                merge_events.append({
                    "canonical": m.canonical_id,
                    "merged": m.merged_entity_id,
                    "reason": m.reason,
                })
        
        if canonical not in canonical_entities:
            canonical_entities.append(canonical)
    
    print(f"\nCanonical entities after dedup: {len(canonical_entities)}")
    print(f"Merges performed: {len(merge_events)}")
    print(f"Reduction: {len(all_entities)} -> {len(canonical_entities)} ({len(all_entities) - len(canonical_entities)} merged)")
    
    print(f"\n--- MERGE LOG ---")
    for m in merge_events:
        print(f"  MERGED: '{m['merged']}' -> '{m['canonical']}' (reason: {m['reason']})")
    
    # Show canonical entities by type
    canon_by_type = defaultdict(list)
    for entity in canonical_entities:
        etype = entity.type.value if hasattr(entity.type, 'value') else str(entity.type)
        canon_by_type[etype].append(entity.name)
    
    print(f"\n--- CANONICAL ENTITIES BY TYPE ---")
    for etype, names in sorted(canon_by_type.items()):
        print(f"\n  {etype} ({len(names)}):")
        for name in sorted(names)[:15]:
            print(f"    - {name}")
        if len(names) > 15:
            print(f"    ... and {len(names) - 15} more")
    
    # Check entity ID resolution
    print(f"\n--- ENTITY ID RESOLUTION SPOT CHECK ---")
    test_names = ["brunolemos", "@brunolemos", "react-dom", "ReactDOM", "Hooks", "hooks"]
    for name in test_names:
        canon_id = canonicalizer.get_canonical_id(name)
        if canon_id and canon_id != name:
            print(f"  '{name}' -> '{canon_id}' [RESOLVED]")
        elif canon_id:
            print(f"  '{name}' -> '{canon_id}' [IDENTITY]")
        else:
            print(f"  '{name}' -> None [NOT FOUND]")
    
    print(f"\n\n{'=' * 70}")
    print("PHASE 3: CLAIM/ASSERTION DEDUP CHECK")
    print("=" * 70)
    
    # Check for duplicate assertions (same subject + object + claim_type)
    assertion_keys = defaultdict(list)
    for a in all_assertions:
        key = f"{a.claim_type}|{(a.subject_id or '').lower()}|{(a.object_id or '').lower()}"
        assertion_keys[key].append(a)
    
    duplicated_claims = {k: v for k, v in assertion_keys.items() if len(v) > 1}
    print(f"\nTotal raw assertions: {len(all_assertions)}")
    print(f"Unique assertion signatures: {len(assertion_keys)}")
    print(f"Duplicated assertion signatures: {len(duplicated_claims)}")
    
    if duplicated_claims:
        print(f"\n--- DUPLICATE CLAIMS ---")
        for key, assertions in list(duplicated_claims.items())[:10]:
            parts = key.split("|")
            print(f"  {parts[0]}: '{parts[1]}' -> '{parts[2]}' ({len(assertions)} times)")
            for a in assertions:
                ev_count = len(a.evidence) if a.evidence else 0
                print(f"    conf={a.confidence}, evidence={ev_count}, type={a.type}")

    print(f"\n\n{'=' * 70}")
    print("PHASE 4: CANONICALIZER STATS")
    print("=" * 70)
    stats = canonicalizer.get_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
