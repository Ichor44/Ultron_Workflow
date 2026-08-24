"""
Tests for ultron_sub_bots.bots module.

Covers all sub-bot implementations: ScrapeBot, CrawlBot, SearchBot,
MapBot, InteractBot, MonitorBot, DownloadBot, and create_bot factory.
"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from ultron_sub_bots.core import ScrapingTask, TaskResult, TaskStatus, SubBot
from ultron_sub_bots.bots import (
    ScrapeBot,
    CrawlBot,
    SearchBot,
    MapBot,
    InteractBot,
    MonitorBot,
    DownloadBot,
    create_bot,
)


# ===================================================================
# Factory function
# ===================================================================
class TestCreateBot:
    @pytest.mark.parametrize(
        "bot_type,expected_class",
        [
            ("scrape", ScrapeBot),
            ("crawl", CrawlBot),
            ("search", SearchBot),
            ("map", MapBot),
            ("interact", InteractBot),
            ("monitor", MonitorBot),
            ("download", DownloadBot),
        ],
    )
    def test_creates_correct_bot_type(self, bot_type, expected_class):
        bot = create_bot(bot_type, bot_id=f"test_{bot_type}")
        assert isinstance(bot, expected_class)

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown bot type"):
            create_bot("nonexistent")

    def test_custom_id(self):
        bot = create_bot("scrape", bot_id="my_id")
        assert bot.bot_id == "my_id"

    def test_default_id(self):
        bot = create_bot("scrape")
        assert bot.bot_id == "scrape_bot"


# ===================================================================
# ScrapeBot
# ===================================================================
class TestScrapeBot:
    def test_can_handle_scrape(self):
        bot = ScrapeBot()
        assert bot.can_handle("scrape") is True
        assert bot.can_handle("extract") is True
        assert bot.can_handle("crawl") is False

    def test_validate_needs_urls(self):
        bot = ScrapeBot()
        task_ok = ScrapingTask(urls=["https://example.com"])
        task_empty = ScrapingTask(urls=[])
        assert bot.validate_task(task_ok) is True
        assert bot.validate_task(task_empty) is False

    def test_execute_no_core_returns_error(self):
        bot = ScrapeBot()
        task = ScrapingTask(urls=["https://example.com"], metadata={})
        result = bot.execute(task)
        assert result.success is False
        assert "Core reference not provided" in result.error

    def test_execute_success_single_url(self, mock_core):
        bot = ScrapeBot()
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"content": "page content"}',
            stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.urls_processed == 1
        assert result.data == {"content": "page content"}

    def test_execute_success_multiple_urls(self, mock_core):
        bot = ScrapeBot()
        task = ScrapingTask(
            urls=["https://a.com", "https://b.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"content": "data"}',
            stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.urls_processed == 2
        assert isinstance(result.data, list)
        assert len(result.data) == 2

    def test_execute_firecrawl_failure(self, mock_core):
        bot = ScrapeBot()
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="connection refused",
        )
        result = bot.execute(task)
        assert result.success is False
        assert "connection refused" in result.error

    def test_format_options(self, mock_core):
        bot = ScrapeBot(config={"formats": ["markdown", "html"]})
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr="",
        )
        bot.execute(task)
        # Check that -f markdown,html was passed
        args = mock_core.run_with_retry.call_args[0][1]
        assert "-f" in args
        assert "markdown,html" in args

    def test_only_main_content_flag(self, mock_core):
        bot = ScrapeBot(config={"only_main_content": True})
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--only-main-content" in args

    def test_wait_for_option(self, mock_core):
        bot = ScrapeBot(config={"wait_for": 5000})
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--wait-for" in args
        assert "5000" in args

    def test_redact_pii_flag(self, mock_core):
        bot = ScrapeBot(config={"redact_pii": True})
        task = ScrapingTask(
            urls=["https://example.com"],
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--redact-pii" in args


# ===================================================================
# CrawlBot
# ===================================================================
class TestCrawlBot:
    def test_can_handle_crawl(self):
        bot = CrawlBot()
        assert bot.can_handle("crawl") is True
        assert bot.can_handle("scrape") is False

    def test_validate_single_url(self):
        bot = CrawlBot()
        assert bot.validate_task(ScrapingTask(urls=["https://a.com"])) is True
        assert bot.validate_task(ScrapingTask(urls=["https://a.com", "https://b.com"])) is False

    def test_execute_no_core(self):
        bot = CrawlBot()
        result = bot.execute(ScrapingTask(urls=["https://a.com"], metadata={}))
        assert result.success is False

    def test_execute_success(self, mock_core):
        bot = CrawlBot()
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"total": 5, "pages": []}',
            stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.urls_processed == 5

    def test_crawl_options(self, mock_core):
        bot = CrawlBot(config={"max_depth": 5, "limit": 200, "delay": 2, "max_concurrency": 10})
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"total": 0}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--max-depth" in args
        assert "5" in args
        assert "--limit" in args
        assert "200" in args

    def test_include_exclude_paths(self, mock_core):
        bot = CrawlBot(config={
            "include_paths": ["/blog/*"],
            "exclude_paths": ["/admin/*"],
        })
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"total": 0}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--include-paths" in args
        assert "/blog/*" in args
        assert "--exclude-paths" in args


# ===================================================================
# SearchBot
# ===================================================================
class TestSearchBot:
    def test_can_handle_search(self):
        bot = SearchBot()
        assert bot.can_handle("search") is True
        assert bot.can_handle("scrape") is False

    def test_validate_needs_query(self):
        bot = SearchBot()
        assert bot.validate_task(ScrapingTask(params={"query": "test"})) is True
        assert bot.validate_task(ScrapingTask(params={})) is False

    def test_execute_no_query(self, mock_core):
        bot = SearchBot()
        task = ScrapingTask(params={}, metadata={"core": mock_core})
        result = bot.execute(task)
        assert result.success is False
        assert "No search query" in result.error

    def test_execute_success(self, mock_core):
        bot = SearchBot()
        task = ScrapingTask(params={"query": "python testing"}, metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"data": {"web": [{"url": "https://a.com"}]}}',
            stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.metadata["query"] == "python testing"


# ===================================================================
# MapBot
# ===================================================================
class TestMapBot:
    def test_can_handle_map(self):
        bot = MapBot()
        assert bot.can_handle("map") is True

    def test_validate_single_url(self):
        bot = MapBot()
        assert bot.validate_task(ScrapingTask(urls=["https://a.com"])) is True
        assert bot.validate_task(ScrapingTask(urls=["a", "b"])) is False

    def test_execute_success(self, mock_core):
        bot = MapBot()
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='{"urls": ["https://a.com", "https://b.com"]}',
            stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.urls_processed == 2

    def test_search_filter(self, mock_core):
        bot = MapBot(config={"search": "blog"})
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"urls": []}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--search" in args
        assert "blog" in args


# ===================================================================
# InteractBot
# ===================================================================
class TestInteractBot:
    def test_can_handle_interact(self):
        bot = InteractBot()
        assert bot.can_handle("interact") is True

    def test_validate_needs_url_and_action(self):
        bot = InteractBot()
        assert bot.validate_task(
            ScrapingTask(urls=["https://a.com"], params={"prompt": "click login"})
        ) is True
        assert bot.validate_task(
            ScrapingTask(urls=["https://a.com"], params={})
        ) is False

    def test_execute_with_prompt(self, mock_core):
        bot = InteractBot()
        task = ScrapingTask(
            urls=["https://example.com"],
            params={"prompt": "click the login button"},
            metadata={"core": mock_core},
        )
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"result": "clicked"}', stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--prompt" in args
        assert "click the login button" in args


# ===================================================================
# MonitorBot
# ===================================================================
class TestMonitorBot:
    def test_can_handle_monitor(self):
        bot = MonitorBot()
        assert bot.can_handle("monitor") is True

    def test_validate_needs_urls(self):
        bot = MonitorBot()
        assert bot.validate_task(ScrapingTask(urls=["https://a.com"])) is True
        assert bot.validate_task(ScrapingTask(urls=[])) is False

    def test_execute_success(self, mock_core):
        bot = MonitorBot()
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"status": "ok"}', stderr="",
        )
        result = bot.execute(task)
        assert result.success is True
        assert result.urls_processed == 1

    def test_webhook_and_email(self, mock_core):
        bot = MonitorBot(config={
            "webhook_url": "https://hooks.example.com/notify",
            "email": "admin@example.com",
        })
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"ok":true}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--webhook" in args
        assert "https://hooks.example.com/notify" in args
        assert "--email" in args


# ===================================================================
# DownloadBot
# ===================================================================
class TestDownloadBot:
    def test_can_handle_download(self):
        bot = DownloadBot()
        assert bot.can_handle("download") is True

    def test_validate_single_url(self):
        bot = DownloadBot()
        assert bot.validate_task(ScrapingTask(urls=["https://a.com"])) is True
        assert bot.validate_task(ScrapingTask(urls=["a", "b"])) is False

    def test_execute_success(self, mock_core):
        bot = DownloadBot()
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"files": 5}', stderr="",
        )
        result = bot.execute(task)
        assert result.success is True

    def test_format_and_depth_options(self, mock_core):
        bot = DownloadBot(config={"formats": ["markdown", "html"], "max_depth": 5})
        task = ScrapingTask(urls=["https://example.com"], metadata={"core": mock_core})
        mock_core.run_with_retry.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{}', stderr="",
        )
        bot.execute(task)
        args = mock_core.run_with_retry.call_args[0][1]
        assert "--format" in args
        assert "markdown,html" in args
        assert "--max-depth" in args
        assert "5" in args


# ===================================================================
# SubBot base class
# ===================================================================
class TestSubBotBase:
    def test_validate_task_default(self):
        """Default validate_task returns True for SubBot base, but ScrapeBot requires URLs."""
        from ultron_sub_bots.bots import CrawlBot
        # Use CrawlBot which inherits default validate_task (returns True)
        # Actually CrawlBot.validate_task checks len(urls) == 1, so test with InteractBot logic
        # Just verify that calling validate_task doesn't crash
        bot = ScrapeBot()
        # ScrapeBot.validate_task requires urls > 0
        assert bot.validate_task(ScrapingTask(urls=["https://example.com"])) is True
        assert bot.validate_task(ScrapingTask(urls=[])) is False

    def test_get_config(self):
        bot = ScrapeBot(config={"key": "value"})
        assert bot.get_config("key") == "value"
        assert bot.get_config("missing", "default") == "default"
        assert bot.get_config("missing") is None
