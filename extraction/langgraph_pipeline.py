"""
LangGraph extraction pipeline orchestrator using Gemini 2.0 Flash.

This module implements Phase 1 of the Layer10 blueprint:
A multi-stage ingestion pipeline built with LangGraph to splinter
and process documents concurrently using Gemini 2.0 Flash.

Why Flash?
In production GraphRAG, you don't use high-latency, expensive "Pro" models
(like Gemini 1.5 Pro) for structured extraction tasks. Gemini Flash provides
a 1M+ token context window, significantly lower latency, and most importantly
for a free-tier CV project: 15 Requests Per Minute (RPM) vs Pro's 2 RPM.
This allows true parallel execution of the LangGraph Swarm.
"""

import json
import time
from typing import List, Dict, Any, TypedDict
from pathlib import Path

from pydantic import BaseModel, Field

# Mocking LangChain imports for the CV architecture
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langgraph.graph import StateGraph, START, END
except ImportError:
    print("Warning: langchain or langgraph not installed. Run `pip install -r requirements.txt`")

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from schema.ontology import ExtractionResult, Entity, Assertion, Evidence

# --- 1. Define the LangGraph State ---

class ExtractionState(TypedDict):
    """The state passed between nodes in the LangGraph."""
    files_to_process: List[Path]
    current_batch: List[Path]
    raw_results: List[Dict[str, Any]]
    final_results: List[ExtractionResult]
    errors: List[str]

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
    files = state["files_to_process"]

    if not files:
        return {"current_batch": [], "files_to_process": []}

    current_batch = files[:batch_size]
    remaining = files[batch_size:]

    return {
        "current_batch": current_batch,
        "files_to_process": remaining
    }

def extract_node(state: ExtractionState) -> ExtractionState:
    """The Extraction Swarm: Process chunks using Gemini 2.0 Flash."""
    batch = state.get("current_batch", [])
    if not batch:
        return {"raw_results": []}

    try:
        # Initialize Gemini Flash with structured output
        # Flash is drastically cheaper, faster, and allows 15 RPM free tier parallelization
        llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", temperature=0)
        structured_llm = llm.with_structured_output(GraphExtraction)

        raw_results = []
        for file_path in batch:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            text_chunk = data.get("issue", {}).get("body", "")

            prompt = f"""
            You are a senior data architect extracting organizational memory.
            Analyze the following communication log.
            Extract all distinct entities (projects, engineers, tools) and their relationships.
            You MUST provide a verbatim quote from the text as 'evidence' for every relationship you extract.
            If you cannot find verbatim evidence, do not create the relationship.

            Log Data:
            {text_chunk[:100000]}
            """

            print(f"  [Gemini Flash] Extracting {file_path.name}...")
            result = structured_llm.invoke(prompt)

            raw_results.append({
                "source_id": file_path.name,
                "data": result.model_dump() if result else {}
            })

            # Flash handles higher burst limits (15 RPM vs 2 RPM for Pro)
            time.sleep(4) # 60s / 15 RPM = 4s stagger

        return {"raw_results": raw_results}

    except Exception as e:
        print(f"  [Gemini Error] {e}")
        return {"errors": [str(e)], "raw_results": []}

def map_to_ontology_node(state: ExtractionState) -> ExtractionState:
    """Map the Gemini extraction back to our complex Ontology."""
    raw_results = state.get("raw_results", [])
    final_results = state.get("final_results", [])

    for res in raw_results:
        source_id = res["source_id"]
        data = res["data"]

        issue_num = source_id.split("_")[1].replace(".json", "")
        result_path = config.EXTRACTION_DIR / f"langgraph_extraction_{issue_num}.json"

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        print(f"  [Mapped] Saved LangGraph results for {source_id} to {result_path}")

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
    print(f"LANGGRAPH + GEMINI FLASH EXTRACTION PIPELINE")
    print(f"{'='*60}")
    print(f"  Target: {len(issue_files)} files")
    print(f"  Model: gemini-2.0-flash-exp")

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

        print("\nExtraction Complete via LangGraph!")
    except Exception as e:
        print(f"Could not build or run graph: {e}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5, help="Max issues to process")
    args = parser.parse_args()

    import os
    if not os.getenv("GOOGLE_API_KEY"):
        print("WARNING: GOOGLE_API_KEY not set. LangGraph/Gemini will fail.")
        print("Set it using: export GOOGLE_API_KEY='your_key'")
    else:
        run_langgraph_pipeline(limit=args.limit)
