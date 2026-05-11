#!/usr/bin/env python3
import sys
import os
import json

# Use the venv's python to ensure we have access to mempalace
PYTHON_EXE = r"C:\Users\cereal\.claude\skills\mempalace-mcp\venv\Scripts\python.exe"

def main():
    if len(sys.argv) < 4:
        print("Usage: write_drawer.py <wing> <room> <content> [source_file]")
        sys.exit(1)

    wing = sys.argv[1]
    room = sys.argv[2]
    content = sys.argv[3]
    source_file = sys.argv[4] if len(sys.argv) > 4 else ""

    # We will call a tiny python script using the venv's python to do the actual work
    # This avoids dependency issues in our wrapper.
    script = f"""
import sys
from mempalace.palace import Palace # Assuming this is how to get the palace logic
from mempalace.config import MempalaceConfig

try:
    config = MempalaceConfig()
    # We need to find where the palace is. Usually it's in ~/.mempalace/palace
    # Or we can pass the path.
    palace_path = config.palace_path
    
    # Based on mempalace/mcp_server.py, the logic for adding a drawer is:
    # 1. Get collection
    # 2. Generate ID
    # 3. Upsert
    
    from mempalace.backends.chroma import ChromaBackend, ChromaCollection
    import hashlib
    from datetime import datetime

    client = ChromaBackend.make_client(palace_path)
    col = ChromaCollection(client.get_or_create_collection(config.collection_name, metadata={{"hnsw:space": "cosine"}}))
    
    drawer_id = f"drawer_{{wing}}_{{room}}_{{hashlib.sha256((wing + room + content).encode()).hexdigest()[:24]}}"
    
    col.upsert(
        ids=[drawer_id],
        documents=[content],
        metadatas=[
            {{
                "wing": wing,
                "room": room,
                "source_file": "{source_file}",
                "chunk_index": 0,
                "added_by": "claude_hook",
                "filed_at": datetime.now().isoformat(),
            }}
        ],
    )
    print(f"SUCCESS: {{drawer_id}}")
except Exception as e:
    print(f"ERROR: {{e}}")
    sys.exit(1)
"""
    # Actually, it's better to just use the existing mcp_server logic if possible, 
    # but since I can't easily run an MCP server and call it via CLI, 
    # let's write a more robust script that imports mempalace directly.

    subprocess.run([PYTHON_EXE, "-c", script])

if __name__ == "__main__":
    main()
