"""
Task helper classes for common scraping patterns.
"""

from typing import Any, Dict, List, Optional, Union, Callable
from dataclasses import dataclass, field

from .core import ScrapingTask
from .manager import SubBotManager


@dataclass
class ScrapeTask:
    """Helper for creating scrape tasks with common patterns."""
    urls: Union[str, List[str]]
    name: str = ""
    formats: List[str] = field(default_factory=lambda: ["markdown"])
    only_main_content: bool = True
    wait_for: int = 0
    include_tags: List[str] = field(default_factory=list)
    exclude_tags: List[str] = field(default_factory=list)
    redact_pii: bool = False
    
    def to_task(self, manager: SubBotManager) -> ScrapingTask:
        return manager.create_scrape_task(
            urls=self.urls,
            name=self.name,
            formats=self.formats,
            only_main_content=self.only_main_content,
            wait_for=self.wait_for,
            include_tags=self.include_tags,
            exclude_tags=self.exclude_tags,
            redact_pii=self.redact_pii,
        )


@dataclass
class CrawlTask:
    """Helper for creating crawl tasks with common patterns."""
    url: str
    name: str = ""
    max_depth: int = 3
    limit: int = 50
    include_paths: List[str] = field(default_factory=list)
    exclude_paths: List[str] = field(default_factory=list)
    delay: int = 0
    max_concurrency: int = 5
    
    def to_task(self, manager: SubBotManager) -> ScrapingTask:
        return manager.create_crawl_task(
            url=self.url,
            name=self.name,
            max_depth=self.max_depth,
            limit=self.limit,
            include_paths=self.include_paths,
            exclude_paths=self.exclude_paths,
            delay=self.delay,
            max_concurrency=self.max_concurrency,
        )


@dataclass
class SearchTask:
    """Helper for creating search tasks with common patterns."""
    query: str
    name: str = ""
    num_results: int = 10
    search_type: str = "auto"  # auto, fast, deep
    live_crawl: str = "fallback"  # fallback, preferred
    
    def to_task(self, manager: SubBotManager) -> ScrapingTask:
        return manager.create_search_task(
            query=self.query,
            name=self.name,
            num_results=self.num_results,
            search_type=self.search_type,
            live_crawl=self.live_crawl,
        )


@dataclass
class ExtractTask:
    """Helper for creating extraction tasks (scrape with query)."""
    urls: Union[str, List[str]]
    query: str
    name: str = ""
    formats: List[str] = field(default_factory=lambda: ["markdown"])
    
    def to_task(self, manager: SubBotManager) -> ScrapingTask:
        if isinstance(self.urls, str):
            urls = [self.urls]
        else:
            urls = self.urls
        
        # For extraction, we use scrape with a query parameter
        task = manager.create_scrape_task(
            urls=urls,
            name=self.name or f"extract_{len(urls)}_urls",
            formats=self.formats,
        )
        task.params["query"] = self.query
        task.task_type = "extract"
        return task


@dataclass
class MonitorTask:
    """Helper for creating monitor tasks with common patterns."""
    urls: Union[str, List[str]]
    name: str = ""
    webhook_url: str = ""
    email: str = ""
    schedule: str = "0 * * * *"  # Hourly
    
    def to_task(self, manager: SubBotManager) -> ScrapingTask:
        return manager.create_monitor_task(
            urls=self.urls,
            name=self.name,
            webhook_url=self.webhook_url,
            email=self.email,
            schedule=self.schedule,
        )


