"""
Hybrid search for retrieval.

Combines BM25 keyword search with FAISS vector similarity
for finding relevant entities and claims.
"""
import numpy as np
from typing import Optional
from rank_bm25 import BM25Okapi

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from graph.memory_graph import MemoryGraph


class HybridSearch:
    """Hybrid keyword + vector search over the memory graph."""

    def __init__(self, graph: MemoryGraph):
        self.graph = graph
        self.embedder = None
        self.faiss_index = None
        self.index_keys = []
        self.index_texts = []
        self.bm25 = None
        self.bm25_corpus = []
        self.bm25_keys = []

    def _get_embedder(self):
        """Lazy-load the sentence transformer model."""
        if self.embedder is None:
            from sentence_transformers import SentenceTransformer
            self.embedder = SentenceTransformer(config.EMBEDDING_MODEL)
        return self.embedder

    def build_index(self):
        """Build both BM25 and FAISS indices from the graph."""
        texts = []
        keys = []

        # Index entity nodes
        for node_id, data in self.graph.backend.get_all_nodes():
            if data.get("_is_event"):
                continue  # Skip event nodes here, index them below
            name = data.get("name", "")
            aliases = " ".join(data.get("aliases", []))
            props = " ".join(str(v) for v in data.get("properties", {}).values())
            text = f"{name} {aliases} {props}".strip()
            if text:
                texts.append(text)
                keys.append(("entity", node_id))

        # Index reified event nodes (claims)
        for node_id, data in self.graph.backend.get_all_nodes():
            if not data.get("_is_event"):
                continue
            claim_type = data.get("type", "")
            props = " ".join(str(val) for val in data.get("properties", {}).values())
            evidence_list = data.get("evidence", [])

            for ev in evidence_list:
                excerpt = ev.get("excerpt", "") if isinstance(ev, dict) else ""
                text = f"{claim_type} {props} {excerpt}".strip()
                if text:
                    texts.append(text)
                    keys.append(("claim", data.get("id", node_id), node_id))

        if not texts:
            print("No texts to index.")
            return

        self.index_texts = texts
        self.index_keys = keys

        # Build BM25 index
        tokenized = [t.lower().split() for t in texts]
        self.bm25 = BM25Okapi(tokenized)
        self.bm25_corpus = tokenized
        self.bm25_keys = keys

        # Build FAISS index
        try:
            import faiss
            embedder = self._get_embedder()
            embeddings = embedder.encode(texts, show_progress_bar=True, batch_size=32)
            embeddings = np.array(embeddings).astype("float32")

            # Normalize for cosine similarity
            faiss.normalize_L2(embeddings)

            dim = embeddings.shape[1]
            self.faiss_index = faiss.IndexFlatIP(dim)  # Inner product = cosine on normalized
            self.faiss_index.add(embeddings)

            print(f"Search index built: {len(texts)} items, dim={dim}")
        except ImportError:
            print("FAISS not available, using BM25 only")
            self.faiss_index = None

    def search(self, query: str, top_k: int = 20, keyword_weight: float = 0.4) -> list[dict]:
        """
        Hybrid search combining BM25 and vector similarity.
        Returns ranked list of results with scores.
        """
        if not self.bm25 and not self.faiss_index:
            print("Index not built. Call build_index() first.")
            return []

        results_map = {}  # key → score

        # BM25 keyword search
        if self.bm25:
            query_tokens = query.lower().split()
            bm25_scores = self.bm25.get_scores(query_tokens)

            # Normalize BM25 scores
            max_score = max(bm25_scores) if max(bm25_scores) > 0 else 1
            for i, score in enumerate(bm25_scores):
                if score > 0:
                    key = str(self.bm25_keys[i])
                    normalized = score / max_score
                    results_map[key] = results_map.get(key, 0) + normalized * keyword_weight

        # Vector search
        if self.faiss_index:
            try:
                embedder = self._get_embedder()
                query_emb = embedder.encode([query]).astype("float32")
                import faiss
                faiss.normalize_L2(query_emb)

                scores, indices = self.faiss_index.search(query_emb, min(top_k * 2, len(self.index_texts)))

                for score, idx in zip(scores[0], indices[0]):
                    if idx >= 0 and idx < len(self.index_keys):
                        key = str(self.index_keys[idx])
                        results_map[key] = results_map.get(key, 0) + float(score) * (1 - keyword_weight)
            except Exception as e:
                print(f"Vector search error: {e}")

        # Build result list
        results = []
        for key_str, score in sorted(results_map.items(), key=lambda x: -x[1])[:top_k]:
            try:
                key_tuple = eval(key_str)
            except Exception:
                continue

            result = {"score": round(score, 4), "key": key_tuple}

            if key_tuple[0] == "entity":
                entity_key = key_tuple[1]
                entity_data = self.graph.get_entity(entity_key)
                if entity_data:
                    result["type"] = "entity"
                    result["data"] = entity_data
            elif key_tuple[0] == "claim":
                event_node_id = key_tuple[2]  # We indexed this as (claim, claim_id, event_node_id)
                if self.graph.backend.has_node(event_node_id):
                    result["type"] = "claim"
                    data = self.graph.backend.get_node(event_node_id)
                    data["_event_node"] = event_node_id
                    
                    # Find subject (incoming edge from non-event node)
                    for edge in self.graph.backend.get_in_edges(event_node_id):
                        source = edge["_source"]
                        if not self.graph.is_event_node(source):
                            data["_source"] = source
                            
                    # Find object (outgoing edge to non-event node)
                    for edge in self.graph.backend.get_out_edges(event_node_id):
                        target = edge["_target"]
                        if not self.graph.is_event_node(target):
                            data["_target"] = target
                            
                    result["data"] = data

            results.append(result)

        return results
