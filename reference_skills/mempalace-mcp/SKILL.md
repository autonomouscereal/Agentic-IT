---
name: mempalace-mcp
description: Use the legacy MemPalace MCP integration for targeted memory lookup or compatibility checks when the PostgreSQL agent-memory backend is not the right source.
---

# MemPalace MCP Skill

This skill allows Codex to interact with the MemPalace memory system via its MCP server. Use this to store, search, and manage your long-term verbatim memories.

## Usage

To use MemPalace, you must first ensure the MCP server is running or configured in your environment.

### 1. Initialization
Before starting a new project or session, initialize a palace for it:
`mempalace init <path_to_project>`

### 2. Core Operations

- **Storing Memories**: Use `mempalace_add_drawer` to file verbatim content into a specific wing (category) and room (topic). Always provide the exact words you want to remember.
- **Searching**: Use `mempalace_search` with keywords to find relevant verbatim snippets from your past conversations or project files.
- **Managing Relationships**: Use Knowledge Graph tools like `mempalace_kg_add`, `mempalace_kg_query`, and `mempalace_kg_invalidate` to maintain a structured map of entities and their evolving relationships.
- **Agent Diary**: Use `mempalace_diary_write` to record your own observations, thoughts, and task completions in AAAK format. This creates a personal journal wing for you.

### 3. Advanced Navigation & Structure

- **Taxonomy**: Use `mempalace_get_taxonomy` or `mempalace_list_wings` to understand how your memories are currently organized.
- **Graph Exploration**: Use `mempalace_traverse` to follow connections between different topics (rooms) and categories (wings).
- **Cross-Wing Connections**: Use `mempalace_create_tunnel` to explicitly link related ideas that live in different wings.

### 4. Maintenance & Status

- **Status Check**: Call `mempalace_status` to see an overview of your total memory count and organization.
- **Syncing**: If you've made changes outside of Codex (e.g., via the CLI), use `mempalace_reconnect`.

## Tool List Summary

| Tool | Description |
|---|---|
| `mempalace_status` | Palace overview (drawers, wings, rooms) |
| `mempalace_list_wings` | List all wings and drawer counts |
| `mempalace_list_rooms` | List rooms within a wing |
| `mempalace_get_taxonomy` | Full wing $\rightarrow$ room $\rightarrow$ count tree |
| `mempalace_search` | Semantic search for verbatim content |
| `mempalace_check_duplicate` | Check if content already exists |
| `mempalace_add_drawer` | File verbatim content into a wing/room |
| `mempalace_delete_drawer` | Remove a drawer by ID |
| `mempalace_get_drawer` | Fetch full content and metadata of a drawer |
| `mempalace_list_drawers` | Paginated list of drawers |
| `mempalace_update_drawer` | Update existing drawer content/metadata |
| `mempalace_kg_query` | Query the entity knowledge graph |
| `mempalace_kg_add` | Add a fact to the knowledge graph |
| `mempalace_kg_invalidate` | Mark a fact as no longer true |
| `mempalace_kg_timeline` | Get chronological timeline of facts |
| `mempalace_kg_stats` | Knowledge graph overview |
| `mempalace_traverse` | Walk the palace graph from a room |
| `mempalace_find_tunnels` | Find rooms bridging two wings |
| `mempalace_graph_stats` | Palace graph connectivity stats |
| `mempalace_create_tunnel` | Link two locations across wings |
| `mempalace_list_tunnels` | List all explicit tunnels |
| `mempalace_delete_tunnel` | Delete a tunnel by ID |
| `mempalace_follow_tunnels` | Follow connections from a room |
| `mempalace_diary_write` | Write an agent diary entry (AAAK format) |
| `mempalace_diary_read` | Read recent agent diary entries |
| `mempalace_reconnect` | Force cache invalidation/reconnect |

 Generated with [Codex](https://Codex.com/Codex)
