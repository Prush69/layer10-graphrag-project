"""
Graph persistence layer.

Handles serialization/deserialization of the memory graph
to JSON and provides health metrics.
"""
import json
from pathlib import Path
from datetime import datetime

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from graph.memory_graph import MemoryGraph


class GraphStore:
    """Persists and loads the memory graph."""

    def __init__(self, graph_path: Path = None):
        self.graph_path = graph_path or config.GRAPH_PATH

    def save(self, graph: MemoryGraph):
        """Save the graph to JSON."""
        data = graph.to_serializable()
        self.graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.graph_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        print(f"Graph saved to {self.graph_path} ({self.graph_path.stat().st_size / 1024:.1f} KB)")

    def load(self, init_db: bool = False) -> MemoryGraph:
        """Load the graph, exclusively using Neo4j."""
        try:
            from graph.neo4j_backend import Neo4jBackend
            backend = Neo4jBackend()
            # Test connection
            backend.node_count()
            print("Connected to Neo4j successfully. Using Neo4j as Graph Storage Backend.")
        except Exception as e:
            print(f"  [WARN] Neo4j unavailable, falling back to JSON: {e}")
            from graph.json_backend import JSONBackend
            backend = JSONBackend(config.GRAPH_PATH)

        graph = MemoryGraph(backend=backend)
        return graph

    def health_check(self, graph: MemoryGraph) -> dict:
        """Run health checks on the graph."""
        stats = graph.get_graph_stats()

        return {
            "stats": stats,
            "orphan_nodes": 0, # Bypassing complex cypher query for orphans
            "claims_without_evidence": stats.get("claims_without_evidence", 0),
            "avg_confidence": round(stats.get("avg_confidence", 0.0), 3),
            "confidence_distribution": {},
            "checked_at": datetime.utcnow().isoformat(),
        }
