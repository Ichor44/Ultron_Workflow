"""
High-level manager for Ultron Sub-Bots.
"""

from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass

from .core import UltronCore, ScrapingTask, TaskResult, TaskStatus
from .bots import (
    ScrapeBot, CrawlBot, SearchBot, MapBot, 
    InteractBot, MonitorBot, DownloadBot, ProteinLabBot, create_bot
)


@dataclass
class BotConfig:
    """Configuration for a sub-bot."""
    bot_type: str
    bot_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class SubBotManager:
    """High-level manager for creating and running sub-bots."""
    
    def __init__(
        self,
        max_workers: int = 4,
        firecrawl_cli: Optional[str] = None,
        default_timeout: int = 120,
        output_dir: str = ".firecrawl/output",
        auto_register_defaults: bool = True,
    ):
        self.core = UltronCore(
            max_workers=max_workers,
            firecrawl_cli=firecrawl_cli,
            default_timeout=default_timeout,
            output_dir=output_dir,
        )
        
        if auto_register_defaults:
            self._register_default_bots()
    
    def _register_default_bots(self) -> None:
        """Register default sub-bots for common tasks."""
        default_bots = [
            BotConfig("scrape", "default_scraper", {
                "formats": ["markdown"],
                "only_main_content": True,
            }),
            BotConfig("crawl", "default_crawler", {
                "max_depth": 3,
                "limit": 50,
                "max_concurrency": 5,
            }),
            BotConfig("search", "default_searcher", {
                "num_results": 10,
                "search_type": "auto",
            }),
            BotConfig("map", "default_mapper", {
                "limit": 1000,
            }),
            BotConfig("interact", "default_interactor", {
                "wait_for": 3000,
            }),
            BotConfig("monitor", "default_monitor", {
                "schedule": "0 * * * *",  # Hourly
            }),
            BotConfig("download", "default_downloader", {
                "formats": ["markdown"],
                "max_depth": 3,
                "limit": 100,
            }),
            BotConfig("protein", "default_protein_lab", {
                "default_action": "analyze",
            }),
        ]
        
        for bot_config in default_bots:
            bot = create_bot(bot_config.bot_type, bot_config.bot_id, bot_config.config)
            self.core.register_bot(bot)
    
    def register_bot(self, bot_type: str, bot_id: str = None, config: Dict[str, Any] = None) -> None:
        """Register a custom sub-bot."""
        bot = create_bot(bot_type, bot_id, config)
        self.core.register_bot(bot)
    
    def unregister_bot(self, bot_id: str) -> bool:
        """Unregister a sub-bot."""
        return self.core.unregister_bot(bot_id)
    
    def list_bots(self) -> List[Dict[str, Any]]:
        """List all registered bots."""
        return [
            {
                "bot_id": bot.bot_id,
                "name": bot.name,
                "config": bot.config,
            }
            for bot in self.core.list_bots()
        ]
    
    # Convenience methods for creating tasks
    def create_scrape_task(
        self,
        urls: Union[str, List[str]],
        name: str = "",
        formats: List[str] = None,
        only_main_content: bool = True,
        wait_for: int = 0,
        **kwargs
    ) -> ScrapingTask:
        """Create a scrape task."""
        if isinstance(urls, str):
            urls = [urls]
        
        params = {}
        if formats:
            params["formats"] = formats
        if only_main_content is not None:
            params["only_main_content"] = only_main_content
        if wait_for:
            params["wait_for"] = wait_for
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"scrape_{len(urls)}_urls",
            task_type="scrape",
            urls=urls,
            params=params,
            metadata={"core": self.core},
        )
    
    def create_crawl_task(
        self,
        url: str,
        name: str = "",
        max_depth: int = 3,
        limit: int = 50,
        include_paths: List[str] = None,
        exclude_paths: List[str] = None,
        **kwargs
    ) -> ScrapingTask:
        """Create a crawl task."""
        params = {
            "max_depth": max_depth,
            "limit": limit,
        }
        if include_paths:
            params["include_paths"] = include_paths
        if exclude_paths:
            params["exclude_paths"] = exclude_paths
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"crawl_{url.replace('https://', '').replace('/', '_')[:30]}",
            task_type="crawl",
            urls=[url],
            params=params,
            metadata={"core": self.core},
        )
    
    def create_search_task(
        self,
        query: str,
        name: str = "",
        num_results: int = 10,
        search_type: str = "auto",
        **kwargs
    ) -> ScrapingTask:
        """Create a search task."""
        params = {
            "query": query,
            "num_results": num_results,
            "search_type": search_type,
        }
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"search_{query[:30].replace(' ', '_')}",
            task_type="search",
            urls=[],  # Search doesn't use URLs directly
            params=params,
            metadata={"core": self.core},
        )
    
    def create_map_task(
        self,
        url: str,
        name: str = "",
        search: str = "",
        limit: int = 1000,
        **kwargs
    ) -> ScrapingTask:
        """Create a map task."""
        params = {
            "search": search,
            "limit": limit,
        }
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"map_{url.replace('https://', '').replace('/', '_')[:30]}",
            task_type="map",
            urls=[url],
            params=params,
            metadata={"core": self.core},
        )
    
    def create_interact_task(
        self,
        url: str,
        prompt: str = "",
        name: str = "",
        actions: List[Dict] = None,
        wait_for: int = 3000,
        **kwargs
    ) -> ScrapingTask:
        """Create an interact task."""
        params = {
            "prompt": prompt,
            "actions": actions or [],
            "wait_for": wait_for,
        }
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"interact_{url.replace('https://', '').replace('/', '_')[:30]}",
            task_type="interact",
            urls=[url],
            params=params,
            metadata={"core": self.core},
        )
    
    def create_monitor_task(
        self,
        urls: Union[str, List[str]],
        name: str = "",
        webhook_url: str = "",
        email: str = "",
        schedule: str = "0 * * * *",
        **kwargs
    ) -> ScrapingTask:
        """Create a monitor task."""
        if isinstance(urls, str):
            urls = [urls]
        
        params = {
            "webhook_url": webhook_url,
            "email": email,
            "schedule": schedule,
        }
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"monitor_{len(urls)}_urls",
            task_type="monitor",
            urls=urls,
            params=params,
            metadata={"core": self.core},
        )
    
    def create_download_task(
        self,
        url: str,
        name: str = "",
        formats: List[str] = None,
        max_depth: int = 3,
        limit: int = 100,
        **kwargs
    ) -> ScrapingTask:
        """Create a download task."""
        params = {
            "formats": formats or ["markdown"],
            "max_depth": max_depth,
            "limit": limit,
        }
        params.update(kwargs)
        
        return ScrapingTask(
            name=name or f"download_{url.replace('https://', '').replace('/', '_')[:30]}",
            task_type="download",
            urls=[url],
            params=params,
            metadata={"core": self.core},
        )
    
    # Execution methods
    def run(self, tasks: Union[ScrapingTask, List[ScrapingTask]]) -> List[TaskResult]:
        """Run tasks synchronously in parallel."""
        if isinstance(tasks, ScrapingTask):
            tasks = [tasks]
        return self.core.run_parallel(tasks)
    
    async def run_async(self, tasks: Union[ScrapingTask, List[ScrapingTask]]) -> List[TaskResult]:
        """Run tasks asynchronously in parallel."""
        if isinstance(tasks, ScrapingTask):
            tasks = [tasks]
        return await self.core.run_parallel_async(tasks)
    
    def run_scrape(
        self,
        urls: Union[str, List[str]],
        **kwargs
    ) -> List[TaskResult]:
        """Quick scrape multiple URLs."""
        task = self.create_scrape_task(urls, **kwargs)
        return self.run(task)
    
    def run_crawl(
        self,
        url: str,
        **kwargs
    ) -> List[TaskResult]:
        """Quick crawl a website."""
        task = self.create_crawl_task(url, **kwargs)
        return self.run(task)
    
    def run_search(
        self,
        query: str,
        **kwargs
    ) -> List[TaskResult]:
        """Quick search the web."""
        task = self.create_search_task(query, **kwargs)
        return self.run(task)
    
    def run_map(
        self,
        url: str,
        **kwargs
    ) -> List[TaskResult]:
        """Quick map a website."""
        task = self.create_map_task(url, **kwargs)
        return self.run(task)
    
    # Result handling
    def get_results(self) -> Dict[str, TaskResult]:
        """Get all completed results."""
        return self.core.get_results()
    
    def get_result(self, task_id: str) -> Optional[TaskResult]:
        """Get a specific result."""
        return self.core.get_results().get(task_id)
    
    def get_task_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get task status."""
        return self.core.get_task_status(task_id)
    
    # Event callbacks
    def on_task_started(self, callback) -> None:
        self.core.on("task_started", callback)
    
    def on_task_completed(self, callback) -> None:
        self.core.on("task_completed", callback)
    
    def on_task_failed(self, callback) -> None:
        self.core.on("task_failed", callback)
    
    def on_all_completed(self, callback) -> None:
        self.core.on("all_completed", callback)
    
    def shutdown(self) -> None:
        """Shutdown the manager."""
        self.core.shutdown()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False


# Convenience function for quick usage
def quick_scrape(urls: Union[str, List[str]], **kwargs) -> List[TaskResult]:
    """Quick scrape without creating a manager."""
    with SubBotManager() as manager:
        return manager.run_scrape(urls, **kwargs)


def quick_crawl(url: str, **kwargs) -> List[TaskResult]:
    """Quick crawl without creating a manager."""
    with SubBotManager() as manager:
        return manager.run_crawl(url, **kwargs)


def quick_search(query: str, **kwargs) -> List[TaskResult]:
    """Quick search without creating a manager."""
    with SubBotManager() as manager:
        return manager.run_search(query, **kwargs)