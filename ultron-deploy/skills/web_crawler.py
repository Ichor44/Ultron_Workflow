"""
Firecrawl Web Skill — unified scrape, search, crawl, and map via Firecrawl CLI.

Requires: firecrawl CLI installed (npm i -g firecrawl) and FIRECRAWL_API_KEY set.

Actions:
  scrape   — extract markdown/content from one or more URLs
  search   — search the web and optionally scrape results
  crawl    — bulk-extract all pages on a site (or section)
  map      — discover URLs on a website
  parse    — parse a local file (PDF, DOCX, HTML, etc.) to markdown
  status   — show auth status, concurrency, and credit usage
"""

import os
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any

NAME = "firecrawl"
DESCRIPTION = "Web scraping, search, crawling, and URL discovery via Firecrawl CLI. Handles JS-rendered pages, full-site crawls, structured extraction, and local file parsing."
PERMISSIONS: set = {"web_scrape"}
TRIGGERS = [
    "scrape", "crawl", "web crawl", "web scrape", "fetch page",
    "get webpage", "extract from url", "download webpage",
    "search web", "find articles", "research topic",
    "map site", "list urls", "sitemap",
    "parse pdf", "parse file", "firecrawl",
    "website content", "web search", "bulk extract",
]

_AGENT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIRECRAWL_DIR = os.path.join(_AGENT_ROOT, ".firecrawl")


def _find_firecrawl() -> str:
    """Find the firecrawl executable (handles Windows .cmd wrapper)."""
    for name in ["firecrawl", "firecrawl.cmd", "firecrawl.exe"]:
        path = shutil.which(name)
        if path:
            return path
    # Check common npm global path
    npm_global = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "npm", "firecrawl.cmd")
    if os.path.exists(npm_global):
        return npm_global
    return "firecrawl"


_FIRECRAWL_BIN = _find_firecrawl()


def _sanitize(text: str) -> str:
    """Sanitize text for safe console output on Windows (cp1252)."""
    return text.encode("ascii", errors="replace").decode("ascii")


