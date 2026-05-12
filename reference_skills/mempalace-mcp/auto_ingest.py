#!/usr/bin/env python3
import sys
import json
import subprocess
import os

# Use the absolute path to the venv's python executable
PYTHON_EXE = r"C:\Users\cereal\.claude\skills\mempalace-mcp\venv\Scripts\python.exe"

def ingest(event_type, payload):
    """
    Ingests a single event into MemPalace using its internal logic via a small wrapper script.
    """
    if event_type == "PostToolUse":
        wing = "wing_agent"
        room = "tool_calls"
    elif event_type == "UserPromptSubmit":
        wing = "wing_user"
        room = "prompts"
    elif event_type == "Stop":
        wing = "wing_system"
        room = "session_end"
    else:
        wing = "wing_system"
        room = "events"

    # Prepare content for the wrapper
    content = json.dumps(payload)
    source_file = "claude_code_hook"

    # The wrapper script will use mempalace directly
    wrapper_script = f"""
import sys
import os
import json
import hashlib
from datetime import datetime

try:
    from mempalace.config import MempalaceConfig
    from mempalace.backends.chroma import ChromaBackend, ChromaCollection

    config = MempalaceConfig()
    # We need to handle the path carefully for the subprocess
    palace_path = config.palace_path

    backend = ChromaBackend()
    col = ChromaCollection(backend.get_collection(
        palace_path=palace_path,
        collection_name=config.collection_name,
        create=True
    ))

    wing = "{wing}"
    room = "{room}"
    content = {repr(content)}
    source_file = "{source_file}"

    drawer_id = f"drawer_{{wing}}_{{room}}_{{hashlib.sha256((wing + room + content).encode()).hexdigest()[:24]}}"

    metadata = {{
        "wing": wing,
        "room": room,
        "source_file": source_file,
        "chunk_index": 0,
        "added_by": "claude_hook",
        "filed_at": datetime.now().isoformat(),
    }}

    col.upsert(
        ids=[drawer_id],
        documents=[content],
        metadatas=[metadata]
    )
    print(f"SUCCESS: {{drawer_id}}")
except Exception as e:
    import traceback
    print(f"ERROR: {{e}}")
    traceback.print_exc()
    sys.exit(1)
"""

    # Execute the wrapper via the venv python
    cmd = [PYTHON_EXE, "-c", wrapper_script]

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        # Use Popen to fire and forget as requested by user's architecture (backgrounding)
        subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)

    event_type = sys.argv[1]
    payload_str = sys.argv[2]

    try:
        payload = json.loads(payload_str)
        ingest(event_type, payload)
    except Exception:
        # If not JSON, treat as raw string for the ingest logic if it were more flexible,
        # but here we'll just pass the error.
        ingest(event_type, payload_str)
