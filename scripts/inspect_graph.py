import json
from pathlib import Path

def inspect():
    graph_path = Path("data/graph.json")
    if not graph_path.exists():
        print("Graph not found")
        return
        
    with open(graph_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))
    id_to_key = data.get("_id_to_key", {})
    
    print(f"Total Nodes: {len(nodes)}")
    print(f"Total Links: {len(links)}")
    print(f"Mappable IDs: {len(id_to_key)}")
    
    # Check brunolemos
    print("\nSearch for brunolemos:")
    for n in nodes:
        if "brunolemos" in n.get("id", "").lower():
            print(f" Node: {n['id']}")
            
    print("\nEdges for Person::person::brunolemos:")
    count = 0
    for l in links:
        if l["source"] == "Person::person::brunolemos" or l["target"] == "Person::person::brunolemos":
            print(f" Link: {l['source']} --[{l.get('type')}]--> {l['target']}")
            count += 1
    print(f" Total: {count}")

    # Check some event nodes
    print("\nSample Event Nodes and their edges:")
    event_nodes = [n["id"] for n in nodes if n.get("_is_event")][:3]
    for en in event_nodes:
        print(f" Event: {en}")
        for l in links:
            if l["source"] == en or l["target"] == en:
                 print(f"   Edge: {l['source']} -> {l['target']}")

if __name__ == "__main__":
    inspect()
