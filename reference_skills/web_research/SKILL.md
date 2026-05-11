---
name: web_research
description: Perform general web searches and deep research using local SearXNG + curl_cffi + trafilatura. Supports categories, time filters, and engine selection. Use this for all non-torrent web research tasks. Can fetch full clean markdown content from any URL.
allowed-tools: Bash("C:/Users/cereal/.Codex/skills/web_research/venv/Scripts/python.exe" "C:/Users/cereal/.Codex/skills/web_research/web_research.py" "*" "--cat *" "--time *" "--url *")
---

# Web Research Skill

This skill provides a high-fidelity research interface for AI agents. It combines the meta-search power of SearXNG with stealthy, browser-impersonating fetches and industry-standard content extraction.

## Capabilities

- **Discovery**: Search via local SearXNG instance with support for multiple engines and categories.
- **Stealth Fetching**: Uses `curl_cffi` to impersonate modern browsers (Chrome), bypassing simple bot detection.
- **Clean Extraction**: Uses `trafilatura` to convert complex HTML into clean, boilerplate-free Markdown optimized for LLM consumption.
- **Deep Research**: Ability to fetch the full content of specific URLs found during search.

## Usage via Bash

The skill is executed through a dedicated virtual environment located in the skill directory.

### 1. General Web Search
Perform a standard search with optional category and time filters.
```bash
"C:/Users/cereal/.Codex/skills/web_research/venv/Scripts/python.exe" "C:/Users/cereal/.Codex/skills/web_research/web_research.py" "your search query" --cat general --time month
```

**Arguments:**
- `query`: The search term (string).
- `--cat`: Category (`general`, `images`, `video`, `news`). Default: `general`.
- `--engines`: Comma-separated list of SearXNG engines.
- `--time`: Time range (`day`, `month`, `year`).
- `--server`: Custom SearXNG URL (default: `http://192.168.50.222:7999`).

### 2. Deep Content Extraction (URL Fetch)
Extract the full, clean Markdown content of a specific webpage.
```bash
"C:/Users/cereal/.Codex/skills/web_research/venv/Scripts/python.exe" "C:/Users/cereal/.Codex/skills/web_research/web_research.py" --url "https://example.com"
```

**Arguments:**
- `--url`: The direct URL to extract content from.
- `--fetch`: (Optional) Used in conjunction with query if the query is a URL.
