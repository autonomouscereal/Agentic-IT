import sys
import io

# Force UTF-8 encoding for stdout/stderr to prevent Windows UnicodeEncodeError
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

import argparse
import json
import os
from typing import List, Optional, Dict, Any

# Try to import the research libraries
try:
    import requests
    from curl_cffi import requests as curl_requests
    import trafilatura
except ImportError as e:
    print(f"[Error] Missing dependency: {e}. Please ensure the virtual environment is active.")
    sys.exit(1)

# Configuration
DEFAULT_SEARXNG_URL = "http://192.168.50.222:7999"

class WebResearchTool:
    def __init__(self, searxng_url: str):
        self.searxng_url = searxng_url

    def search(self, query: str, categories: str = "general", engines: Optional[List[str]] = None,
               time_range: Optional[str] = None, timeout: int = 15) -> List[Dict[str, Any]]:
        """Search via SearXNG API."""
        params = {
            "q": query,
            "categories": categories,
            "format": "json"
        }
        if engines:
            params["engines"] = ",".join(engines)
        if time_range:
            params["time_range"] = time_range

        try:
            response = requests.get(self.searxng_url, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json().get("results", [])
        except Exception as e:
            print(f"[SearXNG Error] {e}", file=sys.stderr)
            return []

    def fetch_content(self, url: str) -> Optional[str]:
        """Fetch page content using curl_cffi to bypass basic bot detection and extract markdown."""
        try:
            # Use curl_cffi with a browser impersonation for stealthier fetching
            response = curl_requests.get(url, impersonate="chrome110", timeout=20)
            response.raise_for_status()
            html = response.text

            if not html:
                return None

            # Use trafilatura to extract the main content as clean markdown
            content = trafilatura.extract(html, output_format="markdown", include_links=True, include_images=False)
            return content
        except Exception as e:
            print(f"[Fetch Error] {url}: {e}", file=sys.stderr)
            return None

    def run_search_flow(self, query: str, categories: str = "general", engines: Optional[List[str]] = None,
                        time_range: Optional[str] = None, fetch_full: bool = False) -> str:
        """Orchestrates search and optional content extraction."""
        results = self.search(query, categories, engines, time_range)

        if not results:
            return "No results found."

        output_lines = []
        output_lines.append(f"### Search Results for: {query}")
        output_lines.append(f"Found {len(results)} results.\n")

        for i, res in enumerate(results):
            title = res.get("title", "No Title")
            url = res.get("url", "")
            snippet = res.get("content", "").strip() or res.get("description", "")
            engine = res.get("engine", "unknown")

            output_lines.append(f"#### [{i+1}] {title}")
            output_lines.append(f"- **URL**: {url}")
            output_lines.append(f"- **Engine**: {engine}")
            if snippet:
                output_lines.append(f"- **Snippet**: {snippet}")

            if fetch_full and url:
                 output_lines.append("- *[Content extraction requested via --fetch flag]*")

            output_lines.append("")

        return "\n".join(output_lines)

    def fetch_single_url(self, url: str) -> str:
        """Directly fetch and return markdown content of a single URL."""
        content = self.fetch_content(url)
        if content:
            return f"### Content from {url}\n\n{content}"
        else:
            return f"Failed to extract content from {url}"

def main():
    parser = argparse.ArgumentParser(description="Web Research Tool for AI Agents")
    parser.add_argument("query", nargs="?", help="Search query or URL to fetch")
    parser.add_argument("--cat", default="general", help="Category (general, images, video, news, etc.)")
    parser.add_argument("--engines", help="Comma-separated list of engines")
    parser.add_argument("--time", help="Time range (day, month, year)")
    parser.add_argument("--fetch", action="store_true", help="If query is a URL, fetch its markdown content.")
    parser.add_argument("--url", help="Specific URL to fetch content from")
    parser.add_argument("--server", default=DEFAULT_SEARXNG_URL, help="SearXNG server URL")

    args = parser.parse_args()
    tool = WebResearchTool(args.server)

    # If --url is provided or if --fetch is used on a string that looks like a URL
    if args.url:
        print(tool.fetch_single_url(args.url))
    elif args.fetch and args.query and (args.query.startswith("http://") or args.query.startswith("https://")):
        print(tool.fetch_single_url(args.query))
    elif args.query:
        engines = [e.strip() for e in args.engines.split(",")] if args.engines else None
        print(tool.run_search_flow(args.query, categories=args.cat, engines=engines, time_range=args.time, fetch_full=args.fetch))
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
