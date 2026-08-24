# Ultron Sub-Bots

A parallel web scraping system built on Firecrawl that allows you to run multiple scraping operations concurrently using "sub-bots" - specialized workers for different scraping tasks.

## Features

- **Parallel Execution**: Run multiple scraping tasks concurrently with configurable worker pools
- **Specialized Sub-Bots**: Pre-built bots for scraping, crawling, searching, mapping, interacting, monitoring, and downloading
- **Flexible Task System**: Create tasks with rich parameters and metadata
- **Event Callbacks**: Hook into task lifecycle events (started, completed, failed)
- **Async Support**: Full async/await support for integration with async applications
- **Workflow Engine**: Chain multi-step operations (search → scrape → extract)
- **Firecrawl Integration**: Uses Firecrawl CLI for reliable, JS-capable scraping

## Installation

```bash
# Install Firecrawl CLI (required)
npm install -g firecrawl

# Or use the local installation
# The system will use `firecrawl` from PATH
```

## Quick Start

```python
from ultron_sub_bots import SubBotManager, quick_scrape, quick_crawl, quick_search

# Simplest usage - quick functions
results = quick_scrape("https://example.com")
results = quick_crawl("https://docs.python.org/3/", max_depth=2, limit=20)
results = quick_search("latest AI news", num_results=10)

# Or use the manager for more control
with SubBotManager(max_workers=4) as manager:
    # Scrape multiple URLs in parallel
    task = manager.create_scrape_task([
        "https://example.com",
        "https://httpbin.org/html",
        "https://httpbin.org/json",
    ])
    results = manager.run(task)
    
    # Crawl a website section
    task = manager.create_crawl_task(
        "https://docs.python.org/3/",
        max_depth=2,
        limit=50,
        include_paths=["/3/tutorial/"],
    )
    results = manager.run(task)
    
    # Search the web
    task = manager.create_search_task("Firecrawl web scraping", num_results=10)
    results = manager.run(task)
```

## Sub-Bot Types

| Bot Type | Purpose | Task Type |
|----------|---------|-----------|
| `ScrapeBot` | Scrape individual URLs | `scrape`, `extract` |
| `CrawlBot` | Crawl entire sites/sections | `crawl` |
| `SearchBot` | Web search with content | `search` |
| `MapBot` | Discover all URLs on a site | `map` |
| `InteractBot` | Browser interaction (clicks, forms) | `interact` |
| `MonitorBot` | Watch for changes | `monitor` |
| `DownloadBot` | Download site as local files | `download` |

## Parallel Execution

The system uses a thread pool for parallel execution. Each sub-bot can handle multiple URLs concurrently (Firecrawl handles this natively), and multiple sub-bots run in parallel via the thread pool.

```python
with SubBotManager(max_workers=4) as manager:
    # These run in parallel (up to 4 at a time)
    tasks = [
        manager.create_scrape_task(["https://site1.com"]),
        manager.create_scrape_task(["https://site2.com"]),
        manager.create_crawl_task("https://site3.com"),
        manager.create_search_task("query"),
    ]
    results = manager.run(tasks)  # All run concurrently
```

## Task Creation Helpers

```python
from ultron_sub_bots import (
    ScrapeTask, CrawlTask, SearchTask, 
    ExtractTask, MonitorTask, TaskBatch
)

# Type-safe task builders
scrape = ScrapeTask(
    urls=["https://example.com"],
    formats=["markdown", "html"],
    only_main_content=True,
)

crawl = CrawlTask(
    url="https://docs.example.com",
    max_depth=3,
    limit=100,
    include_paths=["/guide/", "/api/"],
)

search = SearchTask(
    query="machine learning 2024",
    num_results=20,
    search_type="deep",
)

# Batch creation for maximum parallelism
tasks = TaskBatch.scrape_multiple(
    urls=["https://site1.com", "https://site2.com", "https://site3.com"],
    name_prefix="batch",
)

# Convert to ScrapingTask for execution
manager_tasks = [t.to_task(manager) for t in tasks]
```

## Workflows

Chain multi-step operations:

```python
from ultron_sub_bots import (
    Workflow, create_competitive_analysis_workflow,
    create_market_research_workflow
)

# Pre-built workflows
wf = create_competitive_analysis_workflow([
    "https://competitor1.com",
    "https://competitor2.com",
])

wf = create_market_research_workflow("electric vehicle market", num_sources=10)

# Custom workflow
wf = Workflow("my_workflow")
wf.add_step("search", lambda prev: [SearchTask(query="AI news")])
wf.add_step("scrape", lambda prev: [
    ScrapeTask(urls=[r["url"] for r in prev["search"][0].data["results"]])
], depends_on=["search"])

with SubBotManager() as manager:
    results = wf.execute(manager)
```

## Event Callbacks

Monitor task progress:

```python
with SubBotManager() as manager:
    def on_started(task):
        print(f"Started: {task.name}")
    
    def on_completed(task, result):
        print(f"Done: {task.name} - {result.urls_processed} URLs")
    
    def on_failed(task, result):
        print(f"Failed: {task.name} - {result.error}")
    
    def on_all_done(results):
        print(f"All {len(results)} tasks finished")
    
    manager.on_task_started(on_started)
    manager.on_task_completed(on_completed)
    manager.on_task_failed(on_failed)
    manager.on_all_completed(on_all_done)
    
    manager.run(tasks)
```

## Async Usage

```python
import asyncio
from ultron_sub_bots import SubBotManager

async def main():
    manager = SubBotManager(max_workers=4)
    
    tasks = [
        manager.create_scrape_task(["https://site1.com"]),
        manager.create_search_task("query"),
    ]
    
    results = await manager.run_async(tasks)
    
    manager.shutdown()

asyncio.run(main())
```

## Custom Bots

Register custom configurations:

```python
with SubBotManager(auto_register_defaults=False) as manager:
    manager.register_bot("scrape", "fast_scraper", {
        "formats": ["markdown"],
        "only_main_content": True,
        "wait_for": 1000,
    })
    
    manager.register_bot("crawl", "deep_crawler", {
        "max_depth": 5,
        "limit": 500,
        "max_concurrency": 10,
    })
```

## Output

Results are saved to `.firecrawl/output/` by default. Each task gets a unique output file.

```python
result = results[0]
print(result.success)           # bool
print(result.data)              # Parsed JSON data
print(result.urls_processed)    # Number of URLs processed
print(result.duration_ms)       # Execution time
print(result.metadata)          # Extra info (output files, etc.)
```

## Requirements

- Python 3.8+
- Firecrawl CLI (`npm install -g firecrawl`)
- Firecrawl API key (set `FIRECRAWL_API_KEY` environment variable)

## License

MIT