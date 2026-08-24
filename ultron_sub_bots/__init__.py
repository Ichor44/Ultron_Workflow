"""
Ultron Sub-Bots: Parallel Web Scraping System

A system for managing multiple concurrent web scraping tasks using Firecrawl.
Each "sub-bot" can be configured for different scraping operations that run in parallel.
"""

from .core import (
    UltronCore, 
    SubBot, 
    ScrapingTask, 
    TaskResult,
    find_firecrawl_cli,
    ensure_firecrawl_available,
    TaskStatus,
)
from .manager import SubBotManager, quick_scrape, quick_crawl, quick_search
from .tasks import (
    ScrapeTask,
    CrawlTask,
    SearchTask,
    ExtractTask,
    MonitorTask,
    TaskBatch,
    Workflow,
    create_competitive_analysis_workflow,
    create_market_research_workflow,
)

__version__ = "1.0.0"
__all__ = [
    "UltronCore",
    "SubBot", 
    "ScrapingTask",
    "TaskResult",
    "TaskStatus",
    "find_firecrawl_cli",
    "ensure_firecrawl_available",
    "SubBotManager",
    "quick_scrape",
    "quick_crawl",
    "quick_search",
    "ScrapeTask",
    "CrawlTask", 
    "SearchTask",
    "ExtractTask",
    "MonitorTask",
    "TaskBatch",
    "Workflow",
    "create_competitive_analysis_workflow",
    "create_market_research_workflow",
]