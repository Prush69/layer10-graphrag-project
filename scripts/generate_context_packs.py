import os
import sys
from pathlib import Path

# Add project root to path
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(root)
os.chdir(root) # Ensure relative paths in logic work

from graph.store import GraphStore
from retrieval.search import HybridSearch
from retrieval.context_pack import ContextPackBuilder

def generate():
    print("Loading graph...")
    store = GraphStore()
    graph = store.load()
    
    print("Building search index...")
    search = HybridSearch(graph)
    search.build_index()
    
    builder = ContextPackBuilder(graph)
    
    queries = [
        "What are the problems with multiple instances of React and Hooks?",
        "Who is brunolemos and what did they propose?",
        "What labels are associated with Component: Hooks?",
        "Is there any design proposal for the error message?"
    ]
    
    # Ensure directory exists
    os.makedirs("data/context_packs", exist_ok=True)
    
    for q in queries:
        print(f"\nProcessing query: {q}")
        results = search.search(q, top_k=10)
        pack = builder.build(results, q)
        
        # Save
        builder.save_pack(pack)
        
    print("\n[OK] Context packs generated in data/context_packs")

if __name__ == "__main__":
    generate()
