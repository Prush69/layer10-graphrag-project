import shutil
from pathlib import Path

def copy_mermaid():
    txt_path = Path("c:/Layer10/graph_mermaid.txt")
    md_path = Path("c:/Users/acer/.gemini/antigravity/brain/35c626ca-2de9-4fc0-8df7-e2916b12e4cf/issue_13991_graph.md")
    
    with open(txt_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Memory Graph for Issue #13991\n\n")
        f.write("This diagram proves the graph structure logic, including the auto-upserted Gaearon entity and all topological connections.\n\n")
        f.write("```mermaid\n")
        f.write(content)
        f.write("\n```\n")
        
if __name__ == "__main__":
    copy_mermaid()
