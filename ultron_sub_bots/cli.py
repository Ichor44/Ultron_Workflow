#!/usr/bin/env python
"""
Ultron Sub-Bots CLI

Command-line interface for running scraping tasks.
"""

import argparse
import json
import sys
from typing import List

from ultron_sub_bots import (
    SubBotManager,
    ScrapeTask,
    CrawlTask,
    SearchTask,
    quick_scrape,
    quick_crawl,
    quick_search,
)


def cmd_scrape(args: argparse.Namespace) -> int:
    """Scrape URLs."""
    urls = args.urls
    if args.file:
        with open(args.file) as f:
            urls = [line.strip() for line in f if line.strip()]
    
    if not urls:
        print("Error: No URLs provided", file=sys.stderr)
        return 1
    
    formats = args.format.split(",") if args.format else ["markdown"]
    
    with SubBotManager(max_workers=args.workers) as manager:
        task = manager.create_scrape_task(
            urls=urls,
            name=args.name,
            formats=formats,
            only_main_content=not args.full_page,
            wait_for=args.wait,
        )
        results = manager.run(task)
        
        for r in results:
            if args.json:
                print(json.dumps(r.to_dict(), indent=2))
            else:
                print(f"Task: {r.task_id}")
                print(f"  Success: {r.success}")
                print(f"  URLs: {r.urls_processed}")
                print(f"  Duration: {r.duration_ms:.0f}ms")
                if r.error:
                    print(f"  Error: {r.error}")
    
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    """Crawl a website."""
    with SubBotManager(max_workers=args.workers) as manager:
        task = manager.create_crawl_task(
            url=args.url,
            name=args.name,
            max_depth=args.depth,
            limit=args.limit,
            include_paths=args.include.split(",") if args.include else None,
            exclude_paths=args.exclude.split(",") if args.exclude else None,
        )
        results = manager.run(task)
        
        for r in results:
            if args.json:
                print(json.dumps(r.to_dict(), indent=2))
            else:
                print(f"Task: {r.task_id}")
                print(f"  Success: {r.success}")
                print(f"  Pages: {r.urls_processed}")
                if r.error:
                    print(f"  Error: {r.error}")
    
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Search the web."""
    with SubBotManager(max_workers=args.workers) as manager:
        task = manager.create_search_task(
            query=args.query,
            name=args.name,
            num_results=args.num_results,
            search_type=args.type,
        )
        results = manager.run(task)
        
        for r in results:
            if args.json:
                print(json.dumps(r.to_dict(), indent=2))
            else:
                print(f"Task: {r.task_id}")
                print(f"  Success: {r.success}")
                print(f"  Results: {r.urls_processed}")
                if r.error:
                    print(f"  Error: {r.error}")
    
    return 0


def cmd_map(args: argparse.Namespace) -> int:
    """Map a website URLs."""
    with SubBotManager(max_workers=args.workers) as manager:
        task = manager.create_map_task(
            url=args.url,
            name=args.name,
            search=args.search,
            limit=args.limit,
        )
        results = manager.run(task)
        
        for r in results:
            if args.json:
                print(json.dumps(r.to_dict(), indent=2))
            else:
                print(f"Task: {r.task_id}")
                print(f"  Success: {r.success}")
                print(f"  URLs found: {r.urls_processed}")
                if r.error:
                    print(f"  Error: {r.error}")
    
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Run multiple tasks from a JSON file."""
    with open(args.file) as f:
        tasks_data = json.load(f)
    
    with SubBotManager(max_workers=args.workers) as manager:
        tasks = []
        for task_data in tasks_data:
            task_type = task_data.get("type", "scrape")
            
            if task_type == "scrape":
                task = manager.create_scrape_task(
                    urls=task_data["urls"],
                    name=task_data.get("name"),
                    formats=task_data.get("formats", ["markdown"]),
                    only_main_content=task_data.get("only_main_content", True),
                    wait_for=task_data.get("wait_for", 0),
                )
            elif task_type == "crawl":
                task = manager.create_crawl_task(
                    url=task_data["url"],
                    name=task_data.get("name"),
                    max_depth=task_data.get("max_depth", 3),
                    limit=task_data.get("limit", 50),
                )
            elif task_type == "search":
                task = manager.create_search_task(
                    query=task_data["query"],
                    name=task_data.get("name"),
                    num_results=task_data.get("num_results", 10),
                )
            elif task_type == "map":
                task = manager.create_map_task(
                    url=task_data["url"],
                    name=task_data.get("name"),
                    search=task_data.get("search", ""),
                    limit=task_data.get("limit", 1000),
                )
            else:
                print(f"Unknown task type: {task_type}", file=sys.stderr)
                continue
            
            tasks.append(task)
        
        results = manager.run(tasks)
        
        if args.json:
            print(json.dumps([r.to_dict() for r in results], indent=2))
        else:
            for r in results:
                print(f"Task: {r.task_id} - Success: {r.success} - URLs: {r.urls_processed}")
    
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ultron Sub-Bots - Parallel Web Scraping",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-w", "--workers", type=int, default=4,
        help="Max parallel workers (default: 4)"
    )
    parser.add_argument(
        "-j", "--json", action="store_true",
        help="Output results as JSON"
    )
    parser.add_argument(
        "--firecrawl-path", type=str,
        help="Path to Firecrawl CLI executable"
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # Scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape URLs")
    scrape_parser.add_argument("urls", nargs="*", help="URLs to scrape")
    scrape_parser.add_argument("-f", "--file", help="File with URLs (one per line)")
    scrape_parser.add_argument("-n", "--name", help="Task name")
    scrape_parser.add_argument("--format", default="markdown", help="Output format(s) comma-separated")
    scrape_parser.add_argument("--full-page", action="store_true", help="Include nav/footer")
    scrape_parser.add_argument("--wait", type=int, default=0, help="Wait for JS (ms)")
    
    # Crawl command
    crawl_parser = subparsers.add_parser("crawl", help="Crawl a website")
    crawl_parser.add_argument("url", help="Starting URL")
    crawl_parser.add_argument("-n", "--name", help="Task name")
    crawl_parser.add_argument("-d", "--depth", type=int, default=3, help="Max depth")
    crawl_parser.add_argument("-l", "--limit", type=int, default=50, help="Max pages")
    crawl_parser.add_argument("--include", help="Include paths (comma-separated)")
    crawl_parser.add_argument("--exclude", help="Exclude paths (comma-separated)")
    
    # Search command
    search_parser = subparsers.add_parser("search", help="Search the web")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("-n", "--name", help="Task name")
    search_parser.add_argument("-r", "--num-results", type=int, default=10, help="Number of results")
    search_parser.add_argument("-t", "--type", default="auto", choices=["auto", "fast", "deep"])
    
    # Map command
    map_parser = subparsers.add_parser("map", help="Map website URLs")
    map_parser.add_argument("url", help="Starting URL")
    map_parser.add_argument("-n", "--name", help="Task name")
    map_parser.add_argument("-s", "--search", default="", help="Search filter")
    map_parser.add_argument("-l", "--limit", type=int, default=1000, help="Max URLs")
    
    # Batch command
    batch_parser = subparsers.add_parser("batch", help="Run tasks from JSON file")
    batch_parser.add_argument("file", help="JSON file with task definitions")
    
    args = parser.parse_args()
    
    # Pass firecrawl path to manager via environment or kwargs
    if args.firecrawl_path:
        import os
        os.environ["FIRECRAWL_CLI_PATH"] = args.firecrawl_path
    
    commands = {
        "scrape": cmd_scrape,
        "crawl": cmd_crawl,
        "search": cmd_search,
        "map": cmd_map,
        "batch": cmd_batch,
    }
    
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())