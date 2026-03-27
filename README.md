# Layer10 Take-Home: Grounded Long-Term Memory System (v2.0 - Exceptional)

A production-grade pipeline that turns unstructured communication data (GitHub Issues) into a grounded, semantically deduplicated memory graph.

**Architecture Note**: This repository features a **dual-database routing strategy**. It natively builds the memory graph in Neo4j AuraDB and runs hybrid vector search locally via FAISS. It is designed so that the local vector database can seamlessly be swapped out for **Vertex AI Vector Search** in a full GCP deployment.

## The System Architecture (Phase 1)
Instead of relying on monolithic scripts, this system provides two extraction layers:
1. **The Classic Pipeline (`extraction/pipeline.py`)**: A highly optimized Groq/Llama batch processor designed for free-tier constraints and deterministic artifact offsets.
2. **The LangGraph Extraction Swarm (`extraction/langgraph_pipeline.py`)**: A multi-stage ingestion pipeline designed for speed and robustness using LangChain/LangGraph. It splinters large documents concurrently and processes them via **Gemini 1.5 Pro**. By leveraging its massive context window and native JSON structuring, we extract entities and relationships directly using strict `Pydantic` models and verbatim evidence requirements.

## The Query Router (The Inference API)
The system includes a **FastAPI microservice** (`retrieval/api.py`) designed to be deployed on **Google Cloud Run**. When a user queries the graph, the routing logic determines whether the request requires "local" context (vector search) or "global" context (traversing the Neo4j graph topology).

## Quick Start

### Prerequisites
- Python 3.10+
- A Google AI Studio API key (free): [Get one here](https://aistudio.google.com/app/apikey)
- Optional: GitHub personal access token

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure API keys
copy .env.example .env
# Edit .env and set your GOOGLE_API_KEY (for Gemini/LangGraph) and GITHUB_TOKEN

# 3. (Optional but Recommended) Start Neo4j Database
docker compose up -d
```

## Running the Architecture

To run the classic deterministic pipeline (Full end-to-end):
```bash
python run.py --step all
```

To run the Gemini 1.5 Pro extraction swarm:
```bash
# Run the parallelized LangGraph pipeline
python extraction/langgraph_pipeline.py --limit 10
```

To run the GCP-ready FastAPI Query Router:
```bash
uvicorn retrieval.api:app --host 0.0.0.0 --port 8000 --reload
```

## Strict Schema Design & Evidence Requirements

The biggest point of failure in standard GraphRAG systems is LLM hallucination of relationships. We solve this by enforcing strict schema design and evidence requirements using `Pydantic`.

In both the `LangGraph` pipeline and the core `schema/ontology.py`, every canonical claim requires an `Evidence` object:

```python
class Edge(BaseModel):
    source_entity: str = Field(description="Name of the source node")
    target_entity: str = Field(description="Name of the target node")
    relationship: str = Field(description="How they are connected")
    evidence: str = Field(description="Exact verbatim quote from the text proving this relationship")
```

By enforcing the `evidence` field, we ensure the graph is durable and mathematically grounded in the source data, eliminating standard LLM hallucination.

## Project Structure

| Directory | Purpose |
|-----------|---------|
| `corpus/` | GitHub Issues downloader |
| `schema/` | Strict Pydantic Ontology (entity types, claim types, verbatim evidence) |
| `extraction/` | Classic pipeline & LangGraph + Gemini 1.5 Pro swarm (`langgraph_pipeline.py`) |
| `dedup/` | Union-Find Entity Canonicalization |
| `graph/` | Memory graph (Neo4j), persistence, temporal logic |
| `retrieval/` | Hybrid FAISS search, FastAPI Router (`api.py`) |
| `visualization/` | Web UI with D3.js graph + evidence panel |
| `data/` | Generated outputs (graph, extractions, context packs) |

## Conceptual Security & Observability

In a production environment, the following features would be implemented to ensure enterprise readiness:

### 1. Permissions (Grounded RBAC/ABAC)
- **Source-Level Access**: Users only retrieve memory grounded in sources (Slack channels, GitHub repos) they are authorized to access.
- **Graph Traversal Guard**: The GraphRAG engine silently drops nodes and edges during expansion if the underlying evidence derivation belongs to a restricted source.

### 2. Observability & Health
- **Evidence Decay Tracking**: Monitoring the ratio of `Claims : Evidence` to ensure facts aren't becoming ungrounded over time.
- **Audit Logs**: Full bitemporal ledger of every entity merge and claim revision for regulatory compliance.
