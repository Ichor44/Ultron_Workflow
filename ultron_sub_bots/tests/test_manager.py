"""
Tests for ultron_sub_bots.manager module.

Covers SubBotManager initialization, bot registration, task creation
convenience methods, and the quick_* helper functions.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from ultron_sub_bots.core import ScrapingTask, TaskResult, TaskStatus
from ultron_sub_bots.manager import SubBotManager, BotConfig


# ===================================================================
# SubBotManager initialization
# ===================================================================
class TestSubBotManagerInit:
    def test_creates_with_defaults(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            assert m.core is not None
            # Should have registered default bots
            bots = m.core.list_bots()
            assert len(bots) == 8  # scrape, crawl, search, map, interact, monitor, download, protein

    def test_no_default_bots(self):
        with SubBotManager(
            firecrawl_cli="/usr/bin/firecrawl",
            auto_register_defaults=False,
        ) as m:
            assert len(m.core.list_bots()) == 0

    def test_custom_workers(self):
        with SubBotManager(
            firecrawl_cli="/usr/bin/firecrawl",
            max_workers=8,
        ) as m:
            assert m.core.max_workers == 8


# ===================================================================
# Bot registration
# ===================================================================
class TestBotRegistration:
    def test_register_custom_bot(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl", auto_register_defaults=False) as m:
            m.register_bot("scrape", "custom_scraper", {"formats": ["html"]})
            bot = m.core.get_bot("custom_scraper")
            assert bot is not None
            assert bot.config["formats"] == ["html"]

    def test_unregister_bot(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            assert m.unregister_bot("default_scraper") is True
            assert m.core.get_bot("default_scraper") is None

    def test_list_bots(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            bots = m.list_bots()
            assert len(bots) == 8
            # Each entry has bot_id, name, config
            for bot_info in bots:
                assert "bot_id" in bot_info
                assert "name" in bot_info
                assert "config" in bot_info


# ===================================================================
# Task creation convenience methods
# ===================================================================
class TestTaskCreation:
    def test_create_scrape_task_single_url(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_scrape_task("https://example.com")
            assert isinstance(task, ScrapingTask)
            assert task.task_type == "scrape"
            assert task.urls == ["https://example.com"]
            assert task.metadata["core"] is m.core

    def test_create_scrape_task_multiple_urls(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_scrape_task(["https://a.com", "https://b.com"])
            assert len(task.urls) == 2

    def test_create_scrape_task_with_options(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_scrape_task(
                "https://example.com",
                name="my_scrape",
                formats=["html", "markdown"],
                only_main_content=False,
                wait_for=5000,
            )
            assert task.name == "my_scrape"
            assert task.params["formats"] == ["html", "markdown"]
            assert task.params["only_main_content"] is False
            assert task.params["wait_for"] == 5000

    def test_create_crawl_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_crawl_task(
                "https://example.com",
                name="my_crawl",
                max_depth=5,
                limit=200,
            )
            assert task.task_type == "crawl"
            assert task.urls == ["https://example.com"]
            assert task.params["max_depth"] == 5
            assert task.params["limit"] == 200

    def test_create_search_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_search_task(
                "python testing",
                name="my_search",
                num_results=20,
            )
            assert task.task_type == "search"
            assert task.params["query"] == "python testing"
            assert task.params["num_results"] == 20

    def test_create_map_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_map_task(
                "https://example.com",
                name="my_map",
                search="blog",
                limit=500,
            )
            assert task.task_type == "map"
            assert task.params["search"] == "blog"
            assert task.params["limit"] == 500

    def test_create_interact_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_interact_task(
                "https://example.com",
                prompt="fill the form",
                name="my_interact",
            )
            assert task.task_type == "interact"
            assert task.params["prompt"] == "fill the form"

    def test_create_monitor_task_single_url(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_monitor_task(
                "https://example.com",
                name="my_monitor",
                webhook_url="https://hooks.example.com",
            )
            assert task.task_type == "monitor"
            assert task.urls == ["https://example.com"]
            assert task.params["webhook_url"] == "https://hooks.example.com"

    def test_create_monitor_task_multiple_urls(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_monitor_task(["https://a.com", "https://b.com"])
            assert len(task.urls) == 2

    def test_create_download_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_download_task(
                "https://example.com",
                name="my_download",
                formats=["html"],
                max_depth=2,
            )
            assert task.task_type == "download"
            assert task.params["formats"] == ["html"]
            assert task.params["max_depth"] == 2


# ===================================================================
# Auto-generated task names
# ===================================================================
class TestTaskNames:
    def test_scrape_task_name(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_scrape_task(["https://a.com", "https://b.com"])
            assert "2_urls" in task.name

    def test_crawl_task_name(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_crawl_task("https://example.com/blog")
            assert "crawl" in task.name

    def test_search_task_name(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            task = m.create_search_task("python testing frameworks")
            assert "python" in task.name


# ===================================================================
# Execution (mocked)
# ===================================================================
class TestExecution:
    def test_run_single_task(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            # Mock the core's run_parallel to return a result
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                task = m.create_scrape_task("https://example.com")
                results = m.run(task)
                assert len(results) == 1
                assert results[0].success is True

    def test_run_list_of_tasks(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                t1 = m.create_scrape_task("https://a.com")
                t2 = m.create_scrape_task("https://b.com")
                results = m.run([t1, t2])
                assert len(results) == 1

    def test_run_scrape(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                results = m.run_scrape("https://example.com")
                assert len(results) == 1

    def test_run_crawl(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                results = m.run_crawl("https://example.com")
                assert len(results) == 1

    def test_run_search(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                results = m.run_search("python testing")
                assert len(results) == 1

    def test_run_map(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            expected = [TaskResult(task_id="t1", success=True)]
            with patch.object(m.core, "run_parallel", return_value=expected):
                results = m.run_map("https://example.com")
                assert len(results) == 1


# ===================================================================
# Result handling
# ===================================================================
class TestResultHandling:
    def test_get_results(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            m.core._completed_tasks["t1"] = TaskResult(task_id="t1", success=True)
            results = m.get_results()
            assert "t1" in results

    def test_get_result_by_id(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            m.core._completed_tasks["t1"] = TaskResult(task_id="t1", success=True)
            result = m.get_result("t1")
            assert result.success is True

    def test_get_result_missing(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            assert m.get_result("nonexistent") is None

    def test_get_task_status(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            m.core._completed_tasks["t1"] = TaskResult(task_id="t1", success=True)
            status = m.get_task_status("t1")
            assert status == TaskStatus.COMPLETED


# ===================================================================
# Event callbacks
# ===================================================================
class TestCallbacks:
    def test_register_callbacks(self):
        with SubBotManager(firecrawl_cli="/usr/bin/firecrawl") as m:
            cb = MagicMock()
            m.on_task_started(cb)
            m.on_task_completed(cb)
            m.on_task_failed(cb)
            m.on_all_completed(cb)
            assert cb in m.core._callbacks["task_started"]
            assert cb in m.core._callbacks["task_completed"]
            assert cb in m.core._callbacks["task_failed"]
            assert cb in m.core._callbacks["all_completed"]
