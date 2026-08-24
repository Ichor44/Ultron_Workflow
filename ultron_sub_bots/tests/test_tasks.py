"""
Tests for ultron_sub_bots.tasks module.

Covers task helper dataclasses, TaskBatch, Workflow, and pre-built workflows.
"""

from unittest.mock import patch

import pytest

from ultron_sub_bots.core import ScrapingTask
from ultron_sub_bots.manager import SubBotManager
from ultron_sub_bots.tasks import (
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


# ===================================================================
# Task helper dataclasses
# ===================================================================
class TestScrapeTask:
    def test_defaults(self):
        t = ScrapeTask(urls=["https://example.com"])
        assert t.urls == ["https://example.com"]
        assert t.formats == ["markdown"]
        assert t.only_main_content is True

    def test_to_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            st = ScrapeTask(
                urls=["https://example.com"],
                name="test",
                formats=["html"],
                only_main_content=False,
                wait_for=5000,
            )
            task = st.to_task(m)
            assert isinstance(task, ScrapingTask)
            assert task.task_type == "scrape"
            assert task.params["formats"] == ["html"]
            assert task.params["only_main_content"] is False
            assert task.params["wait_for"] == 5000

    def test_string_url_converted_to_list(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            st = ScrapeTask(urls="https://example.com")
            task = st.to_task(m)
            assert task.urls == ["https://example.com"]


class TestCrawlTask:
    def test_defaults(self):
        t = CrawlTask(url="https://example.com")
        assert t.url == "https://example.com"
        assert t.max_depth == 3
        assert t.limit == 50

    def test_to_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            ct = CrawlTask(
                url="https://example.com",
                name="test_crawl",
                max_depth=5,
                limit=200,
                include_paths=["/blog/*"],
                exclude_paths=["/admin/*"],
            )
            task = ct.to_task(m)
            assert task.task_type == "crawl"
            assert task.urls == ["https://example.com"]
            assert task.params["max_depth"] == 5


class TestSearchTask:
    def test_defaults(self):
        t = SearchTask(query="python testing")
        assert t.query == "python testing"
        assert t.num_results == 10

    def test_to_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            st = SearchTask(query="AI news", num_results=20)
            task = st.to_task(m)
            assert task.task_type == "search"
            assert task.params["query"] == "AI news"
            assert task.params["num_results"] == 20


class TestExtractTask:
    def test_to_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            et = ExtractTask(
                urls=["https://example.com"],
                query="pricing information",
                name="extract_prices",
            )
            task = et.to_task(m)
            assert task.task_type == "extract"
            assert task.params["query"] == "pricing information"

    def test_string_url(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            et = ExtractTask(urls="https://example.com", query="test")
            task = et.to_task(m)
            assert task.urls == ["https://example.com"]


class TestMonitorTask:
    def test_to_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            mt = MonitorTask(
                urls=["https://example.com"],
                webhook_url="https://hooks.example.com",
                email="test@example.com",
                schedule="*/30 * * * *",
            )
            task = mt.to_task(m)
            assert task.task_type == "monitor"
            assert task.params["webhook_url"] == "https://hooks.example.com"
            assert task.params["schedule"] == "*/30 * * * *"

    def test_string_url(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            mt = MonitorTask(urls="https://example.com")
            task = mt.to_task(m)
            assert task.urls == ["https://example.com"]


# ===================================================================
# TaskBatch
# ===================================================================
class TestTaskBatch:
    def test_scrape_multiple(self):
        tasks = TaskBatch.scrape_multiple(
            ["https://a.com", "https://b.com", "https://c.com"],
            name_prefix="batch",
        )
        assert len(tasks) == 3
        for i, t in enumerate(tasks):
            assert isinstance(t, ScrapeTask)
            assert t.urls == [f"https://{chr(97+i)}.com"]
            assert f"batch_{i}" in t.name

    def test_search_and_scrape(self):
        tasks = TaskBatch.search_and_scrape("python", num_results=5)
        assert len(tasks) == 1
        assert isinstance(tasks[0], SearchTask)

    def test_crawl_and_extract(self):
        tasks = TaskBatch.crawl_and_extract("https://example.com", ["/blog/*"])
        assert len(tasks) == 1
        assert isinstance(tasks[0], CrawlTask)

    def test_competitive_intel(self):
        tasks = TaskBatch.competitive_intel([
            "https://competitor1.com",
            "https://competitor2.com",
        ])
        assert len(tasks) == 2
        for t in tasks:
            assert isinstance(t, CrawlTask)
            assert t.max_depth == 2

    def test_research_topic(self):
        tasks = TaskBatch.research_topic("AI trends", num_sources=15)
        assert len(tasks) == 1
        assert isinstance(tasks[0], SearchTask)
        assert tasks[0].num_results == 15


# ===================================================================
# Workflow
# ===================================================================
class TestWorkflow:
    def test_add_step(self):
        wf = Workflow("test_workflow")
        wf.add_step("step1", lambda results: [])
        assert len(wf.steps) == 1
        assert wf.steps[0]["name"] == "step1"

    def test_add_step_returns_self(self):
        wf = Workflow("test")
        result = wf.add_step("s1", lambda r: [])
        assert result is wf

    def test_add_step_with_depends_on(self):
        wf = Workflow("test")
        wf.add_step("s1", lambda r: [])
        wf.add_step("s2", lambda r: [], depends_on=["s1"])
        assert wf.steps[1]["depends_on"] == ["s1"]

    def test_execute_missing_dependency(self):
        wf = Workflow("test")
        wf.add_step("s1", lambda r: [], depends_on=["nonexistent"])
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            with pytest.raises(ValueError, match="Dependency.*not found"):
                wf.execute(m)

    def test_execute_empty_workflow(self):
        wf = Workflow("empty")
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            results = wf.execute(m)
            assert results == {}

    def test_execute_step_with_list_return(self):
        wf = Workflow("test")
        wf.add_step("step1", lambda r: [ScrapeTask(urls=["https://example.com"])])
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            with patch.object(m, "run", return_value=[]) as mock_run:
                results = wf.execute(m)
                mock_run.assert_called_once()

    def test_output_key(self):
        wf = Workflow("test")
        wf.add_step("s1", lambda r: [], output_key="custom_key")
        assert wf.steps[0]["output_key"] == "custom_key"


# ===================================================================
# Pre-built workflows
# ===================================================================
class TestPrebuiltWorkflows:
    def test_competitive_analysis_workflow(self):
        wf = create_competitive_analysis_workflow([
            "https://competitor1.com",
            "https://competitor2.com",
        ])
        assert wf.name == "competitive_analysis"
        assert len(wf.steps) == 2
        assert wf.steps[0]["name"] == "crawl_competitors"
        assert wf.steps[1]["name"] == "extract_info"
        assert "crawl_competitors" in wf.steps[1]["depends_on"]

    def test_market_research_workflow(self):
        wf = create_market_research_workflow("AI trends", num_sources=5)
        assert wf.name == "market_research"
        assert len(wf.steps) == 2
        assert wf.steps[0]["name"] == "search"
        assert wf.steps[1]["name"] == "scrape_sources"
        assert "search" in wf.steps[1]["depends_on"]
