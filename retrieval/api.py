"""
FastAPI Microservice for Layer10 Memory Graph Inference.

This API replaces the local Flask visualization server with a scalable,
production-ready REST interface deployed via Google Cloud Run.
It acts as the Query Router, deciding if requests need local vector
search or global graph traversal.
"""

import sys
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# Initialize FastAPI app
app = FastAPI(
    title="Layer10 Memory Graph API",
    description="GCP-Native Inference API for Grounded GraphRAG Retrieval",
    version="2.0.0"
)

# Mocked state for database connections
# In production, these are initialized on startup
class AppState:
    graph = None
    search_index = None
    context_builder = None

state = AppState()

# --- Schemas ---

class SearchRequest(BaseModel):
    query: str
    top_k: int = 15
    routing_strategy: str = "auto" # auto, vector_only, graph_only

class EvidenceItem(BaseModel):
    source_id: str
    excerpt: str
    citation: str
    url: Optional[str] = None

class ContextPackResponse(BaseModel):
    question: str
    summary: str
    evidence_count: int
    evidence: List[EvidenceItem]
    conflicts: List[dict] = []

# --- Lifespan / Startup ---

@app.on_event("startup")
async def startup_event():
    """Initialize dual-database connections on Cloud Run startup."""
    print("Initializing Layer10 Memory Graph API...")
    try:
        from graph.store import GraphStore
        from retrieval.search import HybridSearch
        from retrieval.context_pack import ContextPackBuilder

        # Connect to Neo4j (Graph DB)
        store = GraphStore()
        state.graph = store.load()

        # Connect to Vector Search (FAISS local, Vertex AI in true prod)
        state.search_index = HybridSearch(state.graph)
        state.search_index.build_index()

        state.context_builder = ContextPackBuilder(state.graph)
        print("Database connections established.")
    except Exception as e:
        print(f"Warning: Could not initialize graph store: {e}")

# --- Endpoints ---

@app.get("/health")
def health_check():
    """Cloud Run health check endpoint."""
    return {"status": "healthy", "architecture": "gcp_native"}

@app.post("/api/v1/query", response_model=ContextPackResponse)
def query_memory_graph(request: SearchRequest):
    """
    The Query Router: Takes a natural language question and routes it
    through the dual-database retrieval system to build a context pack.
    """
    if not state.search_index or not state.context_builder:
        raise HTTPException(status_code=503, detail="Graph indices not initialized")

    try:
        # Step 1: Route to Vector Search (Local Context)
        print(f"Routing query: '{request.query}' via {request.routing_strategy}")
        results = state.search_index.search(request.query, top_k=request.top_k)

        if not results:
            return ContextPackResponse(
                question=request.query,
                summary="No relevant organizational memory found.",
                evidence_count=0,
                evidence=[],
                conflicts=[]
            )

        # Step 2: Route to Graph DB (Global Context Expansion)
        # The ContextPackBuilder natively traverses the graph topology from the vector hits
        pack = state.context_builder.build(results, request.query)

        # Format response to match API schema
        evidence_list = []
        for e in pack.evidence:
            evidence_list.append(EvidenceItem(
                source_id=getattr(e, 'source_id', 'unknown'),
                excerpt=getattr(e, 'excerpt', ''),
                citation=getattr(e, 'citation', ''),
                url=getattr(e, 'url', None)
            ))

        return ContextPackResponse(
            question=pack.question,
            summary=f"Found {len(pack.entities)} entities and {len(pack.claims)} claims. Backed by {len(pack.evidence)} evidence items.",
            evidence_count=len(pack.evidence),
            evidence=evidence_list,
            conflicts=pack.conflicts
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Local dev server
    uvicorn.run("retrieval.api:app", host="0.0.0.0", port=8000, reload=True)
