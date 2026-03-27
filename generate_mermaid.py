import json
from pathlib import Path

def generate_mermaid():
    graph_path = Path("c:/Layer10/data/graph.json")
    if not graph_path.exists():
        print("Graph not found")
        return
        
    with open(graph_path, "r", encoding="utf-8") as f:
        graph = json.load(f)
        
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    
    mermaid = ["graph TD;"]
    
    # Add nodes
    for n in nodes:
        nid = n["id"]
        # Sanitize for mermaid
        safe_id = nid.replace(":", "_").replace("-", "_").replace(" ", "_").replace(".", "_")
        
        name = n.get("name") or n.get("type", "Unknown")
        name = str(name).replace('"', "'")
        
        if n.get("_is_event"):
            # Diamond or square for claims
            claim_type = n.get("type", "Event")
            mermaid.append(f"    {safe_id}{{\"{claim_type}\"}}")
        else:
            # Circle or pill for entities
            ent_type = n.get("type", "Entity")
            mermaid.append(f"    {safe_id}([\"{ent_type}: {name}\"])")
            
    # Add edges
    for e in edges:
        src = e["_source"].replace(":", "_").replace("-", "_").replace(" ", "_").replace(".", "_")
        tgt = e["_target"].replace(":", "_").replace("-", "_").replace(" ", "_").replace(".", "_")
        edge_type = e.get("type", "RELATES_TO")
        
        mermaid.append(f"    {src} -- \"{edge_type}\" --> {tgt}")
        
    out_path = Path("c:/Layer10/graph_mermaid.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(mermaid))
        
    print(f"Mermaid generated at {out_path}")

if __name__ == "__main__":
    generate_mermaid()
