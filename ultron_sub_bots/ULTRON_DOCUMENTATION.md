# Ultron Sub-Bots Complete Documentation

> **A parallel web scraping system built on Firecrawl that lets you run multiple scraping operations at once using specialized "sub-bots" — think of them as your personal team of web researchers working together.**

---

## 📖 Table of Contents

1. [What is Ultron Sub-Bots?](#what-is-ultron-sub-bots)
2. [Quick Start (5 Minutes)](#quick-start-5-minutes)
3. [Core Concepts Explained Simply](#core-concepts-explained-simply)
4. [The 7 Sub-Bot Types](#the-7-sub-bot-types)
5. [Command-Line Interface (CLI)](#command-line-interface-cli)
6. [Python API Reference](#python-api-reference)
7. [Workflows & Automation](#workflows--automation)
8. [Event Callbacks & Monitoring](#event-callbacks--monitoring)
9. [Async/Await Support](#asyncawait-support)
10. [Custom Bots](#custom-bots)
11. [Output & Results](#output--results)
12. [Troubleshooting & FAQ](#troubleshooting--faq)
13. [Examples by Use Case](#examples-by-use-case)

---

## What is Ultron Sub-Bots?

**In plain English:** Ultron Sub-Bots is a tool that helps you collect information from websites automatically. Instead of manually visiting pages, copying text, and saving files, you tell Ultron what you want, and it sends out specialized "sub-bots" (like little robot helpers) to do the work for you — all at the same time.

**Technically:** It's a Python library that wraps the Firecrawl CLI, providing parallel execution, specialized bot types for different scraping tasks, a workflow engine for multi-step operations, and both synchronous and asynchronous APIs.

### Why Use Ultron Sub-Bots?

| Problem | Ultron Solution |
|---------|-----------------|
| "I need to scrape 50 websites" | Run them all in parallel with 4+ workers |
| "I want to crawl an entire documentation site" | CrawlBot handles depth, limits, and path filtering |
| "I need to search the web and get full content" | SearchBot returns actual page content, not just snippets |
| "I need to click buttons, fill forms" | InteractBot drives a real browser |
| "I want to be notified when a page changes" | MonitorBot sets up webhooks/email alerts |
| "I want to download a whole site for offline reading" | DownloadBot saves as local Markdown/HTML files |
| "I have a complex multi-step research task" | Workflow engine chains steps together |

---

## Quick Start (5 Minutes)

### Prerequisites

1. **Python 3.8+** — Check with `python --version`
2. **Node.js & npm** — Needed for Firecrawl CLI
3. **Firecrawl CLI** — Install globally:
   ```bash
   npm install -g firecrawl
   ```
4. **Firecrawl API Key** — Get one at [firecrawl.dev](https://firecrawl.dev) and set it:
   ```bash
   # Windows (PowerShell)
   $env:FIRECRAWL_API_KEY = "your-api-key-here"
   
   # Windows (Command Prompt)
   set FIRECRAWL_API_KEY=your-api-key-here
   
   # Mac/Linux
   export FIRECRAWL_API_KEY="your-api-key-here"
   ```

### Install Ultron Sub-Bots

```bash
# From the ultron_sub_bots directory
pip install -e .
```

### Your First Scrape (Python)

```python
from ultron_sub_bots import quick_scrape

# Scrape a single page - that's it!
results = quick_scrape("https://example.com")

# Check results
for r in results:
    print(f"Success: {r.success}")
    print(f"Content: {r.data}")  # Markdown content
```

### Your First Scrape (Command Line)

```bash
# Scrape one URL
ultron scrape https://example.com

# Scrape multiple URLs
ultron scrape https://site1.com https://site2.com https://site3.com

# Scrape from a file (one URL per line)
ultron scrape -f urls.txt

# Get JSON output
ultron scrape https://example.com --json
```

---

## Core Concepts Explained Simply

### 🤖 Sub-Bots (The Workers)
Think of sub-bots as specialized team members:
- **ScrapeBot** — Reads individual pages
- **CrawlBot** — Explores entire websites
- **SearchBot** — Searches the web like Google but gets full content
- **MapBot** — Lists ALL URLs on a site
- **InteractBot** — Clicks, types, scrolls like a human
- **MonitorBot** — Watches for changes 24/7
- **DownloadBot** — Saves entire sites to your computer

### 📋 Tasks (The Work Orders)
A "task" is a request you give to a sub-bot. It contains:
- **What to do** (scrape, crawl, search, etc.)
- **Where to do it** (URLs, search queries)
- **How to do it** (formats, depth, filters)

### 🏢 Manager (The Supervisor)
The `SubBotManager` coordinates everything:
- Assigns tasks to available sub-bots
- Runs up to N tasks in parallel (default: 4)
- Collects results
- Handles errors

### 🔄 Workflows (The Assembly Lines)
Workflows chain multiple tasks together:
> Search → Get URLs → Scrape each → Extract specific info

---

## The 7 Sub-Bot Types

### 1. ScrapeBot — Read Individual Pages
**Best for:** Getting content from specific known URLs

```python
task = manager.create_scrape_task(
    urls=["https://example.com", "https://example.org"],
    formats=["markdown", "html"],  # Get both formats
    only_main_content=True,         # Skip headers/footers
    wait_for=2000,                  # Wait 2s for JavaScript
)
```

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `formats` | Output formats: `markdown`, `html`, `links`, `screenshot` | `["markdown"]` |
| `only_main_content` | Extract only article content, skip nav/footer | `True` |
| `wait_for` | Milliseconds to wait for JS rendering | `0` |
| `include_tags` | CSS selectors to include | `[]` |
| `exclude_tags` | CSS selectors to exclude | `[]` |
| `redact_pii` | Remove emails, phones, SSNs | `False` |

---

### 2. CrawlBot — Explore Entire Sites
**Best for:** Documentation sites, blogs, product catalogs

```python
task = manager.create_crawl_task(
    url="https://docs.python.org/3/",
    max_depth=3,              # How many link levels to follow
    limit=100,                # Max pages to crawl
    include_paths=["/3/tutorial/"],  # Only crawl these paths
    exclude_paths=["/3/whatsnew/"],  # Skip these paths
    delay=1000,               # Wait 1s between requests
    max_concurrency=5,        # Parallel requests during crawl
)
```

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `max_depth` | Link depth (1 = only start page) | `3` |
| `limit` | Maximum pages to crawl | `50` |
| `include_paths` | Only crawl URLs containing these | `[]` |
| `exclude_paths` | Skip URLs containing these | `[]` |
| `delay` | Milliseconds between requests | `0` |
| `max_concurrency` | Parallel crawl workers | `5` |

---

### 3. SearchBot — Web Search with Full Content
**Best for:** Research, finding articles, current events

```python
task = manager.create_search_task(
    query="latest AI developments 2024",
    num_results=10,
    search_type="deep",    # auto, fast, or deep
    live_crawl="preferred", # Try to get full page content
)
```

**Returns:** Search results WITH full page content (markdown), not just snippets.

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `num_results` | How many results to return | `10` |
| `search_type` | `auto`, `fast`, `deep` | `auto` |
| `live_crawl` | `fallback` or `preferred` | `fallback` |

---

### 4. MapBot — Discover All URLs
**Best for:** Site audits, finding all pages, SEO

```python
task = manager.create_map_task(
    url="https://example.com",
    search="blog",        # Only URLs containing "blog"
    limit=5000,           # Max URLs to return
)
```

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `search` | Filter URLs by keyword | `""` |
| `limit` | Maximum URLs to return | `5000` |

---

### 5. InteractBot — Browser Automation
**Best for:** SPAs, login flows, button clicks, infinite scroll

```python
task = manager.create_interact_task(
    url="https://example.com/dashboard",
    prompt="Click the 'Export' button, wait for download, then click 'Confirm'",
    wait_for=5000,
)
```

**How it works:** You describe what to do in plain English (a "prompt"), and Firecrawl's AI-driven browser executes it.

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `prompt` | Natural language instructions | Required |
| `wait_for` | Milliseconds to wait after actions | `3000` |

---

### 6. MonitorBot — Change Detection
**Best for:** Price tracking, content monitoring, uptime

```python
task = manager.create_monitor_task(
    urls=["https://example.com/pricing"],
    webhook_url="https://your-server.com/firecrawl-webhook",
    email="alerts@yourcompany.com",
    schedule="0 */6 * * *",  # Every 6 hours (cron format)
)
```

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `webhook_url` | POST notifications here | `""` |
| `email` | Email notifications | `""` |
| `schedule` | Cron expression | `"0 * * * *"` (hourly) |

**Cron Examples:**
| Schedule | Meaning |
|----------|---------|
| `0 * * * *` | Every hour |
| `0 */6 * * *` | Every 6 hours |
| `0 9 * * *` | Daily at 9 AM |
| `0 9 * * 1` | Every Monday at 9 AM |

---

### 7. DownloadBot — Offline Archives
**Best for:** Documentation backup, offline reading, archiving

```python
task = manager.create_download_task(
    url="https://docs.example.com",
    formats=["markdown", "html"],
    max_depth=3,
    limit=200,
)
```

**Saves to:** `.firecrawl/output/downloads/<task_id>/` as organized files.

**Options:**
| Option | Description | Default |
|--------|-------------|---------|
| `formats` | File formats to save | `["markdown"]` |
| `max_depth` | Link depth | `3` |
| `limit` | Max pages | `100` |

---

## Command-Line Interface (CLI)

The `ultron` command is installed automatically with `pip install -e .`.

### Global Options
```bash
ultron --help                    # Show help
ultron -w 8                      # Use 8 parallel workers (default: 4)
ultron -j                        # Output JSON instead of human-readable
```

### Commands

#### `ultron scrape` — Scrape URLs
```bash
# Basic usage
ultron scrape https://example.com

# Multiple URLs
ultron scrape https://site1.com https://site2.com

# From file (one URL per line)
ultron scrape -f urls.txt

# Options
ultron scrape https://example.com \
  -n "my_task" \                    # Task name
  --format markdown,html \          # Output formats
  --full-page \                     # Include headers/footers
  --wait 3000                       # Wait 3s for JS
```

#### `ultron crawl` — Crawl a Website
```bash
ultron crawl https://docs.python.org/3/ \
  -n "python_docs" \
  -d 2 \                            # Max depth (default: 3)
  -l 50 \                           # Max pages (default: 50)
  --include "/3/tutorial/,/3/library/" \
  --exclude "/3/whatsnew/"
```

#### `ultron search` — Search the Web
```bash
ultron search "machine learning 2024" \
  -n "ml_search" \
  -r 20 \                           # Number of results (default: 10)
  -t deep                           # Search type: auto, fast, deep
```

#### `ultron batch` — Run Multiple Tasks from JSON
```bash
# Create tasks.json:
[
  {"type": "scrape", "urls": ["https://a.com"], "name": "site_a"},
  {"type": "crawl", "url": "https://b.com", "max_depth": 2},
  {"type": "search", "query": "AI news", "num_results": 5}
]

# Run all in parallel
ultron batch tasks.json
```

---

## Python API Reference

### Quick Functions (Simplest)

```python
from ultron_sub_bots import quick_scrape, quick_crawl, quick_search

# One-liners - no manager needed
results = quick_scrape("https://example.com")
results = quick_crawl("https://docs.example.com", max_depth=2, limit=20)
results = quick_search("Python tutorials", num_results=10)
```

### SubBotManager (Full Control)

```python
from ultron_sub_bots import SubBotManager

# Context manager handles cleanup automatically
with SubBotManager(max_workers=4) as manager:
    # Create tasks
    scrape_task = manager.create_scrape_task(urls=["https://a.com"])
    crawl_task = manager.create_crawl_task(url="https://b.com")
    search_task = manager.create_search_task(query="AI news")
    
    # Run single task
    results = manager.run(scrape_task)
    
    # Run multiple tasks in parallel
    results = manager.run([scrape_task, crawl_task, search_task])
```

### Task Creation Methods

| Method | Purpose | Key Parameters |
|--------|---------|----------------|
| `create_scrape_task(urls, ...)` | Scrape specific URLs | `urls`, `formats`, `only_main_content`, `wait_for` |
| `create_crawl_task(url, ...)` | Crawl a site | `url`, `max_depth`, `limit`, `include_paths`, `exclude_paths` |
| `create_search_task(query, ...)` | Search web | `query`, `num_results`, `search_type` |
| `create_map_task(url, ...)` | List all URLs | `url`, `search`, `limit` |
| `create_interact_task(url, prompt, ...)` | Browser automation | `url`, `prompt`, `wait_for` |
| `create_monitor_task(urls, ...)` | Watch for changes | `urls`, `webhook_url`, `email`, `schedule` |
| `create_download_task(url, ...)` | Download site | `url`, `formats`, `max_depth`, `limit` |

### Quick Execution Methods

```python
# These create and run in one call
manager.run_scrape(urls=["https://a.com", "https://b.com"])
manager.run_crawl(url="https://example.com", max_depth=2)
manager.run_search(query="AI news", num_results=10)
manager.run_map(url="https://example.com")
```

### Result Object

Every task returns a `TaskResult` with:

```python
result.success           # True/False
result.data              # Parsed data (dict, list, or string)
result.raw_output        # Raw Firecrawl output
result.error             # Error message if failed
result.duration_ms       # How long it took
result.urls_processed    # Number of URLs/pages processed
result.credits_used      # Firecrawl credits consumed
result.metadata          # Extra info (output files, etc.)

# Convert to dict for JSON serialization
result.to_dict()
```

---

## Workflows & Automation

### Pre-Built Workflows

```python
from ultron_sub_bots import (
    create_competitive_analysis_workflow,
    create_market_research_workflow
)

# Competitive analysis: crawl competitors + extract key info
workflow = create_competitive_analysis_workflow([
    "https://competitor1.com",
    "https://competitor2.com",
])

# Market research: search topic + scrape top sources
workflow = create_market_research_workflow(
    "electric vehicle market 2024",
    num_sources=10
)

with SubBotManager() as manager:
    results = workflow.execute(manager)
```

### Custom Workflows

```python
from ultron_sub_bots import Workflow, ScrapeTask, SearchTask

wf = Workflow("my_research")

# Step 1: Search
wf.add_step("search", lambda prev: [
    SearchTask(query="AI agent frameworks 2024", num_results=10)
])

# Step 2: Scrape results (depends on search)
wf.add_step("scrape", lambda prev: [
    ScrapeTask(urls=[r["url"] for r in prev["search"][0].data["results"]])
], depends_on=["search"])

# Step 3: Extract specific info from each
wf.add_step("extract", lambda prev: [
    ScrapeTask(urls=[r["url"]], params={"query": "What is the pricing model?"})
    for r in prev["scrape"]
], depends_on=["scrape"])

with SubBotManager() as manager:
    results = wf.execute(manager)
```

### TaskBatch Helpers

```python
from ultron_sub_bots import TaskBatch

# Create individual tasks for MAXIMUM parallelism
# (each URL gets its own worker)
tasks = TaskBatch.scrape_multiple(
    urls=["https://a.com", "https://b.com", "https://c.com"],
    name_prefix="my_batch",
    formats=["markdown"],
)

# Convert to executable tasks
manager_tasks = [t.to_task(manager) for t in tasks]
results = manager.run(manager_tasks)

# Competitive intelligence batch
tasks = TaskBatch.competitive_intel([
    "https://competitor1.com",
    "https://competitor2.com",
])

# Research topic batch
tasks = TaskBatch.research_topic("quantum computing", num_sources=15)
```

---

## Event Callbacks & Monitoring

Track progress in real-time:

```python
with SubBotManager() as manager:
    def on_started(task):
        print(f"🚀 Started: {task.name} ({task.id})")
    
    def on_completed(task, result):
        print(f"✅ Done: {task.name} - {result.urls_processed} URLs in {result.duration_ms:.0f}ms")
    
    def on_failed(task, result):
        print(f"❌ Failed: {task.name} - {result.error}")
    
    def on_all_done(results):
        print(f"🏁 All {len(results)} tasks finished!")
        successful = sum(1 for r in results if r.success)
        print(f"   Success: {successful}/{len(results)}")
    
    # Register callbacks
    manager.on_task_started(on_started)
    manager.on_task_completed(on_completed)
    manager.on_task_failed(on_failed)
    manager.on_all_completed(on_all_done)
    
    # Run tasks
    manager.run(tasks)
```

### Checking Task Status

```python
# Get status of specific task
status = manager.get_task_status("task_id_123")
# Returns: PENDING, RUNNING, COMPLETED, FAILED, CANCELLED

# Get all results
all_results = manager.get_results()

# Get single result
result = manager.get_result("task_id_123")

# Cancel a task
manager.core.cancel_task("task_id_123")
```

---

## Async/Await Support

For integration with async applications (FastAPI, Discord bots, etc.):

```python
import asyncio
from ultron_sub_bots import SubBotManager

async def scrape_multiple_sites():
    manager = SubBotManager(max_workers=4)
    
    tasks = [
        manager.create_scrape_task(["https://site1.com"]),
        manager.create_scrape_task(["https://site2.com"]),
        manager.create_search_task("AI news", num_results=5),
    ]
    
    # Run all concurrently
    results = await manager.run_async(tasks)
    
    for r in results:
        print(f"{r.task_id}: {'✅' if r.success else '❌'}")
    
    manager.shutdown()
    return results

# Run the async function
results = asyncio.run(scrape_multiple_sites())
```

---

## Custom Bots

Register specialized configurations for reuse:

```python
with SubBotManager(auto_register_defaults=False) as manager:
    # Fast scraper - minimal options for speed
    manager.register_bot("scrape", "fast_scraper", {
        "formats": ["markdown"],
        "only_main_content": True,
        "wait_for": 0,
    })
    
    # Deep crawler - thorough exploration
    manager.register_bot("crawl", "deep_crawler", {
        "max_depth": 5,
        "limit": 500,
        "max_concurrency": 10,
        "delay": 500,
    })
    
    # High-volume search
    manager.register_bot("search", "bulk_searcher", {
        "num_results": 50,
        "search_type": "deep",
        "live_crawl": "preferred",
    })
    
    # List registered bots
    for bot in manager.list_bots():
        print(f"{bot['bot_id']}: {bot['name']}")
        print(f"  Config: {bot['config']}")
```

---

## Output & Results

### Where Files Are Saved

By default: `.firecrawl/output/` in your working directory

```
.firecrawl/
└── output/
    ├── scrape_abc123.json      # Scrape results
    ├── crawl_def456.json       # Crawl results
    ├── search_ghi789.json      # Search results
    ├── map_jkl012.json         # URL map
    ├── interact_mno345.json    # Interaction results
    ├── monitor_pqr678.json     # Monitor setup
    └── downloads/
        └── stu901/             # Downloaded site files
            ├── index.md
            ├── about.md
            └── ...
```

### Result Data Structures

**Scrape Result:**
```json
{
  "markdown": "# Page Title\n\nContent here...",
  "html": "<html>...</html>",
  "metadata": {
    "title": "Page Title",
    "description": "Page description",
    "url": "https://example.com",
    "statusCode": 200
  }
}
```

**Crawl Result:**
```json
{
  "total": 42,
  "pages": [
    {"url": "https://site.com/page1", "markdown": "..."},
    {"url": "https://site.com/page2", "markdown": "..."}
  ]
}
```

**Search Result:**
```json
{
  "results": [
    {
      "url": "https://example.com/article",
      "title": "Article Title",
      "description": "Snippet...",
      "markdown": "Full article content...",
      "metadata": {...}
    }
  ]
}
```

**Map Result:**
```json
{
  "urls": [
    "https://example.com/",
    "https://example.com/about",
    "https://example.com/blog/post-1"
  ]
}
```

---

## Troubleshooting & FAQ

### Common Issues

**"Firecrawl CLI not found"**
```bash
# Verify installation
firecrawl --version

# If not found, install globally
npm install -g firecrawl

# Or add npm bin to PATH
# Windows: %APPDATA%\npm
# Mac/Linux: ~/.npm-global/bin
```

**"API Key not set"**
```bash
# Check if set
echo $FIRECRAWL_API_KEY    # Mac/Linux
echo %FIRECRAWL_API_KEY%   # Windows CMD
$env:FIRECRAWL_API_KEY     # PowerShell

# Set it permanently (Windows)
setx FIRECRAWL_API_KEY "your-key"
```

**"Task fails with timeout"**
- Increase `default_timeout` in manager: `SubBotManager(default_timeout=300)`
- Add `wait_for` for JS-heavy sites
- Reduce `max_concurrency` for crawl

**"No sub-bot available for task type"**
- Make sure `auto_register_defaults=True` (default)
- Or manually register: `manager.register_bot("scrape", "my_scraper")`

**"Unicode/emoji errors on Windows"**
- The code handles UTF-8 automatically
- If issues persist, set `PYTHONIOENCODING=utf-8`

### Performance Tips

| Goal | Recommendation |
|------|----------------|
| Maximum speed | Use `TaskBatch.scrape_multiple()` for individual tasks |
| Large crawls | Increase `max_concurrency` to 10-20 |
| JS-heavy sites | Set `wait_for=3000-5000` |
| Rate limits | Add `delay=1000-2000` to crawl |
| Memory issues | Reduce `limit` and `max_depth` |

### Firecrawl Credits

Each operation consumes credits:
- Scrape: ~1 credit per URL
- Crawl: ~1 credit per page
- Search: ~1 credit per search + results
- Map: ~1 credit
- Interact: ~5-10 credits
- Monitor: ~1 credit per check
- Download: ~1 credit per page

Check your usage at [firecrawl.dev/dashboard](https://firecrawl.dev/dashboard)

---

## Examples by Use Case

### 📰 Content Research & Monitoring

```python
# Daily news monitoring
with SubBotManager() as manager:
    # Set up monitors for key sites
    manager.run_monitor(
        urls=[
            "https://techcrunch.com",
            "https://theverge.com",
            "https://arstechnica.com",
        ],
        webhook_url="https://your-app.com/webhook",
        schedule="0 7 * * *",  # Daily at 7 AM
    )
```

### 🛒 E-commerce Price Tracking

```python
# Monitor competitor prices
with SubBotManager() as manager:
    task = manager.create_monitor_task(
        urls=[
            "https://competitor1.com/product-x",
            "https://competitor2.com/product-x",
        ],
        webhook_url="https://your-app.com/price-alert",
        schedule="0 */2 * * *",  # Every 2 hours
    )
    manager.run(task)
```

### 📚 Documentation Archive

```python
# Download entire docs for offline access
with SubBotManager() as manager:
    results = manager.run_download(
        url="https://docs.python.org/3/",
        formats=["markdown", "html"],
        max_depth=3,
        limit=500,
    )
    # Files saved to .firecrawl/output/downloads/<task_id>/
```

### 🔍 SEO Site Audit

```python
# Map all URLs on a site
with SubBotManager() as manager:
    map_results = manager.run_map("https://example.com", limit=10000)
    
    urls = map_results[0].data.get("urls", [])
    print(f"Found {len(urls)} URLs")
    
    # Scrape key pages for metadata
    key_pages = [u for u in urls if any(k in u for k in ["/product/", "/blog/", "/pricing/"])]
    scrape_results = manager.run_scrape(key_pages[:50])
```

### 🤖 AI Training Data Collection

```python
# Collect training data on a topic
with SubBotManager(max_workers=8) as manager:
    # Step 1: Search for sources
    search = manager.run_search("machine learning tutorials 2024", num_results=20)
    
    # Step 2: Extract URLs
    urls = []
    for r in search:
        if r.data and "results" in r.data:
            urls.extend([item["url"] for item in r.data["results"]])
    
    # Step 3: Scrape all in parallel (max parallelism)
    tasks = TaskBatch.scrape_multiple(urls[:50], "ml_training")
    manager_tasks = [t.to_task(manager) for t in tasks]
    results = manager.run(manager_tasks)
    
    # Step 4: Save as JSONL for training
    import jsonlines
    with jsonlines.open("training_data.jsonl", "w") as writer:
        for r in results:
            if r.success and r.data:
                writer.write({"text": r.data.get("markdown", "")})
```

### 🏢 Competitive Intelligence

```python
# Full competitive analysis workflow
workflow = create_competitive_analysis_workflow([
    "https://competitor1.com",
    "https://competitor2.com",
    "https://competitor3.com",
])

with SubBotManager(max_workers=4) as manager:
    results = workflow.execute(manager)
    
    # Results contain:
    # - crawl_competitors: Full site crawls
    # - extract_info: Answers to pricing, features, value prop
```

### 🧪 Testing & QA

```python
# Test multiple URLs for uptime/content
with SubBotManager() as manager:
    urls = [
        "https://app.example.com",
        "https://api.example.com/health",
        "https://docs.example.com",
    ]
    
    results = manager.run_scrape(urls, wait_for=2000)
    
    for r in results:
        if r.success:
            print(f"✅ {r.metadata.get('url', 'unknown')} - OK")
        else:
            print(f"❌ {r.metadata.get('url', 'unknown')} - {r.error}")
```

---

## 📚 Additional Resources

- **Firecrawl Documentation:** https://firecrawl.dev/docs
- **Firecrawl CLI Reference:** `firecrawl --help`
- **API Dashboard:** https://firecrawl.dev/dashboard
- **GitHub Issues:** Report bugs or request features

---

## 📄 License

MIT License — Free for personal and commercial use.

---

*Documentation generated from Ultron Sub-Bots v1.0.0 source code. For the latest version, check the repository.*