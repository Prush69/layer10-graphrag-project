"""
LangGraph extraction pipeline orchestrator using Groq (Llama 3.1 70B).

This module implements Phase 1 of the Layer10 blueprint:
A multi-stage ingestion pipeline built with LangGraph to splinter
and process documents concurrently using Groq's LPUs.

Why Groq?
In production GraphRAG, generation speed (Tokens Per Second) is the primary
bottleneck when extracting hundreds of JSON relationships. Groq provides
800+ TPS on free-tier. While Gemini has a huge context window, Groq's
insane speed and 30 RPM free tier makes it the ultimate engine for a
highly parallelized LangGraph Swarm.
"""

import json
import time
import hashlib
import operator
from typing import List, Dict, Any, TypedDict, Annotated
from pathlib import Path
from datetime import datetime

from pydantic import BaseModel, Field

# Mocking LangChain imports for the CV architecture
try:
    from langchain_groq import ChatGroq
    from langgraph.graph import StateGraph, START, END
except ImportError:
    print("Warning: langchain or langgraph not installed. Run `pip install -r requirements.txt`")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from schema.ontology import ExtractionResult, Entity, Assertion, Evidence, EntityType, AssertionType, ClaimType, SupportStrength

# --- 1. Define the LangGraph State ---

class ExtractionState(TypedDict):
    """
    The state passed between nodes in the LangGraph.
    Using Annotated[..., operator.add] to ensure that parallel or
    sequential node executions correctly aggregate outputs (reduces)
    instead of overwriting the lists.
    """
    files_to_process: List[Path]
    current_batch: List[Path]
    raw_results: Annotated[List[Dict[str, Any]], operator.add]
    final_results: Annotated[List[ExtractionResult], operator.add]
    errors: Annotated[List[str], operator.add]

# --- 2. Define the Pydantic Schema for the LLM ---

class Edge(BaseModel):
    source_entity: str = Field(description="Name of the source node")
    target_entity: str = Field(description="Name of the target node")
    relationship: str = Field(description="How they are connected")
    evidence: str = Field(description="Exact verbatim quote from the text proving this relationship")

class GraphExtraction(BaseModel):
    nodes: List[str] = Field(description="List of unique entities identified")
    edges: List[Edge] = Field(description="List of relationships between nodes")

# --- 3. LangGraph Nodes ---

def splinter_node(state: ExtractionState) -> ExtractionState:
    """Splinter the document/corpus into parallel chunks (batches)."""
    batch_size = config.EXTRACTION_BATCH_SIZE
    files = state.get("files_to_process", [])

    if not files:
        # Return empty explicitly overwriting the keys to stop loop
        return {"current_batch": [], "files_to_process": []}

    current_batch = files[:batch_size]
    remaining = files[batch_size:]

    # In LangGraph, returning dict keys not using operator.add overwrites the state
    return {
        "current_batch": current_batch,
        "files_to_process": remaining
    }

def extract_node(state: ExtractionState) -> ExtractionState:
    """The Extraction Swarm: Process chunks using Groq LPUs."""
    batch = state.get("current_batch", [])
    if not batch:
        return {}

    try:
        # Initialize Groq Llama 3.1 70B with structured output
        # Groq's free tier (30 RPM) and 800+ TPS make it perfect for LangGraph
        llm = ChatGroq(model="llama-3.1-70b-versatile", temperature=0)
        structured_llm = llm.with_structured_output(GraphExtraction)

        raw_results = []
        for file_path in batch:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            text_chunk = data.get("issue", {}).get("body", "")

            # Groq context limit is smaller (128k/8k), so we truncate safely
            prompt = f"""
            You are a senior data architect extracting organizational memory.
            Analyze the following communication log.
            Extract all distinct entities (projects, engineers, tools) and their relationships.
            You MUST provide a verbatim quote from the text as 'evidence' for every relationship you extract.
            If you cannot find verbatim evidence, do not create the relationship.

            Log Data:
            {str(text_chunk)[:20000]}
            """

            print(f"  [Groq LPU] Extracting {file_path.name}...")
            result = structured_llm.invoke(prompt)

            # Add to the reducers list
            raw_results.append({
                "source_id": file_path.name,
                "data": result.model_dump() if result else {},
                "raw_text": str(text_chunk)[:20000]
            })

            # Groq handles 30 RPM, so 2s stagger is completely safe
            time.sleep(2)

        return {"raw_results": raw_results}

    except Exception as e:
        print(f"  [Groq Error] {e}")
        return {"errors": [str(e)]}

