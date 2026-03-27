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

def trace_single_fact(issue_num="13991"):
    extraction_file = root_dir / "data" / "extraction" / f"extraction_{issue_num}.json"
    
    if not extraction_file.exists():
        import config
        extraction_file = config.EXTRACTION_DIR / f"extraction_{issue_num}.json"
        if not extraction_file.exists():
            print(f"Extraction file {extraction_file} not found! Run extraction first.")
            return

    print("="*80)
    print(f"TRACE INVESTIGATION FOR ISSUE {issue_num}")
    print("="*80)
    
    # ---------------------------------------------------------
    # STEP 1: Extraction (Data Ingestion) Proof
    # ---------------------------------------------------------
    print("\n>>> STEP 1: EXTRACTION (Data Ingestion) <<<")
    with open(extraction_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = ExtractionResult(**data)
    
    if not result.assertions:
        print("FAILED: No assertions found in extraction.")
        return
        
    # We trace the very first assertion
    target_ass = result.assertions[0]
    ass_subject_raw = target_ass.subject_id
    ass_object_raw = target_ass.object_id
    
    print(f"  TARGET ASSERTION: '{target_ass.claim_type.value}' by {target_ass.asserted_by}")
    print(f"  INPUT  -> Extracted raw subject_id: '{ass_subject_raw}'")
    print(f"  INPUT  -> Extracted raw object_id:  '{ass_object_raw}'")
    
    # Prove the subject exists in the extracted entities
    subject_extracted_entity = next((e for e in result.entities if e.id == ass_subject_raw or e.name == ass_subject_raw), None)
    if subject_extracted_entity:
        print(f"  OUTPUT -> Proof: Subject DOES exist in extracted entities. Entity ID: '{subject_extracted_entity.id}', Name: '{subject_extracted_entity.name}'")
    else:
        print(f"  OUTPUT -> FAILURE: Subject '{ass_subject_raw}' does NOT match any extracted entity!")

    # ---------------------------------------------------------
    # STEP 2: Canonical Fact Formation (Deduplication) Proof
    # ---------------------------------------------------------
    print("\n>>> STEP 2: DEDUPLICATION (Canonical Fact Formation) <<<")
    canonicalizer = EntityCanonicalizer()
    fact_factory = FactFactory()
    
    all_entities = []
    
    print("  INPUT  -> Registering all entities...")
    for entity in result.entities:
        canonical = canonicalizer.register_entity(entity)
        all_entities.append(canonical)
        
    canon_subj_id = canonicalizer.get_canonical_id(ass_subject_raw)
    canon_obj_id = canonicalizer.get_canonical_id(ass_object_raw) if ass_object_raw else None
    
    print(f"  OUTPUT -> Canonicalizer resolved subject '{ass_subject_raw}' to: '{canon_subj_id}'")
    print(f"  OUTPUT -> Canonicalizer resolved object '{ass_object_raw}' to: '{canon_obj_id}'")
    
    # Form facts
    for assertion in result.assertions:
        canon_subj = canonicalizer.get_canonical_id(assertion.subject_id)
        canon_obj = canonicalizer.get_canonical_id(assertion.object_id) if assertion.object_id else None
        if canon_subj: assertion.subject_id = canon_subj
        if canon_obj: assertion.object_id = canon_obj
        
    all_claims = fact_factory.form_facts(result.assertions)
    
    # Find our traced claim
    target_claim = next((c for c in all_claims if target_ass.id in c.assertions), None)
    if target_claim:
        print(f"  OUTPUT -> Proof: Claim formed successfully. Claim ID: '{target_claim.id}'")
        print(f"  OUTPUT -> Proof: Claim subject_id is EXACTLY: '{target_claim.subject_id}'")
        print(f"  OUTPUT -> Proof: Claim object_id is EXACTLY:  '{target_claim.object_id}'")
    else:
        print("  OUTPUT -> FAILURE: Traced assertion did not form a claim!")
        return

    # ---------------------------------------------------------
    # STEP 3: Graph Storage (Serialization) Proof
    # ---------------------------------------------------------
    print("\n>>> STEP 3: GRAPH STORAGE (MemoryGraph Add) <<<")
    store = GraphStore()
    graph = store.load()
    graph.backend.clear()
    graph.stats = {"entities_added": 0, "claims_added": 0, "evidence_count": 0, "duplicates_skipped": 0}
    graph._ingested_hashes = set()
    graph._id_to_key = {}
    
    for entity in all_entities:
        graph.add_entity(entity)
    for claim in all_claims:
        graph.add_claim(claim)
        
    print(f"  INPUT  -> Added {len(all_entities)} canonical entities and {len(all_claims)} canonical claims.")
    
    # Prove the nodes exist in the backend
    subj_node_id = graph._id_to_key.get(target_claim.subject_id) or f"Entity::{target_claim.subject_id}"
    event_node_id = f"Event::{target_claim.id}"
    
    print(f"  OUTPUT -> Proof: Subject Node ID in backend is EXACTLY: '{subj_node_id}'")
    print(f"  OUTPUT -> Proof: Event Node ID in backend is EXACTLY:   '{event_node_id}'")
    
    if graph.backend.has_node(subj_node_id):
        print(f"  OUTPUT -> Proof: Backend CONFIRMS Subject Node '{subj_node_id}' exists.")
    else:
        print(f"  OUTPUT -> FAILURE: Backend is MISSING Subject Node '{subj_node_id}'!")
        
    if graph.backend.has_node(event_node_id):
        print(f"  OUTPUT -> Proof: Backend CONFIRMS Event Node '{event_node_id}' exists.")
    else:
        print(f"  OUTPUT -> FAILURE: Backend is MISSING Event Node '{event_node_id}'!")
        
    # Prove the edge exists
    out_edges = graph.backend.get_out_edges(subj_node_id)
    target_edge = next((e for e in out_edges if e["_target"] == event_node_id), None)
    if target_edge:
        print(f"  OUTPUT -> Proof: Topological Edge CONFIRMED: '{target_edge['_source']}' -> '{target_edge['_target']}'")
    else:
        print(f"  OUTPUT -> FAILURE: No topological edge connecting '{subj_node_id}' to '{event_node_id}'!")

    # ---------------------------------------------------------
    # STEP 4: UI Serialization (/api/graph mapping) Proof
    # ---------------------------------------------------------
    print("\n>>> STEP 4: UI SERIALIZATION (app.py mapping) <<<")
    
    nodes_payload = []
    for n_data in graph.entities:
        nodes_payload.append({"id": n_data.get("id"), "_is_event": False})
    for n_data in graph.claims:
        nodes_payload.append({"id": n_data.get('id'), "_is_event": True})
        
    edges_payload = []
    for e_data in graph.backend.get_all_edges():
        edges_payload.append({
            "source": e_data.get("_source", ""),
            "target": e_data.get("_target", ""),
            "type": e_data.get("type", "")
        })

    # Find the nodes in the payload
    payload_subj_node = next((n for n in nodes_payload if n["id"] == subj_node_id), None)
    payload_event_node = next((n for n in nodes_payload if n["id"] == target_claim.id), None)
    
    print(f"  INPUT  -> We expect UI payload nodes with IDs: '{subj_node_id}' and '{target_claim.id}'")
    if payload_subj_node:
        print(f"  OUTPUT -> Proof: UI Payload contains Subject Node '{payload_subj_node['id']}'")
    else:
        print(f"  OUTPUT -> FAILURE: UI Payload missing Subject Node '{subj_node_id}'!")
        
    if payload_event_node:
        print(f"  OUTPUT -> Proof: UI Payload contains Event Node '{payload_event_node['id']}'")
    else:
        print(f"  OUTPUT -> FAILURE: UI Payload missing Event Node '{target_claim.id}'!")
        
    # Find the edge in the payload
    payload_edge = next((e for e in edges_payload if e["source"] == subj_node_id), None)
    if payload_edge:
        print(f"  OUTPUT -> Proof: UI Payload contains Edge '{payload_edge['source']}' -> '{payload_edge['target']}'")
        
        # FINAL D3.JS BINDING CHECK
        print("\n>>> FINAL D3.JS BINDING CHECK <<<")
        target_in_nodes = next((n for n in nodes_payload if n["id"] == payload_edge["target"]), None)
        if target_in_nodes:
            print(f"  CONCLUSION: SUCCESS! D3.js WILL bind this edge because '{payload_edge['target']}' EXACTLY matches a node ID.")
        else:
            print(f"  CONCLUSION: FAILURE! D3.js WILL DROP THIS EDGE! The edge targets '{payload_edge['target']}', but NO Node exists with that ID!")
            print(f"              (The claim node was serialized with ID '{payload_event_node['id']}' instead!)")
    else:
        print("  OUTPUT -> FAILURE: UI Payload missing Edge!")

if __name__ == "__main__":
    trace_single_fact()
