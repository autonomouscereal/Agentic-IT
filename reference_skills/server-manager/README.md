# Server Manager Skill

A comprehensive CLI-based skill for managing SSH connections to Media and AI servers. This skill provides interactive shell sessions, server documentation, and connectivity testing capabilities.

## Overview

This skill enables seamless interaction with two remote servers:

| Server | IP Address | Purpose |
|--------|------------|---------|
| **Media Server** | 127.0.0.1 | Media streaming, storage, content delivery |
| **AI Server** | 127.0.0.1 | AI/ML workloads, inference services, model deployment |

## Environment Variables

Credentials are resolved by `credman.py` from the encrypted vault first, then
from environment variables when explicitly configured. Do not store plaintext
passwords in scripts, docs, or repo files.

```bash
python "C:/Users/me/.agents/skills/server-manager/credman.py" set ai "<from secure handoff>"
python "C:/Users/me/.agents/skills/server-manager/credman.py" set media "<from secure handoff>"
```

## Commands

### Interactive SSH Sessions

| Command | Description |
|---------|-------------|
| `server.sh media` | Connect to Media Server interactively |
| `server.sh ai` | Connect to AI Server interactively |
| `server.sh all` | Test both servers and display overview |

### Utility Commands

| Command | Description |
|---------|-------------|
| `server.sh notes [server]` | View server documentation/notes |
| `server.sh status` | Display server configuration overview |
| `server.sh test <server>` | Run connectivity diagnostics |
| `server.sh --command "<cmd>"` | Execute command on remote servers |

## Usage Examples

### Connect to Media Server
```bash
# Interactive SSH session
server.sh media

# With a specific command
server.sh media --command "df -h && systemctl status"
```

### Connect to AI Server
```bash
# Interactive SSH session
server.sh ai

# With GPU monitoring
server.sh ai --command "nvidia-smi && docker ps"
```

### Test Both Servers
```bash
# Comprehensive connection test
server.sh all

# Execute commands on both servers
server.sh all --command "hostname && uptime"
```

### View Server Documentation
```bash
# View all server notes
server.sh notes

# View specific server documentation
server.sh notes media
server.sh notes ai
```

## File Structure

```
.agents/skills/server-manager/
|-- README.md              # This documentation file
|-- server.sh              # Main entry point script
|-- ssh-servers.sh         # Core SSH management logic
|-- quick-ssh.sh           # Quick connection wrapper
`-- notes/
    |-- media-server.md    # Media Server documentation
    `-- ai-server.md       # AI Server documentation
```

## Features

### 1. Interactive Shell Sessions
- Password-based authentication using environment variables
- Full terminal support for command-line workflows
- Seamless transition between local and remote environments

### 2. Server Documentation
- Pre-configured notes for each server
- Common commands and maintenance tasks
- Service configuration details

### 3. Connectivity Testing
- Automated SSH connection verification
- Remote command execution
- Status reporting with color-coded output

## Quick Start

1. **Verify Environment Variables:**
   ```bash
   echo $media_server_password
   echo $ai_server_password
   ```

2. **Test Server Connections:**
   ```bash
   server.sh test all
   ```

3. **Start Interactive Session:**
   ```bash
   server.sh media    # or server.sh ai
   ```

## Troubleshooting

### Connection Issues
If SSH connections fail, verify:
- Environment variables are set correctly
- Network connectivity to server IPs
- Firewall rules allow port 22 access

### Password Authentication
The skill uses password authentication. If passwords change, update the environment variables accordingly.

## Author
Created for Cyril Blyseth - Server Management Workflow
