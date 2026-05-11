#!/usr/bin/env python3
import sys
import subprocess
import os

# The user confirmed that 'python' is the correct command and works in their environment.
# We will use 'python' directly as it is available in their shell.
PYTHON_CMD = "python"

def main():
    if len(sys.argv) < 2:
        print("Usage: mempalace_cli.py <command> [args...]")
        sys.exit(1)

    # The command is 'mempalace' as installed via pip, accessed via module
    cmd = [PYTHON_CMD, "-m", "mempalace"] + sys.argv[1:]
    
    try:
        # Set PYTHONIOENCODING to utf-8 to avoid UnicodeEncodeError on Windows
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            check=False, 
            env=env
        )
        
        if result.returncode == 0:
            print(result.stdout)
        else:
            # Print stderr to stdout so Claude can see the error clearly
            sys.stderr.write(f"Error (exit code {result.returncode}):\n{result.stderr}")
            sys.exit(result.returncode)

    except FileNotFoundError:
        print(f"Error: '{PYTHON_CMD}' command not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