# Batch task creators for common workflows
class TaskBatch:
    """Create batches of related tasks for parallel execution."""
    
    @staticmethod
    def scrape_multiple(
        urls: List[str],
        name_prefix: str = "batch_scrape",
        **kwargs
    ) -> List[ScrapeTask]:
        """Create individual scrape tasks for each URL (for max parallelism)."""
        return [
            ScrapeTask(
                urls=[url],
                name=f"{name_prefix}_{i}",
                **kwargs
            )
            for i, url in enumerate(urls)
        ]
    
    @staticmethod
    def search_and_scrape(
        query: str,
        num_results: int = 10,
        scrape_formats: List[str] = None,
        **kwargs
    ) -> List[ScrapingTask]:
        """Create a search task followed by scrape tasks for results."""
        # This would need to be executed in two phases:
        # 1. Search
        # 2. Scrape results
        # Returning as a workflow description
        return [
            SearchTask(query=query, num_results=num_results, **kwargs),
            # Scrape tasks would be created after search results
        ]
    
    @staticmethod
    def crawl_and_extract(
        url: str,
        extract_queries: List[str],
        **kwargs
    ) -> List[ScrapingTask]:
        """Create a crawl task followed by extraction tasks."""
        # First crawl to get URLs, then extract from each
        return [
            CrawlTask(url=url, **kwargs),
            # Extract tasks created after crawl
        ]
    
    @staticmethod
    def competitive_intel(
        competitor_urls: List[str],
        **kwargs
    ) -> List[ScrapingTask]:
        """Create tasks for competitive intelligence gathering."""
        tasks = []
        for i, url in enumerate(competitor_urls):
            # Crawl each competitor site
            tasks.append(CrawlTask(
                url=url,
                name=f"competitor_{i}_crawl",
                max_depth=2,
                limit=30,
                **kwargs
            ))
        return tasks
    
    @staticmethod
    def research_topic(
        topic: str,
        num_sources: int = 10,
        **kwargs
    ) -> List[ScrapingTask]:
        """Create tasks for researching a topic."""
        return [
            SearchTask(
                query=topic,
                name=f"research_{topic[:30].replace(' ', '_')}",
                num_results=num_sources,
                **kwargs
            )
        ]


# Workflow helpers
class Workflow:
    """Define multi-step workflows that execute in sequence."""
    
    def __init__(self, name: str):
        self.name = name
        self.steps: List[Dict[str, Any]] = []
    
    def add_step(
        self,
        step_name: str,
        task_factory: Callable[[Dict[str, Any]], Union[ScrapingTask, List[ScrapingTask]]],
        depends_on: List[str] = None,
        output_key: str = None,
    ) -> "Workflow":
        """Add a step to the workflow."""
        self.steps.append({
            "name": step_name,
            "factory": task_factory,
            "depends_on": depends_on or [],
            "output_key": output_key or step_name,
        })
        return self
    
    def execute(self, manager: SubBotManager) -> Dict[str, Any]:
        """Execute the workflow steps in order."""
        results = {}
        
        for step in self.steps:
            # Check dependencies
            for dep in step["depends_on"]:
                if dep not in results:
                    raise ValueError(f"Dependency '{dep}' not found for step '{step['name']}'")
            
            # Create and run task(s)
            task_or_tasks = step["factory"](results)
            if isinstance(task_or_tasks, list):
                tasks = task_or_tasks
            else:
                tasks = [task_or_tasks]
            
            result = manager.run(tasks)
            results[step["output_key"]] = result
        
        return results


# Pre-built workflows
def create_competitive_analysis_workflow(
    competitor_urls: List[str],
    queries: List[str] = None,
) -> Workflow:
    """Create a competitive analysis workflow."""
    queries = queries or [
        "What are the pricing tiers?",
        "What features are highlighted?",
        "What is the value proposition?",
    ]
    
    wf = Workflow("competitive_analysis")
    
    # Step 1: Crawl all competitor sites
    def crawl_step(prev_results):
        tasks = [
            CrawlTask(url=url, name=f"comp_{i}_crawl", max_depth=2, limit=20)
            for i, url in enumerate(competitor_urls)
        ]
        return tasks
    
    wf.add_step("crawl_competitors", crawl_step)
    
    # Step 2: Extract key info from each
    def extract_step(prev_results):
        crawl_results = prev_results["crawl_competitors"]
        tasks = []
        for i, result in enumerate(crawl_results):
            if result and result[0].success:
                for q in queries:
                    tasks.append(ExtractTask(
                        urls=[competitor_urls[i]],
                        query=q,
                        name=f"comp_{i}_extract_{q[:20]}",
                    ))
        return tasks
    
    wf.add_step("extract_info", extract_step, depends_on=["crawl_competitors"])
    
    return wf


def create_market_research_workflow(
    topic: str,
    num_sources: int = 10,
) -> Workflow:
    """Create a market research workflow."""
    wf = Workflow("market_research")
    
    def search_step(prev_results):
        return [SearchTask(query=topic, num_results=num_sources)]
    
    wf.add_step("search", search_step)
    
    def scrape_step(prev_results):
        search_results = prev_results["search"]
        if not search_results or not search_results[0].success:
            return []
        
        data = search_results[0].data
        urls = []
        if isinstance(data, dict) and "results" in data:
            urls = [r.get("url") for r in data["results"] if r.get("url")]
        
        return [ScrapeTask(urls=url, name=f"source_{i}") for i, url in enumerate(urls[:num_sources])]
    
    wf.add_step("scrape_sources", scrape_step, depends_on=["search"])
    
    return wf