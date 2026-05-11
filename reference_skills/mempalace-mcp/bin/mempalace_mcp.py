#!/usr/bin/env python3
import sys
import json
import subprocess
from pathlib import Path

# The MCP server command from MemPalace docs
MCP_COMMAND = ["python", "-m", "mempalace.mcp_server"]

def run():
    # We use subprocess to call the actual mcp_server which is installed in the user's env
    # Since it's an MCP server, it communicates via stdin/stdout
    try:
        process = subprocess.Popen(
            MCP_COMMAND,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # For the purpose of this skill wrapper in Claude Code, 
        # we are acting as a bridge. However, Claude Code skills 
        # usually expect to be invoked by name. 
        # Since I cannot easily make this a "real" MCP server that 
        # Claude Code automatically picks up without user config,
        # I will implement the logic here or provide a way for Claude 
        # to call it.
        
        # Actually, the best way is to create a script that Claude can 
        # execute via Bash which then behaves like the MCP server.
        pass
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)

if __name__ == "__main__":
    run()