def map_to_ontology_node(state: ExtractionState) -> ExtractionState:
    """
    CRITICAL TRANSLATION LAYER
    Map the Groq 'Edge' extraction back to our complex system Ontology.
    Without this, the deduplication and Neo4j graph stores will crash.
    """
    # Grab ONLY the current batch of raw_results for this step if possible,
    # but since raw_results accumulates, we need to map the ones we haven't mapped.
    # To keep it simple, we will just use the last extracted batch.
    # LangGraph best practice for this linear flow is to clear raw_results or process them all at once.
    # To prevent double processing, we process the state's raw_results but don't append to it.
    # For now, we process all available raw_results that haven't been saved.

    raw_results = state.get("raw_results", [])
    final_results = []

    for res in raw_results:
        source_id = res["source_id"]
        issue_num = source_id.split("_")[1].replace(".json", "")
        system_source_id = f"issue-{issue_num}"
        result_path = config.EXTRACTION_DIR / f"extraction_{issue_num}.json"

        if result_path.exists():
            continue # already processed

        data = res["data"]
        raw_text = res.get("raw_text", "")

        entities = []
        assertions = []

        # 1. Translate Nodes to Entities
        for node_name in data.get("nodes", []):
            entity_id = f"entity::{hashlib.md5(node_name.encode()).hexdigest()[:8]}"
            entities.append(Entity(
                id=entity_id,
                type=EntityType.COMPONENT, # Defaulting to component for unstructured nodes
                name=node_name,
                aliases=[node_name]
            ))

        # 2. Translate Edges to Assertions
        for edge_data in data.get("edges", []):
            subj = edge_data.get("source_entity", "")
            obj = edge_data.get("target_entity", "")
            rel = edge_data.get("relationship", "")
            excerpt = edge_data.get("evidence", "")

            if not subj or not obj or not excerpt:
                continue

            subj_id = f"entity::{hashlib.md5(subj.encode()).hexdigest()[:8]}"
            obj_id = f"entity::{hashlib.md5(obj.encode()).hexdigest()[:8]}"

            # Create Strict Evidence
            ev = Evidence(
                artifact_version_id=f"{system_source_id}-v1",
                source_id=system_source_id,
                excerpt=excerpt[:200],
                confidence=0.9,
                support_strength=SupportStrength.EXPLICIT,
                source_type="issue"
            )

            # Calculate offsets for grounding verification
            idx = raw_text.find(excerpt)
            if idx != -1:
                ev.offset_start = idx
                ev.offset_end = idx + len(excerpt)

            # Create Semantic Assertion
            aid = hashlib.md5(f"{subj}_{obj}_{rel}".encode()).hexdigest()[:8]
            assertions.append(Assertion(
                id=f"assertion::{aid}",
                artifact_version_id=f"{system_source_id}-v1",
                asserted_by="langgraph-swarm",
                type=AssertionType.OBSERVATION,
                claim_type=ClaimType.RELATED_TO,
                subject_id=subj_id,
                object_id=obj_id,
                properties={"description": rel},
                timestamp=datetime.utcnow().isoformat(),
                confidence=0.9,
                evidence=[ev]
            ))

        # Construct the final expected output schema
        extraction_result = ExtractionResult(
            source_id=system_source_id,
            model="llama-3.1-70b-versatile",
            extracted_at=datetime.utcnow().isoformat(),
            raw_text_length=len(raw_text),
            entities=entities,
            assertions=assertions
        )

        # Save output to disk perfectly matching the classic pipeline's expected format
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(extraction_result.model_dump(), f, indent=2, ensure_ascii=False)

        print(f"  [Mapped] Saved mapped LangGraph ExtractionResult for {system_source_id} to {result_path}")
        final_results.append(extraction_result)

    return {"final_results": final_results}

# --- 4. Build the Graph ---

def build_extraction_graph():
    workflow = StateGraph(ExtractionState)

    workflow.add_node("splinter", splinter_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("map_to_ontology", map_to_ontology_node)

    workflow.add_edge(START, "splinter")
    workflow.add_edge("splinter", "extract")
    workflow.add_edge("extract", "map_to_ontology")

    def route(state: ExtractionState) -> str:
        if state.get("files_to_process", []):
            return "splinter"
        return END

    workflow.add_conditional_edges("map_to_ontology", route)
    return workflow.compile()

def run_langgraph_pipeline(limit: int = None):
    raw_dir = config.RAW_DATA_DIR
    if not raw_dir.exists():
        print("Raw data dir does not exist.")
        return

    issue_files = sorted(raw_dir.glob("issue_*.json"))

    if limit:
        issue_files = issue_files[:limit]

    print(f"\n{'='*60}")
    print(f"LANGGRAPH + GROQ LPU EXTRACTION PIPELINE")
    print(f"{'='*60}")
    print(f"  Target: {len(issue_files)} files")
    print(f"  Model: Llama 3.1 70B (Groq)")

    try:
        app = build_extraction_graph()

        initial_state = {
            "files_to_process": issue_files,
            "current_batch": [],
            "raw_results": [],
            "final_results": [],
            "errors": []
        }

        for output in app.stream(initial_state):
            for key, value in output.items():
                print(f"Finished node: {key}")

        print("\nExtraction Complete via LangGraph (Groq LPU)!")
    except Exception as e:
        print(f"Could not build or run graph: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="Max issues to process")
    args = parser.parse_args()

    import os
    if not os.getenv("GROQ_API_KEY"):
        print("WARNING: GROQ_API_KEY not set. LangGraph/Groq will fail.")
        print("Set it using: export GROQ_API_KEY='your_key'")
    else:
        run_langgraph_pipeline(limit=args.limit)
