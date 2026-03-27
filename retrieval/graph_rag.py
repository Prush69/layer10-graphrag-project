"""
Deterministic GraphRAG Engine.

Implements multi-hop graph expansion starting from entities found via hybrid search.
No Cypher generation; uses deterministic traversal with confidence thresholds.
"""
from typing import Optional
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from graph.memory_graph import MemoryGraph
from retrieval.search import HybridSearch
from retrieval.context_pack import ContextPack, ContextPackBuilder
import math
from datetime import datetime

class GraphRAGEngine:
    """Deterministic GraphRAG via neighbor expansion."""
    
    def __init__(self, graph: MemoryGraph, search: HybridSearch):
        self.graph = graph
        self.search = search
        self.builder = ContextPackBuilder(graph)

    def _calculate_rank_score(self, item_data: dict, question_embedding=None) -> float:
        """
        Multi-signal ranking using the Memory Strength Formula.
        score = similarity + confidence + log(evidence_count) + authority_weight - decay_rate * age
        """
        import numpy as np
        from sklearn.metrics.pairwise import cosine_similarity
        
        # 1. Semantic Similarity
        sim_score = 0.0
        if question_embedding is not None and "embedding" in item_data:
            item_emb = np.array(item_data["embedding"]).reshape(1, -1)
            q_emb = np.array(question_embedding).reshape(1, -1)
            sim_score = float(cosine_similarity(q_emb, item_emb)[0][0])
        
        # 2. Confidence & Grounding
        confidence = float(item_data.get("confidence", 0.5))
        evidence_count = len(item_data.get("evidence", []))
        evidence_boost = math.log1p(evidence_count)
        
        # 3. Authority Weight
        authority_weight = float(item_data.get("authority_weight", 1.0))
        
        # 4. Decay & Age
        decay_rate = float(item_data.get("decay_rate", 0.01))
        age_days = 0.0
        timestamp = item_data.get("extracted_at") or item_data.get("valid_from")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                age_days = (datetime.utcnow() - dt).total_seconds() / 86400.0
            except:
                pass
        decay_penalty = decay_rate * age_days

        # Composite Score (Memory Strength + Relevance)
        # Memory Strength = confidence + evidence_boost + authority_weight - decay_penalty
        memory_strength = confidence + evidence_boost + authority_weight - decay_penalty
        
        # Final rank combines intrinsic strength with query relevance
        total_score = (sim_score * 2.0) + memory_strength
        return total_score

    def query(self, question: str, depth: int = 2, min_confidence: float = 0.4) -> dict:
        """
        Deterministic GraphRAG (5-Step Design):
        1. Entity Detection: NER & Embedding Search
        2. Entity Lookup: Mapping to Graph Nodes
        3. Graph Expansion: Multi-hop neighbor traversal
        4. Ranking Model: Memory Strength + Relevance
        5. Context Pack: Grounded assembly
        """
        print(f"[*] GraphRAG query: '{question}'")

        # Step 1 & 2: Entity Detection & Lookup
        q_emb = self.search.embedder.encode([question])[0] if self.search.embedder else None
        roots = self.search.search(question, top_k=5)
        
        seed_entities = []
        seed_claims = []
        for r in roots:
            if r["type"] == "entity":
                # Use data['id'] if available, otherwise fallback to the key from results
                eid = r["data"].get("id") or (r["key"][1] if isinstance(r["key"], tuple) else None)
                if eid:
                    seed_entities.append(eid)
            elif r["type"] == "claim":
                cid = r["data"].get("id") or (r["key"][1] if isinstance(r["key"], tuple) else None)
                if cid:
                    seed_claims.append(cid)

        # Step 3: Graph Expansion
        expanded_entities = set(seed_entities)
        expanded_claims = set(seed_claims)
        current_layer = set(seed_entities)
        
        for d in range(depth):
            next_layer = set()
            for entity_id in current_layer:
                claims = self.graph.get_claims_for(entity_id, include_historical=False)
                for c in claims:
                    if c.get("confidence", 0) >= min_confidence:
                        cid = c.get("id") or c.get("_event_node")
                        if cid:
                            expanded_claims.add(cid)
                        
                        target = c.get("_target") or c.get("object_id")
                        source = c.get("_source") or c.get("subject_id")
                        
                        neighbor = target if target != entity_id else source
                        if neighbor and neighbor not in expanded_entities:
                            expanded_entities.add(neighbor)
                            next_layer.add(neighbor)
            current_layer = next_layer

        # Step 4: Ranking Model
        results = []
        for eid in expanded_entities:
            data = self.graph.get_entity(eid)
            if data:
                score = self._calculate_rank_score(data, q_emb)
                results.append({"type": "entity", "key": eid, "data": data, "score": score})
        
        for cid in expanded_claims:
            # Re-fetch node data to get full attributes for ranking
            node_id = f"Event::{cid}" if not cid.startswith("Event::") else cid
            data = self.graph.backend.get_node(node_id)
            if data:
                score = self._calculate_rank_score(data, q_emb)
                # Ensure cid is just the base ID if we used the prefix
                clean_cid = cid.replace("Event::", "")
                results.append({"type": "claim", "key": clean_cid, "data": data, "score": score})

        results.sort(key=lambda x: x["score"], reverse=True)

        # Step 5: Context Pack Generation
        pack = self.builder.build(results[:20], question) # Limit to top 20 for pack focus
        return pack.to_dict()
