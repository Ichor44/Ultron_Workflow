"""
Example usage of Ultron Sub-Bots.
"""

import asyncio
from ultron_sub_bots import (
    SubBotManager,
    ScrapeTask,
    CrawlTask,
    SearchTask,
    ExtractTask,
    MonitorTask,
    TaskBatch,
    Workflow,
    create_competitive_analysis_workflow,
    create_market_research_workflow,
    quick_scrape,
    quick_crawl,
    quick_search,
)


def example_basic_parallel_scrape():
    """Example: Scrape multiple URLs in parallel."""
    print("=== Basic Parallel Scrape ===")
    
    urls = [
        "https://example.com",
        "https://httpbin.org/html",
        "https://httpbin.org/json",
    ]
    
    with SubBotManager(max_workers=3) as manager:
        # Method 1: Single task with multiple URLs (Firecrawl handles concurrency)
        task = manager.create_scrape_task(urls, name="multi_scrape")
        results = manager.run(task)
        print(f"Single task results: {len(results)} task(s)")
        for r in results:
            print(f"  Success: {r.success}, URLs: {r.urls_processed}")
        
        # Method 2: Individual tasks for maximum parallelism
        scrape_tasks = TaskBatch.scrape_multiple(urls, "individual")
        tasks = [t.to_task(manager) for t in scrape_tasks]
        results = manager.run(tasks)
        print(f"Individual tasks: {len(results)} completed")
        for r in results:
            print(f"  Task {r.task_id}: Success={r.success}")


def example_crawl_website():
    """Example: Crawl a website section."""
    print("\n=== Crawl Website ===")
    
    with SubBotManager(max_workers=2) as manager:
        task = manager.create_crawl_task(
            url="https://docs.python.org/3/",
            name="python_docs",
            max_depth=2,
            limit=20,
            include_paths=["/3/tutorial/"],
        )
        results = manager.run(task)
        for r in results:
            print(f"Crawl: Success={r.success}, Pages={r.urls_processed}")
            if r.data and isinstance(r.data, dict):
                print(f"  Total pages found: {r.data.get('total', 'N/A')}")


def example_search_and_extract():
    """Example: Search web and extract info."""
    print("\n=== Search and Extract ===")
    
    with SubBotManager(max_workers=3) as manager:
        # Search for something
        search_task = manager.create_search_task(
            query="latest AI developments 2024",
            num_results=5,
        )
        search_results = manager.run(search_task)
        
        for r in search_results:
            print(f"Search: Success={r.success}")
            if r.data and isinstance(r.data, dict):
                results = r.data.get("results", [])
                print(f"  Found {len(results)} results")
                
                # Extract from first result
                if results:
                    first_url = results[0].get("url")
                    if first_url:
                        extract_task = manager.create_scrape_task(
                            urls=[first_url],
                            name="extract_first",
                        )
                        # Add query for extraction
                        extract_task.params["query"] = "What are the key AI developments mentioned?"
                        extract_results = manager.run(extract_task)
                        for er in extract_results:
                            print(f"  Extract: Success={er.success}")


def example_competitive_intelligence():
    """Example: Competitive intelligence gathering."""
    print("\n=== Competitive Intelligence ===")
    
    competitors = [
        "https://openai.com",
        "https://anthropic.com",
    ]
    
    with SubBotManager(max_workers=2) as manager:
        # Create crawl tasks for each competitor
        crawl_tasks = [
            manager.create_crawl_task(
                url=url,
                name=f"competitor_{i}",
                max_depth=1,
                limit=10,
            )
            for i, url in enumerate(competitors)
        ]
        
        results = manager.run(crawl_tasks)
        for r in results:
            print(f"Competitor crawl: {r.task_id} - Success={r.success}, Pages={r.urls_processed}")


def example_monitoring():
    """Example: Set up website monitoring."""
    print("\n=== Website Monitoring ===")
    
    with SubBotManager(max_workers=2) as manager:
        task = manager.create_monitor_task(
            urls=["https://example.com"],
            name="example_monitor",
            webhook_url="https://your-webhook.com/firecrawl",
            schedule="0 */6 * * *",  # Every 6 hours
        )
        results = manager.run(task)
        for r in results:
            print(f"Monitor: Success={r.success}")
            if r.metadata.get("monitors"):
                for m in r.metadata["monitors"]:
                    print(f"  URL: {m.get('url')}, Monitor ID: {m.get('monitor', {}).get('id')}")


