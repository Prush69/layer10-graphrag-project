import json
import sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path("c:/Layer10")
sys.path.insert(0, str(root_dir))

from schema.ontology import ExtractionResult
from dedup.entity_canon import EntityCanonicalizer
from graph.fact_factory import FactFactory
from graph.store import GraphStore

def verify_pipeline(issue_num="13991"):
    extraction_file = root_dir / "data" / "extraction" / f"extraction_{issue_num}.json"
    
    if not extraction_file.exists():
        print(f"Extraction file {extraction_file} not found. Searching in config.EXTRACTION_DIR...")
        import config
        extraction_file = config.EXTRACTION_DIR / f"extraction_{issue_num}.json"
        if not extraction_file.exists():
            print(f"Extraction file {extraction_file} not found! Run extraction first.")
            return

    print("="*50)
    print(f"STEP 1: Extraction Output for {issue_num}")
    print("="*50)
    with open(extraction_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    result = ExtractionResult(**data)
    print(f"Entities: {len(result.entities)}")
    print(f"Assertions: {len(result.assertions)}")
    
    for idx, ass in enumerate(result.assertions[:3]):
        print(f"  Assertion {idx}: {ass.claim_type.value}")
        print(f"    - subject_id: {ass.subject_id}")
        print(f"    - object_id:  {ass.object_id}")

    print("\n" + "="*50)
    print("STEP 2: Canonical Fact Formation (Deduplication)")
    print("="*50)
    canonicalizer = EntityCanonicalizer()
    fact_factory = FactFactory()
    
    all_entities = []
    all_assertions = []
    
    for entity in result.entities:
        canonical = canonicalizer.register_entity(entity)
        all_entities.append(canonical)
        
    for assertion in result.assertions:
        # Pre-resolution checks
        canon_subj = canonicalizer.get_canonical_id(assertion.subject_id)
        canon_obj = canonicalizer.get_canonical_id(assertion.object_id) if assertion.object_id else None
        
        # We need to trace exactly if the canonicalizer actually matched anything, or if it failed mapping
        if canon_subj:
            assertion.subject_id = canon_subj
        else:
            print(f"  [WARNING] Could not resolve canonical ID for subject: {assertion.subject_id}")
            
        if assertion.object_id and canon_obj:
            assertion.object_id = canon_obj
        elif assertion.object_id and not canon_obj:
            print(f"  [WARNING] Could not resolve canonical ID for object: {assertion.object_id}")
            
        all_assertions.append(assertion)
        
    all_claims = fact_factory.form_facts(all_assertions)
    print(f"Formed {len(all_claims)} canonical facts/claims.")
    for idx, clm in enumerate(all_claims[:3]):
        print(f"  Claim {idx}: {clm.type.value}")
        print(f"    - subject_id: {clm.subject_id}")
        print(f"    - object_id:  {clm.object_id}")

    print("\n" + "="*50)
    print("STEP 3: Graph Storage (Serialization)")
    print("="*50)
    store = GraphStore()
    graph = store.load()
    
    # We clear the graph to only see this issue's data natively, or we can just see if edges got added.
    graph.backend.clear()
    graph.stats = {"entities_added": 0, "claims_added": 0, "evidence_count": 0, "duplicates_skipped": 0}
    graph._ingested_hashes = set()
    graph._id_to_key = {}
    
    print("Adding entities and claims to fresh MemoryGraph...")
    for entity in all_entities:
        graph.add_entity(entity)
    for claim in all_claims:
        graph.add_claim(claim)
        
    print(f"Nodes in Graph: {graph.backend.node_count()}")
    print(f"Edges in Graph: {graph.backend.edge_count()}")
    
    out_edges = graph.backend.get_all_edges()
    print(f"Sample Edges (first 5):")
    for idx, edge in enumerate(out_edges[:5]):
        print(f"  Edge {idx}: {edge['_source']} -> {edge['_target']} (type: {edge.get('type')})")

    # Serialize test
    serialized = graph.to_serializable()
    if 'links' in serialized:
        print(f"Serialized links count: {len(serialized['links'])}")
    elif 'edges' in serialized:
        print(f"Serialized edges count: {len(serialized['edges'])}")
        
    print("\n" + "="*50)
    print("STEP 4: UI Endpoint Data Match")
    print("="*50)
    nodes = []
    edges = []
    
    for n_id, n_data in graph.backend.get_all_nodes():
        nodes.append({"id": n_id, "_is_event": n_data.get("_is_event", False)})
        
    for e_data in graph.backend.get_all_edges():
        edges.append({
            "source": e_data.get("_source", ""),
            "target": e_data.get("_target", ""),
            "type": e_data.get("type", "")
        })
        
    print(f"UI Graph /api/graph would return {len(nodes)} nodes and {len(edges)} links.")
    
    # Critical D3.js Link Validation
    node_ids = {n["id"] for n in nodes}
    missing_sources = []
    missing_targets = []
    
    for e in edges:
        if e["source"] not in node_ids:
            missing_sources.append(e["source"])
        if e["target"] not in node_ids:
            missing_targets.append(e["target"])
            
    if missing_sources or missing_targets:
        print("  [CRITICAL ERROR] UI Visualization will drop links because IDs do not match node IDs!")
        if missing_sources:
            print(f"    Missing Sources (Sample): {missing_sources[:3]}")
        if missing_targets:
            print(f"    Missing Targets (Sample): {missing_targets[:3]}")
    else:
        print("  [OK] All links perfectly map to valid nodes in the UI output.")

if __name__ == "__main__":
    verify_pipeline()
