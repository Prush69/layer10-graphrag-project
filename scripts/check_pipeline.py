import json
from pathlib import Path
import sys

BASE_DIR = Path("c:/Layer10")
sys.path.insert(0, str(BASE_DIR))
from schema.ontology import ExtractionResult
from dedup.entity_canon import EntityCanonicalizer
from graph.fact_factory import FactFactory
from graph.store import GraphStore

def check_pipeline(issue_id="24556"):
    print(f"--- CHECKING PIPELINE FOR ISSUE {issue_id} ---")
    
    # 1. Raw Data
    raw_file = BASE_DIR / f"corpus/raw/issue_{issue_id}.json"
    print(f"\n1. RAW DATA: {raw_file}")
    if raw_file.exists():
        with open(raw_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        print(f"Keys: {list(raw_data.keys())}")
        print(f"Title: {raw_data.get('title')}")
        print(f"Num comments: {len(raw_data.get('comments', []))}")
    else:
        print("Raw file not found")
        
    # 2. Extraction Data
    ext_file = BASE_DIR / f"data/extractions/extraction_{issue_id}.json"
    print(f"\n2. EXTRACTION DATA: {ext_file}")
    if ext_file.exists():
        with open(ext_file, 'r', encoding='utf-8') as f:
            ext_data = json.load(f)
        result = ExtractionResult(**ext_data)
        print(f"Entities extracted: {len(result.entities)}")
        print(f"Sample entity: {result.entities[0].name if result.entities else 'None'} ({result.entities[0].type if result.entities else 'None'})")
        print(f"Assertions extracted: {len(result.assertions)}")
        print(f"Sample assertion: {result.assertions[0].subject_id if result.assertions else 'None'} -> {result.assertions[0].claim_type if result.assertions else 'None'} -> {result.assertions[0].object_id if result.assertions else 'None'}")
    else:
        print("Extraction file not found")
        return

    # 3. Canonicalization / Dedup
    print(f"\n3. CANONICALIZATION & DEDUP")
    canonicalizer = EntityCanonicalizer()
    fact_factory = FactFactory()
    
    canon_entities = []
    for entity in result.entities:
        canon_entities.append(canonicalizer.register_entity(entity))
        
    for assertion in result.assertions:
        canon_subj = canonicalizer.get_canonical_id(assertion.subject_id)
        if canon_subj: assertion.subject_id = canon_subj
        if assertion.object_id:
            canon_obj = canonicalizer.get_canonical_id(assertion.object_id)
            if canon_obj: assertion.object_id = canon_obj
        
    facts = fact_factory.form_facts(result.assertions)
    print(f"Canonical entities: {len(set(e.id for e in canon_entities))}")
    print(f"Formed canonical facts: {len(facts)}")
    if facts:
        print(f"Sample fact: {facts[0].subject_id} {facts[0].type} {facts[0].object_id}")
        
    # 4. Graph Store
    print(f"\n4. GRAPH STORE")
    store = GraphStore()
    graph = store.load()
    if graph:
        print(f"Graph loaded. Total nodes: {len(graph.entities) + len(graph.claims)}, Total entities: {len(graph.entities)}, Total claims: {len(graph.claims)}")
        
        # Check if our entities are in the graph
        graph_entities = [n.get("id") for n in graph.entities]
        canon_entity_ids = list(set(e.id for e in canon_entities if e.id))
        print(f"Sample entity IDs in graph: {graph_entities[:5]}")
        print(f"Sample extracted entity IDs: {canon_entity_ids[:5]}")
        found_entities = [e_id for e_id in canon_entity_ids if e_id in graph_entities]
        print(f"Found {len(found_entities)}/{len(canon_entity_ids)} extracted entities in the global graph.")
    else:
        print("Could not load graph.")

if __name__ == '__main__':
    check_pipeline()