def example_async_usage():
    """Example: Async usage with asyncio."""
    print("\n=== Async Usage ===")
    
    async def run_async():
        manager = SubBotManager(max_workers=3)
        
        tasks = [
            manager.create_scrape_task(["https://httpbin.org/html"]),
            manager.create_scrape_task(["https://httpbin.org/json"]),
            manager.create_search_task("Python async programming", num_results=3),
        ]
        
        results = await manager.run_async(tasks)
        for r in results:
            print(f"Async task {r.task_id}: Success={r.success}")
        
        manager.shutdown()
    
    asyncio.run(run_async())


def example_workflow():
    """Example: Multi-step workflow."""
    print("\n=== Workflow Example ===")
    
    # Create a market research workflow
    workflow = create_market_research_workflow("electric vehicle market 2024", num_sources=5)
    
    with SubBotManager(max_workers=3) as manager:
        results = workflow.execute(manager)
        print(f"Workflow completed with {len(results)} steps")
        for step_name, step_results in results.items():
            print(f"  Step '{step_name}': {len(step_results)} task(s)")


def example_callbacks():
    """Example: Using event callbacks."""
    print("\n=== Event Callbacks ===")
    
    with SubBotManager(max_workers=2) as manager:
        def on_started(task):
            print(f"  [STARTED] {task.name} ({task.id})")
        
        def on_completed(task, result):
            print(f"  [COMPLETED] {task.name} - Success: {result.success}")
        
        def on_failed(task, result):
            print(f"  [FAILED] {task.name} - Error: {result.error}")
        
        def on_all_done(results):
            print(f"  [ALL DONE] {len(results)} tasks completed")
        
        manager.on_task_started(on_started)
        manager.on_task_completed(on_completed)
        manager.on_task_failed(on_failed)
        manager.on_all_completed(on_all_done)
        
        tasks = [
            manager.create_scrape_task(["https://httpbin.org/html"]),
            manager.create_search_task("test query", num_results=2),
        ]
        manager.run(tasks)


def example_quick_functions():
    """Example: Quick one-liner functions."""
    print("\n=== Quick Functions ===")
    
    # Quick scrape
    results = quick_scrape("https://httpbin.org/html")
    print(f"Quick scrape: {len(results)} result(s)")
    
    # Quick crawl
    results = quick_crawl("https://httpbin.org", max_depth=1, limit=5)
    print(f"Quick crawl: {len(results)} result(s)")
    
    # Quick search
    results = quick_search("Firecrawl web scraping", num_results=3)
    print(f"Quick search: {len(results)} result(s)")


def example_custom_bot():
    """Example: Registering a custom bot."""
    print("\n=== Custom Bot ===")
    
    with SubBotManager(auto_register_defaults=False) as manager:
        # Register only what we need
        manager.register_bot("scrape", "my_scraper", {
            "formats": ["markdown", "html"],
            "only_main_content": False,
        })
        manager.register_bot("search", "my_searcher", {
            "num_results": 20,
        })
        
        print("Registered bots:")
        for bot in manager.list_bots():
            print(f"  {bot['bot_id']}: {bot['name']}")
        
        # Use custom bot
        task = manager.create_scrape_task(
            ["https://httpbin.org/html"],
            formats=["markdown", "html"],
        )
        results = manager.run(task)
        print(f"Custom bot result: Success={results[0].success}")


if __name__ == "__main__":
    # Run examples (comment out ones that require internet/API)
    example_basic_parallel_scrape()
    # example_crawl_website()  # Requires internet
    # example_search_and_extract()  # Requires API
    # example_competitive_intelligence()  # Requires internet
    # example_monitoring()  # Requires webhook
    # example_async_usage()
    # example_workflow()
    # example_callbacks()
    # example_quick_functions()
    # example_custom_bot()
    
    print("\n=== All examples completed ===")