def _run(args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a firecrawl CLI command."""
    cmd = [_FIRECRAWL_BIN] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=_AGENT_ROOT,
    )


def _ensure_dir():
    os.makedirs(_FIRECRAWL_DIR, exist_ok=True)


def _check_cli() -> Optional[str]:
    """Check firecrawl CLI is installed and authenticated. Returns error message or None."""
    try:
        result = _run(["--version"], timeout=10)
        if result.returncode != 0:
            return f"firecrawl CLI error: {result.stderr.strip()}"
    except FileNotFoundError:
        return (
            "firecrawl CLI not found. Install it with:\n"
            "  npm i -g firecrawl\n"
            "Then authenticate: firecrawl login"
        )
    except subprocess.TimeoutExpired:
        return "firecrawl CLI timed out."

    # Check auth
    result = _run(["--status"], timeout=30)
    if result.returncode != 0:
        return f"firecrawl auth check failed: {result.stderr.strip()}"

    return None


# ── Scrape ──────────────────────────────────────────────────────────────────


def _scrape(
    urls: List[str],
    format: str = "markdown",
    only_main_content: bool = True,
    wait_for: int = 0,
    query: str = "",
    output: str = "",
    json_output: bool = False,
    wait: bool = True,
    **kwargs,
) -> str:
    """Scrape one or more URLs."""
    _ensure_dir()

    out_path = output or os.path.join(_FIRECRAWL_DIR, "scrape-result.md")

    args = ["scrape"] + urls
    args += ["-f", format]
    if only_main_content:
        args.append("--only-main-content")
    if wait_for:
        args += ["--wait-for", str(wait_for)]
    if query:
        args += ["--query", query]
    if json_output:
        args += ["--json", "--pretty"]
    args += ["-o", out_path]

    result = _run(args, timeout=120)

    if result.returncode != 0:
        return _sanitize(f"Scrape failed: {result.stderr.strip()}")

    # Read output file
    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
        if not content.strip():
            return "Scrape returned empty content."
        # For single URL, return content directly
        if len(urls) == 1 and not json_output:
            return _sanitize(content)
        return _sanitize(f"Scraped {len(urls)} URL(s). Output saved to: {out_path}\n\n{content[:2000]}")
    else:
        # Fallback to stdout
        return _sanitize(result.stdout.strip()) or "Scrape completed (no output file written)."


# ── Search ──────────────────────────────────────────────────────────────────


def _search(
    query: str,
    scrape_results: bool = False,
    limit: int = 5,
    sources: str = "",
    categories: str = "",
    output: str = "",
    **kwargs,
) -> str:
    """Search the web via Firecrawl."""
    _ensure_dir()

    out_path = output or os.path.join(_FIRECRAWL_DIR, "search-result.json")

    args = ["search", query]
    args += ["--limit", str(limit)]
    if scrape_results:
        args.append("--scrape")
    if sources:
        args += ["--sources", sources]
    if categories:
        args += ["--categories", categories]
    args += ["-o", out_path, "--json"]

    result = _run(args, timeout=120)

    if result.returncode != 0:
        return f"Search failed: {result.stderr.strip()}"

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract results from response
        results = []
        if isinstance(data, dict):
            inner = data.get("data", data)
            if isinstance(inner, dict):
                results = inner.get("web", inner.get("results", inner.get("developer", [])))
                # Also check developer results
                dev_results = inner.get("developer", [])
            else:
                results = inner if isinstance(inner, list) else []
                dev_results = []
        elif isinstance(data, list):
            results = data
            dev_results = []

        if not results and not dev_results:
            return f"No results for '{query}'. Response: {json.dumps(data)[:300]}"

        lines = []
        if results:
            lines.append(f"Web results for '{query}' ({len(results)} found):\n")
            for i, r in enumerate(results[:limit], 1):
                title = r.get("title", "(no title)")
                url = r.get("url", "")
                desc = r.get("description", r.get("snippet", ""))
                lines.append(f"{i}. {title}")
                lines.append(f"   URL: {url}")
                if desc:
                    lines.append(f"   {desc[:200]}")
                lines.append("")

        if dev_results:
            lines.append(f"\nDeveloper results ({len(dev_results)} found):\n")
            for i, r in enumerate(dev_results[:limit], 1):
                title = r.get("title", "(no title)")
                url = r.get("url", "")
                desc = r.get("description", r.get("snippet", ""))
                lines.append(f"{i}. {title}")
                lines.append(f"   URL: {url}")
                if desc:
                    lines.append(f"   {desc[:200]}")
                lines.append("")

        # Show credits used
        credits = data.get("creditsUsed") if isinstance(data, dict) else None
        if credits:
            lines.append(f"\nCredits used: {credits}")

        return _sanitize("\n".join(lines))
    return _sanitize(result.stdout.strip()) or "Search completed."


# ── Crawl ───────────────────────────────────────────────────────────────────


def _crawl(
    url: str,
    limit: int = 50,
    max_depth: int = 3,
    include_paths: str = "",
    exclude_paths: str = "",
    wait: bool = True,
    output: str = "",
    **kwargs,
) -> str:
    """Crawl a website."""
    _ensure_dir()

    out_path = output or os.path.join(_FIRECRAWL_DIR, "crawl-result.json")

    args = ["crawl", url]
    args += ["--limit", str(limit)]
    args += ["--max-depth", str(max_depth)]
    if include_paths:
        args += ["--include-paths", include_paths]
    if exclude_paths:
        args += ["--exclude-paths", exclude_paths]
    if wait:
        args.append("--wait")
    args += ["-o", out_path, "--pretty"]

    result = _run(args, timeout=300)

    if result.returncode != 0:
        return _sanitize(f"Crawl failed: {result.stderr.strip()}")

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle crawl response format
        if isinstance(data, dict):
            pages = data.get("data", [])
            total = data.get("total", len(pages))
            completed = data.get("completed", len(pages))
            status = data.get("status", "")
        elif isinstance(data, list):
            pages = data
            total = len(pages)
            completed = len(pages)
            status = ""
        else:
            pages = []
            total = 0
            completed = 0
            status = ""

        return _sanitize(
            f"Crawl {status}: {completed}/{total} pages extracted from {url}\n"
            f"Output saved to: {out_path}"
        )
    return _sanitize(result.stdout.strip()) or "Crawl completed."


# ── Map ─────────────────────────────────────────────────────────────────────


def _map(
    url: str,
    limit: int = 100,
    search: str = "",
    output: str = "",
    **kwargs,
) -> str:
    """Map URLs on a website."""
    _ensure_dir()

    out_path = output or os.path.join(_FIRECRAWL_DIR, "map-result.json")

    args = ["map", url]
    args += ["--limit", str(limit)]
    if search:
        args += ["--search", search]
    args += ["-o", out_path, "--json", "--pretty"]

    result = _run(args, timeout=120)

    if result.returncode != 0:
        return _sanitize(f"Map failed: {result.stderr.strip()}")

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Handle different response formats
        urls = []
        if isinstance(data, dict):
            inner = data.get("data", data)
            if isinstance(inner, dict):
                links = inner.get("links", inner.get("urls", inner.get("results", [])))
                if links and isinstance(links[0], dict):
                    # Map format: [{"url": ..., "title": ..., "description": ...}]
                    urls = links
                elif links:
                    urls = [{"url": u, "title": "", "description": ""} for u in links]
            elif isinstance(inner, list):
                if inner and isinstance(inner[0], dict):
                    urls = inner
                else:
                    urls = [{"url": u, "title": "", "description": ""} for u in inner]
        elif isinstance(data, list):
            if data and isinstance(data[0], dict):
                urls = data
            else:
                urls = [{"url": u, "title": "", "description": ""} for u in data]

        if not urls:
            return f"No URLs mapped for {url}."

        lines = [f"Mapped {len(urls)} URLs on {url}:\n"]
        for u in urls[:50]:
            if isinstance(u, dict):
                url_str = u.get("url", "")
                title = u.get("title", "")
                line = f"  - {url_str}"
                if title:
                    line += f" ({title[:60]})"
                lines.append(line)
            else:
                lines.append(f"  - {u}")
        if len(urls) > 50:
            lines.append(f"  ... and {len(urls) - 50} more")
        return _sanitize("\n".join(lines))
    return _sanitize(result.stdout.strip()) or "Map completed."


# ── Parse local file ────────────────────────────────────────────────────────


def _parse(
    file_path: str,
    output: str = "",
    **kwargs,
) -> str:
    """Parse a local file (PDF, DOCX, HTML, etc.) to markdown."""
    _ensure_dir()

    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    out_path = output or os.path.join(_FIRECRAWL_DIR, "parse-result.md")

    args = ["parse", file_path, "-o", out_path]

    result = _run(args, timeout=120)

    if result.returncode != 0:
        return _sanitize(f"Parse failed: {result.stderr.strip()}")

    if os.path.exists(out_path):
        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()
        return _sanitize(content)
    return _sanitize(result.stdout.strip()) or "Parse completed."


# ── Status ──────────────────────────────────────────────────────────────────


def _status(**kwargs) -> str:
    """Show Firecrawl CLI status."""
    result = _run(["--status"], timeout=30)
    if result.returncode != 0:
        return f"Status check failed: {result.stderr.strip()}"
    # Strip ANSI escape codes and sanitize for console
    out = result.stdout.strip()
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)  # ANSI color codes
    # Replace emoji/symbols with ASCII equivalents
    replacements = {"🔥": "", "●": "*", "◐": "o"}
    for old, new in replacements.items():
        out = out.replace(old, new)
    # Remove any remaining non-ASCII
    out = out.encode("ascii", errors="replace").decode("ascii")
    return out


# ── Main entry point ────────────────────────────────────────────────────────


def run(
    action: str = "scrape",
    url: str = "",
    urls: List[str] = None,
    query: str = "",
    search: str = "",
    limit: int = 50,
    max_depth: int = 3,
    format: str = "markdown",
    only_main_content: bool = True,
    wait_for: int = 0,
    scrape_results: bool = False,
    include_paths: str = "",
    exclude_paths: str = "",
    sources: str = "",
    categories: str = "",
    file_path: str = "",
    output: str = "",
    json_output: bool = False,
    wait: bool = True,
    status: bool = False,
    **kwargs,
) -> str:
    """
    Unified Firecrawl web skill.

    Actions:
      scrape  — extract content from URL(s)
      search  — search the web
      crawl   — bulk-extract all pages on a site
      map     — discover URLs on a website
      parse   — parse a local file to markdown
      status  — show auth/credits status

    Common args:
      url(s)  — target URL(s) for scrape/crawl/map
      query   — search query (search) or question about page (scrape --query)
      action  — which operation to perform
    """
    # Check CLI
    err = _check_cli()
    if err:
        return f"Firecrawl not ready:\n{err}"

    action = action.lower().strip()

    if action == "status":
        return _status()

    if action == "scrape":
        all_urls = urls or []
        if url:
            all_urls = [url] + all_urls
        if not all_urls:
            return "Provide url= or urls= to scrape."
        return _scrape(
            urls=all_urls,
            format=format,
            only_main_content=only_main_content,
            wait_for=wait_for,
            query=query,
            output=output,
            json_output=json_output,
            wait=wait,
        )

    if action == "search":
        if not query:
            return "Provide a query to search for."
        return _search(
            query=query,
            scrape_results=scrape_results,
            limit=limit,
            sources=sources,
            categories=categories,
            output=output,
        )

    if action == "crawl":
        if not url:
            return "Provide a url to crawl."
        return _crawl(
            url=url,
            limit=limit,
            max_depth=max_depth,
            include_paths=include_paths,
            exclude_paths=exclude_paths,
            wait=wait,
            output=output,
        )

    if action == "map":
        if not url:
            return "Provide a url to map."
        return _map(url=url, limit=limit, search=search, output=output)

    if action == "parse":
        target = file_path or url
        if not target:
            return "Provide a file_path or url to parse."
        return _parse(file_path=target, output=output)

    return f"Unknown action '{action}'. Use: scrape, search, crawl, map, parse, status"


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 2:
        print(run(action=sys.argv[1], url=sys.argv[2]))
    elif len(sys.argv) > 1:
        if sys.argv[1] == "status":
            print(run(action="status"))
        else:
            print(run(action="scrape", url=sys.argv[1]))
    else:
        print("Usage: firecrawl <action> <url-or-query>")
        print("Actions: scrape, search, crawl, map, parse, status")
